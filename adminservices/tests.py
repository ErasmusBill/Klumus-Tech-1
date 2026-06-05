from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from account.models import School, Subscription, Teacher
from adminservices.forms import AddTeacherForm


User = get_user_model()


class AddTeacherFormTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="adminform",
            email="adminform@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Form School",
            location="Accra",
            phone_number="0201000000",
            admin=self.admin_user,
        )
        Subscription.objects.create(
            school=self.school,
            package=None,
            is_active=True,
            is_trial=True,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=29),
        )

    def _base_form_data(self):
        return {
            "first_name": "Ada",
            "last_name": "Teacher",
            "email": "ada.teacher@example.com",
            "username": "adateacher",
            "password": "",
            "gender": "female",
            "date_of_birth": "1990-01-01",
            "address": "Accra",
            "phone_number": "0201234567",
            "qualification": "BEd",
            "specialization": "Mathematics",
            "experience_years": "5",
            "hire_date": "2020-01-01",
            "department": "",
            "employment_type": "full_time",
            "salary": "1000.00",
            "bio": "Experienced teacher",
            "is_class_teacher": "on",
        }

    def test_class_teacher_requires_assigned_class(self):
        form = AddTeacherForm(data=self._base_form_data(), school=self.school)

        self.assertFalse(form.is_valid())
        self.assertIn("class_teacher_class", form.errors)


class AddTeacherViewTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="adminview",
            email="adminview@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="View School",
            location="Kumasi",
            phone_number="0202000000",
            admin=self.admin_user,
        )
        Subscription.objects.create(
            school=self.school,
            package=None,
            is_active=True,
            is_trial=True,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=29),
        )

    @patch("adminservices.views.send_notification")
    def test_add_teacher_persists_class_teacher_fields(self, mock_send_notification):
        mock_send_notification.return_value = {
            "email_sent": False,
            "sms_sent": False,
            "in_app_created": 0,
        }

        self.client.force_login(self.admin_user)

        response = self.client.post(
            reverse("adminservices:add-teacher"),
            {
                "first_name": "Ada",
                "last_name": "Teacher",
                "email": "ada.teacher@example.com",
                "username": "adateacher",
                "password": "",
                "gender": "female",
                "date_of_birth": "1990-01-01",
                "address": "Accra",
                "phone_number": "0201234567",
                "qualification": "BEd",
                "specialization": "Mathematics",
                "experience_years": "5",
                "hire_date": "2020-01-01",
                "department": "",
                "employment_type": "full_time",
                "salary": "1000.00",
                "bio": "Experienced teacher",
                "is_class_teacher": "on",
                "class_teacher_class": "JHS_1",
            },
        )

        self.assertEqual(response.status_code, 302)
        teacher = Teacher.objects.get(user__username="adateacher")
        self.assertTrue(teacher.is_class_teacher)
        self.assertEqual(teacher.class_teacher_class, "JHS_1")
