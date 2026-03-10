
import logging
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from asgiref.sync import sync_to_async
from account.models import CustomUser
from django.db.models import Q

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

# ===== PASSWORD GENERATION =====

def generate_default_password() -> str:
    """Default password for new teacher/student registrations."""
    return "Abc@12345"

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

async def send_email_async(to_emails: List[str], subject: str, message: str, html_message: Optional[str] = None) -> Dict[str, Any]:
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
            
            sg = SendGridAPIClient(settings.SENDGRID_API_KEY) # type: ignore
            
            from_email = Email(settings.DEFAULT_FROM_EMAIL) # type: ignore
            
            to_emails_list = [To(email) for email in to_emails] # type: ignore
            
            
            # Create content
            if html_message:
                content = Content("text/html", html_message) # type: ignore
            
            else:
                content = Content("text/plain", message) # type: ignore
            
            
            # Send to multiple recipients
            successful_sends = 0
            errors = []
            
            for to_email in to_emails_list:
                try:
                    mail = Mail(from_email, to_email, subject, content)  # type: ignore
                    
                    # Add plain text alternative if sending HTML
                    if html_message:
                        mail.add_content(Content("text/plain", message))  # type: ignore
                    
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

def send_email_sync(to_emails: List[str], subject: str, message: str, html_message: Optional[str] = None) -> Dict[str, Any]:
    """
    Synchronous email sending (no asyncio).
    """
    result = {'success': False, 'message_id': None, 'error': None}

    if not to_emails:
        result['error'] = "No recipient emails provided"
        return result

    try:
        to_emails = list(set([email.strip() for email in to_emails if email.strip()]))

        if SENDGRID_AVAILABLE and getattr(settings, "SENDGRID_API_KEY", None):
            sg = SendGridAPIClient(settings.SENDGRID_API_KEY)  # type: ignore
            from_email = Email(settings.DEFAULT_FROM_EMAIL)  # type: ignore
            to_emails_list = [To(email) for email in to_emails]  # type: ignore
            content = Content("text/html", html_message) if html_message else Content("text/plain", message)  # type: ignore

            successful_sends = 0
            errors = []
            for to_email in to_emails_list:
                try:
                    mail = Mail(from_email, to_email, subject, content)  # type: ignore
                    if html_message:
                        mail.add_content(Content("text/plain", message))  # type: ignore
                    response = sg.send(mail)  # type: ignore
                    if response.status_code in [200, 202]:
                        successful_sends += 1
                        result['message_id'] = response.headers.get('X-Message-Id', 'Unknown')
                    else:
                        errors.append(f"SendGrid API error: {response.status_code} - {response.body}")
                except Exception as e:
                    errors.append(f"Failed to send email to {to_email.email}: {str(e)}")

            result['success'] = successful_sends > 0
            if errors:
                result['error'] = "; ".join(errors)
            return result

        # Fallback to Django email backend (console in dev)
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
        return result

    except Exception as e:
        error_msg = f"Failed to send email: {str(e)}"
        result['error'] = error_msg
        logger.error(error_msg, exc_info=True)
        return result

# ===== SMS FUNCTIONS =====

def send_sms_mock(to_phones: List[str], message: str) -> Dict[str, Any]:
    """
    Mock SMS function for development - logs instead of sending real SMS
    """
    result = {'success': True, 'message_id': 'mock-sms-id', 'error': None}
    
    logger.info(f"MOCK SMS - Would send to: {to_phones}")
    logger.info(f"MOCK SMS Message: {message}")
    
    for phone in to_phones:
        logger.info(f"📱 MOCK: SMS sent to {phone}: {message[:50]}...")
    
    # Also print to console for visibility
    print(f"📱 MOCK SMS sent to {to_phones}")
    print(f"📱 Message: {message}")
    
    return result

async def send_sms_async(to_phones: List[str], message: str) -> Dict[str, Any]:
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
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)  # type: ignore
        
        successful_sends = 0
        errors = []
        
        for phone in to_phones:
            try:
                # Format phone number for GHANA (+233 country code)
                formatted_phone = phone
                if not phone.startswith('+'):
                    # Remove leading 0 and add +233 for Ghana
                    if phone.startswith('0'):
                        formatted_phone = f"+233{phone[1:]}"
                    else:
                        formatted_phone = f"+233{phone}"
                elif phone.startswith('+1'):
                    # Convert from wrong US format to Ghana format
                    # +10540501163 → +233540501163
                    formatted_phone = f"+233{phone[3:]}"
                
                logger.info(f"📱 Sending SMS to {formatted_phone} (original: {phone})")
                
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
                    
            except TwilioRestException as e:  # type: ignore
                if e.code == 21211:  # Invalid phone number
                    error_msg = f"Invalid phone number format: {formatted_phone}. Ghana numbers should start with +233"  # type: ignore
                elif e.code == 21608:  # Phone number not verified (for trial accounts)
                    error_msg = f"Phone number {formatted_phone} not verified in Twilio trial account"  # type: ignore
                elif e.code == 20003:  # Authentication error
                    error_msg = f"Twilio authentication failed: Invalid Account SID or Auth Token"  # type: ignore
                else:
                    error_msg = f"Twilio error for {formatted_phone}: {e.msg} (Code: {e.code})"  # type: ignore
                
                errors.append(error_msg)
                logger.error(error_msg)
            except Exception as e:
                error_msg = f"Unexpected error sending to {formatted_phone}: {str(e)}"  # type: ignore
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
    Synchronous SMS sending (no asyncio).
    """
    result = {'success': False, 'message_sid': None, 'error': None}

    if not to_phones:
        result['error'] = "No recipient phone numbers provided"
        return result

    if not TWILIO_AVAILABLE:
        result['error'] = "Twilio not available"
        return result

    if not all([getattr(settings, "TWILIO_ACCOUNT_SID", None),
                getattr(settings, "TWILIO_AUTH_TOKEN", None),
                getattr(settings, "TWILIO_PHONE_NUMBER", None)]):
        result['error'] = "Twilio credentials not set in environment variables"
        return result

    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)  # type: ignore
        successful_sends = 0
        errors = []

        for phone in to_phones:
            try:
                formatted_phone = phone
                if not phone.startswith('+'):
                    if phone.startswith('0'):
                        formatted_phone = f"+233{phone[1:]}"
                    else:
                        formatted_phone = f"+233{phone}"
                message_obj = client.messages.create(
                    body=message,
                    from_=settings.TWILIO_PHONE_NUMBER,  # type: ignore
                    to=formatted_phone
                )
                result['message_sid'] = message_obj.sid
                successful_sends += 1
            except Exception as e:
                errors.append(str(e))

        result['success'] = successful_sends > 0
        if errors:
            result['error'] = "; ".join(errors)
        return result

    except Exception as e:
        error_msg = f"Failed to send SMS: {str(e)}"
        result['error'] = error_msg
        logger.error(error_msg, exc_info=True)
        return result

# ===== NOTIFICATION MANAGEMENT =====

def create_in_app_notification(
    user, 
    title: str, 
    message: str, 
    notification_type: str = "info",
    related_object=None,
    link: str = ""
) -> bool:
    """
    Create an in-app notification for a user
    """
    try:
        from account.models import Notification
        field_names = {f.name for f in Notification._meta.fields}
        notification_kwargs = {
            "user": user,
            "title": title,
            "message": message,
            "notification_type": notification_type,
        }
        if "related_object" in field_names:
            notification_kwargs["related_object"] = related_object
        if "link" in field_names:
            notification_kwargs["link"] = link or ""
        notification = Notification(**notification_kwargs)
        notification.save()
        logger.info(
            "In-app notification created for %s: %s",
            getattr(user, "username", user),
            title,
        )
        return True
    except Exception as e:
        logger.error(f"Failed to create in-app notification for {user}: {str(e)}")
        return False

def create_bulk_in_app_notifications(
    users, 
    title: str, 
    message: str, 
    notification_type: str = "info",
    related_object=None,
    link: str = ""
) -> int:
    """
    Create in-app notifications for multiple users
    Returns: number of notifications created
    """
    created_count = 0
    try:
        from account.models import Notification
        field_names = {f.name for f in Notification._meta.fields}
        notifications = []
        for user in users:
            notification_kwargs = {
                "user": user,
                "title": title,
                "message": message,
                "notification_type": notification_type,
            }
            if "related_object" in field_names:
                notification_kwargs["related_object"] = related_object
            if "link" in field_names:
                notification_kwargs["link"] = link or ""
            notifications.append(Notification(**notification_kwargs))
        
        # Bulk create for efficiency
        Notification.objects.bulk_create(notifications)
        created_count = len(notifications)
        logger.info(f"Created {created_count} in-app notifications")
        
    except Exception as e:
        logger.error(f"Failed to create bulk notifications: {str(e)}")
    
    return created_count

# ===== MAIN NOTIFICATION FUNCTION =====

async def send_notification_async(
    emails: List[str] = None,  # type: ignore
    phones: List[str] = None,  # type: ignore
    users = None,
    subject: str = "",
    message: str = "",
    html_message: Optional[str] = None,
    create_in_app: bool = True,
    notification_type: str = "info",
    related_object=None,
    link: str = ""
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
        # Queue emails via Celery
        if emails and subject and message:
            try:
                from celery import current_app
                current_app.send_task(
                    "adminservices.tasks.send_email_task",
                    args=[emails, subject, message, html_message],
                )
                results['email_sent'] = True
                results['emails_queued'] = len(emails)
            except Exception as e:
                results['email_error'] = str(e)
        
        # Queue SMS via Celery
        if phones and message:
            try:
                from celery import current_app
                current_app.send_task(
                    "adminservices.tasks.send_sms_task",
                    args=[phones, message],
                )
                results['sms_sent'] = True
                results['sms_sent_count'] = len(phones)
            except Exception as e:
                results['sms_error'] = str(e)
        
        # Create in-app notifications
        if create_in_app and users:
            if hasattr(users, '__iter__') and not isinstance(users, str):
                # Multiple users
                results['in_app_created'] = await sync_to_async(create_bulk_in_app_notifications)(
                    users, subject or "Notification", message, notification_type, related_object, link
                )
            else:
                # Single user
                success = await sync_to_async(create_in_app_notification)(
                    users, subject or "Notification", message, notification_type, related_object, link
                )
                results['in_app_created'] = 1 if success else 0
        
        results['notifications_created'] = results['in_app_created']
        
        # Log results
        logger.info(
            f"Notification results - Emails queued: {results['emails_queued']}, "
            f"SMS queued: {results['sms_sent_count']}, In-app: {results['in_app_created']}"
        )
        
    except Exception as e:
        logger.error(f"Error in send_notification: {str(e)}", exc_info=True)
        results['general_error'] = str(e)
    
    return results

def send_notification(
    emails: List[str] = None,  # type: ignore
    phones: List[str] = None,  # type: ignore
    users = None,
    subject: str = "",
    message: str = "",
    html_message: Optional[str] = None,
    create_in_app: bool = True,
    notification_type: str = "info",
    related_object=None,
    link: str = ""
) -> Dict[str, Any]:
    """
    Synchronous notification function (no asyncio).
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
        if emails and subject and message:
            try:
                from celery import current_app
                current_app.send_task(
                    "adminservices.tasks.send_email_task",
                    args=[emails, subject, message, html_message],
                )
                results['email_sent'] = True
                results['emails_queued'] = len(emails)
            except Exception as e:
                results['email_error'] = str(e)

        if phones and message:
            try:
                from celery import current_app
                current_app.send_task(
                    "adminservices.tasks.send_sms_task",
                    args=[phones, message],
                )
                results['sms_sent'] = True
                results['sms_sent_count'] = len(phones)
            except Exception as e:
                results['sms_error'] = str(e)

        if create_in_app and users:
            if hasattr(users, '__iter__') and not isinstance(users, str):
                results['in_app_created'] = create_bulk_in_app_notifications(
                    users, subject or "Notification", message, notification_type, related_object, link
                )
            else:
                success = create_in_app_notification(
                    users, subject or "Notification", message, notification_type, related_object, link
                )
                results['in_app_created'] = 1 if success else 0

        results['notifications_created'] = results['in_app_created']

    except Exception as e:
        logger.error(f"Error in synchronous notification send: {str(e)}")
        results['general_error'] = str(e)

    return results

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
        
        # Create HTML version for email with current year
        from django.utils import timezone
        html_message = render_to_string('emails/announcement.html', {
            'announcement': announcement,
            'school': school,
            'target_audience': 'all',
            'current_year': timezone.now().year
        })
        
        # Build in-app recipient users for the school (admins, teachers, students)
        users = CustomUser.objects.filter(  # type: ignore
            Q(managed_school=school) |
            Q(teacher_profile__school=school, teacher_profile__is_active=True) |
            Q(student_profile__school=school, student_profile__is_active=True)
        ).distinct()

        # Send notifications
        notification_results = await send_notification_async(
            emails=all_emails,
            phones=all_phones,
            users=users,
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
        if results['errors']:
            logger.warning(
                "Announcement notification errors (all): %s",
                "; ".join(results['errors'])
            )
            
    except Exception as e:
        error_msg = f"Failed to send announcement: {str(e)}"
        results['errors'].append(error_msg)
        logger.error(error_msg, exc_info=True)
    
    return results


def send_announcement_via_email_and_sms(announcement) -> Dict[str, Any]:
    """
    Send announcement to all school members via email, SMS, and in-app (sync).
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
        teacher_emails, teacher_phones = get_all_teachers_contacts(school)
        student_emails, student_phones = get_all_students_parents_contacts(school)

        all_emails = list(set(teacher_emails + student_emails))
        all_phones = list(set(teacher_phones + student_phones))

        subject = f"Announcement: {announcement.title}"
        message_content = f"{announcement.content}\n\n- {school.name} Administration"

        from django.utils import timezone
        html_message = render_to_string('emails/announcement.html', {
            'announcement': announcement,
            'school': school,
            'target_audience': 'all',
            'current_year': timezone.now().year
        })

        users = CustomUser.objects.filter(  # type: ignore
            Q(managed_school=school) |
            Q(teacher_profile__school=school, teacher_profile__is_active=True) |
            Q(student_profile__school=school, student_profile__is_active=True)
        ).distinct()

        notification_results = send_notification(
            emails=all_emails,
            phones=all_phones,
            users=users,
            subject=subject,
            message=message_content,
            html_message=html_message,
            create_in_app=True,
            notification_type="announcement",
            related_object=announcement
        )

        results.update(notification_results)

        if notification_results.get('email_error'):
            results['errors'].append(f"Email: {notification_results['email_error']}")
        if notification_results.get('sms_error'):
            results['errors'].append(f"SMS: {notification_results['sms_error']}")
        if results['errors']:
            logger.warning(
                "Announcement notification errors (all): %s",
                "; ".join(results['errors'])
            )

    except Exception as e:
        error_msg = f"Failed to send announcement: {str(e)}"
        results['errors'].append(error_msg)
        logger.error(error_msg, exc_info=True)

    return results

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
    
    
def send_targeted_announcement(announcement, target_audience: str) -> Dict[str, Any]:
    """
    Send announcement to specific target audience (students, teachers, parents)
    Returns: {'notifications_created': int, 'emails_queued': int, 'sms_sent': int, 'errors': List[str]}
    """
    school = announcement.school
    results = {
        'notifications_created': 0,
        'emails_queued': 0,
        'sms_sent': 0,
        'errors': []
    }
    
    try:
        # Get contacts based on target audience
        if target_audience == 'teachers':
            emails, phones = get_all_teachers_contacts(school)
            users = CustomUser.objects.filter(  # type: ignore
                teacher_profile__school=school, 
                teacher_profile__is_active=True
            )
            
        elif target_audience == 'students':
            emails, phones = get_all_students_contacts(school)
            users = CustomUser.objects.filter(  # type: ignore
                student_profile__school=school, 
                student_profile__is_active=True
            )
            
        elif target_audience == 'parents':
            emails, phones = get_all_parents_contacts(school)
            users = CustomUser.objects.filter(  # type: ignore
                parent_profile__students__school=school
            ).distinct()
            
        else:  # all or unknown
            emails, phones = get_all_contacts(school)
            users = CustomUser.objects.filter(  # type: ignore
                Q(teacher_profile__school=school, teacher_profile__is_active=True) | 
                Q(student_profile__school=school, student_profile__is_active=True) |
                Q(parent_profile__students__school=school)
            ).distinct()
        
        # Remove duplicates
        emails = list(set(emails))
        phones = list(set(phones))
        
        # Prepare message
        subject = f"Announcement: {announcement.title}"
        message_content = f"{announcement.content}\n\n- {school.name} Administration"
        
        # Create HTML version for email
        html_message = render_to_string('emails/announcement.html', {
            'announcement': announcement,
            'school': school,
            'target_audience': target_audience
        })
        
        # Send notifications
        notification_results = send_notification(
            emails=emails,
            phones=phones,
            users=users,
            subject=subject,
            message=message_content,
            html_message=html_message,
            create_in_app=True,
            notification_type="announcement",
            related_object=announcement
        )
        
        # Update results
        results.update(notification_results)
        
        # Log the targeting
        logger.info(f"Targeted announcement sent to {target_audience}: "
                   f"{len(emails)} emails, {len(phones)} phones, {users.count()} users")
        
        # Collect errors
        if notification_results.get('email_error'):
            results['errors'].append(f"Email: {notification_results['email_error']}")
        if notification_results.get('sms_error'):
            results['errors'].append(f"SMS: {notification_results['sms_error']}")
        if results['errors']:
            logger.warning(
                "Announcement notification errors (%s): %s",
                target_audience,
                "; ".join(results['errors'])
            )
            
    except Exception as e:
        error_msg = f"Failed to send targeted announcement to {target_audience}: {str(e)}"
        results['errors'].append(error_msg)
        logger.error(error_msg, exc_info=True)
    
    return results

def get_all_students_contacts(school) -> Tuple[List[str], List[str]]:
    """
    Get all students' email and phone contacts
    """
    emails = []
    phones = []
    
    try:
        from account.models import Student
        students = Student.objects.filter(school=school, is_active=True).select_related('user')
        
        for student in students:
            if student.user.email:
                emails.append(student.user.email)
            if student.user.phone_number:
                phones.append(student.user.phone_number)
                
    except Exception as e:
        logger.error(f"Error getting students contacts for school {school}: {str(e)}")
    
    return emails, phones

def get_all_parents_contacts(school) -> Tuple[List[str], List[str]]:
    """
    Get all parents' email and phone contacts
    """
    emails = []
    phones = []
    
    try:
        from account.models import Student
        students = Student.objects.filter(school=school, is_active=True).select_related('parent')
        
        for student in students:
            if student.parent:
                parent = student.parent
                # Father's contacts
                if parent.father_email:
                    emails.append(parent.father_email)
                if parent.father_phone:
                    phones.append(parent.father_phone)
                # Mother's contacts
                if parent.mother_email:
                    emails.append(parent.mother_email)
                if parent.mother_phone:
                    phones.append(parent.mother_phone)
                
    except Exception as e:
        logger.error(f"Error getting parents contacts for school {school}: {str(e)}")
    
    return emails, phones

def get_all_contacts(school) -> Tuple[List[str], List[str]]:
    """
    Get all contacts (teachers, students, parents) for the school
    """
    teacher_emails, teacher_phones = get_all_teachers_contacts(school)
    student_emails, student_phones = get_all_students_contacts(school)
    parent_emails, parent_phones = get_all_parents_contacts(school)
    
    all_emails = teacher_emails + student_emails + parent_emails
    all_phones = teacher_phones + student_phones + parent_phones
    
    # Remove duplicates
    return list(set(all_emails)), list(set(all_phones))
