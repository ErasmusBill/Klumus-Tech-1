from django.shortcuts import get_object_or_404, render,redirect
from django.contrib import messages
from account.models import Enrollment, ResultSheet, Student, Teacher, Enrollment,Fees,Assignment,Attendance,Announcement,Event,Subject,AssignmentSubmission
from django.db import models
from django.db.models import Q,Avg,Count
from django.utils import timezone
from django.contrib.auth.decorators import login_required
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
    pending_fees = Fees.objects.filter(student=student, paid=False).order_by('due_date')
    total_pending_fees = sum(fee.net_amount() for fee in pending_fees)
    
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
    
    return render(request, 'student/student_dashboard.html', context)

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
    

    results = ResultSheet.objects.filter(student=student).select_related('subject', 'subject__department').order_by('-academic_year', '-term', 'subject__name')
    
    # Calculate summary statistics
    result_summary = {'total_subjects': results.count(),'average_percentage': results.aggregate(avg=models.Avg('percentage'))['avg'] or 0,}
    
    return render(request, "student/view_result.html", {"results": results,"student": student,"result_summary": result_summary,})



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
    
    return render(request, 'student/enrolled_courses.html', context)





@login_required
def list_fees_related(request, student_id):
    # Check authentication and role
    if not request.user.is_authenticated:
        messages.error(request, "Please log in to access this page.")
        return redirect("account:login")
    
    if request.user.role not in ["student", "admin"]:
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")
    
    student = get_object_or_404(Student, id=student_id)
    school = student.school

    if request.user.role == "student":
        if request.user.student_profile.id != student.id:
            messages.error(request, "You can only view your own fees.")
            return redirect("student:student-dashboard")
        
    elif request.user.role == "admin":
        if request.user.managed_school != school:
            messages.error(request, "You can only view fees for students in your school.")
            return redirect("adminservices:admin-dashboard")

    fees = Fees.objects.filter(student=student, school=school).order_by('-due_date')
    
    return render(request, "student/fees_list.html", {"fees": fees, "student": student})



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


    assignments = Assignment.objects.filter(subject__enrollments__student=student,subject__school=school,student_class=student_class,status="published").select_related('subject', 'teacher').order_by('-due_date')

    return render(request, 'student/assignments.html', {
        'assignments': assignments,
        'student': student
    })
    
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
            messages.success(request, "Assignment submitted successfully!")
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