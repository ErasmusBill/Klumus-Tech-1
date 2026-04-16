import requests
from django.conf import settings
from django.core.mail import send_mail

PAYSTACK_SECRET_KEY = settings.PAYSTACK_SECRET_KEY
PAYSTACK_BASE_URL = "https://api.paystack.co"
PAYSTACK_TIMEOUT_SECONDS = 10

def initialize_paystack_payment(email, amount, callback_url, metadata=None, phone_number=None):
    if not PAYSTACK_SECRET_KEY:
        return {"status": False, "message": "PAYSTACK_SECRET_KEY is not configured."}
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "email": email,
        "amount": int(amount * 100),
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
        return response.json()
    except requests.RequestException as exc:
        return {"status": False, "message": f"Payment initialization failed: {exc}"}
    except ValueError:
        return {"status": False, "message": "Invalid response from payment gateway."}

def verify_payment(reference):
    if not PAYSTACK_SECRET_KEY:
        return {"status": False, "message": "PAYSTACK_SECRET_KEY is not configured."}
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}

    try:
        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers=headers,
            timeout=PAYSTACK_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
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
