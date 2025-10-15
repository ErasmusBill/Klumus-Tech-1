from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from .forms import BulkResultForm, EditResultForm,AttendanceForm
from account.models import ResultSheet, Subject, Student, Teacher,Attendance
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.db import models
from django.db.models import Q,Avg,Count


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


    subject_classes = Subject.objects.filter(teacher=teacher,school=school).values_list('subject_class', flat=True).distinct()

    if not subject_classes:
        subject_classes = Student.objects.filter(school=school).values_list('student_class', flat=True).distinct()

    class_options = [
        (code, label)
        for code, label in Attendance.CLASS_CHOICES
        if code in subject_classes
    ]

    return render(request, "teacher/teacher_dashboard.html", {
        "class_options": class_options,
        "teacher": teacher,
    })

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
    subject = get_object_or_404(
        Subject, 
        id=subject_id, 
        school=school, 
        teacher=teacher
    )

    # Get students enrolled in this subject
    students = Student.objects.filter(
        school=school,
        enrollments__subject=subject,
        is_active=True
    ).select_related('user', 'parent').order_by('user__last_name', 'user__first_name').distinct()

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


