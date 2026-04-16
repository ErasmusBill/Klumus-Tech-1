import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Validate MNotify configuration by checking SMS balance and sender ID status."

    def handle(self, *args, **options):
        api_key = getattr(settings, "MNOTIFY_API_KEY", None)
        sender_id = getattr(settings, "MNOTIFY_SENDER_ID", None)
        base_url = getattr(settings, "MNOTIFY_BASE_URL", "https://api.mnotify.com/api").rstrip("/")

        if not api_key:
            raise CommandError("MNOTIFY_API_KEY is not configured.")
        if not sender_id:
            raise CommandError("MNOTIFY_SENDER_ID is not configured.")

        self.stdout.write("Checking MNotify SMS balance...")
        balance_response = requests.get(
            f"{base_url}/balance/sms?key={api_key}",
            timeout=15,
        )
        balance_response.raise_for_status()
        balance_data = balance_response.json()

        if str(balance_data.get("status", "")).lower() != "success":
            raise CommandError(f"Balance check failed: {balance_data}")

        self.stdout.write(
            self.style.SUCCESS(
                f"SMS balance OK. Balance={balance_data.get('balance')} bonus={balance_data.get('bonus')}"
            )
        )

        self.stdout.write(f"Checking sender ID status for '{sender_id}'...")
        sender_response = requests.post(
            f"{base_url}/senderid/status/?key={api_key}",
            json={"sender_name": sender_id},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        sender_response.raise_for_status()
        sender_data = sender_response.json()

        if str(sender_data.get("status", "")).lower() != "success":
            raise CommandError(f"Sender ID check failed: {sender_data}")

        summary = sender_data.get("summary") or {}
        sender_status = summary.get("status", "unknown")
        if str(sender_status).lower() != "approved":
            raise CommandError(
                f"MNotify sender ID '{sender_id}' is not approved. Current status: {sender_status}"
            )

        self.stdout.write(
            self.style.SUCCESS(f"MNotify sender ID '{sender_id}' is approved.")
        )
