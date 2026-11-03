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
    help = "Seed complete school management system data across all apps and display login credentials."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", type=str, default="")
        parser.add_argument("--school-name", type=str, default="")
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args, **options):
        random.seed(options["seed"])

        self.stdout.write("=" * 70)
        self.stdout.write(self.style.MIGRATE_HEADING("1. Seeding Base Admin Services (Super Admin, School, Departments, Classes, Fees, Subjects)..."))
        call_command(
            "seed_adminservices",
            admin_username=options["admin_username"],
            school_name=options["school_name"],
            seed=options["seed"],
        )

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.MIGRATE_HEADING("2. Seeding Teachers & Department Roles..."))
        call_command(
            "seed_teacher",
            admin_username=options["admin_username"],
            school_name=options["school_name"],
            seed=options["seed"],
        )

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.MIGRATE_HEADING("3. Seeding Students, Parents, Enrollments & Fees..."))
        call_command(
            "seed_student",
            admin_username=options["admin_username"],
            school_name=options["school_name"],
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

        students = list(Student.objects.filter(school=school).select_related("user", "student_class"))
        teachers = list(Teacher.objects.filter(school=school).select_related("user", "class_teacher_class"))
        subjects = list(Subject.objects.filter(school=school).select_related("subject_class", "teacher"))
        departments = list(Department.objects.filter(school=school))

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.MIGRATE_HEADING("4. Seeding Academic Activities (Assignments, Results, Attendance, Timetables)..."))
        self._seed_assignments(subjects, teachers)
        self._seed_submissions(students)
        self._seed_results(students, subjects, school)
        self._seed_attendance(students, teachers, admin_user)
        self._seed_announcements(school, admin_user)
        self._seed_events(school, admin_user, students)
        self._seed_timetables(school, departments, subjects, teachers)
        self._seed_leaves(teachers, admin_user)
        self._seed_promotions(students, admin_user)
        self._seed_notifications(admin_user, students)

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.MIGRATE_HEADING("5. Seeding AI Predictor Records..."))
        call_command(
            "seed_ai_predictor",
            count=20,
            seed=options["seed"],
            admin_username=options["admin_username"],
            school_name=options["school_name"],
        )

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("ALL APP SEEDING COMPLETED SUCCESSFULLY!"))
        self._print_credentials_summary(admin_user, school)

    def _get_admin_user(self, admin_username: str):
        username = admin_username.strip()
        if username:
            return CustomUser.objects.filter(username=username, role="admin").first()
        return CustomUser.objects.filter(role="admin", is_superuser=False).first()

    def _seed_assignments(self, subjects: Iterable[Subject], teachers: Iterable[Teacher]) -> None:
        teachers = list(teachers)
        for subject in subjects:
            teacher = subject.teacher or (random.choice(teachers) if teachers else None)
            if not teacher or not subject.subject_class:
                continue
            title = f"{subject.name} Homework Assignment 1"
            Assignment.objects.get_or_create(
                subject=subject,
                title=title,
                defaults={
                    "teacher": teacher,
                    "student_class": subject.subject_class,
                    "description": f"Exercises and problem set for {subject.name}.",
                    "instructions": "Answer all questions and submit your working before the due date.",
                    "due_date": timezone.now().date() + timezone.timedelta(days=7),
                    "total_marks": 100,
                    "status": "published",
                },
            )

    def _seed_submissions(self, students: Iterable[Student]) -> None:
        assignments = list(Assignment.objects.all())
        if not assignments:
            return
        for assignment in assignments[:10]:
            class_students = [s for s in students if s.student_class == assignment.student_class]
            for student in class_students[:3]:
                AssignmentSubmission.objects.get_or_create(
                    assignment=assignment,
                    student=student,
                    defaults={
                        "submission_text": "Completed assignment solutions submitted on time.",
                        "status": "submitted",
                        "marks_obtained": Decimal(random.randint(65, 95)),
                        "graded_date": timezone.now(),
                    },
                )

    def _seed_results(self, students: Iterable[Student], subjects: Iterable[Subject], school: School) -> None:
        academic_year = school.get_current_academic_year() or "2025/2026"
        for student in students[:12]:
            for subject in subjects:
                if subject.subject_class != student.student_class:
                    continue
                result, created = ResultSheet.objects.get_or_create(
                    student=student,
                    subject=subject,
                    term="1",
                    academic_year=academic_year,
                    defaults={
                        "class_score": Decimal(random.randint(15, 20)),
                        "mid_semester": Decimal(random.randint(20, 30)),
                        "end_of_term_exams": Decimal(random.randint(35, 50)),
                        "teacher_comment": "Excellent effort and consistent classroom participation.",
                    },
                )
                if created:
                    result.save()

    def _seed_attendance(self, students: Iterable[Student], teachers: Iterable[Teacher], admin_user: CustomUser) -> None:
        today = timezone.now().date()
        for student in students:
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
        for teacher in teachers:
            target_class = teacher.class_teacher_class or (students[0].student_class if students else None)
            Attendance.objects.get_or_create(
                teacher=teacher,
                date=today,
                defaults={
                    "attendance_type": "teacher",
                    "status": "present",
                    "class_attendance": target_class,
                    "marked_by": admin_user,
                },
            )

    def _seed_announcements(self, school: School, admin_user: CustomUser) -> None:
        announcements_data = [
            ("Welcome to the New Academic Term", "Welcome back students, teachers, and parents! Let us make this term productive and rewarding.", "high", "all"),
            ("Mid-Term Assessment Schedule", "Mid-term examinations will commence next month. Teachers will publish revision outlines.", "medium", "all"),
            ("Parent-Teacher Association (PTA) General Meeting", "The annual general PTA meeting is scheduled for next Friday at the school auditorium.", "high", "parent"),
        ]
        for title, content, priority, audience in announcements_data:
            Announcement.objects.get_or_create(
                school=school,
                title=title,
                defaults={
                    "content": content,
                    "author": admin_user,
                    "priority": priority,
                    "target_audience": audience,
                    "published": True,
                    "publish_date": timezone.now(),
                },
            )

    def _seed_events(self, school: School, admin_user: CustomUser, students: Iterable[Student]) -> None:
        events = [
            ("Inter-House Sports Festival", "Annual track and field sports competition between school houses.", "sports", 14),
            ("STEM & Science Exhibition", "Showcasing student robotics, physics, and chemistry projects.", "academic", 28),
        ]
        for title, desc, ev_type, days_ahead in events:
            event, _ = Event.objects.get_or_create(
                school=school,
                title=title,
                defaults={
                    "description": desc,
                    "event_type": ev_type,
                    "start_date": timezone.now() + timezone.timedelta(days=days_ahead),
                    "end_date": timezone.now() + timezone.timedelta(days=days_ahead, hours=4),
                    "location": "School Sports Complex",
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

        days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
        periods = [
            (timezone.datetime(2026, 1, 1, 8, 0).time(), timezone.datetime(2026, 1, 1, 9, 0).time(), "Room 101"),
            (timezone.datetime(2026, 1, 1, 9, 10).time(), timezone.datetime(2026, 1, 1, 10, 10).time(), "Room 102"),
            (timezone.datetime(2026, 1, 1, 10, 30).time(), timezone.datetime(2026, 1, 1, 11, 30).time(), "Science Lab"),
        ]

        created = 0
        for subj in subjects:
            if not subj.subject_class:
                continue
            day = random.choice(days)
            start_t, end_t, room = random.choice(periods)
            teacher = subj.teacher or teachers[0]
            dept = subj.department or departments[0]
            _, c = Timetable.objects.get_or_create(
                school=school,
                student_class=subj.subject_class,
                day_of_week=day,
                start_time=start_t,
                defaults={
                    "department": dept,
                    "subject": subj,
                    "teacher": teacher,
                    "end_time": end_t,
                    "room_number": room,
                },
            )
            if c:
                created += 1
            if created >= 15:
                break

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
                "reason": "Attending medical consultation.",
                "status": "approved",
                "approved_by": admin_user,
                "approval_date": timezone.now(),
            },
        )

    def _seed_promotions(self, students: Iterable[Student], admin_user: CustomUser) -> None:
        academic_year = "2024/2025"
        for student in students[:5]:
            if not student.student_class:
                continue
            PromotionHistory.objects.get_or_create(
                student=student,
                from_class=student.student_class,
                to_class=student.student_class,
                academic_year=academic_year,
                defaults={
                    "promotion_date": timezone.now().date() - timezone.timedelta(days=90),
                    "promoted_by": admin_user,
                    "average_score": Decimal(random.randint(70, 92)),
                    "remarks": "Promoted with commendable academic achievement.",
                },
            )

    def _seed_notifications(self, admin_user: CustomUser, students: Iterable[Student]) -> None:
        Notification.objects.get_or_create(
            user=admin_user,
            notification_type="system",
            title="System Setup Complete",
            defaults={
                "message": "All school departments, classes, subjects, teachers, and students have been seeded successfully.",
                "link": "/adminservices/admin-dashboard/",
            },
        )
        for student in list(students)[:5]:
            Notification.objects.get_or_create(
                user=student.user,
                notification_type="announcement",
                title="Welcome to Term 1",
                defaults={
                    "message": "Check your timetable and enrolled subjects for this semester.",
                    "link": "/student/dashboard/",
                },
            )

    def _print_credentials_summary(self, admin_user: CustomUser, school: School) -> None:
        superadmin = CustomUser.objects.filter(is_superuser=True).first()
        superadmin_name = superadmin.username if superadmin else "superadmin"

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("              DEMO LOGIN CREDENTIALS DIRECTORY")
        self.stdout.write("=" * 70)
        self.stdout.write(f"School: {school.name} (Active Trial Subscription)")
        self.stdout.write("-" * 70)
        self.stdout.write(f"{'Role':<18} | {'Username':<18} | {'Password':<15} | {'Portal URL'}")
        self.stdout.write("-" * 70)
        self.stdout.write(f"{'Super Admin':<18} | {superadmin_name:<18} | {'Admin@12345':<15} | /admin/")
        self.stdout.write(f"{'School Admin':<18} | {admin_user.username:<18} | {'Admin@12345':<15} | /adminservices/admin-dashboard/")
        self.stdout.write(f"{'Teacher (Math)':<18} | {'teacher_math':<18} | {'Teacher@12345':<15} | /teacher/dashboard/ (JHS 1 Class Teacher)")
        self.stdout.write(f"{'Teacher (Science)':<18} | {'teacher_science':<18} | {'Teacher@12345':<15} | /teacher/dashboard/ (Primary 5 Class Teacher)")
        self.stdout.write(f"{'Teacher (English)':<18} | {'teacher_english':<18} | {'Teacher@12345':<15} | /teacher/dashboard/ (Primary 4 Class Teacher)")
        self.stdout.write(f"{'Teacher (ICT)':<18} | {'teacher_ict':<18} | {'Teacher@12345':<15} | /teacher/dashboard/")
        self.stdout.write(f"{'Student (JHS 1)':<18} | {'student_jhs1':<18} | {'Student@12345':<15} | /student/dashboard/")
        self.stdout.write(f"{'Student (JHS 2)':<18} | {'student_jhs2':<18} | {'Student@12345':<15} | /student/dashboard/")
        self.stdout.write(f"{'Student (P5)':<18} | {'student_p5':<18} | {'Student@12345':<15} | /student/dashboard/")
        self.stdout.write(f"{'Parent':<18} | {'parent_kwame':<18} | {'Parent@12345':<15} | /account/login/")
        self.stdout.write("=" * 70)
