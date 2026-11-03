from ai_predictor.models import PredictedPerformance
from decimal import Decimal
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from account.models import Attendance, Parent, School, Student, Subscription, Teacher, Department, Subject, Enrollment, ResultSheet, PromotionHistory
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


class ResultsAndGradingTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="gradingadmin",
            email="gradingadmin@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Grading School",
            location="Accra",
            phone_number="0201111111",
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

        self.teacher_user = User.objects.create_user(
            username="testteacher",
            email="testteacher@example.com",
            password="StrongPass123!",
            role="teacher",
            first_name="Jane",
            last_name="Doe",
        )
        self.teacher = Teacher.objects.create(
            user=self.teacher_user,
            school=self.school,
            is_class_teacher=True,
            class_teacher_class="JHS_1",
        )

        self.department = Department.objects.create(
            school=self.school,
            name="Science Department",
            code="SCI",
        )
        self.subject = Subject.objects.create(
            school=self.school,
            department=self.department,
            teacher=self.teacher,
            name="Integrated Science",
            subject_class="JHS_1",
        )

        student_user = User.objects.create_user(
            username="gradestudent",
            email="gradestudent@example.com",
            password="StrongPass123!",
            role="student",
            first_name="Kwame",
            last_name="Mensah",
        )
        parent = Parent.objects.create(
            father_name="Kofi Mensah",
            father_phone="0241111111",
            mother_name="Ama Mensah",
            mother_phone="0541111111",
            present_address="Accra",
        )
        self.student = Student.objects.create(
            user=student_user,
            parent=parent,
            school=self.school,
            student_class="JHS_1",
            mobile_number="0202222222",
        )
        Enrollment.objects.get_or_create(
            student=self.student,
            subject=self.subject,
            defaults={"is_active": True},
        )

        self.result = ResultSheet.objects.create(
            student=self.student,
            subject=self.subject,
            term="1",
            academic_year="2026/2027",
            class_score=Decimal('15.0'),
            mid_semester=Decimal('22.5'),
            end_of_term_exams=Decimal('40.0'),
        )

    def test_my_subjects_view(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("teacher:my-subjects"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Integrated Science")
        self.assertEqual(response.context["total_subjects"], 1)
        self.assertEqual(response.context["total_enrollments"], 1)

    def test_list_result_view(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("teacher:list-result"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kwame Mensah")
        self.assertContains(response, "Integrated Science")
        self.assertEqual(response.context["total_results"], 1)
        self.assertGreaterEqual(response.context["pass_rate"], 100)

    def test_bulk_grade_entry_get(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("teacher:enter-bulk-grades", args=[self.subject.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kwame Mensah")
        self.assertContains(response, "Integrated Science")

    def test_bulk_grade_entry_post(self):
        self.client.force_login(self.teacher_user)
        post_data = {
            "term": "1",
            "academic_year": "2026/2027",
            "exam_date": str(date.today()),
            f"class_score_{self.student.id}": "18.00",
            f"mid_semester_{self.student.id}": "25.00",
            f"end_of_term_exams_{self.student.id}": "45.00",
            f"comment_{self.student.id}": "Outstanding performance this term.",
        }
        response = self.client.post(
            reverse("teacher:enter-bulk-grades", args=[self.subject.id]),
            data=post_data,
        )
        self.assertEqual(response.status_code, 302)
        
        # Verify saved result sheet
        updated_res = ResultSheet.objects.get(
            student=self.student,
            subject=self.subject,
            term="1",
            academic_year="2026/2027"
        )
        self.assertEqual(float(updated_res.class_score), 18.0)
        self.assertEqual(float(updated_res.mid_semester), 25.0)
        self.assertEqual(float(updated_res.end_of_term_exams), 45.0)
        self.assertEqual(float(updated_res.total_marks), 88.0)
        self.assertEqual(updated_res.grade, "A")
        self.assertEqual(updated_res.remark, "excellent")

    def test_edit_result_get_and_post(self):
        self.client.force_login(self.teacher_user)
        get_response = self.client.get(reverse("teacher:edit-result", args=[self.result.id]))
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Kwame Mensah")

        post_data = {
            "class_score": "19.00",
            "mid_semester": "28.00",
            "end_of_term_exams": "48.00",
            "teacher_comment": "Top of the class.",
        }
        post_response = self.client.post(
            reverse("teacher:edit-result", args=[self.result.id]),
            data=post_data,
        )
        self.assertEqual(post_response.status_code, 302)

        self.result.refresh_from_db()
        self.assertEqual(float(self.result.total_marks), 95.0)
        self.assertEqual(self.result.grade, "A+")

    def test_view_result_view(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("teacher:view-result", args=[self.student.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kwame Mensah")
        self.assertContains(response, "Integrated Science")
        self.assertEqual(response.context["result_summary"]["total_subjects"], 1)

    def test_delete_result(self):
        self.client.force_login(self.teacher_user)
        response = self.client.post(reverse("teacher:delete-result", args=[self.result.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ResultSheet.objects.filter(id=self.result.id).exists())

    def test_teacher_students_view(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("teacher:teacher-students"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kwame Mensah")
        self.assertEqual(response.context["total_students_count"], 1)

    def test_teacher_students_search_and_filter(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("teacher:teacher-students") + "?search=Kwame")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kwame Mensah")

        # Non-matching search
        empty_response = self.client.get(reverse("teacher:teacher-students") + "?search=NonExistentStudent")
        self.assertEqual(empty_response.status_code, 200)
        self.assertNotContains(empty_response, "Kwame Mensah")

    def test_teacher_students_by_subject_view(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("teacher:teacher-students-by-subject", args=[self.subject.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kwame Mensah")
        self.assertContains(response, "Integrated Science")
        self.assertEqual(response.context["total_students"], 1)


class PromotionAccessControlTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="promoadmin",
            email="promoadmin@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Promotion School",
            location="Accra",
            phone_number="0209999999",
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
            username="promoclassteacher",
            email="promoclassteacher@example.com",
            password="StrongPass123!",
            role="teacher",
            first_name="Alice",
            last_name="ClassTeacher",
        )
        self.class_teacher = Teacher.objects.create(
            user=self.class_teacher_user,
            school=self.school,
            is_class_teacher=True,
            class_teacher_class="JHS_1",
        )

        self.subject_teacher_user = User.objects.create_user(
            username="promosubjectteacher",
            email="promosubjectteacher@example.com",
            password="StrongPass123!",
            role="teacher",
            first_name="Bob",
            last_name="SubjectTeacher",
        )
        self.subject_teacher = Teacher.objects.create(
            user=self.subject_teacher_user,
            school=self.school,
            is_class_teacher=False,
        )

        parent = Parent.objects.create(
            father_name="Kweku Parent",
            father_phone="0240001111",
            mother_name="Akua Parent",
            mother_phone="0540001111",
            present_address="Accra",
        )

        # Create two students: one in JHS 1, one in JHS 2
        student1_user = User.objects.create_user(
            username="promostudent1",
            email="promostudent1@example.com",
            password="StrongPass123!",
            role="student",
            first_name="Kofi",
            last_name="InClass",
        )
        self.student_in_class = Student.objects.create(
            user=student1_user,
            parent=parent,
            school=self.school,
            student_class="JHS_1",
            mobile_number="0201111222",
        )

        student2_user = User.objects.create_user(
            username="promostudent2",
            email="promostudent2@example.com",
            password="StrongPass123!",
            role="student",
            first_name="Ama",
            last_name="OtherClass",
        )
        self.student_other_class = Student.objects.create(
            user=student2_user,
            parent=parent,
            school=self.school,
            student_class="JHS_2",
            mobile_number="0203333444",
        )

    def test_promotion_dashboard_access(self):
        self.client.force_login(self.class_teacher_user)
        response = self.client.get(reverse("teacher:promotion-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_class_teacher"])
        self.assertIsNotNone(response.context["my_class_data"])

    def test_non_class_teacher_blocked_from_managing_promotion(self):
        self.client.force_login(self.subject_teacher_user)
        
        # Blocked from class roster
        res1 = self.client.get(reverse("teacher:view-class-students", args=["JHS_1"]))
        self.assertEqual(res1.status_code, 302)

        # Blocked from bulk promote
        res2 = self.client.get(reverse("teacher:bulk-promote", args=["JHS_1"]))
        self.assertEqual(res2.status_code, 302)

        # Blocked from individual promote
        res3 = self.client.get(reverse("teacher:individual-promotion", args=[self.student_in_class.id]))
        self.assertEqual(res3.status_code, 302)

    def test_class_teacher_cannot_manage_other_class(self):
        self.client.force_login(self.class_teacher_user)

        # Trying to access JHS 2 (not their assigned class)
        res1 = self.client.get(reverse("teacher:view-class-students", args=["JHS_2"]))
        self.assertEqual(res1.status_code, 302)

        res2 = self.client.get(reverse("teacher:bulk-promote", args=["JHS_2"]))
        self.assertEqual(res2.status_code, 302)

        res3 = self.client.get(reverse("teacher:individual-promotion", args=[self.student_other_class.id]))
        self.assertEqual(res3.status_code, 302)

    def test_class_teacher_can_promote_assigned_class_student(self):
        self.client.force_login(self.class_teacher_user)

        # Can view individual promotion for their student
        res_get = self.client.get(reverse("teacher:individual-promotion", args=[self.student_in_class.id]))
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, "Kofi InClass")

        # Promote student to next class
        res_post = self.client.post(
            reverse("teacher:individual-promotion", args=[self.student_in_class.id]),
            {
                "promotion_action": "promote",
                "academic_year": "2026/2027",
                "remarks": "Promoted with good marks",
            }
        )
        self.assertEqual(res_post.status_code, 302)

        self.student_in_class.refresh_from_db()
        self.assertEqual(self.student_in_class.promotion_status, "promoted")
        self.assertTrue(
            PromotionHistory.objects.filter(
                student=self.student_in_class,
                academic_year="2026/2027"
            ).exists()
        )

    def test_class_teacher_can_revert_promotion(self):
        self.client.force_login(self.class_teacher_user)

        # First promote student
        self.client.post(
            reverse("teacher:individual-promotion", args=[self.student_in_class.id]),
            {
                "promotion_action": "promote",
                "academic_year": "2026/2027",
                "remarks": "Promoted",
            }
        )

        # Now revert promotion
        res_revert = self.client.post(
            reverse("teacher:individual-promotion", args=[self.student_in_class.id]),
            {
                "promotion_action": "revert",
                "academic_year": "2026/2027",
                "remarks": "Reverted back",
            }
        )
        self.assertEqual(res_revert.status_code, 302)

        self.student_in_class.refresh_from_db()
        self.assertEqual(self.student_in_class.promotion_status, "pending")


class AIInsightsViewTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="aiadmin",
            email="aiadmin@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="AI Insights School",
            location="Accra",
            phone_number="0205555555",
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

        self.teacher_user = User.objects.create_user(
            username="aiteacher",
            email="aiteacher@example.com",
            password="StrongPass123!",
            role="teacher",
            first_name="AI",
            last_name="Instructor",
        )
        self.teacher = Teacher.objects.create(
            user=self.teacher_user,
            school=self.school,
            is_class_teacher=True,
            class_teacher_class="Basic_1",
        )

        parent = Parent.objects.create(
            father_name="AI Parent",
            father_phone="0241112233",
            present_address="Accra",
        )

        self.student1_user = User.objects.create_user(
            username="aistudent1",
            email="aistudent1@example.com",
            password="StrongPass123!",
            role="student",
            first_name="Kofi",
            last_name="Predicted",
        )
        self.student1 = Student.objects.create(
            user=self.student1_user,
            parent=parent,
            school=self.school,
            student_class="Basic_1",
            mobile_number="0201119999",
        )

        self.student2_user = User.objects.create_user(
            username="aistudent2",
            email="aistudent2@example.com",
            password="StrongPass123!",
            role="student",
            first_name="Ama",
            last_name="Predicted",
        )
        self.student2 = Student.objects.create(
            user=self.student2_user,
            parent=parent,
            school=self.school,
            student_class="Basic_2",
            mobile_number="0202229999",
        )

        # Create Predictions
        self.pred1 = PredictedPerformance.objects.create(
            student=self.student1,
            predicted_grade="F",
            risk_level="High",
        )
        self.pred2 = PredictedPerformance.objects.create(
            student=self.student2,
            predicted_grade="A",
            risk_level="Low",
        )

    def test_ai_dashboard_unauthenticated_redirect(self):
        response = self.client.get(reverse("teacher:ai_dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_ai_dashboard_unauthorized_student(self):
        self.client.force_login(self.student1_user)
        response = self.client.get(reverse("teacher:ai_dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_ai_dashboard_as_teacher(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("teacher:ai_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kofi Predicted")
        self.assertContains(response, "Ama Predicted")
        self.assertEqual(response.context["total_analyzed"], 2)
        self.assertEqual(response.context["high_risk_count"], 1)
        self.assertEqual(response.context["low_risk_count"], 1)

    def test_ai_dashboard_filter_by_risk(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("teacher:ai_dashboard") + "?risk=High")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kofi Predicted")
        self.assertNotContains(response, "Ama Predicted")

    def test_ai_dashboard_filter_by_class(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("teacher:ai_dashboard") + "?class=Basic_2")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Kofi Predicted")
        self.assertContains(response, "Ama Predicted")

    def test_ai_dashboard_filter_by_search(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse("teacher:ai_dashboard") + "?search=Kofi")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kofi Predicted")
        self.assertNotContains(response, "Ama Predicted")

    def test_ai_dashboard_as_admin(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("teacher:ai_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kofi Predicted")
