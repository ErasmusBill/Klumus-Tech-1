from __future__ import annotations

import random
from typing import Iterable

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils.crypto import get_random_string
from django.utils import timezone

from account.models import School, Department, Teacher, Student, Parent, Subject, Subscription


class Command(BaseCommand):
    help = "Seed adminservices-related data: school, departments, teachers, students, subjects."

    def add_arguments(self, parser):
        parser.add_argument("--departments", type=int, default=3)
        parser.add_argument("--teachers", type=int, default=6)
        parser.add_argument("--students", type=int, default=25)
        parser.add_argument("--subjects", type=int, default=9)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--admin-username", type=str, default="")
        parser.add_argument("--school-name", type=str, default="")

    def handle(self, *args, **options):
        random.seed(options["seed"])

        User = get_user_model()

        admin_user, admin_created = self._get_or_create_admin(User, options["admin_username"])
        school, school_created = self._get_or_create_school(
            admin_user,
            options["school_name"],
        )
        if school_created:
            Subscription.objects.get_or_create(
                school=school,
                defaults={
                    "start_date": timezone.now(),
                    "end_date": timezone.now() + timezone.timedelta(days=30),
                    "is_active": True,
                    "is_trial": True,
                },
            )

        departments = self._seed_departments(school, options["departments"])
        teachers = self._seed_teachers(User, school, departments, options["teachers"])
        self._seed_subjects(school, departments, teachers, options["subjects"])
        self._seed_students(User, school, options["students"])

        self.stdout.write(self.style.SUCCESS("Seeding completed."))
        self.stdout.write(
            f"School: {school.name} | Departments: {len(departments)} | Teachers: {len(teachers)} | Students: {options['students']} | Subjects: {options['subjects']}"
        )

    def _get_or_create_admin(self, User, admin_username: str):
        username = admin_username.strip() or "seed_admin"
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "first_name": "Seed",
                "last_name": "Admin",
                "email": "seed_admin@example.com",
                "role": "admin",
            },
        )
        if created:
            user.set_password("admin12345")
            user.save(update_fields=["password"])
        return user, created

    def _get_or_create_school(self, admin_user, school_name: str):
        # Prefer the admin's existing managed school if present.
        existing_school = getattr(admin_user, "managed_school", None)
        if existing_school:
            return existing_school, False

        name = school_name.strip() or "Demo School"
        school, created = School.objects.get_or_create(
            name=name,
            defaults={
                "location": "Accra",
                "phone_number": "0240000000",
                "address": "Demo Address",
                "postal_code": "GA-000",
                "email": "demo-school@example.com",
                "admin": admin_user,
            },
        )
        if not created and school.admin_id != admin_user.id:
            school.admin = admin_user
            school.save(update_fields=["admin"])
        return school, created

    def _seed_departments(self, school: School, count: int) -> list[Department]:
        departments: list[Department] = []
        for i in range(1, count + 1):
            dept, _ = Department.objects.get_or_create(
                school=school,
                name=f"Department {i}",
                defaults={
                    "code": f"DPT-{i:02d}",
                    "description": f"Department {i} description",
                    "head_of_department": f"Head {i}",
                },
            )
            departments.append(dept)
        return departments

    def _seed_teachers(
        self,
        User,
        school: School,
        departments: Iterable[Department],
        count: int,
    ) -> list[Teacher]:
        departments = list(departments)
        teachers: list[Teacher] = []
        for i in range(1, count + 1):
            username = f"seed_teacher_{i}"
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": f"Teacher{i}",
                    "last_name": "Seed",
                    "email": f"{username}@example.com",
                    "role": "teacher",
                },
            )
            if created:
                user.set_password("teacher12345")
                user.save(update_fields=["password"])
            teacher, _ = Teacher.objects.get_or_create(
                user=user,
                defaults={
                    "school": school,
                    "department": random.choice(departments) if departments else None,
                    "qualification": "B.Ed",
                    "specialization": "General Education",
                    "experience_years": random.randint(1, 10),
                    "employment_type": "full_time",
                },
            )
            teachers.append(teacher)
        return teachers

    def _seed_subjects(
        self,
        school: School,
        departments: Iterable[Department],
        teachers: Iterable[Teacher],
        count: int,
    ) -> None:
        departments = list(departments)
        teachers = list(teachers)
        class_choices = [c[0] for c in Student.CLASS_CHOICES]
        for i in range(1, count + 1):
            dept = random.choice(departments) if departments else None
            teacher = random.choice(teachers) if teachers else None
            Subject.objects.get_or_create(
                name=f"Subject {i}",
                department=dept,
                defaults={
                    "teacher": teacher,
                    "school": school,
                    "subject_class": random.choice(class_choices),
                },
            )

    def _seed_students(self, User, school: School, count: int) -> None:
        class_choices = [c[0] for c in Student.CLASS_CHOICES]
        for i in range(1, count + 1):
            username = f"seed_student_{i}"
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": f"Student{i}",
                    "last_name": "Seed",
                    "email": f"{username}@example.com",
                    "role": "student",
                },
            )
            if created:
                user.set_password("student12345")
                user.save(update_fields=["password"])

            if Student.objects.filter(user=user).exists():
                continue

            parent = Parent.objects.create(
                father_name=f"Father {i}",
                father_phone=f"024{random.randint(1000000, 9999999)}",
                father_occupation="Engineer",
                father_email=f"father{i}@example.com",
                mother_name=f"Mother {i}",
                mother_phone=f"054{random.randint(1000000, 9999999)}",
                mother_occupation="Teacher",
                mother_email=f"mother{i}@example.com",
                present_address="Demo Address",
                emergency_contact_name=f"Guardian {i}",
                emergency_contact_phone=f"020{random.randint(1000000, 9999999)}",
                emergency_contact_relation="Guardian",
            )

            Student.objects.create(
                user=user,
                parent=parent,
                school=school,
                student_class=random.choice(class_choices),
                mobile_number=f"027{random.randint(1000000, 9999999)}",
                student_id=self._unique_student_id(),
                admission_number=self._unique_admission_number(),
            )

    def _unique_student_id(self) -> str:
        while True:
            student_id = f"STU-{get_random_string(6).upper()}"
            if not Student.objects.filter(student_id=student_id).exists():
                return student_id

    def _unique_admission_number(self) -> str:
        year = timezone.now().year
        while True:
            suffix = random.randint(1, 9999)
            admission_number = f"{year}-{suffix:04d}"
            if not Student.objects.filter(admission_number=admission_number).exists():
                return admission_number
