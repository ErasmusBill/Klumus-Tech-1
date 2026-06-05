from account.models import Teacher


def notifications_context(request):
    if not request.user.is_authenticated:
        return {}

    notifications_qs = request.user.notifications.order_by("is_read", "-created_at")[:5]
    unread_count = request.user.notifications.filter(is_read=False).count()

    return {
        "navbar_notifications": notifications_qs,
        "navbar_unread_count": unread_count,
    }


def teacher_context(request):
    if not request.user.is_authenticated or getattr(request.user, "role", None) != "teacher":
        return {
            "current_teacher_profile": None,
            "teacher_is_class_teacher": False,
            "teacher_attendance_class": None,
            "teacher_attendance_class_display": None,
        }

    teacher = Teacher.objects.select_related("school", "department").filter(user=request.user).first()
    return {
        "current_teacher_profile": teacher,
        "teacher_is_class_teacher": bool(teacher and teacher.can_take_attendance),
        "teacher_attendance_class": teacher.class_teacher_class if teacher else None,
        "teacher_attendance_class_display": (
            teacher.get_class_teacher_class_display() if teacher and teacher.class_teacher_class else None
        ),
    }
