import os
import requests
import hashlib
from django.core.cache import cache
from django.conf import settings
from django.core.mail import send_mail

PAYSTACK_SECRET_KEY = settings.PAYSTACK_SECRET_KEY
PAYSTACK_BASE_URL = "https://api.paystack.co"
PAYSTACK_TIMEOUT_SECONDS = 10

def initialize_paystack_payment(email, amount, callback_url, metadata=None, phone_number=None):
    if not PAYSTACK_SECRET_KEY:
        return {"status": False, "message": "PAYSTACK_SECRET_KEY is not configured."}
        
    # Generate an idempotency key based on the initialization parameters
    payload_str = f"{email}-{amount}-{callback_url}-{metadata}"
    idemp_key = f"paystack_init_{hashlib.md5(payload_str.encode()).hexdigest()}"
    
    # Check cache to prevent duplicate initializations within 30 minutes
    cached_response = cache.get(idemp_key)
    if cached_response:
        return cached_response
        
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "email": email,
        # Paystack expects amount in the smallest currency unit (pesewas). Allow zero for free trials.
        "amount": int(amount * 100) if float(amount) > 0 else 0,
        "currency": "GHS",
        "callback_url": callback_url,
        "metadata": metadata or {},
    }

    try:
        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transaction/initialize",
            json=data,
            headers=headers,
            timeout=PAYSTACK_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        resp_data = response.json()
        
        # Cache successful response to enforce idempotency for 30 minutes
        if resp_data.get("status"):
            cache.set(idemp_key, resp_data, timeout=1800)
            
        return resp_data
    except requests.RequestException as exc:
        return {"status": False, "message": f"Payment initialization failed: {exc}"}
    except ValueError:
        return {"status": False, "message": "Invalid response from payment gateway."}

def verify_payment(reference):
    if not PAYSTACK_SECRET_KEY:
        return {"status": False, "message": "PAYSTACK_SECRET_KEY is not configured."}
        
    # Cache verification to prevent double-processing if hit multiple times
    verify_cache_key = f"paystack_verify_{reference}"
    cached_verify = cache.get(verify_cache_key)
    if cached_verify and cached_verify.get("data", {}).get("status") == "success":
        return cached_verify
        
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}

    try:
        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers=headers,
            timeout=PAYSTACK_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        resp_data = response.json()
        
        # Cache successful verification for 24h to prevent replay/duplicate handling
        if resp_data.get("status") and resp_data.get("data", {}).get("status") == "success":
            cache.set(verify_cache_key, resp_data, timeout=86400)
            
        return resp_data
    except requests.RequestException as exc:
        return {"status": False, "message": f"Failed to verify payment: {exc}"}
    except ValueError:
        return {"status": False, "message": "Invalid response from payment gateway."}

def send_subscription_sms(phone_number,message):
    from adminservices.utils import send_sms_sync

    result = send_sms_sync([phone_number], message)
    return result.get("success", False)

def send_subscription_email(user_email, subject, message):
    """Notify school admin about subscription activity."""
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user_email],
            fail_silently=False,
        )
        return True
    except Exception:
        return False

def _normalize_recipients(raw_value):
    if not raw_value:
        return []
    if isinstance(raw_value, (list, tuple)):
        return [value for value in raw_value if value]
    return [item.strip() for item in str(raw_value).split(",") if item.strip()]

def get_onboarding_notification_recipients():
    configured = getattr(settings, "SALES_INQUIRY_RECIPIENTS", None) or os.getenv("SALES_INQUIRY_RECIPIENTS")
    recipients = _normalize_recipients(configured)
    if recipients:
        return recipients
    default_email = getattr(settings, "DEFAULT_FROM_EMAIL", "")
    return [default_email] if default_email else []

def send_school_interest_email(onboarding_request):
    recipients = get_onboarding_notification_recipients()
    if not recipients:
        return False

    package_name = (
        onboarding_request.preferred_package.get_name_display()
        if onboarding_request.preferred_package
        else "Not selected"
    )
    subject = f"New School Onboarding Request: {onboarding_request.school_name}"
    
    # Plain text fallback
    message = (
        f"A new school has requested onboarding.\n\n"
        f"School: {onboarding_request.school_name}\n"
        f"Contact: {onboarding_request.contact_full_name}\n"
        f"Role: {onboarding_request.contact_role or 'Not provided'}\n"
        f"Email: {onboarding_request.contact_email}\n"
        f"Phone: {onboarding_request.contact_phone}\n"
        f"Location: {onboarding_request.location}\n"
        f"Address: {onboarding_request.address or 'Not provided'}\n"
        f"Postal code: {onboarding_request.postal_code or 'Not provided'}\n"
        f"Website: {onboarding_request.website or 'Not provided'}\n"
        f"School size: {onboarding_request.get_school_size_display() or 'Not provided'}\n"
        f"Preferred package: {package_name}\n"
        f"Message: {onboarding_request.message or 'No additional message'}\n"
    )

    # HTML Email Template
    html_message = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 0; padding: 20px; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            .header {{ background-color: #2563eb; color: #ffffff; padding: 20px; text-align: center; }}
            .header h2 {{ margin: 0; font-size: 24px; }}
            .content {{ padding: 30px; }}
            .content p {{ font-size: 16px; line-height: 1.5; color: #555; }}
            .details-table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            .details-table th, .details-table td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }}
            .details-table th {{ background-color: #f8fafc; font-weight: 600; color: #333; width: 40%; }}
            .details-table td {{ color: #555; }}
            .footer {{ background-color: #f8fafc; padding: 15px; text-align: center; font-size: 14px; color: #888; border-top: 1px solid #eee; }}
            .highlight {{ color: #2563eb; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>Klumus Tech Onboarding</h2>
            </div>
            <div class="content">
                <p>Hello Team,</p>
                <p>Great news! A new school has just submitted a request to join Klumus. Here are their details:</p>
                
                <table class="details-table">
                    <tr><th>School Name</th><td><strong>{onboarding_request.school_name}</strong></td></tr>
                    <tr><th>Contact Person</th><td>{onboarding_request.contact_full_name}</td></tr>
                    <tr><th>Role</th><td>{onboarding_request.contact_role or 'Not provided'}</td></tr>
                    <tr><th>Email Address</th><td><a href="mailto:{onboarding_request.contact_email}" class="highlight">{onboarding_request.contact_email}</a></td></tr>
                    <tr><th>Phone Number</th><td>{onboarding_request.contact_phone}</td></tr>
                    <tr><th>Location</th><td>{onboarding_request.location}</td></tr>
                    <tr><th>Address</th><td>{onboarding_request.address or 'Not provided'}</td></tr>
                    <tr><th>Postal Code</th><td>{onboarding_request.postal_code or 'Not provided'}</td></tr>
                    <tr><th>Website</th><td>{f'<a href="{onboarding_request.website}" target="_blank">{onboarding_request.website}</a>' if onboarding_request.website else 'Not provided'}</td></tr>
                    <tr><th>School Size</th><td>{onboarding_request.get_school_size_display() or 'Not provided'}</td></tr>
                    <tr><th>Preferred Package</th><td><span style="background-color: #dbeafe; color: #1e40af; padding: 4px 8px; border-radius: 4px; font-weight: 600; font-size: 14px;">{package_name}</span></td></tr>
                    <tr><th>Message</th><td><em>{onboarding_request.message or 'No additional message'}</em></td></tr>
                </table>
            </div>
            <div class="footer">
                <p>Please log in to the admin dashboard to review and provision this school.</p>
                <p>&copy; Klumus Tech. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            recipients,
            fail_silently=False,
            html_message=html_message,
        )
        return True
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error sending onboarding email: {e}")
        return False
