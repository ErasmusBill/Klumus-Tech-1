from django.shortcuts import get_object_or_404, render,redirect
from django.contrib import messages
from account.models import Enrollment, ResultSheet, Student, Teacher, Enrollment,Fees,Assignment,Attendance,Announcement,Event,Subject,AssignmentSubmission
from django.db import models
from django.db.models import Q,Avg,Count
from django.utils import timezone
from django.urls import reverse
from adminservices.utils import create_in_app_notification
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from account.cache_utils import make_cache_key, should_cache, bump_cache_version
from .forms import (StudentEnrollmentForm, BulkStudentEnrollmentForm,AssignmentSubmissionForm)


# Create your views here.


@login_required
def student_dashboard(request):
    if request.user.role != "student":
        messages.error(request, "Access denied")
        return redirect("account:login")
    
    try:
        student = request.user.student_profile
        school = student.school
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found")
        return redirect("account:login")

    cache_key = make_cache_key("student_portal", school.id, f"dashboard:{student.id}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response
    
    today = timezone.now().date()
    current_day = timezone.now().strftime('%A').lower()
    
    # Enrolled courses
    enrolled_courses = Enrollment.objects.filter(student=student, is_active=True).select_related('subject__teacher__user', 'subject__department')[:5]
    
    # Attendance
    total_attendance = Attendance.objects.filter(student=student).count()
    present_count = Attendance.objects.filter(student=student, status='present').count()
    attendance_rate = (present_count / total_attendance * 100) if total_attendance > 0 else 0
    
    # Results
    recent_results = ResultSheet.objects.filter(student=student).select_related('subject').order_by('-exam_date')[:6]
    average_grade = recent_results.aggregate(Avg('percentage'))['percentage__avg']
    
    # Fees
    # We filter for anything that is NOT 'paid'
    # Or specifically for 'unpaid' and 'partial'
    pending_fees = Fees.objects.filter(
        student=student,
        status__in=['unpaid', 'partial', 'overdue']
    ).order_by('due_date')
    
    # Announcements
    announcements = Announcement.objects.filter(
        school=student.school,
        published=True,
        target_audience__in=['all', 'students']
    ).order_by('-created_at')[:5]
    
    # Events
    upcoming_events = Event.objects.filter(
        school=student.school,
        start_date__gte=timezone.now(),
        is_public=True
    ).order_by('start_date')[:5]
    
    # ASSIGNMENTS DATA - NEW ADDITIONS
    # Get all assignments for the student
    assignments = Assignment.objects.filter(
        subject__enrollments__student=student,
        subject__school=school,
        status="published"
    ).select_related('subject', 'teacher__user')
    
    # Assignment statistics
    pending_assignments_count = assignments.filter(
        due_date__gte=timezone.now().date()
    ).exclude(
        id__in=AssignmentSubmission.objects.filter(
            student=student,
            status__in=['submitted', 'graded']
        ).values('assignment_id')
    ).count()
    
    overdue_assignments_count = assignments.filter(
        due_date__lt=timezone.now().date()
    ).exclude(
        id__in=AssignmentSubmission.objects.filter(
            student=student,
            status__in=['submitted', 'graded']
        ).values('assignment_id')
    ).count()
    
    submitted_assignments_count = AssignmentSubmission.objects.filter(
        student=student,
        assignment__in=assignments
    ).count()
    
    # Recent assignments (last 10)
    recent_assignments = assignments.order_by('-created_at')[:10]
    
    # Upcoming deadlines (due in next 7 days)
    upcoming_deadlines = assignments.filter(
        due_date__gte=timezone.now().date(),
        due_date__lte=timezone.now().date() + timezone.timedelta(days=7)
    ).exclude(
        id__in=AssignmentSubmission.objects.filter(
            student=student,
            status__in=['submitted', 'graded']
        ).values('assignment_id')
    ).order_by('due_date')[:5]
    
    upcoming_deadlines_count = upcoming_deadlines.count()
    
    context = {
        'student': student,
        'enrolled_courses': enrolled_courses,
        'enrolled_courses_count': enrolled_courses.count(),
        
        # Assignment data
        'pending_assignments_count': pending_assignments_count,
        'overdue_assignments_count': overdue_assignments_count,
        'submitted_assignments_count': submitted_assignments_count,
        'recent_assignments': recent_assignments,
        'upcoming_deadlines': upcoming_deadlines,
        'upcoming_deadlines_count': upcoming_deadlines_count,
        
        # Existing data
        'attendance_rate': attendance_rate,
        'recent_results': recent_results,
        'average_grade': f"{average_grade:.1f}" if average_grade else None,
        'today': today,
        'pending_fees': pending_fees,
        'total_pending_fees': total_pending_fees,
        'announcements': announcements,
        'upcoming_events': upcoming_events,
    }
    
    response = render(request, 'student/student_dashboard.html', context)
    if should_cache(request):
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

    pending_fees = Fees.objects.filter(student=student, paid=False).order_by('due_date')
    total_pending_fees = sum(fee.net_amount() for fee in pending_fees)

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

def view_result(request, student_id):
    """View student results with proper authorization"""

    if not request.user.is_authenticated:
        messages.error(request, "Please login to view results")
        return redirect("account:login")
    
    if request.user.role not in ["admin", "student", "teacher"]:
        messages.error(request, "You are not authorized to perform this action")
        return redirect("account:login")
    

    student = get_object_or_404(Student, id=student_id)
    school = student.school
    

    if request.user.role == "student":
    
        try:
            if request.user.student_profile.id != student.id:
                messages.error(request, "You can only view your own results")
                return redirect("student:student-dashboard")
        except Student.DoesNotExist:
            messages.error(request, "Student profile not found")
            return redirect("account:login")
    
    elif request.user.role == "teacher":
    
        try:
            teacher = request.user.teacher_profile
            if teacher.school != school:
                messages.error(request, "You can only view results for students in your school")
                return redirect("teacher:teacher-dashboard")
        except Teacher.DoesNotExist:
            messages.error(request, "Teacher profile not found")
            return redirect("account:login")
    
    elif request.user.role == "admin":
    
        if request.user.managed_school != school:
            messages.error(request, "You can only view results for students in your school")
            return redirect("adminservices:admin-dashboard")
    

    cache_key = make_cache_key("student_portal", school.id, f"results:{student.id}:{request.user.id}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    results = ResultSheet.objects.filter(student=student).select_related('subject', 'subject__department').order_by('-academic_year', '-term', 'subject__name')
    
    # Calculate summary statistics
    result_summary = {'total_subjects': results.count(),'average_percentage': results.aggregate(avg=models.Avg('percentage'))['avg'] or 0,}
    
    response = render(request, "student/view_result.html", {"results": results,"student": student,"result_summary": result_summary,})
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
    
    # Get active enrollments
    enrollments = Enrollment.objects.filter(student=student,is_active=True).select_related('subject__teacher__user','subject__department').order_by('subject__name')
    
    # Get enrollment statistics
    total_enrollments = enrollments.count()
    subjects_by_department = enrollments.values('subject__department__name').annotate(count=Count('id'))
    
    context = {
        'student': student,
        'enrollments': enrollments,
        'total_enrollments': total_enrollments,
        'subjects_by_department': subjects_by_department,
    }
    
    response = render(request, 'student/enrolled_courses.html', context)
    if should_cache(request):
        cache.set(cache_key, response, 180)
    return response




@login_required(login_url='account:login')
def list_fees_related(request, student_id):
    """
    Lists all fee records for a specific student.
    Strictly enforced for the specific student or an admin of the student's school.
    """
    # 1. Fetch Student and ensure they belong to a school
    student = get_object_or_404(Student.objects.select_related('school', 'user'), id=student_id)
    school = student.school

    # 2. Role-Based Access Control (RBAC)
    if request.user.role == "student":
        # Check if the logged-in user is actually this student
        # Using hasattr to avoid RelatedObjectDoesNotExist errors
        if not hasattr(request.user, 'student_profile') or request.user.student_profile.id != student.id:
            messages.error(request, "Access denied. You can only view your own financial records.")
            return redirect("student:student-dashboard")

    elif request.user.role == "admin":
        # Check if the admin manages the school this student belongs to
        managed_school = getattr(request.user, 'managed_school', None)
        if not managed_school or managed_school != school:
            messages.error(request, "Permission denied. This student belongs to another institution.")
            return redirect("adminservices:admin-dashboard")

    else:
        # Catch-all for roles like 'teacher' or others who shouldn't see money
        messages.error(request, "You do not have permission to view fee records.")
        return redirect("account:login")

    # 3. Optimized Querygit
    # select_related('fee_structure') helps if your template shows template names/amounts
    fees = Fees.objects.filter(
        student=student,
        school=school
    ).select_related('fee_structure').order_by('-due_date', '-id')

    # 4. Contextual data for the template
    context = {
        "fees": fees,
        "student": student,
        "school": school,
        "total_balance": sum(f.balance for f in fees)  # Optional: Quick sum for the UI
    }

    return render(request, "student/fees_list.html", context)

def view_all_assignment(request):
    if not request.user.is_authenticated or request.user.role != "student":
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

    assignments = Assignment.objects.filter(subject__enrollments__student=student,subject__school=school,student_class=student_class,status="published").select_related('subject', 'teacher').order_by('-due_date')

    response = render(request, 'student/assignments.html', {
        'assignments': assignments,
        'student': student
    })
    if should_cache(request):
        cache.set(cache_key, response, 180)
    return response
    
def view_assignment(request, assignment_id):
    if not request.user.is_authenticated or request.user.role != "student":
        messages.error(request, "Access denied. Students only.")
        return redirect("account:login")

    try:
        student = request.user.student_profile
        school = student.school
    except AttributeError:
        messages.error(request, "Student profile not found.")
        return redirect("account:login")


    assignment = get_object_or_404(Assignment,id=assignment_id,subject__school=school,student_class=student.student_class,status="published")

    # Ensure student is enrolled in the subject
    if not assignment.subject.enrollments.filter(student=student, is_active=True).exists():
        messages.error(request, "You are not enrolled in this subject.")
        return redirect("student:student-dashboard")

    # Get or create submission (to show current status)
    submission, created = AssignmentSubmission.objects.get_or_create(
        assignment=assignment,
        student=student,
        defaults={"status": "pending"}
    )

    return render(request, 'student/assignment_detail.html', {
        'assignment': assignment,
        'submission': submission,
    })
    
def submit_assignment(request, assignment_id):
    if not request.user.is_authenticated or request.user.role != "student":
        messages.error(request, "Only students can submit assignments.")
        return redirect("account:login")

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

    # Verify student is enrolled in the subject
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
            submission.status = "submitted" if not assignment.is_overdue() else "late"
            submission.submission_date = timezone.now()
            submission.save()

            # Notify teacher about submission
            try:
                create_in_app_notification(
                    user=assignment.teacher.user,
                    title=f"Assignment submitted: {assignment.title}",
                    message=f"{student.user.get_full_name()} submitted the assignment.",
                    notification_type="assignment",
                    related_object=submission,
                    link=reverse("teacher:assignment-submissions", args=[assignment.id]),
                )
            except Exception:
                pass

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
