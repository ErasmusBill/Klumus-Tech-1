from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from urllib.parse import urlencode

class SubscriptionEnforcementMiddleware:
    """Blocks access to the application for schools without an active subscription.

    Allowlist: login, logout, select-package, initiate-package, verify-payment, register, provision, contact,
    admin, static and media.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Allow unauthenticated access
        if not request.user or not request.user.is_authenticated:
            return self.get_response(request)

        # Allow staff and superusers (site admins)
        if getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False):
            return self.get_response(request)

        path = request.path_info or request.path
        # Simple allowlist
        allow_prefixes = [
            "/admin/",
            "/static/",
            "/media/",
            "/select-package/",
            "/initiate_package/",
            "/verify-payment/",
            "/login/",
            "/logout/",
            "/register/",
            "/register/provision/",
            "/contact/",
            "/select2/",
            "/ai/",
        ]
        for p in allow_prefixes:
            if path.startswith(p):
                return self.get_response(request)

        # Resolve user's school (if any)
        school = None
        try:
            if request.user.role == "admin":
                school = getattr(request.user, "managed_school", None)
            elif request.user.role == "teacher":
                teacher_profile = getattr(request.user, "teacher_profile", None)
                school = teacher_profile.school if teacher_profile else None
            elif request.user.role == "student":
                student_profile = getattr(request.user, "student_profile", None)
                school = student_profile.school if student_profile else None
        except Exception:
            school = None

        if not school:
            return self.get_response(request)

        try:
            subscription = school.subscription
        except Exception:
            subscription = None

        allowed = False
        reason = "no_subscription"
        now = timezone.now()

        if subscription:
            reason = "inactive"
            try:
                end_date = subscription.end_date
                if end_date and end_date <= now:
                    if subscription.is_active:
                        subscription.is_active = False
                        subscription.save(update_fields=["is_active", "updated_at"])
                    reason = "trial_expired" if subscription.is_trial else "subscription_expired"
                else:
                    trial_active = bool(subscription.is_trial and end_date and end_date > now)
                    paid_active = bool(subscription.is_active and (not end_date or end_date > now))
                    allowed = trial_active or paid_active
            except Exception:
                allowed = False
                reason = "inactive"

        if not allowed:
            target = reverse("account:select-package")
            return redirect(f"{target}?{urlencode({'reason': reason})}")

        return self.get_response(request)
