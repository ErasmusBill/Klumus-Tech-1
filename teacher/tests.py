from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from account.models import Attendance, Parent, School, Student, Subscription, Teacher
from teacher.forms import AttendanceForm


User = get_user_model()


class AttendanceAccessControlTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="schooladmin",
            email="schooladmin@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Access Control School",
            location="Accra",
            phone_number="0200000000",
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

        self.class_teacher_user = User.objects.create_user(
            username="classteacher",
            email="classteacher@example.com",
            password="StrongPass123!",
            role="teacher",
            first_name="Class",
            last_name="Teacher",
        )
        self.class_teacher = Teacher.objects.create(
            user=self.class_teacher_user,
            school=self.school,
            is_class_teacher=True,
            class_teacher_class="JHS_1",
        )

        self.subject_teacher_user = User.objects.create_user(
            username="subjectteacher",
            email="subjectteacher@example.com",
            password="StrongPass123!",
            role="teacher",
            first_name="Subject",
            last_name="Teacher",
        )
        self.subject_teacher = Teacher.objects.create(
            user=self.subject_teacher_user,
            school=self.school,
            is_class_teacher=False,
        )

        self.student_in_class = self._create_student("student-in", "JHS_1", "In", "Class")
        self.student_out_class = self._create_student("student-out", "JHS_2", "Out", "Class")

    def _create_student(self, username: str, student_class: str, first_name: str, last_name: str) -> Student:
        student_user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="StrongPass123!",
            role="student",
            first_name=first_name,
            last_name=last_name,
        )
        parent = Parent.objects.create(
            father_name=f"{first_name} Father",
            father_phone="0240000000",
            mother_name=f"{first_name} Mother",
            mother_phone="0540000000",
            present_address="Accra",
        )
        return Student.objects.create(
            user=student_user,
            parent=parent,
            school=self.school,
            student_class=student_class,
            mobile_number="0200000001",
        )

    def test_attendance_form_limits_students_to_assigned_class(self):
        form = AttendanceForm(school=self.school, teacher=self.class_teacher)

        self.assertTrue(form.restricted_to_class_teacher)
        self.assertEqual(list(form.fields["attendance_type"].choices), [("student", "Student")])
        self.assertNotIn(self.student_out_class.pk, list(form.fields["student"].queryset.values_list("pk", flat=True)))
        self.assertIn(self.student_in_class.pk, list(form.fields["student"].queryset.values_list("pk", flat=True)))

    def test_class_teacher_can_mark_attendance_for_assigned_class(self):
        self.client.force_login(self.class_teacher_user)

        response = self.client.post(
            reverse("teacher:mark-attendance"),
            {
                "student": str(self.student_in_class.pk),
                "date": "2026-06-02",
                "status": "present",
                "remarks": "On time",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("teacher:attendance-list"))
        self.assertTrue(
            Attendance.objects.filter(
                student=self.student_in_class,
                attendance_type="student",
                class_attendance="JHS_1",
                marked_by=self.class_teacher_user,
            ).exists()
        )

    def test_class_teacher_rejects_student_from_other_class(self):
        self.client.force_login(self.class_teacher_user)

        response = self.client.post(
            reverse("teacher:mark-attendance"),
            {
                "student": str(self.student_out_class.pk),
                "date": "2026-06-02",
                "status": "present",
                "remarks": "Wrong class",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            Attendance.objects.filter(
                student=self.student_out_class,
                marked_by=self.class_teacher_user,
            ).exists()
        )

    def test_non_class_teacher_cannot_access_attendance_pages(self):
        self.client.force_login(self.subject_teacher_user)

        list_response = self.client.get(reverse("teacher:attendance-list"))
        self.assertEqual(list_response.status_code, 302)
        self.assertEqual(list_response.url, reverse("teacher:teacher-dashboard"))

        mark_response = self.client.get(reverse("teacher:mark-attendance"))
        self.assertEqual(mark_response.status_code, 302)
        self.assertEqual(mark_response.url, reverse("teacher:teacher-dashboard"))

    def test_class_teacher_sees_only_assigned_class_records(self):
        Attendance.objects.create(
            attendance_type="student",
            student=self.student_in_class,
            class_attendance="JHS_1",
            date=date(2026, 6, 1),
            status="present",
            marked_by=self.class_teacher_user,
        )
        Attendance.objects.create(
            attendance_type="student",
            student=self.student_out_class,
            class_attendance="JHS_2",
            date=date(2026, 6, 1),
            status="present",
            marked_by=self.class_teacher_user,
        )

        self.client.force_login(self.class_teacher_user)
        response = self.client.get(reverse("teacher:attendance-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.student_in_class.user.get_full_name())
        self.assertNotContains(response, self.student_out_class.user.get_full_name())
