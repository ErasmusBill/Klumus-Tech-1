# adminservices/utils.py
import logging
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from account.models import CustomUser, Teacher, Student, Parent, Notification

logger = logging.getLogger(__name__)


def send_announcement_via_email_and_sms(announcement):
    """
    Send announcement to selected audience via:
    - In-app Notification
    - Email
    - SMS (Twilio)
    
    Only sends if announcement.published is True and within active window.
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
        'emails_sent': 0,
        'sms_sent': 0,
        'errors': []
    }

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

        # 2. Email
        if user.email:
            try:
                send_mail(
                    subject=f"📢 Announcement: {announcement.title}",
                    message=announcement.content,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
                logger.info(f"Email sent to {user.email}")
                results['emails_sent'] += 1
            except Exception as e:
                error_msg = f"Email failed for {user.email}: {e}"
                logger.error(error_msg)
                results['errors'].append(error_msg)

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
    Adjust logic if supporting other countries.
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
        # Handle cases like '233241234567' → '+233241234567'
        return '+' + digits[-12:] if len(digits) == 12 else '+233' + digits[3:]
    elif digits.startswith('+'):
        return digits
    elif len(digits) >= 10:
        # Fallback: assume international format without +
        return '+' + digits[-12:]  # Keep last 12 digits max

    return None


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
        
        message = twilio_client.messages.create(
            body=message,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=clean_phone,    
        )
        
        logger.info(f"SMS sent to {clean_phone}. SID: {message.sid}")
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
    
    # Check if credentials are actually set (not None or empty)
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN or not settings.TWILIO_PHONE_NUMBER:
        return False
    
    return True


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


def send_notification(emails, phones, subject, message):
    """Send both email and SMS notifications"""
    results = {
        'email_sent': False,
        'sms_sent': False,
        'email_error': None,
        'sms_error': None,
        'emails_sent_count': 0,
        'sms_sent_count': 0
    }
    
    # Send Email
    if emails:
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=emails,
                fail_silently=False,
            )
            results['email_sent'] = True
            results['emails_sent_count'] = len(emails)
            logger.info(f"Email sent to {len(emails)} recipients")
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
        if not all(sms_results):
            results['sms_error'] = f"{sms_results.count(False)} out of {len(sms_results)} SMS messages failed to send"
    
    return results