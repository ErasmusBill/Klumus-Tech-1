from celery import shared_task

from .utils import send_email_sync, send_sms_sync


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_email_task(self, to_emails, subject, message, html_message=None):
    result = send_email_sync(to_emails, subject, message, html_message)
    if not result.get("success"):
        raise self.retry(exc=Exception(result.get("error") or "Email send failed"))
    return result


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_sms_task(self, to_phones, message):
    result = send_sms_sync(to_phones, message)
    if not result.get("success"):
        raise self.retry(exc=Exception(result.get("error") or "SMS send failed"))
    return result
