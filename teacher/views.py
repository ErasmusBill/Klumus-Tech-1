from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from .forms import BulkResultForm, EditResultForm,AttendanceForm,AssignmentForm
from account.models import ResultSheet, Subject, Student, Teacher,Attendance,Assignment,AssignmentSubmission,PromotionHistory,Enrollment
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.db import models
from django.db.models import Q,Avg,Count
from django.db.models import Count, Q
from django.http import HttpResponse
from django.urls import reverse
import os
from ai_predictor.models import PredictedPerformance
from django.http import JsonResponse
from adminservices.utils import create_bulk_in_app_notifications, create_in_app_notification


def teacher_dashboard(request):
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized to access this page.")
        return redirect("account:login")

    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found.")
        return redirect("account:login")

    # Get teacher's subjects
    subjects = Subject.objects.filter(teacher=teacher, school=school)
    subject_count = subjects.count()
    
    # Get assignments created by teacher
    assignments = Assignment.objects.filter(teacher=teacher, subject__school=school)
    assignment_count = assignments.count()
    
    # Recent assignments
    recent_assignments = assignments.select_related('subject').order_by('-created_at')[:5]
    
    # Pending submissions to grade
    pending_grading_count = AssignmentSubmission.objects.filter(
        assignment__teacher=teacher,
        status__in=['submitted', 'late']
    ).count()
    
    # Simple class count (distinct classes from subjects)
    class_count = subjects.values('subject_class').distinct().count()
    
    # Simple student count
    student_count = Student.objects.filter(
        enrollments__subject__in=subjects,
        is_active=True
    ).distinct().count()

    context = {
        "teacher": teacher,
        "subject_count": subject_count,
        "class_count": class_count,
        "student_count": student_count,
        "assignment_count": assignment_count,
        "recent_assignments": recent_assignments,
        "pending_grading_count": pending_grading_count,
        "teacher_classes": [],  # Empty for now to avoid errors
    }
    
    return render(request, "teacher/teacher_dashboard.html", context)

def my_subjects(request):
    """View that shows teacher's assigned subjects"""
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")

    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found.")
        return redirect("account:login")
    
    # Get subjects with student counts
    subjects = Subject.objects.filter(
        teacher=teacher, 
        school=school
    ).select_related('department').prefetch_related('enrollments')
    
    return render(request, "teacher/my_subjects.html", {
        "subjects": subjects,
        "title": "My Subjects"
    })

@login_required
def enter_bulk_grades(request, subject_id):
    """Teacher enters grades for all students in a subject with manual entry of all three scores."""
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")

    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found.")
        return redirect("account:login")

    # Get the subject and verify teacher has permission
    subject = get_object_or_404(Subject, id=subject_id, school=school, teacher=teacher)

    # Get students enrolled in this subject
    students = Student.objects.filter(school=school,enrollments__subject=subject,is_active=True).select_related('user', 'parent').order_by('user__last_name', 'user__first_name').distinct()

    if not students.exists():
        messages.warning(request, "No students are enrolled in this subject.")
        return redirect("teacher:my-subjects")

    if request.method == "POST":
        form = BulkResultForm(request.POST, students=students)
        if form.is_valid():
            try:
                with transaction.atomic():
                    exam_date = form.cleaned_data['exam_date']
                    academic_year = form.cleaned_data['academic_year']
                    term = form.cleaned_data['term']

                    created_count = 0
                    updated_count = 0
                    emails_sent = 0
                    results_created = []

                    for student in students:
                        class_score_str = request.POST.get(f'class_score_{student.id}', '0') or '0'
                        mid_semester_str = request.POST.get(f'mid_semester_{student.id}', '0') or '0'
                        end_of_term_exams_str = request.POST.get(f'end_of_term_exams_{student.id}', '0') or '0'
                        comment = request.POST.get(f'comment_{student.id}', '')

                        # Convert to Decimal with proper error handling
                        try:
                            class_score = Decimal(class_score_str) if class_score_str.strip() else Decimal('0')
                        except (InvalidOperation, ValueError):
                            class_score = Decimal('0')
                            
                        try:
                            mid_semester = Decimal(mid_semester_str) if mid_semester_str.strip() else Decimal('0')
                        except (InvalidOperation, ValueError):
                            mid_semester = Decimal('0')
                            
                        try:
                            end_of_term_exams = Decimal(end_of_term_exams_str) if end_of_term_exams_str.strip() else Decimal('0')
                        except (InvalidOperation, ValueError):
                            end_of_term_exams = Decimal('0')

                        # Only save if at least one score is provided
                        if class_score > 0 or mid_semester > 0 or end_of_term_exams > 0:
                            # Create or update the result
                            result, created = ResultSheet.objects.update_or_create(
                                student=student,
                                subject=subject,
                                term=term,
                                academic_year=academic_year,
                                defaults={
                                    'class_score': class_score,
                                    'mid_semester': mid_semester,
                                    'end_of_term_exams': end_of_term_exams,
                                    'exam_date': exam_date,
                                    'teacher_comment': comment,
                                }
                            )
                            
                            # Store for email notification
                            results_created.append({
                                'student': student,
                                'result': result,
                                'created': created
                            })
                            
                            if created:
                                created_count += 1
                            else:
                                updated_count += 1

                    # Send email notifications to parents
                    try:
                        emails_sent = send_result_notifications(
                            results_created, subject, term, academic_year, teacher
                        )
                    except Exception as email_error:
                        print(f"Email notification error: {email_error}")
                        # Continue even if emails fail

                    # Create in-app notifications for students
                    for item in results_created:
                        try:
                            student = item['student']
                            result_obj = item['result']
                            create_in_app_notification(
                                user=student.user,
                                title=f"Result posted: {subject.name}",
                                message=f"Your {subject.name} result for {term} {academic_year} is available.",
                                notification_type="result",
                                related_object=result_obj,
                                link=reverse("student:view-result", args=[student.id]),
                            )
                        except Exception:
                            continue

                    # Success message
                    if created_count > 0 or updated_count > 0:
                        messages.success(
                            request,
                            f"Successfully saved {created_count} new and {updated_count} updated results. "
                            f"Notification emails sent to {emails_sent} parents."
                        )
                    else:
                        messages.info(request, "No grades were saved (all scores were zero).")

                    return redirect("teacher:my-subjects")

            except Exception as e:
                messages.error(request, f"An error occurred while saving grades: {str(e)}")
                print(f"Grade saving error: {str(e)}")
        else:
            messages.error(request, "Please correct the errors below.")
            print(f"Form errors: {form.errors}")
    else:
        # GET request - initialize form with current data
        current_year = timezone.now().year
        form = BulkResultForm(
            students=students,
            initial={
                'exam_date': timezone.now().date(),
                'term': "1",
                'academic_year': f"{current_year}/{current_year + 1}"
            }
        )
        
        for student in students:
            try:
                # Try to get existing result for current term/year
                existing_result = ResultSheet.objects.filter(
                    student=student,
                    subject=subject,
                    term=form.initial['term'],
                    academic_year=form.initial['academic_year']
                ).first()
                
                if existing_result:
                    # Convert Decimal to float for form display
                    form.fields[f'class_score_{student.id}'].initial = float(existing_result.class_score)
                    form.fields[f'mid_semester_{student.id}'].initial = float(existing_result.mid_semester)
                    form.fields[f'end_of_term_exams_{student.id}'].initial = float(existing_result.end_of_term_exams)
            except Exception as e:
                print(f"Error loading existing result for {student}: {e}")

    context = {
        "form": form,
        "subject": subject,
        "students": students,
        "title": f"Enter Grades: {subject.name}",
    }
    
    return render(request, "teacher/bulk_grade_entry.html", context)


def send_result_notifications(results_created, subject, term, academic_year, teacher):
    """
    Send email notifications to parents when results are entered/updated.
    Returns the number of emails successfully sent.
    """
    emails_sent = 0
    
    for result_info in results_created:
        student = result_info['student']
        result = result_info['result']
        
        # Get parent emails
        parent_emails = get_parent_emails(student.parent)
        
        if parent_emails:
            try:
                # Prepare email context
                context = {
                    'student': student,
                    'subject': subject,
                    'result': result,
                    'term': term,
                    'academic_year': academic_year,
                    'teacher': teacher,
                    'school': teacher.school,
                }
                
                # Render HTML email
                html_message = render_to_string('teacher/emails/result_notification.html', context)
                plain_message = strip_tags(html_message)
                
                subject_line = f"New Academic Result - {subject.name} - {student.user.get_full_name()}"
                
                # Send email
                send_mail(
                    subject=subject_line,
                    message=plain_message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=parent_emails,
                    html_message=html_message,
                    fail_silently=False,
                )
                
                emails_sent += 1
                print(f"✓ Result notification sent for {student.user.get_full_name()} to {parent_emails}")
                
            except Exception as e:
                print(f"✗ Failed to send email for {student.user.get_full_name()}: {str(e)}")
                # Continue with other emails even if one fails
    
    return emails_sent


def get_parent_emails(parent):
    """
    Extract parent email addresses from parent object.
    Returns a list of valid email addresses.
    """
    emails = []
    
    # Add father's email if available and valid
    if hasattr(parent, 'father_email') and parent.father_email:
        email = parent.father_email.strip()
        if email and '@' in email:
            emails.append(email)
    
    # Add mother's email if available and valid
    if hasattr(parent, 'mother_email') and parent.mother_email:
        email = parent.mother_email.strip()
        if email and '@' in email:
            emails.append(email)
    
    # If no specific parent emails, try to get from user account
    if not emails and hasattr(parent, 'user') and parent.user and parent.user.email:
        email = parent.user.email.strip()
        if email and '@' in email:
            emails.append(email)
    
    return list(set(emails))  

def edit_result(request, result_id):
    """Edit an existing result."""
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized to edit results.")
        return redirect("account:login")

    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found.")
        return redirect("account:login")

    result = get_object_or_404(ResultSheet,id=result_id,subject__teacher=teacher,subject__school=school)

    if request.method == "POST":
        form = EditResultForm(request.POST, instance=result)
        if form.is_valid():
            form.save()
            messages.success(request, "Result updated successfully.")
            return redirect("teacher:my-subjects")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = EditResultForm(instance=result)

    return render(request, "teacher/edit_result.html", {
        "form": form,
        "result": result,
        "title": f"Edit Result - {result.student.user.get_full_name()} ({result.subject.name})"
    })
    
def list_result(request):
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("account:login")
    
    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found")
        return redirect("account:login")
    
    # Filter results through the student's school and teacher's subjects
    results = ResultSheet.objects.filter(
        student__school=school,  # Filter by student's school
        subject__teacher=teacher  # Filter by teacher's subjects
    ).select_related(
        'student__user',
        'subject',
        'subject__department'
    ).order_by('-exam_date', 'student__user__last_name')
    
    return render(request, "teacher/list-result.html", {"results": results})


def delete_result(request, result_id):
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("account:login")
    
    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found")
        return redirect("account:login")
    
    # Filter by student's school and teacher's subjects to ensure authorization
    result = get_object_or_404(
        ResultSheet,
        id=result_id,
        student__school=school,  # Ensure the result belongs to teacher's school
        subject__teacher=teacher  # Ensure the result is for teacher's subject
    )
    
    result.delete()
    messages.success(request, "You have successfully deleted the result")
    return redirect("teacher:list-result")

def mark_attendance(request):
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request,"You are not authorized to perform this action")
        return redirect("account:login")
    
    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except Teacher.DoesNotExist:
        messages.error(request, "Techer with this profile does not exits")
        return redirect("account:login")
    
    if request.method == 'POST':
        form = AttendanceForm(school=school, data=request.POST)
        if form.is_valid():
            attendance = form.save(commit=False)
            attendance.marked_by = teacher.user

            if attendance.attendance_type == 'student':
                attendance.teacher = None
            else:
                attendance.student = None

            # Safety: ensure student/teacher belongs to school
            if attendance.student and attendance.student.school != school:
                messages.error(request, "Selected student does not belong to your school.")
                return render(request, 'attendance/attendance_form.html', {'form': form, 'title': 'Add Attendance'})
            if attendance.teacher and attendance.teacher.school != school:
                messages.error(request, "Selected teacher does not belong to your school.")
                return render(request, 'teacher/add_attendance.html', {'form': form, 'title': 'Add Attendance'})

            try:
                attendance.save()
                messages.success(request, "Attendance record created successfully.")
                return redirect('attendance:attendance_list')
            except Exception as e:
                messages.error(request, f"Error saving attendance: {e}")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AttendanceForm(school=school)

    return render(request, 'teacher/add_attendance.html', {'form': form, 'title': 'Add Attendance'})


@login_required
def attendance_update(request, attendance_id):
    attendance = get_object_or_404(Attendance, id=attendance_id)
    user = request.user


    school = None
    if user.role == "teacher":
        try:
            school = user.teacher_profile.school
        except Teacher.DoesNotExist:
            raise Http404
    elif user.role == "admin":
        try:
            school = user.managed_school
        except AttributeError:
            raise Http404
    else:
        raise Http404

    # Verify attendance belongs to user's school
    if attendance.student and attendance.student.school != school:
        raise Http404
    if attendance.teacher and attendance.teacher.school != school:
        raise Http404

    if request.method == 'POST':
        form = AttendanceForm(school=school, data=request.POST, instance=attendance)
        if form.is_valid():
            updated = form.save(commit=False)
            if updated.attendance_type == 'student':
                updated.teacher = None
            else:
                updated.student = None
            updated.save()
            messages.success(request, "Attendance updated successfully.")
            return redirect('teacher:attendance-list')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AttendanceForm(school=school, instance=attendance)

    return render(request, 'teacher/add_attendance.html', {'form': form, 'title': 'Edit Attendance'})


@login_required
def attendance_delete(request, attendance_id):
    attendance = get_object_or_404(Attendance, id=attendance_id)
    user = request.user

    school = None
    if user.role == "teacher":
        school = getattr(user, 'teacher_profile', None) and user.teacher_profile.school
    elif user.role == "admin":
        school = getattr(user, 'managed_school', None)

    if not school:
        raise Http404

    if (attendance.student and attendance.student.school != school) or \
       (attendance.teacher and attendance.teacher.school != school):
        raise Http404

    if request.method == 'POST':
        attendance.delete()
        messages.success(request, "Attendance record deleted.")
        return redirect('teacher:attendance-list')

    return render(request, 'teacher/attendance_confirm_delete.html', {'attendance': attendance})



@login_required
def attendance_list(request):
    user = request.user
    if user.role == "admin":
        
        school = user.managed_school if hasattr(user, 'managed_school') else None
        if not school:
            messages.error(request, "Admin school not found.")
            return redirect("account:dashboard")
        attendances = Attendance.objects.filter(student__school=school) | Attendance.objects.filter(teacher__school=school)
        
    elif user.role == "teacher":
        try:
            school = user.teacher_profile.school
        except Teacher.DoesNotExist:
            messages.error(request, "Teacher profile not found.")
            return redirect("account:login")
        attendances = Attendance.objects.filter(student__school=school) | Attendance.objects.filter(
            teacher__school=school)
    elif user.role == "student":
        attendances = Attendance.objects.filter(student__user=user)
    else:
        messages.error(request, "You don't have permission to view attendance.")
        return redirect("account:dashboard")

    attendances = attendances.select_related('student__user', 'teacher__user', 'marked_by').order_by('-date')

    return render(request, 'teacher/attendance_list.html', {'attendances': attendances})




@login_required
def teacher_students(request):
    """
    View to fetch all students that the logged-in teacher teaches
    """
    # Check if user is a teacher
    if not hasattr(request.user, 'teacher_profile'):
        messages.error(request, "Access denied. Teacher profile required.")
        return redirect('account:login')
    
    try:
        # Get the teacher profile for the logged-in user
        teacher = get_object_or_404(Teacher, user=request.user)
        
        # Get all subjects taught by this teacher
        subjects_taught = Subject.objects.filter(teacher=teacher)
        
        # Get all students enrolled in these subjects
        students = Student.objects.filter(
            enrollments__subject__in=subjects_taught,
            enrollments__is_active=True
        ).distinct().select_related('user')
        
        # Prepare student data
        students_data = []
        for student in students:
            # Get the subjects this student is taking with this teacher
            student_subjects = subjects_taught.filter(
                enrollments__student=student,
                enrollments__is_active=True
            ).values_list('name', flat=True)
            
            students_data.append({
                'id': student.id,
                'student_id': student.student_id,
                'full_name': student.user.get_full_name(),
                'student_class': student.get_student_class_display(),
                'subjects': list(student_subjects),
                'admission_number': student.admission_number,
                'email': student.user.email,
                'phone': student.mobile_number,
            })
        
        # FIX: Pass the actual subject objects with IDs, not just names
        context = {
            'teacher': teacher,
            'students': students_data,
            'total_students': len(students_data),
            'subjects_taught': subjects_taught,  # Pass the queryset, not just names
        }
        
        return render(request, 'teacher/teacher_students.html', context)
    
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found. Please contact administrator.")
        return redirect('teacher:teacher-dashboard')
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('teacher:teacher-dashboard')

@login_required
def teacher_students_by_subject(request, subject_id=None):
    """
    View to fetch students for a specific subject taught by the teacher
    """
    # Check if user is a teacher
    if not hasattr(request.user, 'teacher_profile'):
        messages.error(request, "Access denied. Teacher profile required.")
        return redirect('account:login')
    
    try:
        teacher = get_object_or_404(Teacher, user=request.user)
        
        if subject_id:
            # Get students for a specific subject
            subject = get_object_or_404(Subject, id=subject_id, teacher=teacher)
            students = Student.objects.filter(
                enrollments__subject=subject,
                enrollments__is_active=True
            ).distinct().select_related('user')
            
            subject_name = subject.name
        else:
            # Get all students across all subjects
            subjects_taught = Subject.objects.filter(teacher=teacher)
            students = Student.objects.filter(
                enrollments__subject__in=subjects_taught,
                enrollments__is_active=True
            ).distinct().select_related('user')
            subject_name = "All Subjects"
        
        context = {
            'teacher': teacher,
            'students': students,
            'subject_name': subject_name,
            'total_students': students.count(),
        }
        
        return render(request, 'teacher/teacher_students_list.html', context)
    
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found.")
        return redirect('teacher:teacher-dashboard')
    except Subject.DoesNotExist:
        messages.error(request, "Subject not found or you don't have permission to access it.")
        return redirect('teacher:teacher-students')
    
    
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
    
    return render(request, "teacher/view_result.html", {"results": results,"student": student,"result_summary": result_summary,})



def add_assignment(request):
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("account:login")

    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found")
        return redirect("account:login")
    
    # Get subjects this teacher teaches
    subjects = Subject.objects.filter(teacher=teacher, school=school)
    if not subjects.exists():
        messages.error(request, "You are not assigned to any subjects. Cannot add assignments.")
        return redirect("teacher:teacher-dashboard")

    if request.method == "POST":
        form = AssignmentForm(school=school, data=request.POST, files=request.FILES)
        if form.is_valid():
            assignment = form.save(commit=False)
            assignment.teacher = teacher
            assignment.status = "published"  
            
            assignment.save()
            
            # Check if any students will see this assignment
            students_in_class = Student.objects.filter(
                school=school,
                student_class=assignment.student_class,
                is_active=True
            )
            enrolled_students = students_in_class.filter(
                enrollments__subject=assignment.subject,
                enrollments__is_active=True
            )

            # Create in-app notifications for enrolled students
            try:
                users = [s.user for s in enrolled_students if s.user_id]
                if users:
                    create_bulk_in_app_notifications(
                        users=users,
                        title=f"New assignment: {assignment.title}",
                        message=f"{assignment.subject.name} assignment has been posted. Due {assignment.due_date}.",
                        notification_type="assignment",
                        related_object=assignment,
                        link=reverse("student:assignment-detail", args=[assignment.id]),
                    )
            except Exception:
                pass
            
            messages.success(request, "Assignment created successfully.")
            return redirect("teacher:assignment-list")
        else:
            messages.error(request, "Please correct the errors below.")
            print("Form errors:", form.errors)
    else:
        form = AssignmentForm(school=school)

    return render(request, 'teacher/add_assignment.html', {
        'form': form, 
        'title': 'Add Assignment',
        'subjects': subjects
    })


def edit_assignment(request, assignment_id):
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except AttributeError:
        messages.error(request, "Teacher profile not found.")
        return redirect("account:login")

    # Ensure the assignment belongs to the teacher AND the subject belongs to the teacher's school
    assignment = get_object_or_404(
        Assignment,
        id=assignment_id,
        teacher=teacher,
        subject__school=school  
    )

    if request.method == "POST":
        form = AssignmentForm(school=school, data=request.POST, files=request.FILES, instance=assignment)
        if form.is_valid():
            form.save()
            messages.success(request, "Assignment updated successfully.")
            return redirect("teacher:assignment-list")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AssignmentForm(school=school, instance=assignment)

    return render(request, 'teacher/add_assignment.html', {
        'form': form,
        'title': 'Edit Assignment'
    })


def list_assignment(request):
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except AttributeError:
        messages.error(request, "Teacher profile not found.")
        return redirect("account:login")

    assignments = Assignment.objects.filter(teacher=teacher,subject__school=school).select_related('subject').order_by('-created_at')

    return render(request, 'teacher/assignment_list.html', {'assignments': assignments})


def delete_assignment(request, assignment_id):
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except AttributeError:
        messages.error(request, "Teacher profile not found.")
        return redirect("account:login")

    assignment = get_object_or_404(Assignment,id=assignment_id,teacher=teacher,subject__school=school  )

    if request.method == 'POST':
        assignment.delete()
        messages.success(request, "Assignment deleted successfully.")
        return redirect('teacher:assignment-list')

    return render(request, 'teacher/assignment_confirm_delete.html', {
        'assignment': assignment
    })




def view_assignment_submissions(request, assignment_id):
    """View all submissions for a specific assignment"""
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except AttributeError:
        messages.error(request, "Teacher profile not found.")
        return redirect("account:login")

    # Get the assignment
    assignment = get_object_or_404(Assignment,id=assignment_id,teacher=teacher,subject__school=school)

    # Get all submissions for this assignment
    submissions = AssignmentSubmission.objects.filter(assignment=assignment).select_related('student__user').order_by('-submission_date')

    # Statistics
    total_students = Student.objects.filter(student_class=assignment.student_class,school=school,is_active=True).count()

    submission_stats = {
        'total': submissions.count(),
        'submitted': submissions.filter(status__in=['submitted', 'graded', 'late']).count(),
        'graded': submissions.filter(status='graded').count(),
        'pending': submissions.filter(status='pending').count(),
        'late': submissions.filter(status='late').count(),
        'not_submitted': total_students - submissions.filter(status__in=['submitted', 'graded', 'late']).count()
    }

    return render(request, 'teacher/assignment_submissions.html', {
        'assignment': assignment,
        'submissions': submissions,
        'submission_stats': submission_stats,
        'total_students': total_students
    })

def download_submission_file(request, submission_id):
    """Download a submission file"""
    if not request.user.is_authenticated or request.user.role != "teacher":
        return HttpResponse("Unauthorized", status=401)

    try:
        teacher = request.user.teacher_profile
        submission = get_object_or_404(
            AssignmentSubmission,
            id=submission_id,
            assignment__teacher=teacher
        )
        
        if submission.submission_file:
            file_path = submission.submission_file.path
            if os.path.exists(file_path):
                with open(file_path, 'rb') as fh:
                    response = HttpResponse(fh.read(), content_type="application/octet-stream")
                    response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
                    return response
            else:
                messages.error(request, "File not found.")
                return redirect('teacher:assignment-submissions', assignment_id=submission.assignment.id)
        else:
            messages.error(request, "No file attached to this submission.")
            return redirect('teacher:assignment-submissions', assignment_id=submission.assignment.id)
            
    except Exception as e:
        messages.error(request, f"Error downloading file: {str(e)}")
        return redirect('teacher:assignment-submissions', assignment_id=submission.assignment.id)

def grade_assignment(request, submission_id):
    """Grade a student's assignment submission"""
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    try:
        teacher = request.user.teacher_profile
        submission = get_object_or_404(
            AssignmentSubmission,
            id=submission_id,
            assignment__teacher=teacher
        )
    except AttributeError:
        messages.error(request, "Teacher profile not found.")
        return redirect("account:login")

    if request.method == "POST":
        marks_obtained = request.POST.get('marks_obtained')
        feedback = request.POST.get('feedback')
        
        try:
            marks_obtained = float(marks_obtained)
            if marks_obtained < 0 or marks_obtained > submission.assignment.total_marks:
                messages.error(request, f"Marks must be between 0 and {submission.assignment.total_marks}")
            else:
                submission.marks_obtained = marks_obtained
                submission.feedback = feedback
                submission.status = 'graded'
                submission.graded_date = timezone.now()
                submission.save()

                # Notify student about grading
                try:
                    create_in_app_notification(
                        user=submission.student.user,
                        title=f"Assignment graded: {submission.assignment.title}",
                        message=f"Your assignment has been graded. Marks: {submission.marks_obtained}/{submission.assignment.total_marks}.",
                        notification_type="assignment",
                        related_object=submission,
                        link=reverse("student:assignment-detail", args=[submission.assignment.id]),
                    )
                except Exception:
                    pass
                
                messages.success(request, "Assignment graded successfully!")
                return redirect('teacher:assignment-submissions', assignment_id=submission.assignment.id)
                
        except ValueError:
            messages.error(request, "Please enter valid marks.")
    
    return render(request, 'teacher/grade_assignment.html', {
        'submission': submission
    })

def bulk_download_submissions(request, assignment_id):
    """Download all submissions for an assignment as a zip file"""
    if not request.user.is_authenticated or request.user.role != "teacher":
        return HttpResponse("Unauthorized", status=401)

    try:
        teacher = request.user.teacher_profile
        assignment = get_object_or_404(
            Assignment,
            id=assignment_id,
            teacher=teacher
        )
        
        submissions = AssignmentSubmission.objects.filter(
            assignment=assignment,
            submission_file__isnull=False
        ).select_related('student__user')
        
        if not submissions.exists():
            messages.error(request, "No files to download.")
            return redirect('teacher:assignment-submissions', assignment_id=assignment_id)
        
        import zipfile
        from io import BytesIO
        
        # Create zip file in memory
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            for submission in submissions:
                if submission.submission_file and os.path.exists(submission.submission_file.path):
                    file_name = f"{submission.student.user.get_full_name()}_{os.path.basename(submission.submission_file.name)}"
                    zip_file.write(submission.submission_file.path, file_name)
        
        zip_buffer.seek(0)
        
        response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{assignment.title}_submissions.zip"'
        return response
        
    except Exception as e:
        messages.error(request, f"Error creating zip file: {str(e)}")
        return redirect('teacher:assignment-submissions', assignment_id=assignment_id)



@login_required
def dashboard(request):
    """
    Show AI prediction summary and risk analysis.
    """
    data = PredictedPerformance.objects.select_related("student", "student__user").all()

    risk_summary = (
        PredictedPerformance.objects
        .values("risk_level")
        .annotate(count=Count("id"))
    )

    return render(request, "teacher/dashboard.html", {
        "data": data,
        "risk_summary": risk_summary,
    })
    
@login_required
def promotion_dashboard(request):
    """Main promotion management dashboard"""
    if request.user.role != "teacher" and request.user.role != "admin":
        messages.error(request, "You are not authorized to access this page.")
        return redirect("account:login")

    try:
        if request.user.role == "teacher":
            teacher = request.user.teacher_profile
            school = teacher.school
        else:  # admin
            school = request.user.managed_school
    except Exception as e:
        messages.error(request, "Profile not found.")
        return redirect("account:login")

    # Get all classes with student counts
    classes_data = []
    for class_choice in Student.CLASS_CHOICES:
        class_code, class_name = class_choice
        student_count = Student.objects.filter(
            school=school,
            student_class=class_code,
            is_active=True
        ).count()
        
        classes_data.append({
            'code': class_code,
            'name': class_name,
            'student_count': student_count
        })

    # Get recent promotion history
    recent_promotions = PromotionHistory.objects.filter(
        student__school=school
    ).select_related('student__user', 'promoted_by').order_by('-promotion_date')[:10]

    context = {
        'classes': classes_data,
        'recent_promotions': recent_promotions,
        'school': school,
        'student_class_keys': Student.CLASS_CHOICES,  
        'title': 'Student Promotion Management'
    }
    
    return render(request, "teacher/promotion_dashboard.html", context)

@login_required
def view_class_students(request, class_name):
    """View students in a specific class for promotion"""
    if request.user.role != "teacher" and request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")

    try:
        if request.user.role == "teacher":
            teacher = request.user.teacher_profile
            school = teacher.school
        else:
            school = request.user.managed_school
    except Exception as e:
        messages.error(request, "Profile not found.")
        return redirect("account:login")

    # Get students in the specified class
    students = Student.objects.filter(
        school=school,
        student_class=class_name,
        is_active=True
    ).select_related('user').order_by('user__last_name', 'user__first_name')

    # Get class progression info
    class_progression = dict(Student.CLASS_CHOICES)
    class_keys = list(class_progression.keys())
    
    try:
        current_index = class_keys.index(class_name)
        next_class = class_keys[current_index + 1] if current_index < len(class_keys) - 1 else None
        next_class_name = class_progression.get(next_class, "Graduation") if next_class else "Graduation"
    except ValueError:
        next_class = None
        next_class_name = "Unknown"

    context = {
        'students': students,
        'current_class': class_name,
        'current_class_display': class_progression.get(class_name, class_name),
        'next_class': next_class,
        'next_class_name': next_class_name,
        'is_final_class': next_class is None,
        'title': f'Students in {class_progression.get(class_name, class_name)}'
    }
    
    return render(request, "teacher/class_students.html", context)

@login_required
def bulk_promote_students(request, class_name):
    """Bulk promote students from one class to another"""
    if request.user.role != "teacher" and request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")

    try:
        if request.user.role == "teacher":
            teacher = request.user.teacher_profile
            school = teacher.school
            promoted_by = request.user
        else:
            school = request.user.managed_school
            promoted_by = request.user
    except Exception as e:
        messages.error(request, "Profile not found.")
        return redirect("account:login")

    if request.method == "POST":
        student_ids = request.POST.getlist('student_ids')
        promotion_action = request.POST.get('promotion_action', 'promote')
        academic_year = request.POST.get('academic_year', school.get_current_academic_year())
        
        if not student_ids:
            messages.error(request, "No students selected for promotion.")
            return redirect('teacher:view-class-students', class_name=class_name)

        # Get class progression
        class_progression = dict(Student.CLASS_CHOICES)
        class_keys = list(class_progression.keys())
        
        try:
            current_index = class_keys.index(class_name)
            if current_index < len(class_keys) - 1:
                next_class = class_keys[current_index + 1]
            else:
                next_class = None
        except ValueError:
            messages.error(request, "Invalid class specified.")
            return redirect('teacher:view-class-students', class_name=class_name)

        promoted_count = 0
        retained_count = 0
        
        try:
            with transaction.atomic():
                for student_id in student_ids:
                    student = Student.objects.get(id=student_id, school=school)
                    
                    if promotion_action == 'promote' and next_class:
                        # Promote student
                        student.previous_class = student.student_class
                        student.student_class = next_class
                        student.promotion_status = 'promoted'
                        student.promoted_to = None
                        student.promotion_date = timezone.now().date()
                        student.save()
                        
                        # Create promotion history record
                        PromotionHistory.objects.create(
                            student=student,
                            from_class=class_name,
                            to_class=next_class,
                            academic_year=academic_year,
                            promotion_date=timezone.now().date(),
                            promoted_by=promoted_by,
                            remarks=f"Bulk promotion from {class_progression.get(class_name)} to {class_progression.get(next_class)}"
                        )
                        
                        # Auto-enroll in new class subjects
                        auto_enroll_student_in_new_class(student, next_class)
                        
                        promoted_count += 1
                        
                    elif promotion_action == 'retain':
                        # Retain student
                        student.promotion_status = 'retained'
                        student.promoted_to = None
                        student.promotion_date = timezone.now().date()
                        student.save()
                        
                        retained_count += 1

                # Success message
                if promotion_action == 'promote':
                    messages.success(
                        request, 
                        f"Successfully promoted {promoted_count} students to {class_progression.get(next_class)}."
                    )
                else:
                    messages.success(
                        request,
                        f"Successfully retained {retained_count} students in {class_progression.get(class_name)}."
                    )
                    
                return redirect('teacher:view-class-students', class_name=class_name)

        except Exception as e:
            messages.error(request, f"An error occurred during promotion: {str(e)}")
            return redirect('teacher:view-class-students', class_name=class_name)

    # GET request - show confirmation page
    students = Student.objects.filter(
        school=school,
        student_class=class_name,
        is_active=True
    ).select_related('user')

    class_progression = dict(Student.CLASS_CHOICES)
    class_keys = list(class_progression.keys())
    
    try:
        current_index = class_keys.index(class_name)
        next_class = class_keys[current_index + 1] if current_index < len(class_keys) - 1 else None
        next_class_name = class_progression.get(next_class, "Graduation") if next_class else "Graduation"
    except ValueError:
        next_class = None
        next_class_name = "Unknown"

    context = {
        'students': students,
        'current_class': class_name,
        'current_class_display': class_progression.get(class_name, class_name),
        'next_class': next_class,
        'next_class_name': next_class_name,
        'academic_year': school.get_current_academic_year(),
        'title': f'Promote Students from {class_progression.get(class_name, class_name)}'
    }
    
    return render(request, "teacher/bulk_promotion.html", context)

def auto_enroll_student_in_new_class(student, new_class):
    """Automatically enroll student in subjects for their new class"""
    try:
        # Get subjects for the new class in the student's school
        new_subjects = Subject.objects.filter(
            school=student.school,
            subject_class=new_class
        )
        
        # Enroll in new subjects
        for subject in new_subjects:
            Enrollment.objects.get_or_create(
                student=student,
                subject=subject,
                defaults={'is_active': True}
            )
        
        # Deactivate enrollments in old class subjects
        old_subjects = Subject.objects.filter(
            school=student.school,
            subject_class=student.previous_class
        )
        
        Enrollment.objects.filter(
            student=student,
            subject__in=old_subjects
        ).update(is_active=False)
        
        return True
    except Exception as e:
        print(f"Error auto-enrolling student {student}: {str(e)}")
        return False

@login_required
def individual_promotion(request, student_id):
    """Promote an individual student"""
    if request.user.role != "teacher" and request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")

    try:
        if request.user.role == "teacher":
            teacher = request.user.teacher_profile
            school = teacher.school
            promoted_by = request.user
        else:
            school = request.user.managed_school
            promoted_by = request.user
    except Exception as e:
        messages.error(request, "Profile not found.")
        return redirect("account:login")

    student = get_object_or_404(Student, id=student_id, school=school)
    
    if request.method == "POST":
        promotion_action = request.POST.get('promotion_action')
        academic_year = request.POST.get('academic_year', school.get_current_academic_year())
        remarks = request.POST.get('remarks', '')
        
        class_progression = dict(Student.CLASS_CHOICES)
        class_keys = list(class_progression.keys())
        
        try:
            current_index = class_keys.index(student.student_class)
            if current_index < len(class_keys) - 1:
                next_class = class_keys[current_index + 1]
            else:
                next_class = None
        except ValueError:
            messages.error(request, "Invalid student class.")
            return redirect('teacher:student-details', student_id=student_id)

        try:
            with transaction.atomic():
                if promotion_action == 'promote' and next_class:
                    # Promote student
                    student.previous_class = student.student_class
                    student.student_class = next_class
                    student.promotion_status = 'promoted'
                    student.promoted_to = None
                    student.promotion_date = timezone.now().date()
                    student.save()
                    
                    # Create promotion history
                    PromotionHistory.objects.create(
                        student=student,
                        from_class=student.previous_class,
                        to_class=next_class,
                        academic_year=academic_year,
                        promotion_date=timezone.now().date(),
                        promoted_by=promoted_by,
                        remarks=remarks or f"Individual promotion to {class_progression.get(next_class)}"
                    )
                    
                    # Auto-enroll in new class
                    auto_enroll_student_in_new_class(student, next_class)
                    
                    messages.success(
                        request, 
                        f"Successfully promoted {student.user.get_full_name()} to {class_progression.get(next_class)}."
                    )
                    
                elif promotion_action == 'retain':
                    # Retain student
                    student.promotion_status = 'retained'
                    student.promoted_to = None
                    student.promotion_date = timezone.now().date()
                    student.save()
                    
                    messages.success(
                        request,
                        f"Successfully retained {student.user.get_full_name()} in {class_progression.get(student.student_class)}."
                    )
                
                elif promotion_action == 'graduate' and not next_class:
                    # Graduate student
                    student.promotion_status = 'graduated'
                    student.promoted_to = None
                    student.promotion_date = timezone.now().date()
                    student.is_active = False  # Optionally deactivate graduated students
                    student.save()
                    
                    messages.success(
                        request,
                        f"Successfully graduated {student.user.get_full_name()}."
                    )

                return redirect('teacher:view-class-students', class_name=student.previous_class or student.student_class)

        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
            return redirect('teacher:individual-promotion', student_id=student_id)

    # GET request - show promotion form
    class_progression = dict(Student.CLASS_CHOICES)
    class_keys = list(class_progression.keys())
    
    try:
        current_index = class_keys.index(student.student_class)
        next_class = class_keys[current_index + 1] if current_index < len(class_keys) - 1 else None
        next_class_name = class_progression.get(next_class, "Graduation") if next_class else "Graduation"
    except ValueError:
        next_class = None
        next_class_name = "Unknown"

    # Get student's academic performance for decision making
    recent_results = ResultSheet.objects.filter(
        student=student
    ).select_related('subject').order_by('-academic_year', '-term')[:10]

    average_percentage = recent_results.aggregate(avg=models.Avg('percentage'))['avg'] or 0

    context = {
        'student': student,
        'recent_results': recent_results,
        'average_percentage': average_percentage,
        'next_class': next_class,
        'next_class_name': next_class_name,
        'can_graduate': next_class is None,
        'academic_year': school.get_current_academic_year(),
        'title': f'Promote {student.user.get_full_name()}'
    }
    
    return render(request, "teacher/individual_promotion.html", context)

@login_required
def promotion_history(request, student_id=None):
    """View promotion history for a student or all students"""
    if request.user.role != "teacher" and request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")

    try:
        if request.user.role == "teacher":
            teacher = request.user.teacher_profile
            school = teacher.school
        else:
            school = request.user.managed_school
    except Exception as e:
        messages.error(request, "Profile not found.")
        return redirect("account:login")

    if student_id:
        # Single student history
        student = get_object_or_404(Student, id=student_id, school=school)
        promotions = PromotionHistory.objects.filter(
            student=student
        ).select_related('promoted_by').order_by('-promotion_date')
        
        context = {
            'promotions': promotions,
            'student': student,
            'title': f'Promotion History - {student.user.get_full_name()}'
        }
        template = "teacher/student_promotion_history.html"
    else:
        # All promotions in school
        promotions = PromotionHistory.objects.filter(
            student__school=school
        ).select_related('student__user', 'promoted_by').order_by('-promotion_date')
        
        context = {
            'promotions': promotions,
            'title': 'School Promotion History'
        }
        template = "teacher/school_promotion_history.html"
    
    return render(request, template, context)

@login_required
def get_student_promotion_data(request, student_id):
    """AJAX endpoint to get student data for promotion decisions"""
    if request.user.role != "teacher" and request.user.role != "admin":
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    try:
        if request.user.role == "teacher":
            school = request.user.teacher_profile.school
        else:
            school = request.user.managed_school
        
        student = Student.objects.get(id=student_id, school=school)
        
        # Get academic performance data
        results = ResultSheet.objects.filter(student=student)
        
        performance_data = {
            'total_subjects': results.count(),
            'average_percentage': results.aggregate(avg=models.Avg('percentage'))['avg'] or 0,
            'subjects_below_50': results.filter(percentage__lt=50).count(),
            'best_subject': results.order_by('-percentage').first(),
            'worst_subject': results.order_by('percentage').first(),
        }
        
        # Get attendance data
        attendance_data = {
            'total_days': 0,  # You would implement this based on your attendance model
            'present_days': 0,
            'attendance_rate': 0,
        }
        
        return JsonResponse({
            'student': {
                'id': student.id,
                'name': student.user.get_full_name(),
                'current_class': student.get_student_class_display(),
                'admission_number': student.admission_number,
            },
            'performance': performance_data,
            'attendance': attendance_data
        })
        
    except Student.DoesNotExist:
        return JsonResponse({'error': 'Student not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
