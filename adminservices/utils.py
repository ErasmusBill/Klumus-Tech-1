# adminservices/utils.py
import logging
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from asgiref.sync import sync_to_async

# Third-party imports
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Email, To, Content
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False
    logging.warning("SendGrid not available. Install with: pip install sendgrid")

try:
    from twilio.rest import Client
    from twilio.base.exceptions import TwilioRestException
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    logging.warning("Twilio not available. Install with: pip install twilio")

logger = logging.getLogger(__name__)

# ===== CONFIGURATION CHECK =====

def check_email_config():
    """Check if email configuration is available"""
    try:
        from django.conf import settings
        
        # Check if we're using console backend (for development)
        if hasattr(settings, 'EMAIL_BACKEND') and 'console' in settings.EMAIL_BACKEND:
            return True, "Using console email backend for development"
        
        # Check if we're using SendGrid backend
        if hasattr(settings, 'EMAIL_BACKEND') and 'sendgrid' in settings.EMAIL_BACKEND.lower():
            if not hasattr(settings, 'SENDGRID_API_KEY') or not settings.SENDGRID_API_KEY:
                return False, "SENDGRID_API_KEY not configured"
        
        # Check required settings
        if not hasattr(settings, 'DEFAULT_FROM_EMAIL') or not settings.DEFAULT_FROM_EMAIL:
            return False, "DEFAULT_FROM_EMAIL not configured"
        
        return True, "Email configuration OK"
        
    except Exception as e:
        return False, f"Email configuration error: {str(e)}"

def check_sms_config():
    """Check if SMS configuration is available"""
    if not TWILIO_AVAILABLE:
        return False, "Twilio not installed"
    
    required_settings = ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE_NUMBER']
    for setting in required_settings:
        if not hasattr(settings, setting) or not getattr(settings, setting):
            return False, f"{setting} not configured"
    
    return True, "SMS configuration OK"

# ===== CONTACT INFORMATION GATHERING =====

def get_teacher_contacts(teacher) -> Tuple[List[str], List[str]]:
    """
    Get email and phone numbers for a teacher
    Returns: (emails_list, phones_list)
    """
    emails = []
    phones = []
    
    try:
        # Teacher's primary contact
        if teacher.user.email:
            emails.append(teacher.user.email)
        
        if teacher.user.phone_number:
            phones.append(teacher.user.phone_number)
            
    except Exception as e:
        logger.error(f"Error getting teacher contacts for {teacher}: {str(e)}")
    
    return emails, phones

def get_student_parent_contacts(student) -> Tuple[List[str], List[str]]:
    """
    Get email and phone numbers for a student's parents
    Returns: (emails_list, phones_list)
    """
    emails = []
    phones = []
    
    try:
        # Student's own contact (if applicable)
        if student.user.email:
            emails.append(student.user.email)
        
        # Parent contacts - using the actual Parent model structure
        if student.parent:
            parent = student.parent
            
            # Father's contact information
            if parent.father_email:
                emails.append(parent.father_email)
            if parent.father_phone:
                phones.append(parent.father_phone)
            
            # Mother's contact information
            if parent.mother_email:
                emails.append(parent.mother_email)
            if parent.mother_phone:
                phones.append(parent.mother_phone)
                
            # Emergency contact (if available)
            if hasattr(parent, 'emergency_contact_phone') and parent.emergency_contact_phone:
                phones.append(parent.emergency_contact_phone)
                
        else:
            logger.warning(f"Student {student} has no parent associated")
                
    except Exception as e:
        logger.error(f"Error getting parent contacts for student {student}: {str(e)}")
    
    # Remove any empty strings and duplicates
    emails = [email for email in emails if email]
    phones = [phone for phone in phones if phone]
    
    logger.info(f"Found contacts for {student}: {len(emails)} emails, {len(phones)} phones")
    
    return emails, phones

def get_user_contact_info(user) -> Tuple[List[str], List[str]]:
    """
    Get email and phone numbers for any user
    Returns: (emails_list, phones_list)
    """
    emails = []
    phones = []
    
    try:
        if user.email:
            emails.append(user.email)
        
        if user.phone_number:
            phones.append(user.phone_number)
            
    except Exception as e:
        logger.error(f"Error getting contacts for user {user}: {str(e)}")
    
    return emails, phones

def get_all_teachers_contacts(school) -> Tuple[List[str], List[str]]:
    """
    Get all active teachers' contacts for a school
    Returns: (emails_list, phones_list)
    """
    emails = []
    phones = []
    
    try:
        from account.models import Teacher
        teachers = Teacher.objects.filter(school=school, is_active=True).select_related('user')
        
        for teacher in teachers:
            teacher_emails, teacher_phones = get_teacher_contacts(teacher)
            emails.extend(teacher_emails)
            phones.extend(teacher_phones)
            
    except Exception as e:
        logger.error(f"Error getting all teachers contacts for school {school}: {str(e)}")
    
    # Remove duplicates
    emails = list(set(emails))
    phones = list(set(phones))
    
    return emails, phones

def get_all_students_parents_contacts(school) -> Tuple[List[str], List[str]]:
    """
    Get all students and parents contacts for a school
    Returns: (emails_list, phones_list)
    """
    emails = []
    phones = []
    
    try:
        from account.models import Student
        students = Student.objects.filter(school=school, is_active=True).select_related('user', 'parent')
        
        for student in students:
            student_emails, student_phones = get_student_parent_contacts(student)
            emails.extend(student_emails)
            phones.extend(student_phones)
            
    except Exception as e:
        logger.error(f"Error getting all students contacts for school {school}: {str(e)}")
    
    # Remove duplicates
    emails = list(set(emails))
    phones = list(set(phones))
    
    return emails, phones

# ===== EMAIL FUNCTIONS =====

async def send_email_async(
    to_emails: List[str], 
    subject: str, 
    message: str, 
    html_message: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send email asynchronously using SendGrid API
    Returns: {'success': bool, 'message_id': str, 'error': str}
    """
    result = {'success': False, 'message_id': None, 'error': None}
    
    if not to_emails:
        result['error'] = "No recipient emails provided"
        return result
    
    try:
        # Remove duplicates and validate emails
        to_emails = list(set([email.strip() for email in to_emails if email.strip()]))
        
        # Use SendGrid API directly
        if SENDGRID_AVAILABLE:
            if not hasattr(settings, 'SENDGRID_API_KEY') or not settings.SENDGRID_API_KEY:
                result['error'] = "SENDGRID_API_KEY not configured"
                return result
            
            sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
            
            from_email = Email(settings.DEFAULT_FROM_EMAIL)
            to_emails_list = [To(email) for email in to_emails]
            
            # Create content
            if html_message:
                content = Content("text/html", html_message)
            else:
                content = Content("text/plain", message)
            
            # Send to multiple recipients
            successful_sends = 0
            errors = []
            
            for to_email in to_emails_list:
                try:
                    mail = Mail(from_email, to_email, subject, content)
                    
                    # Add plain text alternative if sending HTML
                    if html_message:
                        mail.add_content(Content("text/plain", message))
                    
                    response = await sync_to_async(sg.send)(mail)
                    
                    if response.status_code in [200, 202]:
                        successful_sends += 1
                        result['message_id'] = response.headers.get('X-Message-Id', 'Unknown')
                        logger.info(f"Email sent successfully to {to_email.email}. Message ID: {result['message_id']}")
                    else:
                        error_msg = f"SendGrid API error: {response.status_code} - {response.body}"
                        errors.append(error_msg)
                        logger.error(f"Failed to send email to {to_email.email}: {error_msg}")
                        
                except Exception as e:
                    error_msg = f"Failed to send email to {to_email.email}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)
            
            result['success'] = successful_sends > 0
            if errors:
                result['error'] = "; ".join(errors)
        
        # Fallback to Django's send_mail
        else:
            send_mail(
                subject=subject,
                message=message,
                html_message=html_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=to_emails,
                fail_silently=False,
            )
            
            result['success'] = True
            result['message_id'] = "django-fallback-sent"
            logger.info(f"Email sent via Django fallback to {len(to_emails)} recipients")
            
    except Exception as e:
        error_msg = f"Failed to send email: {str(e)}"
        result['error'] = error_msg
        logger.error(error_msg, exc_info=True)
    
    return result

def send_email_sync(
    to_emails: List[str], 
    subject: str, 
    message: str, 
    html_message: Optional[str] = None
) -> Dict[str, Any]:
    """
    Synchronous wrapper for email sending
    """
    try:
        return asyncio.run(send_email_async(to_emails, subject, message, html_message))
    except Exception as e:
        logger.error(f"Error in synchronous email send: {str(e)}")
        return {'success': False, 'error': str(e)}

# ===== SMS FUNCTIONS =====

def send_sms_mock(to_phones: List[str], message: str) -> Dict[str, Any]:
    """
    Mock SMS function for development - logs instead of sending real SMS
    """
    result = {'success': True, 'message_id': 'mock-sms-id', 'error': None}
    
    logger.info(f"📱 MOCK SMS - Would send to: {to_phones}")
    logger.info(f"📱 MOCK SMS Message: {message}")
    
    for phone in to_phones:
        logger.info(f"📱 MOCK: SMS sent to {phone}: {message[:50]}...")
    
    # Also print to console for visibility
    print(f"📱 MOCK SMS sent to {to_phones}")
    print(f"📱 Message: {message}")
    
    return result

async def send_sms_async(
    to_phones: List[str], 
    message: str
) -> Dict[str, Any]:
    """
    Send SMS asynchronously using Twilio
    Returns: {'success': bool, 'message_sid': str, 'error': str}
    """
    result = {'success': False, 'message_sid': None, 'error': None}
    
    if not to_phones:
        result['error'] = "No recipient phone numbers provided"
        return result
    
    # Check if Twilio is available
    if not TWILIO_AVAILABLE:
        result['error'] = "Twilio not available"
        return result
    
    # Check if Twilio settings are configured
    if not all([hasattr(settings, 'TWILIO_ACCOUNT_SID'), 
                hasattr(settings, 'TWILIO_AUTH_TOKEN'),
                hasattr(settings, 'TWILIO_PHONE_NUMBER')]):
        result['error'] = "Twilio configuration missing in settings"
        return result
    
    if not all([settings.TWILIO_ACCOUNT_SID, 
                settings.TWILIO_AUTH_TOKEN, 
                settings.TWILIO_PHONE_NUMBER]):
        result['error'] = "Twilio credentials not set in environment variables"
        return result
    
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        successful_sends = 0
        errors = []
        
        for phone in to_phones:
            try:
                # Format phone number (ensure E.164 format)
                formatted_phone = phone
                if not phone.startswith('+'):
                    formatted_phone = f"+1{phone}"  # Default to US
                
                # Send SMS
                twilio_message = await sync_to_async(client.messages.create)(
                    body=message,
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=formatted_phone
                )
                
                if twilio_message.sid:
                    successful_sends += 1
                    result['message_sid'] = twilio_message.sid
                    logger.info(f"SMS sent successfully to {formatted_phone}. SID: {twilio_message.sid}")
                else:
                    errors.append(f"Twilio returned no SID for {formatted_phone}")
                    
            except TwilioRestException as e:
                error_msg = f"Twilio error for {formatted_phone}: {e.msg} (Code: {e.code})"
                errors.append(error_msg)
                logger.error(error_msg)
            except Exception as e:
                error_msg = f"Unexpected error sending to {formatted_phone}: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        result['success'] = successful_sends > 0
        if errors:
            result['error'] = "; ".join(errors)
            
    except Exception as e:
        error_msg = f"Failed to send SMS: {str(e)}"
        result['error'] = error_msg
        logger.error(error_msg, exc_info=True)
    
    return result

def send_sms_sync(to_phones: List[str], message: str) -> Dict[str, Any]:
    """
    Synchronous wrapper for SMS sending
    """
    # Use mock SMS for development - comment out when ready for production
    return send_sms_mock(to_phones, message)
    
    # Uncomment this when you fix Twilio credentials:
    # try:
    #     return asyncio.run(send_sms_async(to_phones, message))
    # except Exception as e:
    #     logger.error(f"Error in synchronous SMS send: {str(e)}")
    #     return {'success': False, 'error': str(e)}

# ===== NOTIFICATION MANAGEMENT =====

def create_in_app_notification(
    user, 
    title: str, 
    message: str, 
    notification_type: str = "info",
    related_object=None
) -> bool:
    """
    Create an in-app notification for a user
    """
    try:
        from account.models import Notification
        notification = Notification(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
            related_object=related_object,
        )
        notification.save()
        return True
    except Exception as e:
        logger.error(f"Failed to create in-app notification for {user}: {str(e)}")
        return False

def create_bulk_in_app_notifications(
    users, 
    title: str, 
    message: str, 
    notification_type: str = "info",
    related_object=None
) -> int:
    """
    Create in-app notifications for multiple users
    Returns: number of notifications created
    """
    created_count = 0
    try:
        from account.models import Notification
        notifications = []
        for user in users:
            notifications.append(Notification(
                user=user,
                title=title,
                message=message,
                notification_type=notification_type,
                related_object=related_object,
            ))
        
        # Bulk create for efficiency
        Notification.objects.bulk_create(notifications)
        created_count = len(notifications)
        logger.info(f"Created {created_count} in-app notifications")
        
    except Exception as e:
        logger.error(f"Failed to create bulk notifications: {str(e)}")
    
    return created_count

# ===== MAIN NOTIFICATION FUNCTION =====

async def send_notification_async(
    emails: List[str] = None,
    phones: List[str] = None,
    users = None,
    subject: str = "",
    message: str = "",
    html_message: Optional[str] = None,
    create_in_app: bool = True,
    notification_type: str = "info",
    related_object=None
) -> Dict[str, Any]:
    """
    Main notification function that handles email, SMS, and in-app notifications asynchronously
    Returns comprehensive results dictionary
    """
    emails = emails or []
    phones = phones or []
    users = users or []
    
    results = {
        'email_sent': False,
        'sms_sent': False,
        'in_app_created': 0,
        'email_error': None,
        'sms_error': None,
        'in_app_error': None,
        'notifications_created': 0,
        'emails_queued': 0,
        'sms_sent_count': 0
    }
    
    try:
        # Send emails asynchronously
        if emails and subject and message:
            email_result = await send_email_async(emails, subject, message, html_message)
            results['email_sent'] = email_result['success']
            results['emails_queued'] = len(emails) if email_result['success'] else 0
            results['email_error'] = email_result.get('error')
        
        # Send SMS asynchronously
        if phones and message:
            sms_result = await send_sms_async(phones, message)
            results['sms_sent'] = sms_result['success']
            results['sms_sent_count'] = len(phones) if sms_result['success'] else 0
            results['sms_error'] = sms_result.get('error')
        
        # Create in-app notifications
        if create_in_app and users:
            if hasattr(users, '__iter__') and not isinstance(users, str):
                # Multiple users
                results['in_app_created'] = await sync_to_async(create_bulk_in_app_notifications)(
                    users, subject or "Notification", message, notification_type, related_object
                )
            else:
                # Single user
                success = await sync_to_async(create_in_app_notification)(
                    users, subject or "Notification", message, notification_type, related_object
                )
                results['in_app_created'] = 1 if success else 0
        
        results['notifications_created'] = results['in_app_created']
        
        # Log results
        logger.info(
            f"Notification results - Emails: {results['emails_queued']}, "
            f"SMS: {results['sms_sent_count']}, In-app: {results['in_app_created']}"
        )
        
    except Exception as e:
        logger.error(f"Error in send_notification: {str(e)}", exc_info=True)
        results['general_error'] = str(e)
    
    return results

def send_notification(
    emails: List[str] = None,
    phones: List[str] = None,
    users = None,
    subject: str = "",
    message: str = "",
    html_message: Optional[str] = None,
    create_in_app: bool = True,
    notification_type: str = "info",
    related_object=None
) -> Dict[str, Any]:
    """
    Synchronous wrapper for the main notification function
    """
    try:
        return asyncio.run(send_notification_async(
            emails=emails,
            phones=phones,
            users=users,
            subject=subject,
            message=message,
            html_message=html_message,
            create_in_app=create_in_app,
            notification_type=notification_type,
            related_object=related_object
        ))
    except Exception as e:
        logger.error(f"Error in synchronous notification send: {str(e)}")
        return {'general_error': str(e)}

# ===== ANNOUNCEMENT SPECIFIC FUNCTIONS =====

async def send_announcement_via_email_and_sms_async(announcement) -> Dict[str, Any]:
    """
    Send announcement to all school members via email and SMS
    """
    school = announcement.school
    results = {
        'notifications_created': 0,
        'emails_queued': 0,
        'sms_sent': 0,
        'errors': []
    }
    
    try:
        # Get all contacts for the school
        teacher_emails, teacher_phones = await sync_to_async(get_all_teachers_contacts)(school)
        student_emails, student_phones = await sync_to_async(get_all_students_parents_contacts)(school)
        
        all_emails = teacher_emails + student_emails
        all_phones = teacher_phones + student_phones
        
        # Remove duplicates
        all_emails = list(set(all_emails))
        all_phones = list(set(all_phones))
        
        # Prepare message
        subject = f"Announcement: {announcement.title}"
        message_content = f"{announcement.content}\n\n- {school.name} Administration"
        
        # Create HTML version for email
        html_message = render_to_string('emails/announcement.html', {
            'announcement': announcement,
            'school': school
        })
        
        # Send notifications
        notification_results = await send_notification_async(
            emails=all_emails,
            phones=all_phones,
            subject=subject,
            message=message_content,
            html_message=html_message,
            create_in_app=True,
            notification_type="announcement",
            related_object=announcement
        )
        
        # Update results
        results.update(notification_results)
        
        # Collect errors
        if notification_results.get('email_error'):
            results['errors'].append(f"Email: {notification_results['email_error']}")
        if notification_results.get('sms_error'):
            results['errors'].append(f"SMS: {notification_results['sms_error']}")
            
    except Exception as e:
        error_msg = f"Failed to send announcement: {str(e)}"
        results['errors'].append(error_msg)
        logger.error(error_msg, exc_info=True)
    
    return results

def send_announcement_via_email_and_sms(announcement) -> Dict[str, Any]:
    """
    Synchronous wrapper for announcement sending
    """
    try:
        return asyncio.run(send_announcement_via_email_and_sms_async(announcement))
    except Exception as e:
        logger.error(f"Error in synchronous announcement send: {str(e)}")
        return {'errors': [str(e)]}

# ===== SIMPLIFIED SMS FUNCTION (for direct use) =====

def send_sms(to_phones: List[str], message: str) -> bool:
    """
    Simplified SMS function for direct use in views
    Returns: True if at least one SMS was sent successfully
    """
    try:
        result = send_sms_sync(to_phones, message)
        return result.get('success', False)
    except Exception as e:
        logger.error(f"Error in simplified SMS send: {str(e)}")
        return False