from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.hashers import make_password
from django.contrib.auth import login, authenticate,update_session_auth_hash,logout
from django.urls import reverse
import uuid
from .utils import (
    initialize_paystack_payment,
    verify_payment,
    send_subscription_email,
    send_school_interest_email,
)
from .models import (
    CustomUser,
    RequestPasswordReset,
    School,
    Subscription,
    Package,
    Notification,
    SchoolOnboardingRequest,
    Transaction,
    SubscriptionHistory,
)
from .forms import PasswordRequestForm, SchoolInterestForm, SchoolProvisionForm, ChangePasswordForm, PasswordResetForm
from django.conf import settings
from django.core.exceptions import PermissionDenied
import json
from decimal import Decimal
import logging
from django.core.mail import send_mail
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods
from django.utils.http import url_has_allowed_host_and_scheme
from django.core.cache import cache
from django.db import transaction
from .cache_utils import make_cache_key, make_user_cache_key, should_cache, bump_user_cache_version
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

PASSWORD_RESET_COOLDOWN_SECONDS = 60
PASSWORD_RESET_MAX_REQUESTS_PER_HOUR = 5
FREE_TRIAL_DAYS = getattr(settings, "FREE_TRIAL_DAYS", 30)
try:
    FREE_TRIAL_PAYSTACK_AMOUNT = Decimal(str(getattr(settings, "FREE_TRIAL_PAYSTACK_AMOUNT", "0.000")))
except Exception:
    FREE_TRIAL_PAYSTACK_AMOUNT = Decimal("0.000")


def _is_trial_checkout(subscription):
    return bool(
        subscription
        and subscription.is_trial
        and not subscription.package_id
        and subscription.end_date
        and subscription.end_date > timezone.now()
    )


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

def home(request):
    cache_key = make_cache_key("home", "public", "landing")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    subscription = Subscription.objects.all()
    packages = Package.objects.filter(is_active=True).order_by("price")
    packages_by_name = {p.name: p for p in packages}
    response = render(
        request,
        "account/home.html",
        {
            "subscription": subscription,
            "packages": packages,
            "packages_by_name": packages_by_name,
            "paystack_public_key": settings.PAYSTACK_PUBLIC_KEY,
        },
    )
    if should_cache(request):
        cache.set(cache_key, response, 300)
    return response

@require_POST
def contact_submit(request):
    """Handle contact form submissions from the public footer.

    Sends an email to the support inbox and provides user feedback via messages.
    """
    name = (request.POST.get("name") or "").strip()
    email = (request.POST.get("email") or "").strip()
    message = (request.POST.get("message") or "").strip()

    if not email or not message:
        messages.error(request, "Please provide an email and a message.")
        return redirect(request.META.get("HTTP_REFERER") or reverse("account:home") + "#contact")

    subject = f"Website Contact: {name or email}"
    body = (
        f"Name: {name}\n"
        f"Email: {email}\n\n"
        f"Message:\n{message}\n\n"
        f"IP: {request.META.get('REMOTE_ADDR')}"
    )

    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, ["support@kiddocore.com"], fail_silently=False)
        messages.success(request, "Thanks — your message has been sent. We'll get back to you soon.")
    except Exception as exc:
        logger.exception("Error sending contact email: %s", exc)
        messages.error(request, "Unable to send message right now. Please try again later.")

    return redirect(request.META.get("HTTP_REFERER") or reverse("account:home") + "#contact")


def register_school(request):
    if request.method == "POST":
        form = SchoolInterestForm(request.POST)
        if form.is_valid():
            onboarding_request = form.save()
            email_sent = send_school_interest_email(onboarding_request)
            messages.success(
                request,
                "Your request has been submitted. Our onboarding team will review it and contact you shortly."
            )
            if not email_sent:
                logger.warning("School onboarding request email failed for request=%s", onboarding_request.id)
                messages.warning(
                    request,
                    "Your request was saved, but the internal email alert could not be delivered. Please follow up from the admin panel."
                )
            return redirect("account:register-school")
    else:
        initial = {}
        plan_name = request.GET.get("plan", "").strip().lower()
        if plan_name:
            package = Package.objects.filter(name__iexact=plan_name).first()
            if package:
                initial["preferred_package"] = package
        form = SchoolInterestForm(initial=initial)
    return render(request, "account/register_school.html", {"form": form})


@login_required(login_url="account:login")
def provision_school(request, inquiry_id):
    if not request.user.is_staff:
        raise PermissionDenied("Only staff can provision schools.")

    inquiry = get_object_or_404(SchoolOnboardingRequest.objects.select_related("preferred_package"), id=inquiry_id)
    if inquiry.provisioned_school_id:
        messages.info(request, "This onboarding request has already been provisioned.")
        return redirect("admin:index")

    if request.method == "POST":
        form = SchoolProvisionForm(request.POST, request.FILES, inquiry=inquiry)
        if form.is_valid():
            with transaction.atomic():
                full_name = form.cleaned_data["admin_full_name"].split()
                first_name = full_name[0]
                last_name = " ".join(full_name[1:])
                admin_user = CustomUser.objects.create(
                    username=form.cleaned_data["admin_username"],
                    first_name=first_name,
                    last_name=last_name,
                    email=form.cleaned_data["admin_email"],
                    phone_number=form.cleaned_data["admin_phone"],
                    role="admin",
                    password=make_password(form.cleaned_data["password"]),
                )

                school = School.objects.create(
                    name=form.cleaned_data["school_name"],
                    logo=form.cleaned_data.get("school_logo"),
                    location=form.cleaned_data["location"],
                    phone_number=form.cleaned_data["phone_number"],
                    address=form.cleaned_data["address"],
                    postal_code=form.cleaned_data["postal_code"],
                    email=form.cleaned_data["email"],
                    website=form.cleaned_data["website"],
                    admin=admin_user,
                )

                Subscription.objects.create(
                    school=school,
                    package=None,
                    start_date=timezone.now(),
                    end_date=timezone.now() + timedelta(days=FREE_TRIAL_DAYS),
                    is_active=True,
                    is_trial=True,
                )

                inquiry.status = "provisioned"
                inquiry.provisioned_school = school
                inquiry.reviewed_at = timezone.now()
                inquiry.save(update_fields=["status", "provisioned_school", "reviewed_at", "updated_at"])

            login_url = request.build_absolute_uri(reverse("account:login"))
            email_sent = send_subscription_email(
                admin_user.email,
                "Your Klumus school workspace is ready",
                (
                    f"Hello {admin_user.first_name or inquiry.contact_full_name},\n\n"
                    f"Your school workspace for '{school.name}' has been created.\n"
                    f"Login URL: {login_url}\n"
                    f"Username: {admin_user.username}\n"
                    f"Temporary password: {form.cleaned_data['password']}\n\n"
                    f"Please sign in and change your password immediately.\n"
                ),
            )
            messages.success(request, f"{school.name} has been provisioned successfully.")
            if not email_sent:
                messages.warning(request, "Provisioning succeeded, but the access email could not be sent.")
            return redirect("admin:index")
    else:
        seed_name = "".join(ch for ch in inquiry.school_name.lower() if ch.isalnum())[:12] or "schooladmin"
        form = SchoolProvisionForm(
            inquiry=inquiry,
            initial={
                "school_name": inquiry.school_name,
                "location": inquiry.location,
                "phone_number": inquiry.contact_phone,
                "address": inquiry.address,
                "postal_code": inquiry.postal_code,
                "email": inquiry.contact_email,
                "website": inquiry.website,
                "admin_full_name": inquiry.contact_full_name,
                "admin_email": inquiry.contact_email,
                "admin_phone": inquiry.contact_phone,
                "admin_username": seed_name,
            },
        )

    preferred_package_name = inquiry.preferred_package.get_name_display() if inquiry.preferred_package else "Not selected"
    return render(
        request,
        "account/provision_school.html",
        {"form": form, "inquiry": inquiry, "preferred_package_name": preferred_package_name},
    )

def login_user(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        if not username or not password:
            messages.error(request, "Please enter both username and password.")
            return redirect("account:login")

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)

            school = None
            if user.role == "admin":
                school = getattr(user, "managed_school", None)
            elif user.role == "teacher":
                teacher_profile = getattr(user, "teacher_profile", None)
                school = teacher_profile.school if teacher_profile else None
            elif user.role == "student":
                student_profile = getattr(user, "student_profile", None)
                school = student_profile.school if student_profile else None
            if school:
                subscription = Subscription.objects.filter(school=school).first()
                
                # Force package selection on first login after onboarding
                if not subscription or not subscription.package:
                    messages.info(request, "Welcome! Please select a package to complete your school's setup and activate your account.")
                    return redirect("account:select-package")
                
                if subscription and subscription.end_date < timezone.now(): # type: ignore
                    subscription.is_active = False
                    subscription.save()
                    messages.error(request, "Your subscription has expired. Please renew.")
                    return redirect("account:select-package")

            if user.role == "admin": # type: ignore
                return redirect("adminservices:admin-dashboard")
            elif user.role == "teacher": # type: ignore
                return redirect("teacher:teacher-dashboard")
            elif user.role == "student": # type: ignore
                return redirect("student:student-dashboard")
        else:
            messages.error(request, "Invalid username or password.")
            return redirect("account:login")

    return render(request, "account/login.html")

@require_POST
def logout_user(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("account:home")


@login_required(login_url="account:login")
def notification_go(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.mark_as_read()
    target = notification.link or request.META.get("HTTP_REFERER")
    if target and url_has_allowed_host_and_scheme(target, {request.get_host()}):
        return redirect(target)
    return redirect("account:home")


@login_required(login_url="account:login")
@require_POST
def notifications_clear(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    bump_user_cache_version(request.user.id, "notifications")
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "account:home")


@login_required(login_url="account:login")
def notifications_list(request):
    cache_key = make_user_cache_key("notifications", request.user.id, request.GET.urlencode())
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    filter_key = request.GET.get("filter", "all")
    qs = Notification.objects.filter(user=request.user).order_by("-created_at")
    if filter_key == "unread":
        qs = qs.filter(is_read=False)
    elif filter_key == "read":
        qs = qs.filter(is_read=True)

    base_template = "student/base.html"
    wrap_in_page = True
    if request.user.role == "admin":
        base_template = "adminservices/base.html"
        wrap_in_page = True
    elif request.user.role == "teacher":
        base_template = "teacher/base.html"
        wrap_in_page = False

    response = render(
        request,
        "account/notifications.html",
        {
            "notifications": qs,
            "filter_key": filter_key,
            "base_template": base_template,
            "wrap_in_page": wrap_in_page,
            "total_count": request.user.notifications.count(),
            "unread_count": request.user.notifications.filter(is_read=False).count(),
            "read_count": request.user.notifications.filter(is_read=True).count(),
        },
    )
    if should_cache(request):
        cache.set(cache_key, response, 90)
    return response


@login_required(login_url="account:login")
@require_POST
def notification_mark_read(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.mark_as_read()
    bump_user_cache_version(request.user.id, "notifications")
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "account:notifications-list")


@login_required(login_url="account:login")
@require_POST
def notification_mark_unread(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    if notification.is_read:
        notification.is_read = False
        notification.read_at = None
        notification.save(update_fields=["is_read", "read_at"])
    bump_user_cache_version(request.user.id, "notifications")
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "account:notifications-list")


@login_required(login_url="account:login")
@require_POST
def notification_delete(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.delete()
    bump_user_cache_version(request.user.id, "notifications")
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "account:notifications-list")


@login_required(login_url="account:login")
@require_POST
def notifications_delete_all(request):
    Notification.objects.filter(user=request.user).delete()
    bump_user_cache_version(request.user.id, "notifications")
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "account:notifications-list")

@login_required(login_url="account:login")
def change_password(request):
    if not request.user.is_authenticated:
        raise PermissionDenied("You are not authorized to perform this action")

    if request.method == "POST":
        user = request.user
        form = ChangePasswordForm(request.POST)
        if form.is_valid():
            current_password = form.cleaned_data['current_password']
            new_password = form.cleaned_data['new_password']
            confirm_password = form.cleaned_data['confirm_password']
            
            
            if not current_password or not new_password or not confirm_password:
                messages.error(request,"All fields are required")
                return redirect("account:change-password")

           
            if not user.check_password(current_password):
                messages.error(request, "Your current password is incorrect.")
                return render(request, "account/change_password.html", {"form": form})

        
            user.set_password(new_password)
            user.save()

          
            update_session_auth_hash(request,user)
            messages.success(request, "Your password has been changed successfully.")
            
            if request.user.role == "admin":
                return redirect("adminservices:admin-dashboard")
            elif request.user.role == "teacher":
                return redirect("teacher:teacher-dashboard")  
            elif request.user.role == "student":
                return redirect("student:student-dashboard")
    else:
        form = ChangePasswordForm()

    return render(request, "account/change_password.html", {"form": form})


@require_http_methods(["GET", "POST"])
def request_for_password_reset(request):
    if request.method == "POST":
        form = PasswordRequestForm(request.POST)
        if form.is_valid():  
            email = form.cleaned_data.get("email")

            user = CustomUser.objects.filter(email__iexact=email).first()
            if user:
                now = timezone.now()
                one_hour_ago = now - timedelta(hours=1)
                cooldown_window = now - timedelta(seconds=PASSWORD_RESET_COOLDOWN_SECONDS)
                recent_resets = RequestPasswordReset.objects.filter(
                    user=user,
                    created_at__gte=one_hour_ago,
                )

                if recent_resets.count() >= PASSWORD_RESET_MAX_REQUESTS_PER_HOUR:
                    logger.warning("Password reset rate limit reached for user=%s", user.id)
                elif recent_resets.filter(created_at__gte=cooldown_window).exists():
                    logger.info("Password reset cooldown active for user=%s", user.id)
                else:
                    with transaction.atomic():
                        RequestPasswordReset.objects.filter(
                            user=user,
                            is_used=False,
                            expires_at__gt=now,
                        ).update(is_used=True)
                        password_reset = RequestPasswordReset.objects.create(
                            user=user,
                            email=email
                        )
                    
                    domain = request.build_absolute_uri('/').rstrip('/')
                    email_sent = password_reset.send_reset_email(domain=domain)
                    if not email_sent:
                        logger.error("Failed to send password reset email to %s", email)
                        
            messages.success(request, "If the email exists, a password reset link has been sent.")
            return redirect("account:login")
    else:
        form = PasswordRequestForm()

    return render(request, "account/password_reset_request.html", {"form": form})

def verify_reset_token(request, token):
    try:
        reset_token = RequestPasswordReset.objects.get(token=token, is_used=False)
    except RequestPasswordReset.DoesNotExist:
        messages.error(request, "Invalid or expired reset link.")
        return redirect("account:forgot-password")

    # Check if token expired (1-hour validity)
    if not reset_token.is_valid():
        messages.error(request, "This reset link has expired.")
        return redirect("account:forgot-password")

    if request.method == "POST":
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            new_password = form.cleaned_data.get("new_password")
            confirm_password = form.cleaned_data.get("confirm_password")

            if new_password != confirm_password:
                messages.error(request, "Passwords do not match.")
                return redirect("account:verify-reset-token", token=token)

            user = reset_token.user
            try:
                validate_password(new_password, user=user)
            except ValidationError as e:
                for error in e.messages:
                    messages.error(request, error)
                return redirect("account:verify-reset-token", token=token)

            # Reset password
            user.set_password(new_password)
            user.save(update_fields=["password"])

            # Mark token as used
            reset_token.is_used = True
            reset_token.save(update_fields=["is_used"])

            messages.success(request, "Your password has been reset. You can now log in.")
            return redirect("account:login")
    else:
        form = PasswordResetForm()

    return render(request, "account/verify_reset_token.html", {"form": form})


@login_required(login_url="account:login")
def select_package(request):
    if request.user.role != "admin":
        messages.error(request, "Only school admins can manage subscriptions.")
        return redirect("account:home")

    school = getattr(request.user, "managed_school", None)
    if not school:
        messages.error(request, "Your account is not linked to a school.")
        return redirect("account:register-school")

    packages = Package.objects.filter(is_active=True).order_by("price")
    if request.method == "POST":
        package_id = request.POST.get("package_id")
        package = get_object_or_404(Package, id=package_id)
        return redirect("account:initiate-package", package_id=package.id)

    packages_by_name = {p.name: p for p in packages}
    return render(
        request,
        "account/select_package.html",
        {
            "subscription": Subscription.objects.filter(school=school),
            "packages": packages,
            "packages_by_name": packages_by_name,
            "paystack_public_key": settings.PAYSTACK_PUBLIC_KEY,
        },
    )


@login_required(login_url="account:login")
def initiate_payment(request, package_id):
    if request.user.role != "admin":
        messages.error(request, "Only school admins can initiate package payment.")
        return redirect("account:home")

    package = get_object_or_404(Package, id=package_id)
    school = getattr(request.user, "managed_school", None)
    if not school:
        messages.error(request, "Your account is not linked to a school.")
        return redirect("account:register-school")

    subscription = Subscription.objects.filter(school=school).first()
    trial_checkout = _is_trial_checkout(subscription)
    charge_amount = FREE_TRIAL_PAYSTACK_AMOUNT if trial_checkout else package.price

    payment_reference = f"SUB-{uuid.uuid4().hex[:10].upper()}"

    transaction = Transaction.objects.create(
        school=school,
        amount=charge_amount,
        paystack_reference=payment_reference,
        status="pending",
    )

    callback_url = request.build_absolute_uri(
        reverse("account:verify-payment", kwargs={"school_id": school.id})
    )

    metadata = {
        "school_id": str(school.id),
        "package_id": str(package.id),
        "trial_checkout": trial_checkout,
        "trial_days": FREE_TRIAL_DAYS,
        "custom_fields": [
            {"display_name": "School ID", "variable_name": "school_id", "value": str(school.id)},
            {"display_name": "Package ID", "variable_name": "package_id", "value": str(package.id)},
            {"display_name": "Trial Checkout", "variable_name": "trial_checkout", "value": str(trial_checkout)},
            {"display_name": "Trial Days", "variable_name": "trial_days", "value": str(FREE_TRIAL_DAYS)},
        ],
    }

    response = initialize_paystack_payment(
        email=request.user.email,
        amount=charge_amount,
        callback_url=callback_url,
        reference=payment_reference,
        metadata=metadata,
    )

    if response.get("status") and response.get("data", {}).get("authorization_url"):
        return redirect(response["data"]["authorization_url"])

    else:
        transaction.status = "failed"
        transaction.save()
        messages.error(request, "Payment initialization failed. Try again.")
        return redirect("account:select-package")


@login_required(login_url="account:login")
def verify_payment_view(request, school_id):
    # 1. Permission & Role Checks
    if request.user.role != "admin":
        messages.error(request, "Only school admins can verify subscription payments.")
        return redirect("account:home")

    managed_school = getattr(request.user, "managed_school", None)
    if not managed_school or str(managed_school.id) != str(school_id):
        messages.error(request, "Unauthorized access.")
        return redirect("account:home")

    # 2. Extract Reference
    reference = request.GET.get("reference")
    if request.method == "POST":
        try:
            data = json.loads(request.body or "{}")
            reference = data.get("reference") or reference
        except json.JSONDecodeError:
            pass

    if not reference:
        messages.error(request, "Payment reference not provided.")
        return redirect("account:select-package")

    # 3. Call Paystack API
    response = verify_payment(reference)
    data = response.get("data")

    # 4. Process Success
    if response.get("status") and data and data.get("status") == "success":
        # Extract Metadata
        metadata = data.get("metadata") or {}
        # Support both standard metadata and Paystack's custom_fields array
        if "custom_fields" in metadata:
            fields = {
                field.get("variable_name"): field.get("value")
                for field in metadata["custom_fields"]
                if field.get("variable_name")
            }
        else:
            fields = metadata

        package_id = fields.get("package_id")
        trial_checkout = _as_bool(fields.get("trial_checkout"))

        # 5. Atomic Database Operations
        try:
            with transaction.atomic():
                # Fetch Models
                school = get_object_or_404(School, id=school_id)
                package = get_object_or_404(Package, id=package_id)

                # A. Update/Create Transaction Record
                # We use update_or_create in case the Webhook already processed this
                paid_amount = Decimal(str(data.get("amount") or 0)) / 100
                txn, _ = Transaction.objects.update_or_create(
                    paystack_reference=reference,
                    defaults={
                        "school": school,
                        "amount": paid_amount,
                        'status': 'success',
                        "currency": data.get("currency", "GHS"),
                        "payment_date": timezone.now(),
                        "gateway_response": data,  # Store the full response for auditing
                    }
                )

                # B. Update the Active Subscription
                subscription, _ = Subscription.objects.get_or_create(school=school)
                previous_package = subscription.package

                # If they were on a different plan, we might want to log that as a change status
                history_status = "active"
                if previous_package and previous_package != package and not trial_checkout:
                    history_status = "upgraded" if package.price > previous_package.price else "downgraded"

                subscription.package = package
                subscription.is_active = True
                subscription.is_trial = trial_checkout
                subscription.start_date = timezone.now()
                subscription.end_date = timezone.now() + timedelta(
                    days=FREE_TRIAL_DAYS if trial_checkout else package.duration_days
                )
                subscription.save()

                # C. Create Subscription History Record
                SubscriptionHistory.objects.create(
                    school=school,
                    package=package,
                    start_date=subscription.start_date,
                    end_date=subscription.end_date,
                    status=history_status,
                    amount_paid=txn.amount
                )

            messages.success(request, f"Success! {package.get_name_display()} package is now active.")
            return redirect("account:home")  # Redirect to dashboard

        except Exception:
            logger.exception("Subscription activation failed after Paystack verification")
            messages.error(request, "An error occurred while activating your subscription. Please contact support.")
            return redirect("account:select-package")

    # 6. Process Failure
    messages.error(request, "Payment could not be verified by the gateway.")
    return redirect("account:select-package")

@login_required(login_url="account:login")
@require_POST
def upgrade_package(request, new_package_id):
    if request.user.role != "admin":
        messages.error(request, "Only school admins can upgrade subscriptions.")
        return redirect("account:home")

    school = getattr(request.user, "managed_school", None)
    if not school:
        messages.error(request, "Your account is not linked to a school.")
        return redirect("account:select-package")
    new_package = get_object_or_404(Package, id=new_package_id)

    subscription = Subscription.objects.filter(school=school).first()

    if not subscription:
        messages.error(request, "You don’t have an active subscription.")
        return redirect("account:select-package")

    if new_package.price <= subscription.package.price: # type: ignore
        messages.error(request, "This is not an upgrade. Please select a higher package.")
        return redirect("account:select-package")

    # Restart subscription with new package
    subscription.package = new_package
    subscription.start_date = timezone.now()
    subscription.end_date = timezone.now() + timedelta(days=new_package.duration_days)
    subscription.is_active = False 
    subscription.save()

    send_subscription_email(
        school.admin.email,
        "Upgrade Initiated",
        f"You are upgrading to '{new_package.name}'. Please complete payment to activate."
    )

    return redirect("account:initiate-package", package_id=new_package.id)


@login_required(login_url="account:login")
@require_POST
def downgrade_package(request, new_package_id):
    if request.user.role != "admin":
        messages.error(request, "Only school admins can downgrade subscriptions.")
        return redirect("account:home")

    school = getattr(request.user, "managed_school", None)
    if not school:
        messages.error(request, "Your account is not linked to a school.")
        return redirect("account:select-package")
    new_package = get_object_or_404(Package, id=new_package_id)

    subscription = Subscription.objects.filter(school=school).first()

    if not subscription:
        messages.error(request, "You don’t have an active subscription.")
        return redirect("account:select-package")

    if new_package.price >= subscription.package.price: # type: ignore
        messages.error(request, "This is not a downgrade. Please pick a lower package.")
        return redirect("account:select-package")

   
    subscription.package = new_package
    subscription.start_date = timezone.now()
    subscription.end_date = timezone.now() + timedelta(days=new_package.duration_days)
    subscription.is_active = False 
    subscription.save()

    send_subscription_email(
        school.admin.email,
        "Downgrade Initiated",
        f"You are downgrading to '{new_package.name}'. Please complete payment to activate."
    )

    return redirect("account:initiate-package", package_id=new_package.id)
