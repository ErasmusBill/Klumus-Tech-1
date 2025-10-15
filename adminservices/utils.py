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