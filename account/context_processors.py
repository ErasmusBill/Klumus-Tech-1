def notifications_context(request):
    if not request.user.is_authenticated:
        return {}

    notifications_qs = request.user.notifications.order_by("is_read", "-created_at")[:5]
    unread_count = request.user.notifications.filter(is_read=False).count()

    return {
        "navbar_notifications": notifications_qs,
        "navbar_unread_count": unread_count,
    }
