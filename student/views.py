import logging
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.db import models
from django.db.models import Q, Avg, Count, Sum, F
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.core.cache import cache

# Model Imports
from account.models import (
    Enrollment, ResultSheet, Student, Teacher, Fees,
    Assignment, Attendance, Announcement, Event, Subject,
    AssignmentSubmission, Timetable
)
# Cache and Utils Imports
from account.cache_utils import make_cache_key, should_cache, bump_cache_version
from adminservices.utils import create_in_app_notification

# Form Imports
from .forms import (
    StudentEnrollmentForm, BulkStudentEnrollmentForm, AssignmentSubmissionForm
)

logger = logging.getLogger(__name__)


@login_required(login_url='account:login')
def student_dashboard(request):
    """
    Modern, intuitive student dashboard view providing real-time academic KPIs,
    coursework and assignment status tracking, exam results, financial records,
    and institutional notices.
    """
    if request.user.role != "student":
        messages.error(request, "Access denied. Student portal only.")
        return redirect("account:login")

    try:
        student = Student.objects.select_related("school", "user", "parent").get(user=request.user)
        school = student.school
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect("account:login")

    # --- Cache Check ---
    cache_key = make_cache_key("student_portal", school.id, f"dashboard:{student.id}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    today = timezone.now().date()

    # 1. Enrolled Courses
    all_enrolled_courses = Enrollment.objects.filter(
        student=student,
        is_active=True
    ).select_related("subject__teacher__user", "subject__department")
    enrolled_courses_count = all_enrolled_courses.count()
    enrolled_courses = all_enrolled_courses[:6]

    # 2. Attendance Performance
    total_attendance = Attendance.objects.filter(student=student).count()
    present_count = Attendance.objects.filter(student=student, status="present").count()
    attendance_rate = (present_count / total_attendance * 100) if total_attendance > 0 else 0

    # 3. Recent Exam Results
    recent_results = ResultSheet.objects.filter(student=student).select_related("subject").order_by("-exam_date")[:6]
    average_grade = recent_results.aggregate(Avg("percentage"))["percentage__avg"]
    best_result = ResultSheet.objects.filter(student=student).order_by("-percentage").first()
    best_score = best_result.percentage if best_result else None

    # 4. Financial Records
    pending_fees = Fees.objects.filter(
        student=student,
        status__in=["unpaid", "partial", "overdue"]
    ).order_by("due_date")

    total_pending_fees = pending_fees.aggregate(
        total=Sum(F("amount_required") - F("discount") - F("amount_paid"))
    )["total"] or 0

    # 5. School Notices & Calendar
    announcements = Announcement.objects.filter(
        school=school,
        published=True,
        target_audience__in=["all", "students"]
    ).order_by("-created_at")[:5]

    upcoming_events = Event.objects.filter(
        school=school,
        start_date__gte=timezone.now(),
        is_public=True
    ).order_by("start_date")[:5]

    # 6. Assignments & Submissions
    assignments = Assignment.objects.filter(
        subject__enrollments__student=student,
        subject__school=school,
        status="published"
    ).select_related("subject", "teacher__user")

    # Fetch all submissions by this student
    student_submissions = AssignmentSubmission.objects.filter(student=student)
    submissions_dict = {sub.assignment_id: sub for sub in student_submissions}
    submitted_ids = [sub.assignment_id for sub in student_submissions if sub.status in ["submitted", "graded"]]
    graded_count = sum(1 for sub in student_submissions if sub.status == "graded")

    pending_assignments_count = assignments.filter(
        due_date__gte=today
    ).exclude(id__in=submitted_ids).count()

    overdue_assignments_count = assignments.filter(
        due_date__lt=today
    ).exclude(id__in=submitted_ids).count()

    # Deadlines for the next 7 days
    upcoming_deadlines = assignments.filter(
        due_date__gte=today,
        due_date__lte=today + timezone.timedelta(days=7)
    ).exclude(id__in=submitted_ids).order_by("due_date")[:5]

    # Enriched assignment cards list with clear status
    assignment_items = []
    for a in assignments.order_by("-created_at")[:8]:
        sub = submissions_dict.get(a.id)
        is_sub = sub is not None and sub.status in ["submitted", "graded"]
        is_ovd = a.is_overdue() and not is_sub
        
        if sub and sub.status == "graded":
            status_label = "Graded"
            status_badge = "success"
        elif sub and sub.status == "submitted":
            status_label = "Submitted"
            status_badge = "info"
        elif is_ovd:
            status_label = "Overdue"
            status_badge = "danger"
        else:
            status_label = "To-Do"
            status_badge = "warning"

        assignment_items.append({
            "assignment": a,
            "submission": sub,
            "is_submitted": is_sub,
            "is_overdue": is_ovd,
            "status_label": status_label,
            "status_badge": status_badge,
        })

    # 7. Today's Class Timetable / Schedule
    today_day_str = timezone.now().strftime('%A').lower()
    student_class = student.student_class

    today_class_schedule = []
    has_class_timetable = False

    if student_class:
        class_timetables_today = Timetable.objects.filter(
            student_class=student_class,
            school=school,
            day_of_week=today_day_str,
            is_active=True
        ).select_related('subject', 'teacher__user').order_by('start_time')

        now_time = timezone.now().time()
        for item in class_timetables_today:
            if item.start_time <= now_time <= item.end_time:
                time_status = "current"
            elif now_time < item.start_time:
                time_status = "upcoming"
            else:
                time_status = "completed"
            today_class_schedule.append({
                'entry': item,
                'status': time_status,
            })

        has_class_timetable = Timetable.objects.filter(
            student_class=student_class,
            school=school,
            is_active=True
        ).exists()

    # 8. Context Assembly
    context = {
        "today_class_schedule": today_class_schedule,
        "today_day_name": timezone.now().strftime('%A'),
        "has_class_timetable": has_class_timetable,
        "student": student,
        "enrolled_courses": enrolled_courses,
        "enrolled_courses_count": enrolled_courses_count,

        # Assignment metrics
        "pending_assignments_count": pending_assignments_count,
        "overdue_assignments_count": overdue_assignments_count,
        "submitted_assignments_count": len(submitted_ids),
        "graded_assignments_count": graded_count,
        "assignment_items": assignment_items,
        "recent_assignments": assignments.order_by("-created_at")[:10],
        "upcoming_deadlines": upcoming_deadlines,
        "upcoming_deadlines_count": upcoming_deadlines.count(),

        # Financial summary
        "pending_fees": pending_fees,
        "total_pending_fees": total_pending_fees,

        # Performance/Social metrics
        "attendance_rate": round(attendance_rate, 1),
        "recent_results": recent_results,
        "average_grade": round(average_grade, 1) if average_grade else None,
        "best_score": round(best_score, 1) if best_score else None,
        "today": today,
        "announcements": announcements,
        "upcoming_events": upcoming_events,
    }

    response = render(request, "student/student_dashboard.html", context)
    if should_cache(request):
        cache.set(cache_key, response, 180)
    return response


@login_required
def student_detail(request):
    """
    Comprehensive Student Profile view presenting academic identity,
    guardian information, active course enrollments, attendance record,
    and financial ledger summary.
    """
    if request.user.role != "student":
        messages.error(request, "Access denied. Student portal only.")
        return redirect("account:login")

    try:
        student = Student.objects.select_related("user", "parent", "school", "student_class", "previous_class").get(user=request.user)
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect("account:login")

    cache_key = make_cache_key("student_portal", student.school_id, f"detail:{student.id}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    # Enrollments
    enrolled_courses = Enrollment.objects.filter(
        student=student,
        is_active=True
    ).select_related("subject__teacher__user", "subject__department")
    enrollments_count = enrolled_courses.count()

    # Attendance
    total_attendance = Attendance.objects.filter(student=student).count()
    present_count = Attendance.objects.filter(student=student, status="present").count()
    attendance_rate = (present_count / total_attendance * 100) if total_attendance > 0 else 0

    # Financial status
    pending_fees = Fees.objects.filter(student=student, status__in=["unpaid", "partial", "overdue"]).order_by("due_date")
    fee_aggregate = pending_fees.aggregate(total=Sum(F("amount_required") - F("discount") - F("amount_paid")))
    total_pending_fees = fee_aggregate["total"] or 0

    # Recent Results & Academic Standing
    recent_results = ResultSheet.objects.filter(student=student).select_related("subject").order_by("-exam_date")[:5]
    average_grade = recent_results.aggregate(Avg("percentage"))["percentage__avg"]

    # Assignments
    assignments_count = Assignment.objects.filter(
        subject__enrollments__student=student,
        status="published"
    ).distinct().count()
    submissions_count = AssignmentSubmission.objects.filter(
        student=student,
        status__in=["submitted", "graded"]
    ).count()

    context = {
        "student": student,
        "enrollments_count": enrollments_count,
        "enrolled_courses": enrolled_courses[:6],
        "attendance_rate": round(attendance_rate, 1),
        "total_attendance": total_attendance,
        "present_count": present_count,
        "pending_fees": pending_fees[:5],
        "total_pending_fees": total_pending_fees,
        "recent_results": recent_results,
        "average_grade": round(average_grade, 1) if average_grade else None,
        "assignments_count": assignments_count,
        "submissions_count": submissions_count,
    }

    response = render(request, "student/student_detail.html", context)
    if should_cache(request):
        cache.set(cache_key, response, 180)
    return response


@login_required
def view_result(request, student_id):
    """View student results with proper authorization"""
    student = get_object_or_404(Student, id=student_id)
    school = student.school

    # RBAC Checks
    if request.user.role == "student":
        if request.user.student_profile.id != student.id:
            messages.error(request, "You can only view your own results")
            return redirect("student:student-dashboard")
    elif request.user.role == "teacher":
        if request.user.teacher_profile.school != school:
            messages.error(request, "You can only view results for students in your school")
            return redirect("teacher:teacher-dashboard")
    elif request.user.role == "admin":
        if request.user.managed_school != school:
            messages.error(request, "You can only view results for students in your school")
            return redirect("adminservices:admin-dashboard")
    else:
        messages.error(request, "Unauthorized role.")
        return redirect("account:login")

    selected_year = request.GET.get("academic_year", "").strip()
    selected_term = request.GET.get("term", "").strip()

    cache_key = make_cache_key("student_portal", school.id, f"results:{student.id}:{request.user.id}:{selected_year}:{selected_term}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    base_results = ResultSheet.objects.filter(student=student).select_related(
        "subject__department", "subject__teacher__user"
    ).order_by("-academic_year", "-term", "subject__name")

    available_years = list(base_results.values_list("academic_year", flat=True).distinct().order_by("-academic_year"))

    results = base_results
    if selected_year:
        results = results.filter(academic_year=selected_year)
    if selected_term:
        results = results.filter(term=selected_term)

    # Statistical Computations
    total_subjects = results.count()
    avg_percentage = results.aggregate(avg=Avg("percentage"))["avg"] or 0
    avg_percentage = round(float(avg_percentage), 1)

    # Dynamic Standing Grade & Remark
    if avg_percentage >= 80:
        standing_grade = "A"
        standing_remark = "Outstanding Academic Excellence"
    elif avg_percentage >= 70:
        standing_grade = "B"
        standing_remark = "Commendable Performance"
    elif avg_percentage >= 60:
        standing_grade = "C"
        standing_remark = "Satisfactory Progress"
    elif avg_percentage >= 50:
        standing_grade = "D"
        standing_remark = "Pass - Room for Growth"
    else:
        standing_grade = "F"
        standing_remark = "Needs Intervention & Support"

    best_result = results.order_by("-percentage").first()
    distinctions_count = sum(1 for r in results if r.grade and "A" in r.grade)

    result_summary = {
        "total_subjects": total_subjects,
        "average_percentage": avg_percentage,
        "standing_grade": standing_grade,
        "standing_remark": standing_remark,
        "best_result": best_result,
        "distinctions_count": distinctions_count,
    }

    # Group results dynamically by Academic Year and Term with genuine calculated term averages
    TERM_MAP = {
        "1": "First Term",
        "2": "Second Term",
        "3": "Third Term",
    }
    grouped_reports = []
    sessions = (
        results.values("academic_year", "term")
        .distinct()
        .order_by("-academic_year", "-term")
    )

    for session in sessions:
        year = session["academic_year"]
        t_code = session["term"]
        term_label = TERM_MAP.get(str(t_code), f"Term {t_code}")

        term_results = [r for r in results if r.academic_year == year and str(r.term) == str(t_code)]
        if not term_results:
            continue

        term_avg = sum(float(r.percentage or 0) for r in term_results) / len(term_results)
        term_highest = max(term_results, key=lambda r: float(r.percentage or 0))

        grouped_reports.append({
            "academic_year": year,
            "term": t_code,
            "term_label": term_label,
            "results": term_results,
            "subject_count": len(term_results),
            "term_average": round(term_avg, 1),
            "highest_result": term_highest,
        })

    # Prepare Chart Data
    chart_subjects = [r.subject.name for r in results]
    chart_percentages = [float(r.percentage or 0) for r in results]

    response = render(request, "student/view_result.html", {
        "results": results,
        "student": student,
        "result_summary": result_summary,
        "grouped_reports": grouped_reports,
        "available_years": available_years,
        "selected_year": selected_year,
        "selected_term": selected_term,
        "chart_subjects": chart_subjects,
        "chart_percentages": chart_percentages,
    })
    if should_cache(request):
        cache.set(cache_key, response, 180)
    return response


@login_required
def student_enrolled_courses(request):
    """
    User-friendly, intuitive overview of student's enrolled courses and curriculum.
    Presents subject metrics, assigned teacher credentials, pending assignments count,
    latest performance scores, and department distributions.
    """
    if request.user.role != "student":
        messages.error(request, "Access denied. Students only.")
        return redirect("account:login")

    try:
        student = Student.objects.select_related("user", "school", "student_class").get(user=request.user)
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect("account:login")

    # Filter parameters
    search_query = request.GET.get("search", "").strip()
    selected_dept = request.GET.get("department", "").strip()

    cache_key = make_cache_key("student_portal", student.school_id, f"courses:{student.id}:{search_query}:{selected_dept}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    all_active_enrollments = Enrollment.objects.filter(
        student=student,
        is_active=True
    ).select_related(
        "subject__teacher__user",
        "subject__department"
    ).order_by("subject__name")

    # Department breakdown from all active enrollments
    departments_summary = (
        all_active_enrollments
        .exclude(subject__department__name__isnull=True)
        .values("subject__department__name")
        .annotate(count=Count("id"))
        .order_by("subject__department__name")
    )

    # Filter for display if search or department selected
    filtered_enrollments = all_active_enrollments
    if search_query:
        filtered_enrollments = filtered_enrollments.filter(
            Q(subject__name__icontains=search_query) |
            Q(subject__teacher__user__first_name__icontains=search_query) |
            Q(subject__teacher__user__last_name__icontains=search_query) |
            Q(subject__department__name__icontains=search_query)
        )
    if selected_dept:
        filtered_enrollments = filtered_enrollments.filter(
            subject__department__name__iexact=selected_dept
        )

    all_subject_ids = [e.subject_id for e in all_active_enrollments]

    # Pre-fetch published assignments for these subjects in student's class
    assignment_filter = Q(subject_id__in=all_subject_ids, status="published")
    if student.student_class:
        assignment_filter &= Q(student_class=student.student_class)
    assignments = Assignment.objects.filter(assignment_filter)

    # Submissions by student
    student_submissions = AssignmentSubmission.objects.filter(
        student=student,
        assignment__in=assignments,
        status__in=["submitted", "graded"]
    ).values_list("assignment_id", flat=True)
    submitted_assignment_ids = set(student_submissions)

    # Group assignments count and pending count
    subject_assignments_count = {}
    subject_pending_count = {}
    for a in assignments:
        s_id = a.subject_id
        subject_assignments_count[s_id] = subject_assignments_count.get(s_id, 0) + 1
        if a.id not in submitted_assignment_ids:
            subject_pending_count[s_id] = subject_pending_count.get(s_id, 0) + 1

    # Pre-fetch recent examination results for these subjects
    results = ResultSheet.objects.filter(
        student=student,
        subject_id__in=all_subject_ids
    ).order_by("-exam_date")

    latest_results_by_subject = {}
    for r in results:
        if r.subject_id not in latest_results_by_subject:
            latest_results_by_subject[r.subject_id] = r

    # Build enriched course objects for filtered list
    courses_data = []
    teachers_set = set()
    for e in all_active_enrollments:
        if e.subject.teacher and e.subject.teacher_id:
            teachers_set.add(e.subject.teacher_id)

    for e in filtered_enrollments:
        subj = e.subject
        courses_data.append({
            "enrollment": e,
            "subject": subj,
            "teacher": subj.teacher,
            "department": subj.department,
            "assignments_count": subject_assignments_count.get(subj.id, 0),
            "pending_assignments_count": subject_pending_count.get(subj.id, 0),
            "latest_result": latest_results_by_subject.get(subj.id),
        })

    total_pending_tasks = sum(subject_pending_count.values())

    context = {
        "student": student,
        "enrollments": filtered_enrollments,
        "courses_data": courses_data,
        "total_enrollments": all_active_enrollments.count(),
        "filtered_count": len(courses_data),
        "total_teachers": len(teachers_set),
        "total_departments": len(departments_summary),
        "total_pending_tasks": total_pending_tasks,
        "subjects_by_department": departments_summary,
        "search_query": search_query,
        "selected_dept": selected_dept,
    }

    response = render(request, "student/enrolled_courses.html", context)
    if should_cache(request):
        cache.set(cache_key, response, 180)
    return response


@login_required(login_url='account:login')
def list_fees_related(request, student_id):
    """Lists all fee records for a specific student."""
    student = get_object_or_404(Student.objects.select_related('school', 'user'), id=student_id)
    school = student.school

    # RBAC Logic
    if request.user.role == "student":
        if not hasattr(request.user, 'student_profile') or request.user.student_profile.id != student.id:
            messages.error(request, "Access denied. You can only view your own financial records.")
            return redirect("student:student-dashboard")
    elif request.user.role == "admin":
        managed_school = getattr(request.user, 'managed_school', None)
        if not managed_school or managed_school != school:
            messages.error(request, "Permission denied. This student belongs to another institution.")
            return redirect("adminservices:admin-dashboard")
    else:
        messages.error(request, "You do not have permission to view fee records.")
        return redirect("account:login")

    fees_qs = Fees.objects.filter(student=student, school=school).select_related('fee_structure', 'student_class').order_by('-due_date', '-id')
    fees_list = list(fees_qs)

    total_billed = sum(f.total_bill for f in fees_list)
    total_paid = sum(f.amount_paid for f in fees_list)
    total_balance = sum(f.balance for f in fees_list)
    settled_count = sum(1 for f in fees_list if f.is_paid_in_full)
    pending_count = sum(1 for f in fees_list if not f.is_paid_in_full)
    overdue_count = sum(1 for f in fees_list if f.is_overdue)

    context = {
        "fees": fees_list,
        "student": student,
        "school": school,
        "total_billed": total_billed,
        "total_paid": total_paid,
        "total_balance": total_balance,
        "settled_count": settled_count,
        "pending_count": pending_count,
        "overdue_count": overdue_count,
    }
    return render(request, "student/fees_list.html", context)


@login_required
def view_all_assignment(request):
    """
    User-friendly, intuitive assignment overview for students.
    Provides coursework status tracking, submission deadlines, score breakdowns,
    and fast search/filtering across active subjects.
    """
    if request.user.role != "student":
        messages.error(request, "Access denied. Students only.")
        return redirect("account:login")

    try:
        student = Student.objects.select_related("school", "user", "student_class").get(user=request.user)
        school = student.school
        student_class = student.student_class
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect("account:login")

    today = timezone.now().date()

    # Search & Filter params
    search_query = request.GET.get("search", "").strip()
    selected_subject = request.GET.get("subject", "").strip()
    selected_status = request.GET.get("status", "").strip()

    cache_key = make_cache_key("student_portal", school.id, f"assignments:{student.id}:{search_query}:{selected_subject}:{selected_status}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    # Base queryset of published assignments for student
    assignments_qs = Assignment.objects.filter(
        subject__enrollments__student=student,
        subject__school=school,
        status="published"
    )
    if student_class:
        assignments_qs = assignments_qs.filter(student_class=student_class)
    assignments_qs = assignments_qs.select_related("subject__department", "teacher__user").order_by("due_date")

    # Get all submissions for THIS student only
    student_submissions = AssignmentSubmission.objects.filter(student=student)
    submissions_by_assignment = {sub.assignment_id: sub for sub in student_submissions}

    # Distinct subjects for the filter dropdown
    distinct_subjects = Subject.objects.filter(
        enrollments__student=student,
        school=school
    ).distinct().order_by("name")

    # Classify assignments into data items with accurate status
    all_items = []
    total_count = 0
    pending_count = 0
    submitted_count = 0
    graded_count = 0
    overdue_count = 0

    for a in assignments_qs:
        total_count += 1
        sub = submissions_by_assignment.get(a.id)

        # Determine true status for THIS student
        if sub and sub.status in ["submitted", "graded", "late"]:
            if sub.status == "graded":
                status_key = "graded"
                graded_count += 1
                submitted_count += 1
            else:
                status_key = "submitted"
                submitted_count += 1
        else:
            if a.due_date and a.due_date < today:
                status_key = "overdue"
                overdue_count += 1
            else:
                status_key = "pending"
                pending_count += 1

        # Days remaining or overdue
        if a.due_date:
            days_diff = (a.due_date - today).days
        else:
            days_diff = None

        all_items.append({
            "assignment": a,
            "submission": sub,
            "status_key": status_key,
            "days_diff": days_diff,
            "is_overdue": a.due_date < today if a.due_date else False,
        })

    # Apply search and filters
    filtered_items = all_items
    if search_query:
        sq = search_query.lower()
        filtered_items = [
            item for item in filtered_items
            if sq in item["assignment"].title.lower()
            or sq in (item["assignment"].subject.name or "").lower()
            or (item["assignment"].teacher and sq in item["assignment"].teacher.user.get_full_name().lower())
        ]

    if selected_subject:
        filtered_items = [
            item for item in filtered_items
            if str(item["assignment"].subject_id) == selected_subject
            or item["assignment"].subject.name.lower() == selected_subject.lower()
        ]

    if selected_status:
        if selected_status == "submitted":
            filtered_items = [item for item in filtered_items if item["status_key"] in ["submitted", "graded"]]
        else:
            filtered_items = [item for item in filtered_items if item["status_key"] == selected_status]

    context = {
        "student": student,
        "items": filtered_items,
        "total_count": total_count,
        "pending_count": pending_count,
        "submitted_count": submitted_count,
        "graded_count": graded_count,
        "overdue_count": overdue_count,
        "distinct_subjects": distinct_subjects,
        "subjects": distinct_subjects,
        "search_query": search_query,
        "selected_subject": selected_subject,
        "selected_status": selected_status,
        "assignments": [item["assignment"] for item in filtered_items],
    }

    response = render(request, "student/assignments.html", context)
    if should_cache(request):
        cache.set(cache_key, response, 180)
    return response


@login_required
def view_assignment(request, assignment_id):
    """Detail view of a specific assignment."""
    try:
        student = request.user.student_profile
        school = student.school
    except AttributeError:
        messages.error(request, "Student profile not found.")
        return redirect("account:login")

    assignment = get_object_or_404(
        Assignment,
        id=assignment_id,
        subject__school=school,
        student_class=student.student_class,
        status="published"
    )

    if not assignment.subject.enrollments.filter(student=student, is_active=True).exists():
        messages.error(request, "You are not enrolled in this subject.")
        return redirect("student:student-dashboard")

    submission, created = AssignmentSubmission.objects.get_or_create(
        assignment=assignment,
        student=student,
        defaults={"status": "pending"}
    )

    return render(request, 'student/assignment_detail.html', {
        'assignment': assignment,
        'submission': submission,
        'student': student,
    })


@login_required
def submit_assignment(request, assignment_id):
    """View to handle assignment submission."""
    try:
        student = request.user.student_profile
        school = student.school
    except AttributeError:
        messages.error(request, "Student profile not found.")
        return redirect("account:login")

    assignment = get_object_or_404(
        Assignment,
        id=assignment_id,
        subject__school=school,
        status="published"
    )

    if not assignment.subject.enrollments.filter(student=student, is_active=True).exists():
        messages.error(request, "You are not enrolled in this subject.")
        return redirect("student:student-dashboard")

    submission, created = AssignmentSubmission.objects.get_or_create(
        assignment=assignment,
        student=student,
        defaults={'status': 'pending'}
    )

    if request.method == "POST":
        form = AssignmentSubmissionForm(request.POST, request.FILES, instance=submission)
        if form.is_valid():
            submission = form.save(commit=False)
            # Logic for late submission
            is_overdue = assignment.due_date < timezone.now().date()
            submission.status = "late" if is_overdue else "submitted"
            submission.submission_date = timezone.now()
            submission.save()

            # Async notification attempt
            try:
                create_in_app_notification(
                    user=assignment.teacher.user,
                    title=f"Assignment submitted: {assignment.title}",
                    message=f"{student.user.get_full_name()} submitted the assignment.",
                    notification_type="assignment",
                    related_object=submission,
                    link=reverse("teacher:assignment-submissions", args=[assignment.id]),
                )
            except Exception as e:
                logger.error(f"Notification error: {e}")

            messages.success(request, "Assignment submitted successfully!")
            bump_cache_version(school.id, "student_portal")
            bump_cache_version(school.id, "teacher_portal")
            return redirect("student:assignment-detail", assignment_id=assignment.id)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AssignmentSubmissionForm(instance=submission)

    return render(request, 'student/submit_assignment.html', {
        'assignment': assignment,
        'form': form,
        'submission': submission,
        'student': student,
    })

@login_required
def student_timetable(request):
    """Weekly class timetable schedule view for students."""
    if request.user.role != "student":
        messages.error(request, "Access denied. Students only.")
        return redirect("account:login")

    student = get_object_or_404(Student.objects.select_related('school', 'student_class', 'user'), user=request.user)
    school = student.school
    student_class = student.student_class

    DAYS = [
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
    ]
    days_schedule = {day_code: {'label': day_label, 'entries': []} for day_code, day_label in DAYS}

    if student_class:
        all_entries = Timetable.objects.filter(
            student_class=student_class,
            school=school,
            is_active=True
        ).select_related('subject', 'teacher__user').order_by('start_time')

        for item in all_entries:
            if item.day_of_week in days_schedule:
                days_schedule[item.day_of_week]['entries'].append(item)
    else:
        all_entries = []

    today_day_str = timezone.now().strftime('%A').lower()

    context = {
        'student': student,
        'school': school,
        'student_class': student_class,
        'days_schedule': days_schedule,
        'today_day': today_day_str,
        'total_periods': len(all_entries) if isinstance(all_entries, list) else all_entries.count(),
    }
    return render(request, 'student/timetable.html', context)
