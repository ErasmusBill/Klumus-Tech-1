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


class DeleteClassViewTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admindelclass",
            email="admindelclass@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Delete Class School",
            location="Accra",
            phone_number="0203000000",
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
        self.client.force_login(self.admin_user)

    def test_get_delete_class_renders_confirmation_page(self):
        from account.models import SchoolClass
        test_class = SchoolClass.objects.create(
            school=self.school,
            name="Confirmation Test Class",
            code="CONF_1",
            order=50
        )
        response = self.client.get(reverse("adminservices:delete-class", args=[test_class.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Confirmation Test Class")
        self.assertContains(response, "Yes, Delete Permanently")

    def test_post_delete_empty_custom_class_succeeds(self):
        from account.models import SchoolClass
        test_class = SchoolClass.objects.create(
            school=self.school,
            name="Empty Custom Class",
            code="EMPTY_1",
            order=51
        )
        class_id = test_class.id
        response = self.client.post(reverse("adminservices:delete-class", args=[class_id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SchoolClass.objects.filter(id=class_id).exists())
        self.assertContains(response, "deleted successfully")

    def test_post_delete_class_with_students_is_blocked(self):
        from account.models import SchoolClass, Student, Parent
        test_class = SchoolClass.objects.create(
            school=self.school,
            name="Protected Class",
            code="PROT_1",
            order=52
        )
        parent = Parent.objects.create(
            father_name="Father", father_phone="0240000000",
            mother_name="Mother", mother_phone="0240000001"
        )
        student_user = User.objects.create_user(
            username="studprot", email="studprot@example.com",
            role="student"
        )
        Student.objects.create(
            user=student_user, parent=parent, school=self.school,
            student_class=test_class
        )
        response = self.client.post(reverse("adminservices:delete-class", args=[test_class.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(SchoolClass.objects.filter(id=test_class.id).exists())
        self.assertContains(response, "Cannot delete class")

    def test_post_delete_global_class_excludes_for_school(self):
        from account.models import SchoolClass
        global_class, _ = SchoolClass.objects.get_or_create(
            school=None,
            name="Global Test Grade",
            defaults={"code": "GLOBAL_GRADE", "order": 53}
        )
        response = self.client.post(reverse("adminservices:delete-class", args=[global_class.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "deleted successfully")
        classes_for_school = SchoolClass.for_school(self.school)
        self.assertNotIn(global_class, classes_for_school)


class SubjectDetailViewTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="adminsubject",
            email="adminsubject@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Subject Test School",
            location="Accra",
            phone_number="0203000000",
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
        from account.models import Department, Subject, SchoolClass
        self.dept = Department.objects.create(
            school=self.school,
            name="Science Department"
        )
        self.sclass = SchoolClass.objects.create(
            school=self.school,
            name="Primary 4 Testing",
            code="P4_TEST",
            order=10
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="Integrated Science",
            department=self.dept,
            subject_class=self.sclass
        )

    def test_subject_detail_canonical_url_renders_successfully(self):
        self.client.force_login(self.admin_user)
        url = reverse("adminservices:subject-detail", args=[self.subject.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "adminservices/subject_detail.html")
        self.assertContains(response, self.subject.name)
        self.assertContains(response, self.dept.name)
        self.assertContains(response, self.sclass.name)

    def test_subject_detail_typo_url_backward_compatibility(self):
        self.client.force_login(self.admin_user)
        # Verify the legacy / typo URL works without raising TemplateDoesNotExist
        response = self.client.get(f"/adminservices/subject-detial/{self.subject.id}")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "adminservices/subject_detail.html")
        self.assertContains(response, self.subject.name)

    def test_subject_detail_unauthorized_for_anonymous(self):
        url = reverse("adminservices:subject-detail", args=[self.subject.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_edit_subject_get_renders_successfully(self):
        self.client.force_login(self.admin_user)
        url = reverse("adminservices:edit-subject", args=[self.subject.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "adminservices/edit_subject.html")
        self.assertContains(response, self.subject.name)

    def test_edit_subject_post_updates_name(self):
        self.client.force_login(self.admin_user)
        url = reverse("adminservices:edit-subject", args=[self.subject.id])
        post_data = {
            "name": "Updated Science Name",
            "department": str(self.dept.id),
            "subject_class": str(self.sclass.id),
            "teacher": "",
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        self.subject.refresh_from_db()
        self.assertEqual(self.subject.name, "Updated Science Name")


class StudentGuardianAndAdmissionFormTests(TestCase):
    def setUp(self):
        from account.models import SchoolClass, Student, Parent
        self.admin_user = User.objects.create_user(
            username="adminstudent",
            email="adminstudent@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Apex Academy",
            location="Accra Central",
            phone_number="0244123456",
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
        self.sclass = SchoolClass.objects.create(
            school=self.school,
            name="Grade 6 Gold",
            code="G6_GOLD",
            order=6,
        )
        self.prev_class = SchoolClass.objects.create(
            school=self.school,
            name="Grade 5 Silver",
            code="G5_SILVER",
            order=5,
        )

    def _base_student_data(self):
        return {
            "first_name": "Kofi",
            "last_name": "Mensah",
            "email": "kofi.mensah@example.com",
            "username": "kofimensah",
            "date_of_birth": "2012-05-15",
            "gender": "male",
            "blood_group": "A+",
            "address": "House 42, Accra",
            "mobile_number": "0244000111",
            "student_class": str(self.sclass.id),
            "roll_number": "12",
            "admission_number": "ADM-2026-001",
            "joining_date": "2026-09-01",
            "previous_school": "St. Peters Primary",
            "previous_class": str(self.prev_class.id),
            "allergies": "Peanuts",
            "medical_conditions": "Mild asthma",
            "notes": "Requires front row seating",
            # Guardian fields
            "guardian_name": "Kwame Mensah",
            "guardian_relation": "Uncle / Legal Guardian",
            "guardian_phone": "0244999888",
            "guardian_email": "kwame.guardian@example.com",
            "guardian_occupation": "Civil Engineer",
            # Emergency & addresses
            "emergency_contact_name": "Akua Mensah",
            "emergency_contact_phone": "0244777666",
            "emergency_contact_relation": "Aunt",
            "present_address": "Airport Residential, Accra",
            "permanent_address": "Kumasi Central",
        }

    def test_form_valid_with_only_guardian(self):
        from adminservices.forms import AddStudentForm
        data = self._base_student_data()
        form = AddStudentForm(data=data, school=self.school)
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_invalid_if_no_parent_or_guardian(self):
        from adminservices.forms import AddStudentForm
        data = self._base_student_data()
        data["guardian_name"] = ""
        data["guardian_phone"] = ""
        form = AddStudentForm(data=data, school=self.school)
        self.assertFalse(form.is_valid())
        self.assertIn("at least one parent or guardian", str(form.errors))

    @patch("adminservices.views.send_notification")
    def test_create_student_with_guardian_view(self, mock_notify):
        mock_notify.return_value = {"email_sent": False, "sms_sent": False, "in_app_created": 0}
        self.client.force_login(self.admin_user)
        from account.models import Student, Parent
        url = reverse("adminservices:add-student")
        response = self.client.post(url, self._base_student_data())
        self.assertEqual(response.status_code, 302)

        student = Student.objects.get(user__username="kofimensah")
        self.assertEqual(student.school, self.school)
        self.assertEqual(student.student_class, self.sclass)
        self.assertEqual(student.previous_school, "St. Peters Primary")
        self.assertEqual(student.previous_class, self.prev_class)

        parent = student.parent
        self.assertIsNotNone(parent)
        self.assertEqual(parent.guardian_name, "Kwame Mensah")
        self.assertEqual(parent.guardian_phone, "0244999888")
        self.assertEqual(parent.guardian_relation, "Uncle / Legal Guardian")
        self.assertEqual(parent.guardian_email, "kwame.guardian@example.com")
        self.assertEqual(parent.guardian_occupation, "Civil Engineer")
        self.assertEqual(parent.emergency_contact_name, "Akua Mensah")
        self.assertEqual(parent.present_address, "Airport Residential, Accra")

    @patch("adminservices.views.send_notification")
    def test_student_detail_renders_guardian_and_class(self, mock_notify):
        mock_notify.return_value = {"email_sent": False, "sms_sent": False, "in_app_created": 0}
        self.client.force_login(self.admin_user)
        from account.models import Student
        self.client.post(reverse("adminservices:add-student"), self._base_student_data())
        student = Student.objects.get(user__username="kofimensah")

        url = reverse("adminservices:student-detail", args=[student.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kwame Mensah")
        self.assertContains(response, "Uncle / Legal Guardian")
        self.assertContains(response, "Grade 6 Gold")
        self.assertContains(response, "St. Peters Primary")
        self.assertContains(response, "Akua Mensah")

    @patch("adminservices.views.send_notification")
    def test_print_admission_form_renders_complete_data(self, mock_notify):
        mock_notify.return_value = {"email_sent": False, "sms_sent": False, "in_app_created": 0}
        self.client.force_login(self.admin_user)
        from account.models import Student
        self.client.post(reverse("adminservices:add-student"), self._base_student_data())
        student = Student.objects.get(user__username="kofimensah")

        url = reverse("adminservices:print-admission-form", args=[student.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "adminservices/admission_form.html")
        # Verify student details
        self.assertContains(response, "Kofi Mensah")
        self.assertContains(response, student.admission_number)
        # Verify class display (Grade 6 Gold)
        self.assertContains(response, "Grade 6 Gold")
        # Verify previous school and class
        self.assertContains(response, "St. Peters Primary")
        self.assertContains(response, "Grade 5 Silver")
        # Verify guardian details
        self.assertContains(response, "Kwame Mensah")
        self.assertContains(response, "Uncle / Legal Guardian")
        self.assertContains(response, "0244999888")
        self.assertContains(response, "Civil Engineer")
        # Verify emergency contact & address
        self.assertContains(response, "Akua Mensah")
        self.assertContains(response, "Airport Residential, Accra")
        self.assertContains(response, "Kumasi Central")
        # Verify medical information
        self.assertContains(response, "Peanuts")
        self.assertContains(response, "Mild asthma")

    @patch("adminservices.views.send_notification")
    def test_download_admission_form_pdf_endpoint(self, mock_notify):
        mock_notify.return_value = {"email_sent": False, "sms_sent": False, "in_app_created": 0}
        self.client.force_login(self.admin_user)
        from account.models import Student
        self.client.post(reverse("adminservices:add-student"), self._base_student_data())
        student = Student.objects.get(user__username="kofimensah")

        url = reverse("adminservices:download-admission-form", args=[student.id])
        response = self.client.get(url)
        # Should either return PDF response (status 200) or redirect if WeasyPrint is not installed
        self.assertIn(response.status_code, [200, 302])


class DeleteTeacherViewTests(TestCase):
    def setUp(self):
        from account.models import Teacher, Subject, Assignment, Timetable, SchoolClass
        self.admin_user = User.objects.create_user(
            username="admindelteach",
            email="admindelteach@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Delete Teacher School",
            location="Accra",
            phone_number="0203000001",
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
            username="teacher_to_delete",
            email="teacher_delete@example.com",
            password="StrongPass123!",
            role="teacher",
            first_name="Ama",
            last_name="Teacher",
        )
        from account.models import Department
        self.dept = Department.objects.create(
            school=self.school,
            name="Math Dept",
        )
        self.sclass = SchoolClass.objects.create(
            school=self.school,
            name="Class 1",
            code="CLS_1",
            order=1,
        )
        self.teacher = Teacher.objects.create(
            user=self.teacher_user,
            school=self.school,
            employment_type="full_time",
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="Mathematics",
            teacher=self.teacher,
            subject_class=self.sclass,
            department=self.dept,
        )
        self.assignment = Assignment.objects.create(
            subject=self.subject,
            teacher=self.teacher,
            student_class=self.sclass,
            title="Homework 1",
            description="Do exercise 1",
            due_date=timezone.now() + timedelta(days=2),
            total_marks=20,
        )

    def test_delete_teacher_with_related_assignment_succeeds(self):
        from account.models import Teacher, Assignment
        self.client.force_login(self.admin_user)
        url = reverse("adminservices:delete-teacher", args=[self.teacher.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Teacher.objects.filter(id=self.teacher.id).exists())
        self.assertFalse(Assignment.objects.filter(id=self.assignment.id).exists())


class DepartmentDetailViewTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admindetaildept",
            email="admindetaildept@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Detail School",
            location="Accra",
            phone_number="0203000000",
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
        from account.models import Department, SchoolClass, Subject
        self.dept = Department.objects.create(
            school=self.school,
            name="Science Department",
            code="SCI-01",
            description="Focuses on Physics, Chemistry, and Biology.",
            head_of_department="Kofi Mensah",
            number_of_students=45,
        )
        self.teacher_user = User.objects.create_user(
            username="scienceteacher",
            email="sciteacher@example.com",
            password="StrongPass123!",
            role="teacher",
            first_name="Kofi",
            last_name="Mensah",
        )
        self.teacher = Teacher.objects.create(
            user=self.teacher_user,
            school=self.school,
            department=self.dept,
            qualification="MSc Physics",
            specialization="Physics",
            employment_type="full_time",
        )
        self.sclass = SchoolClass.objects.create(
            school=self.school,
            name="Grade 10",
            code="G10",
            order=10,
        )
        self.subject = Subject.objects.create(
            school=self.school,
            name="Integrated Science",
            department=self.dept,
            teacher=self.teacher,
            subject_class=self.sclass,
        )

    def test_department_detail_renders_successfully(self):
        self.client.force_login(self.admin_user)
        url = reverse("adminservices:department-detail", args=[self.dept.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "adminservices/department_detail.html")
        self.assertContains(response, "Science Department")
        self.assertContains(response, "SCI-01")
        self.assertContains(response, "Integrated Science")
        self.assertContains(response, "Kofi Mensah")
        # Verify no static avatar fallbacks
        self.assertNotContains(response, "avatar-01.jpg")

    def test_department_detail_different_school_returns_404(self):
        other_admin = User.objects.create_user(
            username="otheradmin",
            email="otheradmin@example.com",
            password="StrongPass123!",
            role="admin",
        )
        other_school = School.objects.create(
            name="Other School",
            location="Kumasi",
            phone_number="0204000000",
            admin=other_admin,
        )
        Subscription.objects.create(
            school=other_school,
            package=None,
            is_active=True,
            is_trial=True,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=29),
        )
        self.client.force_login(other_admin)
        url = reverse("adminservices:department-detail", args=[self.dept.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class FeeManagementViewTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="adminfee",
            email="adminfee@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Fee School",
            location="Accra",
            phone_number="0205000000",
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
        from account.models import SchoolClass, Student, Fees, Parent
        from decimal import Decimal
        self.sclass = SchoolClass.objects.create(
            school=self.school,
            name="Class 1 Alpha",
            code="C1A",
            order=1,
        )
        self.parent = Parent.objects.create(
            father_name="Kwesi Boateng",
            father_phone="0240000000",
            mother_name="Akua Boateng",
            mother_phone="0240000001",
        )
        self.student_user = User.objects.create_user(
            username="feestudent",
            email="feestudent@example.com",
            password="StrongPass123!",
            role="student",
            first_name="Yaw",
            last_name="Boateng",
        )
        self.student = Student.objects.create(
            user=self.student_user,
            parent=self.parent,
            school=self.school,
            student_class=self.sclass,
            student_id="STU-99001",
        )
        self.fee = Fees.objects.create(
            school=self.school,
            student=self.student,
            student_class=self.sclass,
            fee_type="tuition",
            amount_required=Decimal("500.00"),
            discount=Decimal("50.00"),
            amount_paid=Decimal("200.00"),
            due_date=timezone.now().date() + timedelta(days=15),
        )

    def test_list_fees_displays_human_readable_class_name(self):
        self.client.force_login(self.admin_user)
        url = reverse("adminservices:list-fees")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Class 1 Alpha")
        self.assertContains(response, "Yaw Boateng")
        self.assertNotContains(response, "avatar-01.jpg")

    def test_fee_receipt_does_not_contain_scholarship(self):
        self.client.force_login(self.admin_user)
        url = reverse("adminservices:print-fee-receipt", args=[self.fee.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Scholarship")
        self.assertContains(response, "Discount:")


class TimetableFeatureTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="ttadmin",
            email="ttadmin@example.com",
            password="AdminPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Timetable Test Academy",
            location="Kumasi",
            phone_number="0244111222",
            admin=self.admin_user,
        )
        Subscription.objects.create(
            school=self.school,
            package=None,
            is_active=True,
            is_trial=True,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=30),
        )

        from account.models import SchoolClass, Department, Subject, Teacher, Student, Timetable
        self.sclass = SchoolClass.objects.create(name="Basic 7", school=self.school)
        self.dept = Department.objects.create(name="Science Dept", school=self.school)

        self.teacher_user = User.objects.create_user(
            username="ttteacher",
            email="ttteacher@example.com",
            password="TeacherPass123!",
            first_name="John",
            last_name="Doe",
            role="teacher",
        )
        self.teacher = Teacher.objects.create(
            user=self.teacher_user,
            school=self.school,
            department=self.dept,
            qualification="BSc Physics",
        )

        self.subject = Subject.objects.create(
            name="Integrated Science",
            school=self.school,
            department=self.dept,
            teacher=self.teacher,
            subject_class=self.sclass,
        )

        from account.models import Parent
        self.parent = Parent.objects.create(
            father_name="Kwame Kofi",
            father_phone="0244111333",
            mother_name="Akosua Kofi",
            mother_phone="0244111444",
        )
        self.student_user = User.objects.create_user(
            username="ttstudent",
            email="ttstudent@example.com",
            password="StudentPass123!",
            first_name="Ama",
            last_name="Kofi",
            role="student",
        )
        self.student = Student.objects.create(
            user=self.student_user,
            parent=self.parent,
            school=self.school,
            student_class=self.sclass,
            student_id="STU-TT01",
        )

    def test_admin_create_timetable_and_visibility_on_dashboards(self):
        from account.models import Timetable
        import datetime
        from django.utils import timezone

        # 1. Admin logs in and views timetable list
        self.client.force_login(self.admin_user)
        list_url = reverse("adminservices:timetable-list")
        res = self.client.get(list_url)
        self.assertEqual(res.status_code, 200)

        # 2. Admin creates a timetable entry
        today_code = timezone.now().strftime("%A").lower()
        create_url = reverse("adminservices:add-timetable")
        post_data = {
            "student_class": str(self.sclass.id),
            "subject": str(self.subject.id),
            "teacher": str(self.teacher.id),
            "day_of_week": today_code,
            "start_time": "08:00",
            "end_time": "09:30",
            "room_number": "Lab 1",
            "is_active": "on",
        }
        res_post = self.client.post(create_url, post_data)
        self.assertEqual(res_post.status_code, 302)

        # Verify entry created in DB
        tt = Timetable.objects.filter(school=self.school, student_class=self.sclass).first()
        self.assertIsNotNone(tt)
        self.assertEqual(tt.subject, self.subject)
        self.assertEqual(tt.teacher, self.teacher)
        self.assertEqual(tt.room_number, "Lab 1")

        # 3. Teacher logs in and sees it on dashboard & timetable page
        self.client.force_login(self.teacher_user)
        teacher_dash = self.client.get(reverse("teacher:teacher-dashboard"))
        self.assertEqual(teacher_dash.status_code, 200)
        self.assertContains(teacher_dash, "Integrated Science")
        self.assertContains(teacher_dash, "Basic 7")

        teacher_tt = self.client.get(reverse("teacher:timetable"))
        self.assertEqual(teacher_tt.status_code, 200)
        self.assertContains(teacher_tt, "Integrated Science")

        # 4. Student logs in and sees it on dashboard & timetable page
        self.client.force_login(self.student_user)
        student_dash = self.client.get(reverse("student:student-dashboard"))
        self.assertEqual(student_dash.status_code, 200)
        self.assertContains(student_dash, "Integrated Science")
        self.assertContains(student_dash, "John Doe")

        student_tt = self.client.get(reverse("student:student-timetable"))
        self.assertEqual(student_tt.status_code, 200)
        self.assertContains(student_tt, "Integrated Science")


import io
import tempfile
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SchoolSettingsTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="settingsadmin",
            email="settingsadmin@example.com",
            password="AdminPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="Alpha Academy",
            location="Accra",
            phone_number="0244000111",
            admin=self.admin_user,
        )
        Subscription.objects.create(
            school=self.school,
            package=None,
            is_active=True,
            is_trial=True,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=30),
        )
        from account.models import SchoolClass, Department, Teacher, Student
        self.sclass = SchoolClass.objects.create(name="Class 1", school=self.school)
        self.dept = Department.objects.create(name="Primary", school=self.school)

        self.teacher_user = User.objects.create_user(
            username="settingsteacher",
            email="teacher@example.com",
            password="TeacherPass123!",
            role="teacher",
        )
        self.teacher = Teacher.objects.create(
            user=self.teacher_user,
            school=self.school,
            department=self.dept,
        )

        from account.models import Parent
        self.parent = Parent.objects.create(father_name="Kwame", father_phone="024111222")
        self.student_user = User.objects.create_user(
            username="settingsstudent",
            email="student@example.com",
            password="StudentPass123!",
            role="student",
        )
        self.student = Student.objects.create(
            user=self.student_user,
            parent=self.parent,
            school=self.school,
            student_class=self.sclass,
            student_id="STU-SET01",
        )

    def test_school_settings_get_and_post_logo_upload(self):
        # 1. Non-admin cannot access
        self.client.force_login(self.student_user)
        res = self.client.get(reverse("adminservices:school-settings"))
        self.assertEqual(res.status_code, 302)

        # 2. Admin can access settings
        self.client.force_login(self.admin_user)
        res = self.client.get(reverse("adminservices:school-settings"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Alpha Academy")

        # 3. Before upload, dashboard headers show placeholder
        admin_dash = self.client.get(reverse("adminservices:admin-dashboard"))
        self.assertEqual(admin_dash.status_code, 200)
        self.assertContains(admin_dash, "school-brand-placeholder")
        self.assertContains(admin_dash, "Alpha Academy")

        # 4. Upload valid PNG image generated via Pillow
        buf = io.BytesIO()
        img = Image.new("RGB", (20, 20), color="blue")
        img.save(buf, format="PNG")
        buf.seek(0)
        logo_file = SimpleUploadedFile("school_logo.png", buf.getvalue(), content_type="image/png")

        post_data = {
            "name": "Alpha Academy Elite",
            "logo": logo_file,
            "phone_number": "0244000111",
            "email": "info@alphaacademy.edu",
            "website": "https://alphaacademy.edu",
            "location": "Accra Central",
            "address": "123 High Street",
            "postal_code": "GA-100",
        }
        res_post = self.client.post(reverse("adminservices:school-settings"), post_data, follow=True)
        self.assertEqual(res_post.status_code, 200)

        self.school.refresh_from_db()
        self.assertEqual(self.school.name, "Alpha Academy Elite")
        self.assertTrue(bool(self.school.logo))
        logo_url = self.school.logo.url

        # 5. Check Admin header displays logo
        res_admin = self.client.get(reverse("adminservices:admin-dashboard"))
        self.assertEqual(res_admin.status_code, 200)
        self.assertContains(res_admin, logo_url)
        self.assertContains(res_admin, "school-brand-logo")
        self.assertContains(res_admin, "Alpha Academy Elite")

        # 6. Check Teacher header displays logo
        self.client.force_login(self.teacher_user)
        res_teacher = self.client.get(reverse("teacher:teacher-dashboard"))
        self.assertEqual(res_teacher.status_code, 200)
        self.assertContains(res_teacher, logo_url)
        self.assertContains(res_teacher, "school-brand-logo")
        self.assertContains(res_teacher, "Alpha Academy Elite")

        # 7. Check Student header displays logo
        self.client.force_login(self.student_user)
        res_student = self.client.get(reverse("student:student-dashboard"))
        self.assertEqual(res_student.status_code, 200)
        self.assertContains(res_student, logo_url)
        self.assertContains(res_student, "school-brand-logo")
        self.assertContains(res_student, "Alpha Academy Elite")

        # 8. Admin removes the logo
        self.client.force_login(self.admin_user)
        res_remove = self.client.post(reverse("adminservices:school-settings"), {"remove_logo": "1"}, follow=True)
        self.assertEqual(res_remove.status_code, 200)

        self.school.refresh_from_db()
        self.assertFalse(bool(self.school.logo))

        # 9. Admin header falls back to placeholder
        res_admin_after = self.client.get(reverse("adminservices:admin-dashboard"))
        self.assertEqual(res_admin_after.status_code, 200)
        self.assertContains(res_admin_after, "school-brand-placeholder")
