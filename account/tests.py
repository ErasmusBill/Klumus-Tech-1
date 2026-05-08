from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.utils import timezone
from datetime import timedelta
from account.models import Notification, Parent, RequestPasswordReset, School, Student, Subscription


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


class TrialSubscriptionFlowTests(TestCase):
    def setUp(self):
        self.password = "StrongPass123!"
        self.admin = User.objects.create_user(
            username="schooladmin",
            email="admin@example.com",
            password=self.password,
            role="admin",
        )
        self.school = School.objects.create(
            name="Test School",
            location="Accra",
            phone_number="0200000000",
            admin=self.admin,
        )

    def test_admin_login_during_trial_redirects_to_dashboard(self):
        Subscription.objects.create(
            school=self.school,
            package=None,
            is_active=True,
            is_trial=True,
            start_date=timezone.now() - timedelta(days=2),
            end_date=timezone.now() + timedelta(days=28),
        )

        response = self.client.post(
            reverse("account:login"),
            {"username": self.admin.username, "password": self.password},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("adminservices:admin-dashboard"))

    def test_trial_message_shows_once_on_first_admin_login(self):
        Subscription.objects.create(
            school=self.school,
            package=None,
            is_active=True,
            is_trial=True,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=29),
        )

        first_response = self.client.post(
            reverse("account:login"),
            {"username": self.admin.username, "password": self.password},
        )
        first_messages = [m.message for m in get_messages(first_response.wsgi_request)]
        self.assertTrue(any("30-day free trial" in msg for msg in first_messages))

        self.client.post(reverse("account:logout"))

        second_response = self.client.post(
            reverse("account:login"),
            {"username": self.admin.username, "password": self.password},
        )
        second_messages = [m.message for m in get_messages(second_response.wsgi_request)]
        self.assertFalse(any("30-day free trial" in msg for msg in second_messages))

    def test_admin_login_after_trial_redirects_to_package_selection(self):
        Subscription.objects.create(
            school=self.school,
            package=None,
            is_active=True,
            is_trial=True,
            start_date=timezone.now() - timedelta(days=35),
            end_date=timezone.now() - timedelta(days=1),
        )

        response = self.client.post(
            reverse("account:login"),
            {"username": self.admin.username, "password": self.password},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('account:select-package')}?reason=trial_expired")

    def test_middleware_blocks_expired_trial_access(self):
        Subscription.objects.create(
            school=self.school,
            package=None,
            is_active=True,
            is_trial=True,
            start_date=timezone.now() - timedelta(days=35),
            end_date=timezone.now() - timedelta(days=1),
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("adminservices:admin-dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('account:select-package')}?reason=trial_expired")


class StudentIdentifierGenerationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="idadmin",
            email="idadmin@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Identifier Test School",
            location="Accra",
            phone_number="0201111111",
            admin=self.admin,
        )

    def _create_student(self, index: int) -> Student:
        user = User.objects.create_user(
            username=f"student_seq_{index}",
            email=f"student_seq_{index}@example.com",
            password="StrongPass123!",
            role="student",
            first_name=f"Student{index}",
            last_name="Seq",
        )
        parent = Parent.objects.create(
            father_name=f"Father {index}",
            father_phone=f"02412345{index:02d}",
            mother_name=f"Mother {index}",
            mother_phone=f"05412345{index:02d}",
            present_address="Accra",
        )
        return Student.objects.create(
            user=user,
            parent=parent,
            school=self.school,
            student_class="JHS_1",
            mobile_number=f"02012345{index:02d}",
        )

    def test_student_id_is_auto_generated_unique_and_sequential(self):
        first = self._create_student(1)
        second = self._create_student(2)

        self.assertRegex(first.student_id, r"^STU-\d{6}$")
        self.assertRegex(second.student_id, r"^STU-\d{6}$")
        self.assertNotEqual(first.student_id, second.student_id)

        first_seq = int(first.student_id.split("-")[1])
        second_seq = int(second.student_id.split("-")[1])
        self.assertEqual(second_seq, first_seq + 1)
