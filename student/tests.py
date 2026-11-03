from django.contrib.staticfiles import finders
from django.test import SimpleTestCase


class StudentStaticAssetTests(SimpleTestCase):
    def test_empty_assignments_illustration_exists(self):
        self.assertIsNotNone(
            finders.find("assets/img/no-tasks.svg"),
            "Expected student empty-state illustration to exist at static/assets/img/no-tasks.svg.",
        )

    def test_billing_empty_state_illustration_exists(self):
        self.assertIsNotNone(
            finders.find("assets/img/no-billing.svg"),
            "Expected billing empty-state illustration to exist at static/assets/img/no-billing.svg.",
        )

from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from account.models import (
    School, Student, Parent, Subscription, Department, Subject, Teacher,
    Enrollment, Assignment, AssignmentSubmission, ResultSheet, Fees, SchoolClass
)

User = get_user_model()


class StudentDashboardViewTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="studentdashadmin",
            email="sdadmin@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Apex Student Academy",
            location="Accra",
            phone_number="0201110000",
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

        self.student_user = User.objects.create_user(
            username="dashstudent",
            email="dashstudent@example.com",
            password="StrongPass123!",
            role="student",
            first_name="Emmanuel",
            last_name="Quaye",
        )
        self.parent = Parent.objects.create(
            father_name="Kofi Quaye",
            father_phone="0241112233",
            present_address="Accra",
        )
        self.student = Student.objects.create(
            user=self.student_user,
            school=self.school,
            parent=self.parent,
            student_class="Basic_1",
            mobile_number="0203334444",
        )

        self.teacher_user = User.objects.create_user(
            username="dashteacher",
            email="dashteacher@example.com",
            password="StrongPass123!",
            role="teacher",
            first_name="Grace",
            last_name="Teacher",
        )

    def test_student_dashboard_redirects_unauthenticated(self):
        response = self.client.get(reverse("student:student-dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_student_dashboard_blocks_non_student(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("student:student-dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_student_dashboard_renders_successfully(self):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse("student:student-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Emmanuel")
        self.assertContains(response, "Apex Student Academy")
        self.assertIn("enrolled_courses", response.context)
        self.assertIn("attendance_rate", response.context)
        self.assertIn("pending_assignments_count", response.context)

    def test_student_dashboard_with_results_and_fees(self):
        dept = Department.objects.create(name="Sciences", school=self.school)
        subj = Subject.objects.create(
            name="Science",
            school=self.school,
            department=dept,
            subject_class="Basic_1",
        )
        Enrollment.objects.get_or_create(student=self.student, subject=subj, defaults={"is_active": True})

        ResultSheet.objects.create(
            student=self.student,
            subject=subj,
            term="1",
            academic_year="2026/2027",
            class_score=18,
            mid_semester=27,
            end_of_term_exams=45,
            total_marks=90,
            percentage=90,
            grade="A",
            remark="Excellent",
        )

        Fees.objects.create(
            student=self.student,
            school=self.school,
            academic_year="2026/2027",
            term="1",
            amount_required=500,
            discount=50,
            amount_paid=100,
            status="partial",
            due_date=timezone.now().date() + timedelta(days=10),
        )

        self.client.force_login(self.student_user)
        response = self.client.get(reverse("student:student-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Science")
        self.assertContains(response, "90")
        self.assertContains(response, "GHS 350.00")
        self.assertEqual(response.context["total_pending_fees"], 350)
        self.assertEqual(response.context["average_grade"], 90.0)

    def test_submit_assignment_on_time_and_overdue(self):
        teacher = Teacher.objects.create(
            user=self.teacher_user,
            school=self.school,
        )
        dept = Department.objects.create(name="English Dept", school=self.school)
        subj = Subject.objects.create(
            name="English",
            school=self.school,
            department=dept,
            teacher=teacher,
            subject_class="Basic_1",
        )
        Enrollment.objects.get_or_create(student=self.student, subject=subj, defaults={"is_active": True})

        # 1. On-time assignment
        assignment_ontime = Assignment.objects.create(
            subject=subj,
            teacher=teacher,
            student_class=self.student.student_class,
            title="Grammar Essay",
            due_date=timezone.now().date() + timedelta(days=2),
            status="published",
        )

        self.client.force_login(self.student_user)
        post_url = reverse("student:submit-assignment", args=[assignment_ontime.id])
        res_ontime = self.client.post(post_url, {
            "submission_text": "Here is my completed essay."
        })
        self.assertEqual(res_ontime.status_code, 302)
        sub_ontime = AssignmentSubmission.objects.get(assignment=assignment_ontime, student=self.student)
        self.assertEqual(sub_ontime.status, "submitted")

        # 2. Overdue assignment
        assignment_late = Assignment.objects.create(
            subject=subj,
            teacher=teacher,
            student_class=self.student.student_class,
            title="Late Essay",
            due_date=timezone.now().date() - timedelta(days=2),
            status="published",
        )
        post_url_late = reverse("student:submit-assignment", args=[assignment_late.id])
        res_late = self.client.post(post_url_late, {
            "submission_text": "Here is my late essay."
        })
        self.assertEqual(res_late.status_code, 302)
        sub_late = AssignmentSubmission.objects.get(assignment=assignment_late, student=self.student)
        self.assertEqual(sub_late.status, "late")

    def test_student_detail_view_renders_successfully(self):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse("student:student-detail"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Emmanuel Quaye")
        self.assertContains(response, "Kofi Quaye")
        self.assertIn("student", response.context)
        self.assertIn("attendance_rate", response.context)
        self.assertIn("total_pending_fees", response.context)

    def test_student_detail_view_with_pending_fees(self):
        # Create a pending fee with NO fee_structure (verifies display_name and balance fallback)
        Fees.objects.create(
            student=self.student,
            school=self.school,
            academic_year="2026/2027",
            term="1",
            amount_required=500,
            discount=50,
            amount_paid=100,
            status="partial",
            due_date=timezone.now().date() + timedelta(days=5),
        )
        self.client.force_login(self.student_user)
        response = self.client.get(reverse("student:student-detail"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "350.00")
        self.assertContains(response, "Tuition &amp; School Fees")

    def test_student_detail_view_with_class_fee_structure(self):
        from account.models import ClassFee
        class_fee = ClassFee.objects.create(
            school=self.school,
            student_class=self.student.student_class,
            fee_type="tuition",
            amount=600,
            academic_year="2026/2027",
            term="1",
        )
        Fees.objects.create(
            student=self.student,
            school=self.school,
            fee_structure=class_fee,
            academic_year="2026/2027",
            term="1",
            amount_required=600,
            discount=0,
            amount_paid=200,
            status="partial",
            due_date=timezone.now().date() + timedelta(days=5),
        )
        self.client.force_login(self.student_user)
        response = self.client.get(reverse("student:student-detail"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "400.00")
        self.assertContains(response, "Tuition Fee")

    def test_enrolled_courses_view_renders_successfully(self):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse("student:enrolled-courses"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "My Enrolled Courses &amp; Curriculum")
        self.assertIn("courses_data", response.context)
        self.assertIn("total_enrollments", response.context)

    def test_enrolled_courses_with_rich_subject_data(self):
        teacher = Teacher.objects.create(
            user=self.teacher_user,
            school=self.school,
        )
        dept = Department.objects.create(name="Sciences", school=self.school)
        subj = Subject.objects.create(
            name="Physics 101",
            school=self.school,
            department=dept,
            teacher=teacher,
            subject_class="Basic_1",
        )
        enrollment, _ = Enrollment.objects.get_or_create(student=self.student, subject=subj, defaults={"is_active": True})

        assignment = Assignment.objects.create(
            subject=subj,
            teacher=teacher,
            student_class=self.student.student_class,
            title="Lab Report",
            due_date=timezone.now().date() + timedelta(days=3),
            status="published",
        )

        ResultSheet.objects.create(
            student=self.student,
            subject=subj,
            term="1",
            academic_year="2026/2027",
            class_score=19,
            mid_semester=28,
            end_of_term_exams=48,
            total_marks=95,
            percentage=95,
            grade="A+",
            remark="Excellent",
        )

        self.client.force_login(self.student_user)
        response = self.client.get(reverse("student:enrolled-courses"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Physics 101")
        self.assertContains(response, "Sciences")
        self.assertContains(response, "Grace Teacher")
        self.assertContains(response, "1 Due")
        self.assertContains(response, "A+")

        # Test search filter
        response_search = self.client.get(reverse("student:enrolled-courses") + "?search=Physics")
        self.assertEqual(response_search.status_code, 200)
        self.assertContains(response_search, "Physics 101")

        # Test department filter
        response_dept = self.client.get(reverse("student:enrolled-courses") + "?department=Sciences")
        self.assertEqual(response_dept.status_code, 200)
        self.assertContains(response_dept, "Physics 101")

    def test_view_all_assignment_renders_successfully(self):
        teacher = Teacher.objects.create(
            user=self.teacher_user,
            school=self.school,
        )
        dept = Department.objects.create(name="Languages", school=self.school)
        subj = Subject.objects.create(
            name="Literature",
            school=self.school,
            department=dept,
            teacher=teacher,
            subject_class="Basic_1",
        )
        Enrollment.objects.get_or_create(student=self.student, subject=subj, defaults={"is_active": True})

        assignment = Assignment.objects.create(
            subject=subj,
            teacher=teacher,
            student_class=self.student.student_class,
            title="Shakespeare Essay",
            due_date=timezone.now().date() + timedelta(days=5),
            status="published",
            total_marks=50,
        )

        self.client.force_login(self.student_user)
        response = self.client.get(reverse("student:list-all-assignments"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shakespeare Essay")
        self.assertContains(response, "Literature")
        self.assertContains(response, "Grace Teacher")
        self.assertEqual(response.context["total_count"], 1)
        self.assertEqual(response.context["pending_count"], 1)

        # Detail view
        detail_response = self.client.get(reverse("student:assignment-detail", args=[assignment.id]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Shakespeare Essay")
        self.assertContains(detail_response, "50 Points")

    def test_view_result_renders_successfully(self):
        dept = Department.objects.create(name="Mathematics Dept", school=self.school)
        subj = Subject.objects.create(
            name="General Mathematics",
            school=self.school,
            department=dept,
            subject_class="Basic_1",
        )
        ResultSheet.objects.create(
            student=self.student,
            subject=subj,
            term="1",
            academic_year="2026/2027",
            class_score=18,
            mid_semester=28,
            end_of_term_exams=46,
            total_marks=92,
            percentage=92,
            grade="A+",
            remark="excellent",
            teacher_comment="Outstanding mathematical aptitude",
        )

        self.client.force_login(self.student_user)
        response = self.client.get(reverse("student:view-result", args=[self.student.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "General Mathematics")
        self.assertContains(response, "First Term")
        self.assertContains(response, "2026/2027")
        self.assertContains(response, "92.0%")
        self.assertContains(response, "Outstanding mathematical aptitude")
        self.assertEqual(response.context["result_summary"]["standing_grade"], "A")
        self.assertEqual(len(response.context["grouped_reports"]), 1)
        self.assertEqual(response.context["grouped_reports"][0]["term_average"], 92.0)

        # Test filtering by academic year and term
        filtered_res = self.client.get(reverse("student:view-result", args=[self.student.id]) + "?academic_year=2026/2027&term=1")
        self.assertEqual(filtered_res.status_code, 200)
        self.assertContains(filtered_res, "General Mathematics")

        # Test filter with no match
        empty_res = self.client.get(reverse("student:view-result", args=[self.student.id]) + "?academic_year=2024/2025")
        self.assertEqual(empty_res.status_code, 200)
        self.assertContains(empty_res, "No Academic Records Found")
