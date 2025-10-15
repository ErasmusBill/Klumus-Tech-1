import requests
from django.conf import settings
from django.core.mail import send_mail

PAYSTACK_SECRET_KEY = settings.PAYSTACK_SECRET_KEY
PAYSTACK_BASE_URL = "https://api.paystack.co"

def initialize_paystack_payment(phone_number, amount, callback_url, metadata=None):
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "phoone_number": phone_number,
        "amount": int(amount * 100), 
        "callback_url": callback_url,
        "metadata": metadata or {},
    }

    response = requests.post(f"{PAYSTACK_BASE_URL}/transaction/initialize", json=data, headers=headers)
    return response.json()

def verify_payment(reference):
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    response = requests.get(f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}", headers=headers)
    return response.json()


def send_subscription_sms(phone_number,message):
    pass    


def send_subscription_email(user_email, subject, message):
    """Notify school admin about subscription activity."""
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user_email],
        fail_silently=False,
    )
