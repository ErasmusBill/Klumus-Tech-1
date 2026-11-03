from __future__ import annotations

import random
from decimal import Decimal
from typing import Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from account.models import (
    ClassFee,
    Department,
    School,
    SchoolClass,
    Subject,
    Subscription,
    _resolve_school_class,
)

FREE_TRIAL_DAYS = getattr(settings, "FREE_TRIAL_DAYS", 30)

DEFAULT_SUPERADMIN_USERNAME = "superadmin"
DEFAULT_SUPERADMIN_PASSWORD = "Admin@12345"
DEFAULT_ADMIN_USERNAME = "schooladmin"
DEFAULT_ADMIN_PASSWORD = "Admin@12345"
DEFAULT_SCHOOL_NAME = "KiddoCore International Academy"


class Command(BaseCommand):
    help = "Seed adminservices data: superadmin, school admin, school, subscription, departments, classes, class fees, subjects."

    def add_arguments(self, parser):
        parser.add_argument("--superadmin-username", type=str, default=DEFAULT_SUPERADMIN_USERNAME)
        parser.add_argument("--superadmin-password", type=str, default=DEFAULT_SUPERADMIN_PASSWORD)
        parser.add_argument("--admin-username", type=str, default=DEFAULT_ADMIN_USERNAME)
        parser.add_argument("--admin-password", type=str, default=DEFAULT_ADMIN_PASSWORD)
        parser.add_argument("--school-name", type=str, default=DEFAULT_SCHOOL_NAME)
        parser.add_argument("--departments", type=int, default=4)
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args, **options):
        random.seed(options["seed"])
        User = get_user_model()

        # 1. Super Admin
        superadmin, superadmin_created = self._seed_superadmin(
            User,
            username=options["superadmin_username"] or DEFAULT_SUPERADMIN_USERNAME,
            password=options["superadmin_password"] or DEFAULT_SUPERADMIN_PASSWORD,
        )

        # 2. School Admin
        admin_user, admin_created = self._seed_school_admin(
            User,
            username=options["admin_username"] or DEFAULT_ADMIN_USERNAME,
            password=options["admin_password"] or DEFAULT_ADMIN_PASSWORD,
        )

        # 3. School
        school, school_created = self._seed_school(
            admin_user,
            school_name=options["school_name"] or DEFAULT_SCHOOL_NAME,
        )

        # 4. Active Subscription
        subscription = self._ensure_active_subscription(school)

        # 5. Departments
        departments = self._seed_departments(school)

        # 6. School Classes verification
        school_classes = self._seed_classes(school)

        # 7. Class Fees
        class_fees = self._seed_class_fees(school, school_classes)

        # 8. Subjects
        subjects = self._seed_subjects(school, departments, school_classes)

        self.stdout.write(self.style.SUCCESS("Adminservices seeding completed successfully!"))
        self.stdout.write(
            f"School: {school.name}\n"
            f"Super Admin: {superadmin.username} ({'Created' if superadmin_created else 'Updated'})\n"
            f"School Admin: {admin_user.username} ({'Created' if admin_created else 'Updated'})\n"
            f"Subscription: Active trial ({subscription.days_remaining()} days remaining)\n"
            f"Departments: {len(departments)} | Classes: {len(school_classes)} | Subjects: {len(subjects)} | Fee Structures: {len(class_fees)}"
        )

    def _seed_superadmin(self, User, username: str, password: str):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "first_name": "System",
                "last_name": "SuperAdmin",
                "email": "superadmin@kiddocore.edu",
                "role": "admin",
                "is_superuser": True,
                "is_staff": True,
                "is_active": True,
            },
        )
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        user.role = "admin"
        user.set_password(password)
        user.save()
        return user, created

    def _seed_school_admin(self, User, username: str, password: str):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "first_name": "Kwame",
                "last_name": "Mensah",
                "email": "schooladmin@kiddocore.edu",
                "role": "admin",
                "phone_number": "+233244123456",
                "is_active": True,
            },
        )
        user.role = "admin"
        user.is_active = True
        user.set_password(password)
        user.save()
        return user, created

    def _seed_school(self, admin_user, school_name: str) -> tuple[School, bool]:
        # If admin already manages a school, reuse it
        existing_school = getattr(admin_user, "managed_school", None)
        if existing_school:
            if existing_school.name != school_name:
                existing_school.name = school_name
                existing_school.save(update_fields=["name"])
            return existing_school, False

        school, created = School.objects.get_or_create(
            name=school_name,
            defaults={
                "location": "East Legon, Accra",
                "phone_number": "+233244123456",
                "address": "12 Kofi Annan Avenue, East Legon",
                "postal_code": "GA-102-4567",
                "email": "admin@kiddocore.edu",
                "website": "https://kiddocore.edu",
                "admin": admin_user,
                "verified": True,
            },
        )
        if not created and school.admin_id != admin_user.id:
            school.admin = admin_user
            school.save(update_fields=["admin"])
        return school, created

    def _ensure_active_subscription(self, school: School) -> Subscription:
        sub, _ = Subscription.objects.get_or_create(
            school=school,
            defaults={
                "start_date": timezone.now(),
                "end_date": timezone.now() + timezone.timedelta(days=FREE_TRIAL_DAYS),
                "is_active": True,
                "is_trial": True,
            },
        )
        # Always ensure trial is active and not expired
        sub.is_active = True
        sub.is_trial = True
        if not sub.end_date or sub.end_date <= timezone.now():
            sub.end_date = timezone.now() + timezone.timedelta(days=FREE_TRIAL_DAYS)
        sub.save()
        return sub

    def _seed_departments(self, school: School) -> list[Department]:
        dept_data = [
            ("Sciences & Mathematics", "DPT-SCI", "Dr. Robert Mensah", "Instruction in Pure & Applied Sciences and Mathematics."),
            ("Languages & Humanities", "DPT-LANG", "Mrs. Grace Appiah", "Instruction in English, Ghanaian Languages, and Social Studies."),
            ("Creative Arts & Technology", "DPT-TECH", "Mr. Emmanuel Boateng", "Instruction in ICT, Creative Arts, Design and Computing."),
            ("Early Childhood Education", "DPT-ECE", "Mrs. Vivian Osei", "Foundational education and early childhood development."),
        ]
        departments: list[Department] = []
        for name, code, head, desc in dept_data:
            dept, _ = Department.objects.get_or_create(
                school=school,
                name=name,
                defaults={
                    "code": code,
                    "head_of_department": head,
                    "description": desc,
                },
            )
            departments.append(dept)
        return departments

    def _seed_classes(self, school: School) -> list[SchoolClass]:
        class_definitions = [
            ("Creche", "CRECHE", 1),
            ("Nursery 1", "NURSERY_1", 2),
            ("Nursery 2", "NURSERY_2", 3),
            ("Kindergarten 1", "KINDERGARTEN_1", 4),
            ("Kindergarten 2", "KINDERGARTEN_2", 5),
            ("Primary 1", "PRIMARY_1", 6),
            ("Primary 2", "PRIMARY_2", 7),
            ("Primary 3", "PRIMARY_3", 8),
            ("Primary 4", "PRIMARY_4", 9),
            ("Primary 5", "PRIMARY_5", 10),
            ("Primary 6", "PRIMARY_6", 11),
            ("JHS 1", "JHS_1", 12),
            ("JHS 2", "JHS_2", 13),
            ("JHS 3", "JHS_3", 14),
        ]
        classes: list[SchoolClass] = []
        for name, code, order in class_definitions:
            sc = _resolve_school_class(code, school)
            if not sc:
                sc, _ = SchoolClass.objects.get_or_create(
                    school=school,
                    name=name,
                    defaults={"code": code, "order": order, "is_active": True},
                )
            classes.append(sc)
        return classes

    def _seed_class_fees(self, school: School, classes: list[SchoolClass]) -> list[ClassFee]:
        academic_year = school.get_current_academic_year() or "2025/2026"
        term = "TERM_1"
        fee_records = []
        for sc in classes:
            # Tuition
            tuition_amount = Decimal("1500.00") if "JHS" in sc.name else Decimal("1200.00")
            cf, _ = ClassFee.objects.get_or_create(
                school=school,
                student_class=sc,
                fee_type="tuition",
                academic_year=academic_year,
                term=term,
                defaults={"amount": tuition_amount},
            )
            fee_records.append(cf)

            # Library fee
            cf_lib, _ = ClassFee.objects.get_or_create(
                school=school,
                student_class=sc,
                fee_type="library",
                academic_year=academic_year,
                term=term,
                defaults={"amount": Decimal("150.00")},
            )
            fee_records.append(cf_lib)

            # Sports fee
            cf_sport, _ = ClassFee.objects.get_or_create(
                school=school,
                student_class=sc,
                fee_type="sports",
                academic_year=academic_year,
                term=term,
                defaults={"amount": Decimal("100.00")},
            )
            fee_records.append(cf_sport)
        return fee_records

    def _seed_subjects(
        self,
        school: School,
        departments: list[Department],
        classes: list[SchoolClass],
    ) -> list[Subject]:
        dept_by_code = {d.code: d for d in departments}
        sci_dept = dept_by_code.get("DPT-SCI") or departments[0]
        lang_dept = dept_by_code.get("DPT-LANG") or departments[0]
        tech_dept = dept_by_code.get("DPT-TECH") or departments[0]

        subject_templates = [
            ("Mathematics", sci_dept),
            ("Integrated Science", sci_dept),
            ("English Language", lang_dept),
            ("Information Technology", tech_dept),
            ("Social Studies", lang_dept),
        ]

        created_subjects: list[Subject] = []
        # Target primary & JHS classes for standard curriculum subjects
        target_classes = [c for c in classes if any(k in c.name for k in ["JHS", "Primary"])]
        for sc in target_classes:
            for name, dept in subject_templates:
                # Primary classes might not have Social Studies as separate, but JHS and upper primary do
                subject, _ = Subject.objects.get_or_create(
                    school=school,
                    name=name,
                    subject_class=sc,
                    defaults={"department": dept},
                )
                created_subjects.append(subject)
        return created_subjects
