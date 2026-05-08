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
    AssignmentSubmission
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
    Complete Student Dashboard view with fixed NameError for Sum/F
    and corrected Fee logic using Status choices.
    """
    if request.user.role != "student":
        messages.error(request, "Access denied. Student portal only.")
        return redirect("account:login")

    try:
        # Optimized fetch using select_related for the school object
        student = Student.objects.select_related('school').get(user=request.user)
        school = student.school
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect("account:login")

    # --- Cache Check ---
    cache_key = f"student_portal_{school.id}_dashboard_{student.id}"
    cached_response = cache.get(cache_key)
    if cached_response:
        return cached_response

    today = timezone.now().date()

    # 1. Enrolled Courses (limit 5)
    enrolled_courses = Enrollment.objects.filter(
        student=student,
        is_active=True
    ).select_related('subject__teacher__user', 'subject__department')[:5]

    # 2. Attendance Performance
    total_attendance = Attendance.objects.filter(student=student).count()
    present_count = Attendance.objects.filter(student=student, status='present').count()
    attendance_rate = (present_count / total_attendance * 100) if total_attendance > 0 else 0

    # 3. Recent Exam Results
    recent_results = ResultSheet.objects.filter(student=student).select_related('subject').order_by('-exam_date')[:6]
    average_grade = recent_results.aggregate(Avg('percentage'))['percentage__avg']

    # 4. Financial Records (Fixed Sum/F logic)
    pending_fees = Fees.objects.filter(
        student=student,
        status__in=['unpaid', 'partial', 'overdue']
    ).order_by('due_date')

    # Database-level calculation for accuracy and speed
    total_pending_fees = pending_fees.aggregate(
        total=Sum(F('amount_required') - F('discount') - F('amount_paid'))
    )['total'] or 0

    # 5. School Notices & Calendar
    announcements = Announcement.objects.filter(
        school=school,
        published=True,
        target_audience__in=['all', 'students']
    ).order_by('-created_at')[:5]

    upcoming_events = Event.objects.filter(
        school=school,
        start_date__gte=timezone.now(),
        is_public=True
    ).order_by('start_date')[:5]

    # 6. Assignments & Submissions
    assignments = Assignment.objects.filter(
        subject__enrollments__student=student,
        subject__school=school,
        status="published"
    ).select_related('subject', 'teacher__user')

    # Exclude IDs already submitted or graded
    submitted_ids = AssignmentSubmission.objects.filter(
        student=student,
        status__in=['submitted', 'graded']
    ).values_list('assignment_id', flat=True)

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
    ).exclude(id__in=submitted_ids).order_by('due_date')[:5]

    # 7. Context Assembly
    context = {
        'student': student,
        'enrolled_courses': enrolled_courses,
        'enrolled_courses_count': enrolled_courses.count(),

        # Assignment metrics
        'pending_assignments_count': pending_assignments_count,
        'overdue_assignments_count': overdue_assignments_count,
        'submitted_assignments_count': len(submitted_ids),
        'recent_assignments': assignments.order_by('-created_at')[:10],
        'upcoming_deadlines': upcoming_deadlines,
        'upcoming_deadlines_count': upcoming_deadlines.count(),

        # Financial summary
        'pending_fees': pending_fees,
        'total_pending_fees': total_pending_fees,

        # Performance/Social metrics
        'attendance_rate': round(attendance_rate, 1),
        'recent_results': recent_results,
        'average_grade': round(average_grade, 1) if average_grade else None,
        'today': today,
        'announcements': announcements,
        'upcoming_events': upcoming_events,
    }

    response = render(request, 'student/student_dashboard.html', context)

    # Cache the rendered dashboard for 3 minutes to save resources
    cache.set(cache_key, response, 180)
    return response


@login_required
def student_detail(request):
    """Student profile detail view"""
    if request.user.role != "student":
        messages.error(request, "Access denied")
        return redirect("account:login")

    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found")
        return redirect("account:login")

    cache_key = make_cache_key("student_portal", student.school_id, f"detail:{student.id}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    enrollments_count = Enrollment.objects.filter(student=student, is_active=True).count()

    total_attendance = Attendance.objects.filter(student=student).count()
    present_count = Attendance.objects.filter(student=student, status='present').count()
    attendance_rate = (present_count / total_attendance * 100) if total_attendance > 0 else 0

    # Updated fee logic to match database aggregate patterns
    # Update 'paid=False' to 'status="pending"' (or "unpaid" depending on your choices)
    pending_fees = Fees.objects.filter(student=student, status="pending").order_by('due_date')
    fee_aggregate = pending_fees.aggregate(total=Sum(F('amount_required') - F('discount') - F('amount_paid')))
    total_pending_fees = fee_aggregate['total'] or 0

    context = {
        "student": student,
        "enrollments_count": enrollments_count,
        "attendance_rate": attendance_rate,
        "pending_fees": pending_fees[:5],
        "total_pending_fees": total_pending_fees,
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

    cache_key = make_cache_key("student_portal", school.id, f"results:{student.id}:{request.user.id}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    results = ResultSheet.objects.filter(student=student).select_related('subject', 'subject__department').order_by(
        '-academic_year', '-term', 'subject__name')

    result_summary = {
        'total_subjects': results.count(),
        'average_percentage': results.aggregate(avg=Avg('percentage'))['avg'] or 0,
    }

    response = render(request, "student/view_result.html", {
        "results": results,
        "student": student,
        "result_summary": result_summary,
    })
    if should_cache(request):
        cache.set(cache_key, response, 180)
    return response


@login_required
def student_enrolled_courses(request):
    """View for students to see their enrolled courses"""
    if request.user.role != "student":
        messages.error(request, "Access denied. Students only.")
        return redirect("account:login")

    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found")
        return redirect("account:login")

    cache_key = make_cache_key("student_portal", student.school_id, f"courses:{student.id}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    enrollments = Enrollment.objects.filter(student=student, is_active=True).select_related('subject__teacher__user',
                                                                                            'subject__department').order_by(
        'subject__name')
    subjects_by_department = enrollments.values('subject__department__name').annotate(count=Count('id'))

    context = {
        'student': student,
        'enrollments': enrollments,
        'total_enrollments': enrollments.count(),
        'subjects_by_department': subjects_by_department,
    }

    response = render(request, 'student/enrolled_courses.html', context)
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

    fees = Fees.objects.filter(student=student, school=school).select_related('fee_structure').order_by('-due_date',
                                                                                                        '-id')

    # Efficient calculation for total balance using pre-existing net_amount logic or Sum/F
    fee_aggregate = fees.aggregate(balance=Sum(F('amount_required') - F('discount') - F('amount_paid')))
    total_balance = fee_aggregate['balance'] or 0

    context = {
        "fees": fees,
        "student": student,
        "school": school,
        "total_balance": total_balance
    }
    return render(request, "student/fees_list.html", context)


@login_required
def view_all_assignment(request):
    """View all assignments published for the student's class and enrolled subjects."""
    if request.user.role != "student":
        messages.error(request, "Access denied. Students only.")
        return redirect("account:login")

    try:
        student = request.user.student_profile
        school = student.school
        student_class = student.student_class
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect("account:login")

    cache_key = make_cache_key("student_portal", school.id, f"assignments:{student.id}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    assignments = Assignment.objects.filter(
        subject__enrollments__student=student,
        subject__school=school,
        student_class=student_class,
        status="published"
    ).select_related('subject', 'teacher__user').order_by('-due_date')

    response = render(request, 'student/assignments.html', {
        'assignments': assignments,
        'student': student
    })
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
            is_overdue = assignment.due_date < timezone.now()
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
    })