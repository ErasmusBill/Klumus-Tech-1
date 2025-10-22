import logging
import time
from threading import Thread
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from account.models import CustomUser, Teacher, Student, Parent, Notification

logger = logging.getLogger(__name__)

# ========================
# ASYNC EMAIL HELPERS
# ========================

def send_email_async(subject, message, recipient_list, from_email=None):
    """
    Send email in a background thread to avoid blocking requests.
    """
    def _send():
        try:
            result = send_mail(
                subject=subject,
                message=message,
                from_email=from_email or settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipient_list,
                fail_silently=False,
            )
            logger.info(f"✅ Email sent successfully to {len(recipient_list)} recipients")
            return result
        except Exception as e:
            logger.error(f"❌ Failed to send email to {recipient_list}: {str(e)}")
            return 0
    
    thread = Thread(target=_send)
    thread.daemon = True
    thread.start()
    return True

def send_email_async_with_retry(subject, message, recipient_list, max_retries=3, from_email=None):
    """
    Send email in background thread with retry logic to handle timeouts
    """
    def _send_with_retry():
        for attempt in range(max_retries):
            try:
                result = send_mail(
                    subject=subject,
                    message=message,
                    from_email=from_email or settings.DEFAULT_FROM_EMAIL,
                    recipient_list=recipient_list,
                    fail_silently=False,
                )
                logger.info(f"✅ Email sent successfully to {len(recipient_list)} recipients (attempt {attempt + 1})")
                return result
                
            except Exception as e:
                logger.warning(f"⚠️ Email attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5  # 5, 10, 15 seconds
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"❌ All email attempts failed for {recipient_list}: {str(e)}")
                    return 0
    
    thread = Thread(target=_send_with_retry)
    thread.daemon = True
    thread.start()
    return True

# ========================
# ANNOUNCEMENT SENDING
# ========================

def send_announcement_via_email_and_sms(announcement):
    """
    Send announcement to selected audience via:
    - In-app Notification
    - Email (async)
    - SMS (Twilio)
    """
    if not announcement.published:
        logger.info(f"Announcement '{announcement.title}' is not published. Skipping send.")
        return

    now = timezone.now()
    if announcement.publish_date and now < announcement.publish_date:
        logger.info(f"Announcement '{announcement.title}' scheduled for future. Skipping send.")
        return

    if announcement.expiry_date and now > announcement.expiry_date:
        logger.info(f"Announcement '{announcement.title}' has expired. Skipping send.")
        return

    school = announcement.school
    audience = announcement.target_audience

    # Build recipient queryset based on audience
    recipients = get_announcement_recipients(school, audience)
    
    logger.info(f"Announcement '{announcement.title}' (ID: {announcement.id}) sending to {recipients.count()} recipients.")

    short_msg = (announcement.content[:150] + "...") if len(announcement.content) > 150 else announcement.content

    # Initialize Twilio client
    twilio_client = None
    if is_twilio_configured():
        try:
            twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        except Exception as e:
            logger.warning(f"Twilio client initialization failed: {e}")

    results = {
        'notifications_created': 0,
        'emails_queued': 0,
        'sms_sent': 0,
        'errors': []
    }

    # Collect all emails for batch sending
    email_recipients = []

    for user in recipients:
        logger.info(f"Processing recipient: {user.username} (Email: {user.email}, Phone: {_get_user_phone(user)})")

        # 1. In-app notification
        try:
            Notification.objects.create(
                user=user,
                notification_type="announcement",
                title=announcement.title,
                message=short_msg,
                link=f"/announcements/{announcement.id}/",
            )
            results['notifications_created'] += 1
        except Exception as e:
            error_msg = f"Failed to create notification for user {user.id}: {e}"
            logger.error(error_msg)
            results['errors'].append(error_msg)

        # 2. Collect email addresses
        if user.email:
            email_recipients.append(user.email)

        # 3. SMS
        phone = _get_user_phone(user)
        if phone and twilio_client:
            clean_phone = _normalize_phone(phone)
            if clean_phone:
                try:
                    twilio_client.messages.create(
                        body=f"📢 {announcement.title}\n{short_msg}",
                        from_=settings.TWILIO_PHONE_NUMBER,
                        to=clean_phone,
                    )
                    logger.info(f"SMS sent to {clean_phone}")
                    results['sms_sent'] += 1
                except TwilioRestException as e:
                    error_msg = f"SMS failed to {phone} (normalized: {clean_phone}) for user {user.id}: {e.msg}"
                    logger.error(error_msg)
                    results['errors'].append(error_msg)
                except Exception as e:
                    error_msg = f"SMS failed to {phone} (normalized: {clean_phone}) for user {user.id}: {e}"
                    logger.error(error_msg)
                    results['errors'].append(error_msg)

    # Send all emails asynchronously in one batch
    if email_recipients:
        try:
            send_email_async_with_retry(
                subject=f"📢 Announcement: {announcement.title}",
                message=announcement.content,
                recipient_list=email_recipients,
                max_retries=3
            )
            results['emails_queued'] = len(email_recipients)
            logger.info(f"✉️ Queued emails for {len(email_recipients)} recipients with retry logic")
        except Exception as e:
            error_msg = f"Failed to queue emails: {e}"
            logger.error(error_msg)
            results['errors'].append(error_msg)

    logger.info(f"Announcement sending completed: {results}")
    return results


def get_announcement_recipients(school, audience):
    """Get recipients based on audience type"""
    if audience == "all":
        teachers = CustomUser.objects.filter(teacher_profile__school=school, is_active=True)
        students = CustomUser.objects.filter(student_profile__school=school, is_active=True)
        parents = CustomUser.objects.filter(
            parent_profile__students__school=school,
            is_active=True
        ).distinct()
        return (teachers | students | parents).distinct()

    elif audience == "teachers":
        return CustomUser.objects.filter(teacher_profile__school=school, is_active=True)

    elif audience == "students":
        return CustomUser.objects.filter(student_profile__school=school, is_active=True)

    elif audience == "parents":
        return CustomUser.objects.filter(
            parent_profile__students__school=school,
            is_active=True
        ).distinct()

    elif audience == "staff":
        admins = CustomUser.objects.filter(managed_school=school, is_active=True)
        teachers = CustomUser.objects.filter(teacher_profile__school=school, is_active=True)
        return (admins | teachers).distinct()

    else:
        return CustomUser.objects.none()


# ========================
# PHONE HELPERS
# ========================

def _get_user_phone(user):
    """Extract the best available phone number for a user."""
    # Primary phone from CustomUser
    if user.phone_number:
        return user.phone_number

    # Parent: try father, mother, or emergency contact
    if hasattr(user, 'parent_profile'):
        p = user.parent_profile
        return p.father_phone or p.mother_phone or p.emergency_contact_phone

    # Student: get parent's phone
    if hasattr(user, 'student_profile'):
        student = user.student_profile
        if student.parent:
            p = student.parent
            return p.father_phone or p.mother_phone or p.emergency_contact_phone

    # Teacher: only user.phone_number (already checked)
    return None


def _normalize_phone(phone):
    """
    Normalize phone number to E.164 format.
    Assumes Ghana numbers (country code +233).
    """
    if not phone:
        return None

    # Remove all non-digits
    digits = ''.join(filter(str.isdigit, phone))
    if not digits:
        return None

    # Ghana-specific normalization
    if len(digits) == 10 and digits.startswith('0'):
        return '+233' + digits[1:]
    elif len(digits) == 9:
        return '+233' + digits
    elif digits.startswith('233') and len(digits) in (11, 12):
        return '+' + digits[-12:] if len(digits) == 12 else '+233' + digits[3:]
    elif digits.startswith('+'):
        return digits
    elif len(digits) >= 10:
        return '+' + digits[-12:]  # Keep last 12 digits max

    return None


# ========================
# SMS FUNCTIONS
# ========================

def send_sms(message, recipient_phone):
    """Send SMS using Twilio"""
    if not recipient_phone:
        logger.warning("No recipient phone number provided")
        return False
    
    if not is_twilio_configured():
        logger.error("Twilio credentials not configured in settings")
        return False
    
    clean_phone = _normalize_phone(recipient_phone)
    if not clean_phone:
        logger.error(f"Invalid phone number format: {recipient_phone}")
        return False
    
    try:
        twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        sms_message = twilio_client.messages.create(
            body=message,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=clean_phone,    
        )
        
        logger.info(f"SMS sent to {clean_phone}. SID: {sms_message.sid}")
        return True
        
    except TwilioRestException as e:
        logger.error(f"Twilio error sending SMS to {clean_phone}: {e.msg}")
        return False
    except Exception as e:
        logger.error(f"Failed to send SMS to {clean_phone}: {str(e)}")
        return False


def is_twilio_configured():
    """Check if Twilio is properly configured"""
    required_attrs = ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE_NUMBER']
    
    if not all(hasattr(settings, attr) for attr in required_attrs):
        return False
    
    # Check if credentials are actually set
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN or not settings.TWILIO_PHONE_NUMBER:
        return False
    
    return True


# ========================
# CONTACT INFO HELPERS
# ========================

def get_user_contact_info(user):
    """Get email and phone number from any user type"""
    email = getattr(user, 'email', None)
    phone = getattr(user, 'phone_number', None)
    return email, phone


def get_student_parent_contacts(student):
    """Get all contact information for a student and their parents"""
    emails = []
    phones = []
    
    # Student contact info
    student_email, student_phone = get_user_contact_info(student.user)
    if student_email:
        emails.append(student_email)
    if student_phone:
        phones.append(student_phone)
    
    # Parent contact info
    if hasattr(student, 'parent') and student.parent:
        parent = student.parent
        # Father's contact
        if parent.father_email:
            emails.append(parent.father_email)
        if parent.father_phone:
            phones.append(parent.father_phone)
        # Mother's contact
        if parent.mother_email:
            emails.append(parent.mother_email)
        if parent.mother_phone:
            phones.append(parent.mother_phone)
    
    return list(set(emails)), list(set(phones))


def get_teacher_contacts(teacher):
    """Get contact information for a teacher"""
    emails = []
    phones = []
    
    teacher_email, teacher_phone = get_user_contact_info(teacher.user)
    if teacher_email:
        emails.append(teacher_email)
    if teacher_phone:
        phones.append(teacher_phone)
    
    return emails, phones


# ========================
# MAIN NOTIFICATION FUNCTION
# ========================

def send_notification(emails, phones, subject, message):
    """
    Send both email and SMS notifications asynchronously.
    """
    results = {
        'email_sent': False,
        'sms_sent': False,
        'email_error': None,
        'sms_error': None,
        'emails_queued': 0,
        'sms_sent_count': 0
    }
    
    # Send Email (ASYNC)
    if emails:
        try:
            send_email_async_with_retry(
                subject=subject,
                message=message,
                recipient_list=emails,
                max_retries=3
            )
            results['email_sent'] = True
            results['emails_queued'] = len(emails)
            logger.info(f"✉️ Queued emails for {len(emails)} recipients with retry logic")
        except Exception as e:
            results['email_error'] = str(e)
            logger.error(f"❌ Failed to queue email to {emails}: {e}")
    
    # Send SMS
    if phones:
        sms_results = []
        for phone in phones:
            try:
                success = send_sms(message, phone)
                sms_results.append(success)
                if success:
                    results['sms_sent_count'] += 1
            except Exception as e:
                sms_results.append(False)
                logger.error(f"Failed to send SMS to {phone}: {e}")
        
        results['sms_sent'] = any(sms_results)
        if sms_results and not all(sms_results):
            failed_count = sms_results.count(False)
            results['sms_error'] = f"{failed_count} out of {len(sms_results)} SMS messages failed to send"
    
    return results


def send_notification_sync(emails, phones, subject, message):
    """
    Alternative function that sends emails synchronously with fail_silently=True
    """
    results = {
        'email_sent': False,
        'sms_sent': False,
        'email_error': None,
        'sms_error': None,
        'emails_sent_count': 0,
        'sms_sent_count': 0
    }
    
    # Send Email (synchronous with fail_silently)
    if emails:
        try:
            count = send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=emails,
                fail_silently=True,  # Don't crash if email fails
            )
            results['email_sent'] = count > 0
            results['emails_sent_count'] = count
            if count > 0:
                logger.info(f"Email sent to {count} recipients")
            else:
                logger.warning("Email sending returned 0 - may have failed silently")
        except Exception as e:
            results['email_error'] = str(e)
            logger.error(f"Failed to send email to {emails}: {e}")
    
    # Send SMS
    if phones:
        sms_results = []
        for phone in phones:
            try:
                success = send_sms(message, phone)
                sms_results.append(success)
                if success:
                    results['sms_sent_count'] += 1
            except Exception as e:
                sms_results.append(False)
                logger.error(f"Failed to send SMS to {phone}: {e}")
        
        results['sms_sent'] = any(sms_results)
        if sms_results and not all(sms_results):
            failed_count = sms_results.count(False)
            results['sms_error'] = f"{failed_count} out of {len(sms_results)} SMS messages failed to send"
    
    return results