from __future__ import annotations

import random
from decimal import Decimal
from typing import Iterable

from django.core.management import BaseCommand, call_command
from django.utils import timezone

from account.models import (
    Announcement,
    Assignment,
    AssignmentSubmission,
    Attendance,
    CustomUser,
    Department,
    Enrollment,
    Event,
    Fees,
    Leave,
    Notification,
    PromotionHistory,
    ResultSheet,
    School,
    Student,
    Subject,
    Teacher,
    Timetable,
)


class Command(BaseCommand):
    help = "Seed account app data and related models for training/demo."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", type=str, default="")
        parser.add_argument("--school-name", type=str, default="")
        parser.add_argument("--students", type=int, default=25)
        parser.add_argument("--teachers", type=int, default=6)
        parser.add_argument("--departments", type=int, default=3)
        parser.add_argument("--subjects", type=int, default=9)
        parser.add_argument("--assignments", type=int, default=6)
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args, **options):
        random.seed(options["seed"])

        # Base entities (school, departments, teachers, students, subjects)
        call_command(
            "seed_adminservices",
            admin_username=options["admin_username"],
            school_name=options["school_name"],
            students=options["students"],
            teachers=options["teachers"],
            departments=options["departments"],
            subjects=options["subjects"],
            seed=options["seed"],
        )

        admin_user = self._get_admin_user(options["admin_username"])
        if not admin_user:
            self.stdout.write(self.style.WARNING("Admin user not found."))
            return
        school = getattr(admin_user, "managed_school", None)
        if not school:
            self.stdout.write(self.style.WARNING("No managed school found for admin."))
            return

        students = list(Student.objects.filter(school=school).select_related("user"))
        teachers = list(Teacher.objects.filter(school=school).select_related("user"))
        subjects = list(Subject.objects.filter(school=school))
        departments = list(Department.objects.filter(school=school))

        if not students or not teachers or not subjects:
            self.stdout.write(self.style.WARNING("Missing students/teachers/subjects; seed_adminservices may have failed."))
            return

        self._seed_enrollments(students, subjects)
        self._seed_assignments(subjects, teachers, options["assignments"])
        self._seed_submissions(students)
        self._seed_results(students, subjects, school)
        self._seed_fees(students, school)
        self._seed_attendance(students, teachers, admin_user)
        self._seed_announcements(school, admin_user)
        self._seed_events(school, admin_user, students)
        self._seed_timetables(school, departments, subjects, teachers)
        self._seed_leaves(teachers, admin_user)
        self._seed_promotions(students, admin_user)
        self._seed_notifications(admin_user, students)

        # AI predictor data
        call_command(
            "seed_ai_predictor",
            count=20,
            seed=options["seed"],
            admin_username=options["admin_username"],
            school_name=options["school_name"],
        )

        self.stdout.write(self.style.SUCCESS("Account seeding completed."))

    def _get_admin_user(self, admin_username: str):
        username = admin_username.strip()
        if username:
            return CustomUser.objects.filter(username=username, role="admin").first()
        return CustomUser.objects.filter(role="admin").first()

    def _seed_enrollments(self, students: Iterable[Student], subjects: Iterable[Subject]) -> None:
        subjects_by_class = {}
        for subject in subjects:
            subjects_by_class.setdefault(subject.subject_class, []).append(subject)

        for student in students:
            class_subjects = subjects_by_class.get(student.student_class, [])
            for subject in class_subjects[:3]:
                Enrollment.objects.get_or_create(student=student, subject=subject)

    def _seed_assignments(self, subjects: Iterable[Subject], teachers: Iterable[Teacher], count: int) -> None:
        teachers = list(teachers)
        created = 0
        for subject in subjects:
            if created >= count:
                break
            teacher = subject.teacher or (random.choice(teachers) if teachers else None)
            if not teacher:
                continue
            title = f"Seed Assignment {subject.name}"
            Assignment.objects.get_or_create(
                subject=subject,
                title=title,
                defaults={
                    "teacher": teacher,
                    "student_class": subject.subject_class,
                    "description": "Complete the exercises for this topic.",
                    "instructions": "Submit before due date.",
                    "due_date": timezone.now().date() + timezone.timedelta(days=7),
                    "total_marks": 100,
                    "status": "published",
                },
            )
            created += 1

    def _seed_submissions(self, students: Iterable[Student]) -> None:
        assignments = list(Assignment.objects.all())
        if not assignments:
            return
        for assignment in assignments:
            class_students = [s for s in students if s.student_class == assignment.student_class]
            for student in class_students[:2]:
                AssignmentSubmission.objects.get_or_create(
                    assignment=assignment,
                    student=student,
                    defaults={
                        "submission_text": "Seed submission text.",
                        "status": "submitted",
                        "marks_obtained": Decimal(random.randint(60, 95)),
                        "graded_date": timezone.now(),
                    },
                )

    def _seed_results(self, students: Iterable[Student], subjects: Iterable[Subject], school: School) -> None:
        academic_year = school.get_current_academic_year()
        for student in students[:10]:
            for subject in subjects[:3]:
                if subject.subject_class != student.student_class:
                    continue
                result, created = ResultSheet.objects.get_or_create(
                    student=student,
                    subject=subject,
                    term="1",
                    academic_year=academic_year,
                    defaults={
                        "class_score": Decimal(random.randint(10, 20)),
                        "mid_semester": Decimal(random.randint(15, 30)),
                        "end_of_term_exams": Decimal(random.randint(25, 50)),
                        "teacher_comment": "Seeded result.",
                    },
                )
                if created:
                    result.save()

    def _seed_fees(self, students: Iterable[Student], school: School) -> None:
        for student in students[:15]:
            due_date = timezone.now().date() + timezone.timedelta(days=30)
            Fees.objects.get_or_create(
                school=school,
                student=student,
                fee_type="tuition",
                due_date=due_date,
                defaults={
                    "amount": Decimal("500.00"),
                    "discount": Decimal("0.00"),
                    "status": "unpaid",
                },
            )

    def _seed_attendance(self, students: Iterable[Student], teachers: Iterable[Teacher], admin_user: CustomUser) -> None:
        today = timezone.now().date()
        for student in students[:10]:
            Attendance.objects.get_or_create(
                student=student,
                date=today,
                defaults={
                    "attendance_type": "student",
                    "status": "present",
                    "class_attendance": student.student_class,
                    "marked_by": admin_user,
                },
            )
        for teacher in teachers[:5]:
            class_choice = students[0].student_class if students else "CRECHE"
            Attendance.objects.get_or_create(
                teacher=teacher,
                date=today,
                defaults={
                    "attendance_type": "teacher",
                    "status": "present",
                    "class_attendance": class_choice,
                    "marked_by": admin_user,
                },
            )

    def _seed_announcements(self, school: School, admin_user: CustomUser) -> None:
        Announcement.objects.get_or_create(
            school=school,
            title="Welcome Back",
            defaults={
                "content": "Welcome to the new term. Stay focused and engaged.",
                "author": admin_user,
                "priority": "medium",
                "target_audience": "all",
                "published": True,
                "publish_date": timezone.now(),
            },
        )

    def _seed_events(self, school: School, admin_user: CustomUser, students: Iterable[Student]) -> None:
        event, _ = Event.objects.get_or_create(
            school=school,
            title="Sports Day",
            defaults={
                "description": "Annual sports competition.",
                "event_type": "sports",
                "start_date": timezone.now() + timezone.timedelta(days=14),
                "end_date": timezone.now() + timezone.timedelta(days=14, hours=3),
                "location": "Main Field",
                "organizer": admin_user,
            },
        )
        for student in list(students)[:5]:
            event.participants.add(student.user)

    def _seed_timetables(
        self,
        school: School,
        departments: Iterable[Department],
        subjects: Iterable[Subject],
        teachers: Iterable[Teacher],
    ) -> None:
        departments = list(departments)
        subjects = list(subjects)
        teachers = list(teachers)
        if not departments or not subjects or not teachers:
            return
        day = "monday"
        start_time = timezone.datetime(2026, 1, 1, 8, 0).time()
        end_time = timezone.datetime(2026, 1, 1, 9, 0).time()
        for subject in subjects[:5]:
            Timetable.objects.get_or_create(
                school=school,
                student_class=subject.subject_class,
                day_of_week=day,
                start_time=start_time,
                defaults={
                    "department": subject.department or departments[0],
                    "subject": subject,
                    "teacher": subject.teacher or teachers[0],
                    "end_time": end_time,
                    "room_number": "A1",
                },
            )

    def _seed_leaves(self, teachers: Iterable[Teacher], admin_user: CustomUser) -> None:
        teacher = next(iter(teachers), None)
        if not teacher:
            return
        Leave.objects.get_or_create(
            teacher=teacher,
            leave_type="sick",
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=2),
            defaults={
                "reason": "Seeded sick leave.",
                "status": "approved",
                "approved_by": admin_user,
                "approval_date": timezone.now(),
            },
        )

    def _seed_promotions(self, students: Iterable[Student], admin_user: CustomUser) -> None:
        students = list(students)
        academic_year = timezone.now().strftime("%Y/") + str(timezone.now().year + 1)
        for student in students[:5]:
            PromotionHistory.objects.get_or_create(
                student=student,
                from_class=student.student_class,
                to_class=student.student_class,
                academic_year=academic_year,
                defaults={
                    "promotion_date": timezone.now().date(),
                    "promoted_by": admin_user,
                    "average_score": Decimal(random.randint(50, 95)),
                    "remarks": "Seeded promotion record.",
                },
            )

    def _seed_notifications(self, admin_user: CustomUser, students: Iterable[Student]) -> None:
        Notification.objects.get_or_create(
            user=admin_user,
            notification_type="system",
            title="Seed Complete",
            defaults={
                "message": "System seed completed successfully.",
                "link": "",
            },
        )
        for student in list(students)[:5]:
            Notification.objects.get_or_create(
                user=student.user,
                notification_type="announcement",
                title="Welcome",
                defaults={
                    "message": "Welcome to the new term.",
                    "link": "",
                },
            )
