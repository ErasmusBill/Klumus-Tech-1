from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.hashers import make_password
from django.contrib.auth import login, authenticate,update_session_auth_hash,logout
from django.urls import reverse
from requests import Request
from .utils import initialize_paystack_payment, verify_payment, send_subscription_email
from .models import CustomUser, RequestPasswordReset, School, Subscription, Package
from .forms import PasswordRequestForm, SchoolRegistrationForm,ChangePasswordForm,PasswordResetForm
from django.conf import settings
from django.core.exceptions import PermissionDenied
import json
from django.http import JsonResponse


def home(request):
    subscription = Subscription.objects.all()
    packages = Package.objects.all()
    return render(request,"account/home.html",{"subscription":subscription,"packages":packages})

def register_school(request):
    if request.method == "POST":
        form = SchoolRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
         
            admin_user = CustomUser.objects.create(
                username=form.cleaned_data["admin_username"],
                first_name=form.cleaned_data["admin_full_name"].split(" ")[0],
                last_name=" ".join(form.cleaned_data["admin_full_name"].split(" ")[1:]),
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
                address = form.cleaned_data["address"],
                postal_code = form.cleaned_data["postal_code"],
                email = form.cleaned_data["email"],
                admin=admin_user,
            )

         
            Subscription.objects.create(
                school=school,
                package=None,
                start_date=timezone.now(),
                end_date=timezone.now() + timedelta(days=30),
                is_active=True,
                is_trial=True,
            )

            send_subscription_email(
                admin_user.email,
                "Free Trial Activated",
                f"Hello {admin_user.first_name}, your school '{school.name}' has been registered with a free 30-day trial."
            )

            messages.success(request, "School registered successfully! Free trial activated (30 days).")
            return redirect("account:login")
    else:
        form = SchoolRegistrationForm()
    return render(request, "account/register_school.html", {"form": form})

def login_user(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        if not username or not password:
            messages.error(request, "Please enter both username and password.")
            return redirect("administration:login")

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)

            school = getattr(user, "school", None)
            if school:
                subscription = Subscription.objects.filter(school=school).first()
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

def logout_user(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("account:home")

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
                return redirect(request,"account:change-password")

           
            if not user.check_password(current_password):
                messages.error(request, "Your current password is incorrect.")
                return render(request, "account/change_password.html", {"form": form})

        
            user.set_password(new_password)
            user.save()

          
            update_session_auth_hash(request,user)
            messages.success(request, "Your password has been changed successfully.")
            
            if request.user.role == "admin":
                return redirect("administration:admin-dashboard")
            elif request.user.role == "teacher":
                return redirect("teacher:teacher-dashboard")  
            elif request.user.role == "student":
                return redirect("student:student-dashboard")
    else:
        form = ChangePasswordForm()

    return render(request, "account/change_password.html", {"form": form})


def request_for_password_reset(request):
    if request.method == "POST":
        form = PasswordRequestForm(request.POST)
        if form.is_valid():  
            email = form.cleaned_data.get("email")

            if not CustomUser.objects.filter(email__iexact=email).exists():
                messages.error(request, "This email is not associated with any account")
                return redirect("account:forgot-password")

            user = CustomUser.objects.get(email__iexact=email)

            password_reset = RequestPasswordReset.objects.create(
                user=user,
                email=email
            )
            password_reset.send_reset_email(domain=settings.DOMAIN_URL)

            messages.success(request, "A password reset link has been sent to your email.")
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
    if reset_token.created_at < timezone.now() - timezone.timedelta(hours=1):
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

            # Reset password
            user = reset_token.user
            user.password = make_password(new_password)
            user.save()

            # Mark token as used
            reset_token.is_used = True
            reset_token.save()

            messages.success(request, "Your password has been reset. You can now log in.")
            return redirect("account:login")
    else:
        form = PasswordResetForm()

    return render(request, "account/verify_reset_token.html", {"form": form})



def select_package(request):
    packages = Package.objects.all()
    if request.method == "POST":
        package_id = request.POST.get("package_id")
        package = get_object_or_404(Package, id=package_id)

        school = request.user.school  

        subscription, _ = Subscription.objects.get_or_create(school=school)
        subscription.package = package
        subscription.start_date = timezone.now()
        subscription.end_date = timezone.now() + timedelta(days=package.duration_days)
        subscription.is_active = False
        subscription.is_trial = False
        subscription.save()

        return redirect("initiate-payment", package_id=package.id)

    return render(request, "account/login.html", {"packages": packages})


def initiate_payment(request, package_id):
    package = get_object_or_404(Package, id=package_id)
    school = request.user.school

    callback_url = request.build_absolute_uri(reverse("verify_payment"))

    response = initialize_paystack_payment(
        email=request.user.email,
        amount=package.price,
        callback_url=callback_url,
        metadata={"school_id": school.id, "package_id": package.id},
    )

    if response.get("status"):
        return redirect(response["data"]["authorization_url"])
    else:
        messages.error(request, "Payment initialization failed. Try again.")
        return redirect("account:select-package")

def verify_payment_view(request):
    if request.method == "POST":
        data = json.loads(request.body)
        reference = data.get("reference")

        response = verify_payment(reference)

        if response.get("status") and response["data"]["status"] == "success":
            metadata = response["data"]["metadata"]
            fields = {f["variable_name"]: f["value"] for f in metadata["custom_fields"]}

            school = School.objects.get(id="school_id")
            package = Package.objects.get(id=fields["package_id"])

            subscription = Subscription.objects.filter(school=school).first()
            subscription.package = package
            subscription.is_active = True
            subscription.is_trial = False
            subscription.start_date = timezone.now()
            subscription.end_date = timezone.now() + timedelta(days=package.duration_days)
            subscription.save()

            return JsonResponse({"status": "success"})

        return JsonResponse({"status": "failed"})

def upgrade_package(request, new_package_id):
    school = request.user.school
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

    return redirect("account:initiate-payment", package_id=new_package.id)


def downgrade_package(request, new_package_id):
    school = request.user.school
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

    return redirect("account:initiate-payment", package_id=new_package.id)



    