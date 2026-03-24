from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from account.models import Notification, RequestPasswordReset


User = get_user_model()


class AccountSecurityHardeningTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="tester",
            email="tester@example.com",
            password="StrongPass123!",
            role="student",
        )
        self.client.force_login(self.user)

    def test_logout_is_post_only(self):
        get_response = self.client.get(reverse("account:logout"))
        self.assertEqual(get_response.status_code, 405)

        post_response = self.client.post(reverse("account:logout"))
        self.assertEqual(post_response.status_code, 302)

    def test_notifications_clear_is_post_only(self):
        Notification.objects.create(
            user=self.user,
            notification_type="system",
            title="Hello",
            message="World",
            is_read=False,
        )

        get_response = self.client.get(reverse("account:notifications-clear"))
        self.assertEqual(get_response.status_code, 405)

        post_response = self.client.post(reverse("account:notifications-clear"))
        self.assertEqual(post_response.status_code, 302)
        self.assertFalse(Notification.objects.filter(user=self.user, is_read=False).exists())

    def test_password_reset_enforces_short_cooldown(self):
        self.client.logout()
        payload = {"email": self.user.email}

        first = self.client.post(reverse("account:forgot-password"), payload)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(RequestPasswordReset.objects.filter(user=self.user).count(), 1)

        second = self.client.post(reverse("account:forgot-password"), payload)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(
            RequestPasswordReset.objects.filter(user=self.user).count(),
            1,
            "Expected cooldown to avoid issuing another reset token immediately.",
        )
