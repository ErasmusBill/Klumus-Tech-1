from __future__ import annotations

import random
from decimal import Decimal
from typing import Iterable

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from account.models import (
    CustomUser,
    Department,
    School,
    SchoolClass,
    Subject,
    Teacher,
    _resolve_school_class,
)

DEFAULT_TEACHER_PASSWORD = "Teacher@12345"

TEACHER_PROFILES = [
    {
        "username": "teacher_math",
        "first_name": "Michael",
        "last_name": "Mensah",
        "email": "m.mensah@kiddocore.edu",
        "department_code": "DPT-SCI",
        "specialization": "Mathematics & Statistics",
        "qualification": "B.Sc. Mathematics Education",
        "experience_years": 8,
        "is_class_teacher": True,
        "class_code": "JHS_1",
        "subject_name": "Mathematics",
        "bio": "Passionate STEM educator focused on making algebra and geometry intuitive and engaging.",
        "salary": Decimal("3500.00"),
    },
    {
        "username": "teacher_science",
        "first_name": "Sarah",
        "last_name": "Addo",
        "email": "s.addo@kiddocore.edu",
        "department_code": "DPT-SCI",
        "specialization": "Integrated & Natural Science",
        "qualification": "M.Sc. Science Education",
        "experience_years": 6,
        "is_class_teacher": True,
        "class_code": "PRIMARY_5",
        "subject_name": "Integrated Science",
        "bio": "Experienced science teacher dedicated to hands-on experiments and critical inquiry.",
        "salary": Decimal("3400.00"),
    },
    {
        "username": "teacher_english",
        "first_name": "Comfort",
        "last_name": "Arthur",
        "email": "c.arthur@kiddocore.edu",
        "department_code": "DPT-LANG",
        "specialization": "English Language & Literature",
        "qualification": "B.A. English & Linguistics",
        "experience_years": 5,
        "is_class_teacher": True,
        "class_code": "PRIMARY_4",
        "subject_name": "English Language",
        "bio": "Literature enthusiast driving reading clubs, creative writing, and public speaking.",
        "salary": Decimal("3200.00"),
    },
    {
        "username": "teacher_ict",
        "first_name": "David",
        "last_name": "Acheampong",
        "email": "d.acheampong@kiddocore.edu",
        "department_code": "DPT-TECH",
        "specialization": "Computer Science & ICT Education",
        "qualification": "B.Sc. Information Technology",
        "experience_years": 4,
        "is_class_teacher": False,
        "class_code": None,
        "subject_name": "Information Technology",
        "bio": "Tech educator teaching foundational coding, digital literacy, and computer hardware.",
        "salary": Decimal("3300.00"),
    },
    {
        "username": "teacher_social",
        "first_name": "Ebenezer",
        "last_name": "Kusi",
        "email": "e.kusi@kiddocore.edu",
        "department_code": "DPT-LANG",
        "specialization": "Social Studies & History",
        "qualification": "B.Ed. Social Sciences",
        "experience_years": 7,
        "is_class_teacher": True,
        "class_code": "JHS_2",
        "subject_name": "Social Studies",
        "bio": "Committed to civic education, cultural preservation, and social awareness in students.",
        "salary": Decimal("3100.00"),
    },
    {
        "username": "teacher_ece",
        "first_name": "Patience",
        "last_name": "Baah",
        "email": "p.baah@kiddocore.edu",
        "department_code": "DPT-ECE",
        "specialization": "Early Childhood Development",
        "qualification": "Diploma in Early Childhood Education",
        "experience_years": 9,
        "is_class_teacher": True,
        "class_code": "KINDERGARTEN_1",
        "subject_name": None,
        "bio": "Nurturing early childhood educator focused on phonics, motor skills, and creative play.",
        "salary": Decimal("2800.00"),
    },
]


class Command(BaseCommand):
    help = "Seed teacher profiles, credentials, department assignments, and class teacher roles."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", type=str, default="")
        parser.add_argument("--school-name", type=str, default="")
        parser.add_argument("--password", type=str, default=DEFAULT_TEACHER_PASSWORD)
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args, **options):
        random.seed(options["seed"])
        User = get_user_model()

        school = self._resolve_school(options["admin_username"], options["school_name"])
        if not school:
            self.stdout.write("No school found. Running seed_adminservices first...")
            call_command("seed_adminservices")
            school = self._resolve_school(options["admin_username"], options["school_name"])

        if not school:
            self.stderr.write("Unable to resolve school for seeding teachers.")
            return

        password = options["password"] or DEFAULT_TEACHER_PASSWORD
        teachers = self._seed_teachers(User, school, password)

        self.stdout.write(self.style.SUCCESS(f"Successfully seeded {len(teachers)} teachers for '{school.name}'!"))
        for t in teachers:
            role_desc = f"Class Teacher ({t.class_teacher_class.name})" if t.is_class_teacher and t.class_teacher_class else "Subject Teacher"
            self.stdout.write(f"  • {t.user.username} ({t.user.get_full_name()}) | {role_desc} | Dept: {t.department.name if t.department else 'N/A'}")

    def _resolve_school(self, admin_username: str, school_name: str) -> School | None:
        if admin_username:
            admin_user = CustomUser.objects.filter(username=admin_username, role="admin").first()
            if admin_user and hasattr(admin_user, "managed_school"):
                return admin_user.managed_school
        if school_name:
            school = School.objects.filter(name__icontains=school_name).first()
            if school:
                return school
        # Default lookup
        admin_user = CustomUser.objects.filter(role="admin", is_superuser=False).first()
        if admin_user and hasattr(admin_user, "managed_school"):
            return admin_user.managed_school
        return School.objects.first()

    def _seed_teachers(self, User, school: School, password: str) -> list[Teacher]:
        departments = {d.code: d for d in Department.objects.filter(school=school)}
        default_dept = next(iter(departments.values()), None)

        seeded_teachers: list[Teacher] = []

        for info in TEACHER_PROFILES:
            username = info["username"]
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": info["first_name"],
                    "last_name": info["last_name"],
                    "email": info["email"],
                    "role": "teacher",
                    "is_active": True,
                },
            )
            user.role = "teacher"
            user.first_name = info["first_name"]
            user.last_name = info["last_name"]
            user.email = info["email"]
            user.is_active = True
            user.set_password(password)
            user.save()

            dept = departments.get(info["department_code"], default_dept)
            class_teacher_class = None
            if info["is_class_teacher"] and info["class_code"]:
                class_teacher_class = _resolve_school_class(info["class_code"], school)

            teacher, _ = Teacher.objects.get_or_create(
                user=user,
                defaults={
                    "school": school,
                    "department": dept,
                    "specialization": info["specialization"],
                    "qualification": info["qualification"],
                    "experience_years": info["experience_years"],
                    "is_class_teacher": info["is_class_teacher"],
                    "class_teacher_class": class_teacher_class,
                    "bio": info["bio"],
                    "salary": info["salary"],
                    "hire_date": timezone.now().date() - timezone.timedelta(days=365 * 2),
                    "is_active": True,
                },
            )
            # Update fields to ensure state matches
            teacher.school = school
            teacher.department = dept
            teacher.specialization = info["specialization"]
            teacher.qualification = info["qualification"]
            teacher.experience_years = info["experience_years"]
            teacher.is_class_teacher = info["is_class_teacher"]
            teacher.class_teacher_class = class_teacher_class
            teacher.bio = info["bio"]
            teacher.salary = info["salary"]
            teacher.is_active = True
            teacher.save()

            # Link teacher to their subjects across the school if defined
            if info["subject_name"]:
                Subject.objects.filter(school=school, name__icontains=info["subject_name"]).update(
                    teacher=teacher,
                    department=dept or Subject.objects.filter(school=school, name__icontains=info["subject_name"]).first().department
                )

            seeded_teachers.append(teacher)

        return seeded_teachers
