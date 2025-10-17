# adminservices/utils.py
import logging
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from twilio.rest import Client
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
    if audience == "all":
        teachers = CustomUser.objects.filter(teacher_profile__school=school, is_active=True)
        students = CustomUser.objects.filter(student_profile__school=school, is_active=True)
        parents = CustomUser.objects.filter(
            parent_profile__students__school=school,
            is_active=True
        ).distinct()
        recipients = (teachers | students | parents).distinct()

    elif audience == "teachers":
        recipients = CustomUser.objects.filter(teacher_profile__school=school, is_active=True)

    elif audience == "students":
        recipients = CustomUser.objects.filter(student_profile__school=school, is_active=True)

    elif audience == "parents":
        recipients = CustomUser.objects.filter(
            parent_profile__students__school=school,
            is_active=True
        ).distinct()

    elif audience == "staff":
        admins = CustomUser.objects.filter(managed_school=school, is_active=True)
        teachers = CustomUser.objects.filter(teacher_profile__school=school, is_active=True)
        recipients = (admins | teachers).distinct()

    else:
        recipients = CustomUser.objects.none()

    logger.info(f"Announcement '{announcement.title}' (ID: {announcement.id}) sending to {recipients.count()} recipients.")

    short_msg = (announcement.content[:150] + "...") if len(announcement.content) > 150 else announcement.content

    # Initialize Twilio client
    twilio_client = None
    try:
        if hasattr(settings, 'TWILIO_ACCOUNT_SID') and hasattr(settings, 'TWILIO_AUTH_TOKEN'):
            twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    except Exception as e:
        logger.warning(f"Twilio client initialization failed: {e}")

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
        except Exception as e:
            logger.error(f"Failed to create notification for user {user.id}: {e}")

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
            except Exception as e:
                logger.error(f"Email failed for {user.email}: {e}")

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
                except Exception as e:
                    logger.error(f"SMS failed to {phone} (normalized: {clean_phone}) for user {user.id}: {e}")


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
    
    # Check if Twilio is configured
    if not all(hasattr(settings, attr) for attr in ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE_NUMBER']):
        logger.error("Twilio credentials not configured in settings")
        return False
    
    # Check if credentials are actually set (not None or empty)
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN or not settings.TWILIO_PHONE_NUMBER:
        logger.error("Twilio credentials are empty or None")
        return False
    
    # Validate phone number format
    if not recipient_phone.startswith('+'):
        logger.warning(f"Phone number {recipient_phone} may not be in international format")
        # You might want to format it properly here
    
    try:
        twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        message = twilio_client.messages.create(
            body=message,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=recipient_phone,    
        )
        
        logger.info(f"SMS sent to {recipient_phone}. SID: {message.sid}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send SMS to {recipient_phone}: {str(e)}")
        return False

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
        'sms_error': None
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
            logger.info(f"Email sent to {emails}")
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
            except Exception as e:
                sms_results.append(False)
                logger.error(f"Failed to send SMS to {phone}: {e}")
        
        results['sms_sent'] = any(sms_results)
        if not all(sms_results):
            results['sms_error'] = "Some SMS messages failed to send"
    
    return results

def send_announcement_via_email_and_sms(announcement):
    """Send announcement to target audience via both email and SMS"""
    school = announcement.school
    target_audience = announcement.target_audience
    
    emails = []
    phones = []
    
    if target_audience in ['all', 'students', 'parents']:
        # Get all students and their parents
        students = Student.objects.filter(school=school, is_active=True)
        for student in students:
            student_emails, student_phones = get_student_parent_contacts(student)
            emails.extend(student_emails)
            phones.extend(student_phones)
    
    if target_audience in ['all', 'teachers']:
        # Get all teachers
        teachers = Teacher.objects.filter(school=school, is_active=True)
        for teacher in teachers:
            teacher_emails, teacher_phones = get_teacher_contacts(teacher)
            emails.extend(teacher_emails)
            phones.extend(teacher_phones)
    
    if target_audience in ['all', 'staff']:
        # Get all staff (admin users for the school)
        staff_users = CustomUser.objects.filter(
            managed_school=school, 
            role='admin',
            is_active=True
        )
        for user in staff_users:
            user_email, user_phone = get_user_contact_info(user)
            if user_email:
                emails.append(user_email)
            if user_phone:
                phones.append(user_phone)
    
    # Remove duplicates
    emails = list(set(emails))
    phones = list(set(phones))
    
    # Prepare message
    sms_message = f"{announcement.title}: {announcement.content[:100]}..."
    email_message = f"""
    {announcement.title}
    
    {announcement.content}
    
    Best regards,
    {school.name} Administration
    """
    
    # Send notifications
    results = send_notification(
        emails=emails,
        phones=phones,
        subject=f"Announcement: {announcement.title}",
        message=email_message
    )
    
    return results