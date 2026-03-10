from __future__ import annotations

import random

from django.core.management.base import BaseCommand
from django.utils import timezone

from account.models import Student, School, CustomUser
from ai_predictor.models import PredictedPerformance


class Command(BaseCommand):
    help = "Seed AI predictor data (PredictedPerformance) for existing students."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=20)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--school-name", type=str, default="")
        parser.add_argument("--admin-username", type=str, default="")

    def handle(self, *args, **options):
        random.seed(options["seed"])
        students = list(self._get_students(options["school_name"], options["admin_username"]))
        if not students:
            self.stdout.write(self.style.WARNING("No students found. Seed students first."))
            return

        count = min(options["count"], len(students))
        selected = random.sample(students, k=count)
        grades = ["A", "B", "C", "D", "F"]
        risks = ["Low", "Medium", "High"]

        created = 0
        for student in selected:
            if PredictedPerformance.objects.filter(student=student).exists():
                continue
            PredictedPerformance.objects.create(
                student=student,
                predicted_grade=random.choice(grades),
                risk_level=random.choice(risks),
                created_at=timezone.now(),
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(f"PredictedPerformance created: {created}"))

    def _get_students(self, school_name: str, admin_username: str):
        school = None
        if admin_username:
            admin = CustomUser.objects.filter(username=admin_username, role="admin").first()
            school = getattr(admin, "managed_school", None) if admin else None
        if school is None and school_name:
            school = School.objects.filter(name=school_name).first()
        if school:
            return Student.objects.filter(school=school).select_related("user")
        return Student.objects.select_related("user")
