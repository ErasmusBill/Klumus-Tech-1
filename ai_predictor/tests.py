from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from account.models import (
    CustomUser,
    Department,
    Parent,
    ResultSheet,
    School,
    Student,
    Subject,
)
from ai_predictor.models import PredictedPerformance


class AIPredictorViewTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="StrongPass123!",
            role="admin",
        )
        self.school = School.objects.create(
            name="AI Test School",
            location="Accra",
            phone_number="0200000000",
            admin=self.admin,
        )

        self.student_user = CustomUser.objects.create_user(
            username="student1",
            email="student1@example.com",
            password="StrongPass123!",
            role="student",
            first_name="Test",
            last_name="Student",
        )
        self.parent = Parent.objects.create(
            father_name="Father One",
            father_phone="0240000001",
            mother_name="Mother One",
            mother_phone="0240000002",
            present_address="Accra",
        )
        self.student = Student.objects.create(
            user=self.student_user,
            parent=self.parent,
            school=self.school,
            student_class="JHS_1",
            mobile_number="0240000003",
        )

        self.department = Department.objects.create(
            school=self.school,
            name="Science",
        )
        self.subject = Subject.objects.create(
            department=self.department,
            school=self.school,
            name="Mathematics",
            subject_class="JHS_1",
        )

        ResultSheet.objects.create(
            student=self.student,
            subject=self.subject,
            term="1",
            academic_year="2025/2026",
            class_score=16,
            mid_semester=22,
            end_of_term_exams=41,
            exam_date=date(2026, 4, 20),
        )

        self.predict_url = reverse(
            "ai_predictor:predict_student_performance",
            args=[self.student.student_id],
        )

    def test_predict_endpoint_uses_model_when_available(self):
        class DummyModel:
            def predict(self, _):
                return ["B"]

        self.client.force_login(self.admin)
        with patch("ai_predictor.views.get_model", return_value=DummyModel()):
            response = self.client.get(self.predict_url)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["predicted_grade"], "B")
        self.assertEqual(payload["risk_level"], "Low")
        self.assertEqual(payload["model_source"], "model")
        self.assertTrue(
            PredictedPerformance.objects.filter(
                student=self.student,
                predicted_grade="B",
                risk_level="Low",
            ).exists()
        )

    def test_predict_endpoint_falls_back_when_model_fails(self):
        self.client.force_login(self.admin)
        with patch("ai_predictor.views.get_model", side_effect=RuntimeError("boom")):
            response = self.client.get(self.predict_url)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(payload["predicted_grade"], {"A", "B", "C", "D", "F"})
        self.assertIn(payload["risk_level"], {"Low", "Medium", "High"})
        self.assertEqual(payload["model_source"], "heuristic")
        self.assertTrue(PredictedPerformance.objects.filter(student=self.student).exists())

    def test_predict_endpoint_returns_404_without_results(self):
        user = CustomUser.objects.create_user(
            username="student2",
            email="student2@example.com",
            password="StrongPass123!",
            role="student",
            first_name="No",
            last_name="Result",
        )
        student_without_results = Student.objects.create(
            user=user,
            parent=self.parent,
            school=self.school,
            student_class="JHS_1",
            mobile_number="0240000004",
        )
        predict_url = reverse(
            "ai_predictor:predict_student_performance",
            args=[student_without_results.student_id],
        )

        self.client.force_login(self.admin)
        response = self.client.get(predict_url)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "No result found for this student.")
