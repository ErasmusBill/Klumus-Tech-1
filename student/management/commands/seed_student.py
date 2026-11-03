from __future__ import annotations

import random
from decimal import Decimal
from typing import Iterable

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from account.models import (
    ClassFee,
    CustomUser,
    Enrollment,
    Fees,
    Parent,
    School,
    SchoolClass,
    Student,
    Subject,
    _resolve_school_class,
)

DEFAULT_STUDENT_PASSWORD = "Student@12345"
DEFAULT_PARENT_PASSWORD = "Parent@12345"

PRIMARY_STUDENT_PROFILES = [
    {
        "username": "student_jhs1",
        "first_name": "Kwame",
        "last_name": "Osei",
        "gender": "male",
        "class_code": "JHS_1",
        "parent_username": "parent_kwame",
        "parent_father": "Mr. Joseph Osei",
        "parent_mother": "Mrs. Mary Osei",
        "parent_phone": "+233244987654",
        "parent_email": "parent.osei@example.com",
    },
    {
        "username": "student_jhs2",
        "first_name": "Abena",
        "last_name": "Mensah",
        "gender": "female",
        "class_code": "JHS_2",
        "parent_username": "parent_abena",
        "parent_father": "Dr. Peter Mensah",
        "parent_mother": "Mrs. Grace Mensah",
        "parent_phone": "+233201234567",
        "parent_email": "parent.mensah@example.com",
    },
    {
        "username": "student_jhs3",
        "first_name": "Kofi",
        "last_name": "Appiah",
        "gender": "male",
        "class_code": "JHS_3",
        "parent_username": None,
        "parent_father": "Mr. Daniel Appiah",
        "parent_mother": "Mrs. Esther Appiah",
        "parent_phone": "+233245678901",
        "parent_email": "parent.appiah@example.com",
    },
    {
        "username": "student_p6",
        "first_name": "Akosua",
        "last_name": "Darko",
        "gender": "female",
        "class_code": "PRIMARY_6",
        "parent_username": None,
        "parent_father": "Mr. Richard Darko",
        "parent_mother": "Mrs. Joyce Darko",
        "parent_phone": "+233501234567",
        "parent_email": "parent.darko@example.com",
    },
    {
        "username": "student_p5",
        "first_name": "Yaw",
        "last_name": "Boakye",
        "gender": "male",
        "class_code": "PRIMARY_5",
        "parent_username": None,
        "parent_father": "Mr. Francis Boakye",
        "parent_mother": "Mrs. Felicia Boakye",
        "parent_phone": "+233271234567",
        "parent_email": "parent.boakye@example.com",
    },
    {
        "username": "student_p4",
        "first_name": "Ama",
        "last_name": "Serwaa",
        "gender": "female",
        "class_code": "PRIMARY_4",
        "parent_username": None,
        "parent_father": "Mr. Anthony Serwaa",
        "parent_mother": "Mrs. Rita Serwaa",
        "parent_phone": "+233261234567",
        "parent_email": "parent.serwaa@example.com",
    },
    {
        "username": "student_p3",
        "first_name": "Emmanuel",
        "last_name": "Asante",
        "gender": "male",
        "class_code": "PRIMARY_3",
        "parent_username": None,
        "parent_father": "Mr. Isaac Asante",
        "parent_mother": "Mrs. Beatrice Asante",
        "parent_phone": "+233241234567",
        "parent_email": "parent.asante@example.com",
    },
    {
        "username": "student_p2",
        "first_name": "Yaa",
        "last_name": "Pokua",
        "gender": "female",
        "class_code": "PRIMARY_2",
        "parent_username": None,
        "parent_father": "Mr. Samuel Poku",
        "parent_mother": "Mrs. Lydia Poku",
        "parent_phone": "+233209876543",
        "parent_email": "parent.poku@example.com",
    },
    {
        "username": "student_p1",
        "first_name": "Samuel",
        "last_name": "Frimpong",
        "gender": "male",
        "class_code": "PRIMARY_1",
        "parent_username": None,
        "parent_father": "Mr. George Frimpong",
        "parent_mother": "Mrs. Theresa Frimpong",
        "parent_phone": "+233549876543",
        "parent_email": "parent.frimpong@example.com",
    },
    {
        "username": "student_kg",
        "first_name": "Jessica",
        "last_name": "Owusu",
        "gender": "female",
        "class_code": "KINDERGARTEN_2",
        "parent_username": None,
        "parent_father": "Mr. Charles Owusu",
        "parent_mother": "Mrs. Gloria Owusu",
        "parent_phone": "+233248889900",
        "parent_email": "parent.owusu@example.com",
    },
]


class Command(BaseCommand):
    help = "Seed students, parents, subject enrollments, and fees."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", type=str, default="")
        parser.add_argument("--school-name", type=str, default="")
        parser.add_argument("--student-password", type=str, default=DEFAULT_STUDENT_PASSWORD)
        parser.add_argument("--parent-password", type=str, default=DEFAULT_PARENT_PASSWORD)
        parser.add_argument("--extra-students", type=int, default=15)
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
            self.stderr.write("Unable to resolve school for seeding students.")
            return

        student_pwd = options["student_password"] or DEFAULT_STUDENT_PASSWORD
        parent_pwd = options["parent_password"] or DEFAULT_PARENT_PASSWORD

        # 1. Seed Core Student & Parent Profiles
        seeded_students = self._seed_core_students(User, school, student_pwd, parent_pwd)

        # 2. Seed Extra Students across classes for realistic volume
        extra_count = options["extra_students"]
        if extra_count > 0:
            extra_students = self._seed_extra_students(User, school, extra_count, student_pwd)
            seeded_students.extend(extra_students)

        # 3. Auto-Enroll students in their class subjects
        enrolled_count = self._enroll_students(school, seeded_students)

        # 4. Generate fees for students
        fees_count = self._generate_fees(school, seeded_students)

        self.stdout.write(self.style.SUCCESS(f"Successfully seeded {len(seeded_students)} students for '{school.name}'!"))
        self.stdout.write(f"  • Subject Enrollments Created: {enrolled_count}")
        self.stdout.write(f"  • Student Fee Bills Created: {fees_count}")

    def _resolve_school(self, admin_username: str, school_name: str) -> School | None:
        if admin_username:
            admin_user = CustomUser.objects.filter(username=admin_username, role="admin").first()
            if admin_user and hasattr(admin_user, "managed_school"):
                return admin_user.managed_school
        if school_name:
            school = School.objects.filter(name__icontains=school_name).first()
            if school:
                return school
        admin_user = CustomUser.objects.filter(role="admin", is_superuser=False).first()
        if admin_user and hasattr(admin_user, "managed_school"):
            return admin_user.managed_school
        return School.objects.first()

    def _seed_core_students(self, User, school: School, student_pwd: str, parent_pwd: str) -> list[Student]:
        students: list[Student] = []

        for info in PRIMARY_STUDENT_PROFILES:
            # 1. Parent setup
            parent_user = None
            if info.get("parent_username"):
                p_username = info["parent_username"]
                parent_user, _ = User.objects.get_or_create(
                    username=p_username,
                    defaults={
                        "first_name": info["parent_father"].split()[-1],
                        "last_name": info["last_name"],
                        "email": info["parent_email"],
                        "role": "parent",
                        "phone_number": info["parent_phone"],
                        "is_active": True,
                    },
                )
                parent_user.role = "parent"
                parent_user.is_active = True
                parent_user.set_password(parent_pwd)
                parent_user.save()

            if parent_user:
                parent = Parent.objects.filter(user=parent_user).first()
            else:
                parent = Parent.objects.filter(
                    father_name=info["parent_father"],
                    father_phone=info["parent_phone"],
                ).first()

            if not parent:
                parent = Parent.objects.create(
                    user=parent_user,
                    father_name=info["parent_father"],
                    father_phone=info["parent_phone"],
                    father_email=info["parent_email"],
                    father_occupation="Professional / Civil Servant",
                    mother_name=info["parent_mother"],
                    mother_phone=info["parent_phone"],
                    mother_email=info["parent_email"],
                    mother_occupation="Business / Educator",
                    present_address="14 Independence Ave, Accra",
                    permanent_address="Accra, Greater Accra",
                    emergency_contact_name=info["parent_father"],
                    emergency_contact_phone=info["parent_phone"],
                    emergency_contact_relation="Father",
                )

            # 2. Student user setup
            username = info["username"]
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": info["first_name"],
                    "last_name": info["last_name"],
                    "email": f"{username}@kiddocore.edu",
                    "role": "student",
                    "gender": info["gender"],
                    "phone_number": info["parent_phone"],
                    "is_active": True,
                },
            )
            user.role = "student"
            user.first_name = info["first_name"]
            user.last_name = info["last_name"]
            user.is_active = True
            user.set_password(student_pwd)
            user.save()

            # 3. Student model
            sc = _resolve_school_class(info["class_code"], school)
            student, _ = Student.objects.get_or_create(
                user=user,
                defaults={
                    "parent": parent,
                    "school": school,
                    "student_class": sc,
                    "mobile_number": info["parent_phone"],
                    "joining_date": timezone.now().date() - timezone.timedelta(days=200),
                },
            )
            student.school = school
            student.parent = parent
            student.student_class = sc
            student.is_active = True
            student.save()

            students.append(student)

        return students

    def _seed_extra_students(self, User, school: School, count: int, student_pwd: str) -> list[Student]:
        classes = list(SchoolClass.objects.filter(school=school))
        if not classes:
            classes = list(SchoolClass.objects.filter(school__isnull=True))

        first_names = ["Kojo", "Efua", "Fiifi", "Esi", "Kobby", "Serwaa", "Nana", "Kwabena", "Maame", "Paa", "Kweku", "Afia", "Boadi", "Antwi"]
        last_names = ["Annan", "Agyemang", "Baffoe", "Kusi", "Danquah", "Darkwah", "Twumasi", "Sackey", "Acheampong", "Amponsah"]

        extra_students: list[Student] = []
        for i in range(1, count + 1):
            fn = random.choice(first_names)
            ln = random.choice(last_names)
            gender = "female" if fn in ["Efua", "Esi", "Serwaa", "Maame", "Afia"] else "male"
            username = f"student_extra_{i}"

            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": fn,
                    "last_name": ln,
                    "email": f"{username}@kiddocore.edu",
                    "role": "student",
                    "gender": gender,
                    "is_active": True,
                },
            )
            user.role = "student"
            user.is_active = True
            user.set_password(student_pwd)
            user.save()

            target_class = random.choice(classes) if classes else None

            if Student.objects.filter(user=user).exists():
                student = Student.objects.get(user=user)
                student.school = school
                student.student_class = target_class
                student.save()
                extra_students.append(student)
                continue

            parent = Parent.objects.create(
                father_name=f"Mr. {ln}",
                father_phone=f"+23324{random.randint(1000000, 9999999)}",
                father_email=f"parent.{ln.lower()}{i}@example.com",
                father_occupation="Trader / Professional",
                mother_name=f"Mrs. {ln}",
                mother_phone=f"+23320{random.randint(1000000, 9999999)}",
                mother_email=f"mother.{ln.lower()}{i}@example.com",
                mother_occupation="Self-employed",
                present_address="Greater Accra, Ghana",
                emergency_contact_name=f"Mr. {ln}",
                emergency_contact_phone=f"+23324{random.randint(1000000, 9999999)}",
                emergency_contact_relation="Parent",
            )

            student = Student.objects.create(
                user=user,
                parent=parent,
                school=school,
                student_class=target_class,
                mobile_number=parent.father_phone,
                joining_date=timezone.now().date() - timezone.timedelta(days=random.randint(30, 300)),
            )
            extra_students.append(student)

        return extra_students

    def _enroll_students(self, school: School, students: list[Student]) -> int:
        enrolled_count = 0
        for student in students:
            if not student.student_class:
                continue
            subjects = Subject.objects.filter(school=school, subject_class=student.student_class)
            for subj in subjects:
                _, created = Enrollment.objects.get_or_create(
                    student=student,
                    subject=subj,
                    defaults={"is_active": True},
                )
                if created:
                    enrolled_count += 1
        return enrolled_count

    def _generate_fees(self, school: School, students: list[Student]) -> int:
        academic_year = school.get_current_academic_year() or "2025/2026"
        term = "TERM_1"
        due_date = timezone.now().date() + timezone.timedelta(days=30)
        fees_created = 0

        for student in students:
            if not student.student_class:
                continue

            fee_structures = ClassFee.objects.filter(
                school=school,
                student_class=student.student_class,
                academic_year=academic_year,
                term=term,
            )

            # If no specific ClassFee, create a default tuition structure
            if not fee_structures.exists():
                fee_structures = [
                    ClassFee.objects.create(
                        school=school,
                        student_class=student.student_class,
                        fee_type="tuition",
                        academic_year=academic_year,
                        term=term,
                        amount=Decimal("1200.00"),
                    )
                ]

            for fs in fee_structures:
                # Randomize payment status for realistic dashboard KPIs
                rand_val = random.random()
                if rand_val > 0.6:
                    status = "paid"
                    amount_paid = fs.amount
                elif rand_val > 0.3:
                    status = "partial"
                    amount_paid = Decimal(int(fs.amount * Decimal("0.5")))
                else:
                    status = "unpaid"
                    amount_paid = Decimal("0.00")

                _, created = Fees.objects.get_or_create(
                    school=school,
                    student=student,
                    fee_structure=fs,
                    student_class=student.student_class,
                    term=term,
                    academic_year=academic_year,
                    fee_type=fs.fee_type,
                    defaults={
                        "amount_required": fs.amount,
                        "amount_paid": amount_paid,
                        "discount": Decimal("0.00"),
                        "status": status,
                        "due_date": due_date,
                    },
                )
                if created:
                    fees_created += 1

        return fees_created
