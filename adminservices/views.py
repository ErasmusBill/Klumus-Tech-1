# adminservices/views.py
import logging
from django.contrib import messages
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.conf import settings
from django.views.decorators.cache import never_cache

from account.models import (
     Teacher, CustomUser, Department, School, 
    Student, Parent, Fees, Subject, Announcement, Notification
)
from .forms import (
    AddTeacherForm, AddDepartmentForm, AddStudentForm, 
    AddFeesForm, AddSubjectForm, AnnouncementForm
)
from .utils import *
from .utils import send_announcement_via_email_and_sms_async
from django.template.loader import render_to_string
from django.http import HttpResponse    
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
try:
    from weasyprint import HTML
except ImportError:
    HTML = None

logger = logging.getLogger(__name__)

# ===== DASHBOARD VIEWS =====

@login_required(login_url='account:login')
def admin_dashboard(request):
    """Admin dashboard with school overview and student search"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("account:login")
    
    try:
        school = request.user.managed_school
    except School.DoesNotExist: 
        messages.error(request, "You haven't registered for a school")
        return redirect("account:login")

    # Get basic counts
    students_count = Student.objects.filter(school=school).count()
    teachers_count = Teacher.objects.filter(school=school).count()
    departments_count = Department.objects.filter(school=school).count()
    
    # Handle student search
    students = Student.objects.filter(school=school).select_related('user')
    search_query = None
    
    if request.method == "POST":
        search_query = request.POST.get("search")  
        if search_query:
            students = students.filter(
                Q(user__first_name__icontains=search_query) |
                Q(user__last_name__icontains=search_query) |
                Q(student_id__icontains=search_query) |
                Q(admission_number__icontains=search_query)
            )
            if not students.exists():
                messages.info(request, f"No students found matching '{search_query}'")
        else:
            messages.error(request, "Please enter a search term")
    
    context = {
        "students_count": students_count,
        "departments_count": departments_count,
        "teachers_count": teachers_count,
        "students": students,
        "search_query": search_query
    }
    
    return render(request, 'adminservices/admin_dashboard.html', context)

@never_cache
@login_required(login_url='account:login')
def add_teacher(request):
    """Add a new teacher with async notification handling"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform that action")
        return redirect("adminservices:list-teachers")
    
    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "Your account is not linked to a school.")
        return redirect("adminservices:list-teachers")

    if request.method == "POST":
        form = AddTeacherForm(request.POST, request.FILES, school=school)
        
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Create user account
                    user = CustomUser.objects.create_user(
                        username=form.cleaned_data['username'],
                        email=form.cleaned_data['email'],
                        password=form.cleaned_data['password'],
                        first_name=form.cleaned_data['first_name'],
                        last_name=form.cleaned_data['last_name'],
                        role="teacher",
                        gender=form.cleaned_data['gender'],
                        date_of_birth=form.cleaned_data['date_of_birth'],
                        address=form.cleaned_data['address'],
                        phone_number=form.cleaned_data.get('phone_number', ''),
                    )
                    
                    # Add profile picture if provided
                    if form.cleaned_data.get('profile_picture'):
                        user.profile_picture = form.cleaned_data['profile_picture']
                        user.save()
                    
                    # Create teacher profile
                    teacher = Teacher(
                        user=user,
                        school=school,
                        qualification=form.cleaned_data['qualification'],
                        specialization=form.cleaned_data['specialization'],
                        experience_years=form.cleaned_data['experience_years'],
                        employment_type=form.cleaned_data['employment_type'],
                        hire_date=form.cleaned_data['hire_date'],
                        department=form.cleaned_data.get('department'),
                        salary=form.cleaned_data.get('salary'),
                        bio=form.cleaned_data.get('bio', ''),
                        is_active=True
                    )
                    
                    if form.cleaned_data.get('image'):
                        teacher.image = form.cleaned_data['image']
                    teacher.save()
                    
                    # Send welcome notifications (ASYNC - Won't block)
                    teacher_emails, teacher_phones = get_teacher_contacts(teacher)
                    password = form.cleaned_data.get('password')
                    
                    email_message = (
                        f'Hello {user.first_name},\n\n'
                        f'You have been added as a teacher at {school.name}.\n\n'
                        f'Your login details:\n'
                        f'Username: {user.username}\n'
                        f'Password: {password}\n\n'
                        f'Please log in and change your password after first login.\n\n'
                        f'Best regards,\n{school.name} Administration'
                    )
                    
                    sms_message = (
                        f"Welcome to {school.name}! You've been added as a teacher. "
                        f"Username: {user.username}. Check your email for details."
                    )
                    
                    # Send notifications - emails now async, won't timeout
                    try:
                        notification_results = send_notification(
                            emails=teacher_emails,
                            phones=teacher_phones,
                            subject='Welcome to the School',
                            message=email_message
                        )
                        
                        # Provide feedback based on results
                        if notification_results.get('email_sent') and notification_results.get('sms_sent'): # type: ignore
                            messages.success(request, 
                                f"Teacher added successfully! Welcome notifications queued for {user.email}"
                            )
                        elif notification_results.get('email_sent'): # type: ignore
                            messages.success(request, 
                                f"Teacher added successfully! Welcome email queued for {user.email}"
                            )
                        elif notification_results.get('sms_sent'): # type: ignore
                            messages.success(request, 
                                f"Teacher added successfully! Welcome SMS sent"
                            )
                        else:
                            messages.success(request, 
                                f"Teacher '{user.get_full_name()}' added successfully!"
                            )
                            if notification_results.get('email_error'):
                                logger.warning(f"Email notification failed: {notification_results['email_error']}") # type: ignore
                        
                        logger.info(f"Teacher {user.username} created. Notifications: {notification_results}")
                        
                    except Exception as e:
                        # Don't fail the entire operation if notifications fail
                        logger.error(f"Notification error for teacher {user.username}: {str(e)}")
                        messages.success(request, 
                            f"Teacher '{user.get_full_name()}' added successfully! "
                            f"(Notifications may be delayed)"
                        )
                    
                    return redirect("adminservices:list-teachers")
                    
            except Exception as e:
                # Rollback user creation if teacher creation fails
                if 'user' in locals() and user.pk: # type: ignore
                    user.delete()
                
                logger.error(f"Failed to create teacher: {str(e)}", exc_info=True)
                messages.error(request, f"An error occurred while creating the teacher: {str(e)}")
        else:
            # Display form validation errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = AddTeacherForm(school=school)
    
    return render(request, "adminservices/add_teacher.html", {"form": form})

@login_required(login_url='account:login')
def list_teachers(request):
    """List all teachers with pagination"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("adminservices:list-teachers")
    
    school = request.user.managed_school
    teachers = Teacher.objects.filter(school=school, is_active=True).select_related('user', 'department')
    
    paginator = Paginator(teachers, 50)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    
    return render(request, "adminservices/list-teachers.html", {"page_obj": page_obj})

@login_required(login_url='account:login')
def update_teacher(request, teacher_id):
    """Update teacher information with notification"""
    if request.user.role not in ["admin", "teacher"]:
        messages.error(request, "You are not authorized to perform that action")
        return redirect("adminservices:list-teachers")

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "Your account is not linked to a school.")
        return redirect("adminservices:list-teachers")

    teacher = get_object_or_404(Teacher, id=teacher_id, school=school)
    user = teacher.user

    if request.method == "POST":
        form = AddTeacherForm(request.POST, request.FILES, school=school, instance=teacher)
        form.fields['password'].required = False

        if form.is_valid():
            try:
                # Update user information
                user.first_name = form.cleaned_data['first_name']
                user.last_name = form.cleaned_data['last_name']
                user.email = form.cleaned_data['email']
                user.username = form.cleaned_data['username']
                user.gender = form.cleaned_data['gender']
                user.date_of_birth = form.cleaned_data['date_of_birth']
                user.address = form.cleaned_data['address']
                user.phone_number = form.cleaned_data.get('phone_number', '')

                # Update password if provided
                password = form.cleaned_data.get('password')
                if password:
                    user.set_password(password)

                if 'profile_picture' in request.FILES:
                    user.profile_picture = request.FILES['profile_picture']

                user.save()

                # Update teacher profile
                updated_teacher = form.save(commit=False)
                updated_teacher.school = school
                updated_teacher.save()

                # Send update notification (async)
                try:
                    teacher_emails, teacher_phones = get_teacher_contacts(teacher)
                    
                    email_message = (
                        f"Hello {user.first_name},\n\n"
                        f"Your teacher account at {school.name} has been updated.\n"
                        f"If you changed your password, please use the new one to log in.\n\n"
                        f"Best regards,\n{school.name} Administration"
                    )

                    notification_results = send_notification(
                        emails=teacher_emails,
                        phones=teacher_phones,
                        subject='Your Account Has Been Updated',
                        message=email_message
                    )

                    if notification_results.get('email_sent') or notification_results.get('sms_sent'): # type: ignore
                        messages.success(request, "Teacher updated successfully! Notification sent.")
                    else:
                        messages.success(request, "Teacher updated successfully!")
                        
                except Exception as e:
                    logger.error(f"Notification error: {str(e)}")
                    messages.success(request, "Teacher updated successfully!")

                return redirect("adminservices:list-teachers")

            except Exception as e:
                logger.error(f"Failed to update teacher {teacher_id}: {str(e)}", exc_info=True)
                messages.error(request, f"An error occurred while updating: {str(e)}")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = AddTeacherForm(instance=teacher, school=school)
        form.fields['password'].required = False
        form.fields['password'].initial = ''

    return render(request, "adminservices/edit-teacher.html", {
        "form": form,
        "teacher": teacher
    })

@login_required(login_url='account:login')
def delete_teacher(request, teacher_id):
    """Delete a teacher"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("adminservices:list-teachers")
    
    school = request.user.managed_school
    teacher = get_object_or_404(Teacher, id=teacher_id, school=school)
    
    teacher_name = teacher.user.get_full_name()
    teacher.delete()
    
    messages.success(request, f"Teacher '{teacher_name}' deleted successfully")
    return redirect("adminservices:list-teachers")

@login_required
def teacher_detail(request, teacher_id):
    """View teacher details"""
    
    if request.user.role not in ["admin", "teacher"]:
        messages.error(request, "You are not authorized to perform this action")
        return redirect("adminservices:list-teachers")
  
    if request.user.role == "admin":
        try:
            school = request.user.managed_school
        except School.DoesNotExist:
            messages.error(request, "You are an admin but have no school assigned.")
            return redirect("dashboard") 


    elif request.user.role == "teacher":
        try:
            school = request.user.teacher_profile.school
        except Teacher.DoesNotExist:
            messages.error(request, "Teacher profile not found.")
            return redirect("dashboard")

    teacher = get_object_or_404(Teacher, id=teacher_id, school=school)
    
    return render(request, "adminservices/teacher_detail_edit.html", {"teacher": teacher})

@login_required(login_url='account:login')
def add_department(request):
    """Add a new department"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("adminservices:list-departments")

    try:
        school = request.user.managed_school
    except School.DoesNotExist:
        messages.error(request, "Your account is not linked to any school.")
        return redirect("adminservices:admin-dashboard")

    if request.method == "POST":
        form = AddDepartmentForm(request.POST)
        if form.is_valid():
            department = form.save(commit=False)
            department.school = school
            department.save()
            
            messages.success(request, f"Department '{department.name}' added successfully!")
            return redirect("adminservices:list-departments")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AddDepartmentForm(school=school)

    return render(request, "adminservices/add_department.html", {"form": form})

@login_required(login_url='account:login')
def list_departments(request):
    """List all departments with pagination"""
    if request.user.role != "admin":
        messages.error(request, "Not authorized.")
        return redirect("adminservices:admin-dashboard")
    
    try:
        school = request.user.managed_school 
    except School.DoesNotExist:
        messages.error(request, "No school linked to your account.")
        return redirect("adminservices:admin-dashboard")

    departments = Department.objects.filter(school=school)
    paginator = Paginator(departments, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    
    return render(request, "adminservices/list_department.html", {"page_obj": page_obj})

@login_required(login_url='account:login')
def edit_department(request, department_id):
    """Edit department information"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("adminservices:list-departments")
    
    school = request.user.managed_school
    department = get_object_or_404(Department, id=department_id, school=school)
    
    if request.method == "POST":
        form = AddDepartmentForm(request.POST, instance=department, school=school)
        if form.is_valid():
            department = form.save(commit=False)
            department.school = school
            department.save()
            
            messages.success(request, f"Department '{department.name}' updated successfully!")
            return redirect("adminservices:list-departments")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AddDepartmentForm(instance=department, school=school)

    return render(request, "adminservices/edit_department.html", {"form": form})

@login_required(login_url='account:login')
def delete_department(request, department_id):
    """Delete a department"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("adminservices:list-departments")
    
    school = request.user.managed_school
    department = get_object_or_404(Department, id=department_id, school=school)
    
    department_name = department.name
    department.delete()
    
    messages.success(request, f"Department '{department_name}' deleted successfully")
    return redirect("adminservices:list-departments")

@login_required(login_url='account:login')
def department_detail(request, department_id):
    """View department details"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("adminservices:list-teachers")
    
    school = request.user.managed_school
    department = get_object_or_404(Department, id=department_id, school=school)
    
    return render(request, "adminservices/department-detail.html", {"department": department})

# ===== STUDENT MANAGEMENT VIEWS =====
@login_required(login_url='account:login')
def add_student(request):
    """Add a new student with parent notifications"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login") 

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "Your account is not linked to a school.")
        return redirect("adminservices:admin-dashboard")

    if request.method == "POST":
        form = AddStudentForm(request.POST, request.FILES, school=school)
        if form.is_valid():
            try:
                with transaction.atomic():
                    student = form.save()
                    password = form.cleaned_data.get('password')
                    
                    # Send enrollment notifications
                    try:
                        parent_emails, parent_phones = get_student_parent_contacts(student)
                        
                        # Log contact information for debugging
                        logger.info(f"Student {student.user.get_full_name()} - Emails: {parent_emails}, Phones: {parent_phones}")
                        
                        # Check email configuration
                        email_config_ok, email_config_msg = check_email_config()
                        logger.info(f"Email configuration: {email_config_msg}")
                        
                        # Only send notifications if we have at least one contact method
                        if parent_emails or parent_phones:
                            email_message = (
                                f"Dear Parent/Guardian,\n\n"
                                f"Your child, {student.user.first_name} {student.user.last_name}, "
                                f"has been enrolled at {school.name}.\n\n"
                                f"Please use the following credentials to access their student portal:\n\n"
                                f"Username: {student.user.username}\n"
                                f"Password: {password}\n\n"
                                f"We recommend changing the password after the first login for security.\n\n"
                                f"Best regards,\n"
                                f"{school.name} Administration"
                            )
                            
                            # Use the synchronous notification function
                            notification_results = send_notification(
                                emails=parent_emails,
                                phones=parent_phones,
                                subject=f"Login Details for {student.user.get_full_name()} - {school.name}",
                                message=email_message
                            )
                            
                            # Debug log the notification results
                            logger.info(f"Notification results: {notification_results}")
                            
                            # Provide feedback based on results
                            if notification_results.get('email_sent') and notification_results.get('sms_sent'):
                                messages.success(
                                    request, 
                                    f"Student '{student.user.get_full_name()}' added successfully! "
                                    f"Parents notified via email and SMS."
                                )
                            elif notification_results.get('email_sent'):
                                messages.success(
                                    request, 
                                    f"Student '{student.user.get_full_name()}' added successfully! "
                                    f"Welcome email sent to parents."
                                )
                            elif notification_results.get('sms_sent'):
                                messages.success(
                                    request, 
                                    f"Student '{student.user.get_full_name()}' added successfully! "
                                    f"Welcome SMS sent to parents."
                                )
                            else:
                                messages.success(
                                    request,
                                    f"Student '{student.user.get_full_name()}' created successfully!"
                                )
                                # Log notification errors for debugging
                                if notification_results.get('email_error'):
                                    logger.warning(f"Email notification failed: {notification_results['email_error']}")
                                if notification_results.get('sms_error'):
                                    logger.warning(f"SMS notification failed: {notification_results['sms_error']}")
                        else:
                            # No contact information available
                            messages.success(
                                request,
                                f"Student '{student.user.get_full_name()}' created successfully! "
                                f"(No parent contact information provided for notifications)"
                            )
                            logger.info(f"No contact information available for student {student.user.get_full_name()}")
                        
                    except Exception as e:
                        # Don't fail student creation if notifications fail
                        logger.error(f"Notification error for student {student.user.username}: {str(e)}", exc_info=True)
                        messages.success(
                            request,
                            f"Student '{student.user.get_full_name()}' created successfully! "
                            f"(Notification system encountered an error)"
                        )
                    
                    return redirect("adminservices:list-students")
                    
            except Exception as e:
                logger.error(f"Failed to create student: {str(e)}", exc_info=True)
                messages.error(request, f"An error occurred while creating the student: {str(e)}")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = AddStudentForm(school=school)
 
    return render(request, "adminservices/add_student.html", {
        "form": form,
        "title": "Add New Student"
    })
    
@login_required(login_url='account:login')
def list_students(request):
    """List all students with pagination"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "Unauthorized.")
        return redirect("login")

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "No school assigned.")
        return redirect("adminservices:admin-dashboard")

    students = Student.objects.filter(school=school).select_related('user', 'parent').order_by('-created_at')
    paginator = Paginator(students, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, "adminservices/list_students.html", {
        "page_obj": page_obj,
        "year": 2025  
    })

@login_required(login_url='account:login') 
def student_detail(request, student_id):
    """View student details"""
    student = get_object_or_404(Student, id=student_id, school=request.user.managed_school)
    return render(request, "adminservices/student_detail.html", {"student": student})

@login_required(login_url='account:login')
def edit_student(request, student_id):
    """Edit student information"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("adminservices:list-students")
    
    school = request.user.managed_school
    student = get_object_or_404(
        Student.objects.select_related('user', 'parent'), 
        id=student_id, 
        school=school
    )
    
    if request.method == "POST":
        form = AddStudentForm(request.POST, request.FILES, instance=student, school=school)
        if form.is_valid():
            form.save()
            messages.success(request, "Student updated successfully!")
            return redirect("adminservices:student-detail", student_id=student.id)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AddStudentForm(instance=student, school=school)
    
    return render(request, "adminservices/edit_student.html", {
        "form": form,
        "student": student
    })

@login_required(login_url='account:login')
def delete_student(request, student_id):
    """Delete a student"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("adminservices:list-students")

    school = request.user.managed_school
    student = get_object_or_404(Student, id=student_id, school=school)
    
    student_name = student.user.get_full_name()
    student.delete()
    
    messages.success(request, f"Student '{student_name}' deleted successfully")
    return redirect("adminservices:list-students")

# ===== FEES MANAGEMENT VIEWS =====

@login_required(login_url='account:login')
def add_fees(request):
    """Add new fees with async parent notifications"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "Your account is not linked to a school.")
        return redirect("adminservices:admin-dashboard")

    if request.method == "POST":
        form = AddFeesForm(request.POST, school=school)
        if form.is_valid():
            try:
                with transaction.atomic(): 
                    fee = form.save(commit=False)
                    fee.school = school  
                    fee.save()

                    # Send fee notification (ASYNC)
                    try:
                        student = fee.student
                        parent_emails, parent_phones = get_student_parent_contacts(student)
                        
                        email_message = (
                            f"Dear Parent/Guardian,\n\n"
                            f"A new fee has been added for your child:\n\n"
                            f"Student: {student.user.get_full_name()}\n"
                            f"Fee Type: {fee.get_fee_type_display()}\n"
                            f"Amount: ${fee.amount:.2f}\n"
                            f"Due Date: {fee.due_date}\n"
                            f"Status: {fee.get_status_display()}\n\n"
                            f"Please make payment before the due date.\n\n"
                            f"Thank you,\n"
                            f"{school.name} Administration"
                        )
                        
                        sms_message = (
                            f"New fee for {student.user.first_name}: {fee.get_fee_type_display()} - "
                            f"${fee.amount:.2f} due {fee.due_date}. Check email for details."
                        )
                        
                        notification_results = send_notification(
                            emails=parent_emails,
                            phones=parent_phones,
                            subject=f"New Fee Added for {student.user.get_full_name()} - {school.name}",
                            message=email_message
                        )
                        
                        # Provide feedback
                        if notification_results.get('email_sent') and notification_results.get('sms_sent'):
                            messages.success(request, 
                                f"Fee for '{student.user.get_full_name()}' added successfully! "
                                f"Parents notified."
                            )
                        elif notification_results.get('email_sent'):
                            messages.success(request, 
                                f"Fee for '{student.user.get_full_name()}' added successfully! "
                                f"Email queued for parents."
                            )
                        else:
                            messages.success(request, 
                                f"Fee for '{student.user.get_full_name()}' added successfully!"
                            )
                            
                    except Exception as e:
                        logger.error(f"Notification error: {str(e)}")
                        messages.success(request, 
                            f"Fee for '{student.user.get_full_name()}' added successfully!" # type: ignore
                        )
                    
                    return redirect("adminservices:list-fees")

            except Exception as e:
                logger.error(f"Failed to add fee: {str(e)}", exc_info=True)
                messages.error(request, f"An error occurred while saving: {str(e)}")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AddFeesForm(school=school)
    
    students = Student.objects.filter(school=school, is_active=True).select_related('user')
    return render(request, "adminservices/add_fees.html", {"form": form, "students": students})


@login_required(login_url='account:login')
def edit_fees(request, fee_id):
    """Edit fee information"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    school = request.user.managed_school
    fee = get_object_or_404(Fees, id=fee_id, student__school=school)

    if request.method == "POST":
        form = AddFeesForm(request.POST, instance=fee, school=school)
        if form.is_valid():
            form.save()
            messages.success(request, "Fee updated successfully!")
            return redirect("adminservices:list-fees")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AddFeesForm(instance=fee, school=school)

    return render(request, "adminservices/edit_fees.html", {"form": form, "fee": fee})

@login_required(login_url='account:login')
def list_fees(request):
    """List all fees with pagination"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    school = request.user.managed_school
    fees = Fees.objects.filter(student__school=school).select_related('student__user', 'student__parent').order_by('-created_at')

    paginator = Paginator(fees, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, "adminservices/list_fees.html", {"page_obj": page_obj})

@login_required(login_url='account:login')
def delete_fees(request, fee_id):
    """Delete a fee record"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    school = request.user.managed_school
    fee = get_object_or_404(Fees, id=fee_id, student__school=school)

    if request.method == "POST":
        student_name = fee.student.user.get_full_name()
        fee.delete()
        messages.success(request, f"Fee for '{student_name}' deleted successfully.")
        return redirect("adminservices:list-fees")

    return render(request, "adminservices/confirm_delete.html", {"fee": fee})

# ===== SUBJECT MANAGEMENT VIEWS =====

@login_required(login_url='account:login')
def add_subject(request):
    """Add a new subject"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "No school assigned.")
        return redirect("adminservices:admin-dashboard")

    if request.method == "POST":
        form = AddSubjectForm(request.POST, school=school)
        if form.is_valid():
            subject = form.save(commit=False)
            subject.school = school
            subject.save()
            
            messages.success(request, f"Subject '{subject.name}' added successfully!")
            return redirect("adminservices:list-subjects")
        else:
            logger.warning(f"Subject form errors: {form.errors}")
            messages.error(request, "Please correct the errors below.")
    else:
        form = AddSubjectForm(school=school)

    return render(request, "adminservices/add_subject.html", {"form": form})

@login_required(login_url='account:login')
def list_subjects(request):
    """List all subjects with pagination"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "Unauthorized.")
        return redirect("account:login")

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "No school assigned.")
        return redirect("adminservices:admin-dashboard")

    subjects = Subject.objects.filter(school=school).select_related('teacher__user', 'department').order_by('-created_at')
    paginator = Paginator(subjects, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, "adminservices/list_subjects.html", {"page_obj": page_obj})

@login_required(login_url='account:login')
def subject_detail(request, subject_id):
    """View subject details"""
    school = getattr(request.user, 'managed_school', None)
    subject = get_object_or_404(Subject, id=subject_id, school=school)
    
    return render(request, "adminservices/subject_detail.html", {"subject": subject})

@login_required(login_url='account:login')
def edit_subject(request, subject_id):
    """Edit subject information"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")
    
    school = getattr(request.user, 'managed_school', None)
    subject = get_object_or_404(Subject, id=subject_id, school=school)

    if request.method == "POST":
        form = AddSubjectForm(request.POST, instance=subject, school=school)
        if form.is_valid():
            form.save()
            messages.success(request, "Subject updated successfully!")
            return redirect("adminservices:subject-detail", subject_id=subject.id)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AddSubjectForm(instance=subject, school=school)

    return render(request, "adminservices/edit_subject.html", {
        "form": form,
        "subject": subject
    })

@login_required
def delete_subject(request, subject_id):
    """Delete a subject"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "Unauthorized.")
        return redirect("account:login")

    school = getattr(request.user, 'managed_school', None)
    subject = get_object_or_404(Subject, id=subject_id, school=school)

    name = subject.name
    subject.delete()
    
    messages.success(request, f"Subject '{name}' deleted successfully.")
    return redirect("adminservices:list-subjects")

# ===== ANNOUNCEMENT MANAGEMENT VIEWS =====

@login_required(login_url='account:login')
def manage_announcement(request, pk=None):
    """Create or edit announcements with targeted notification handling"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to manage announcements.")
        return redirect("account:home")

    if not hasattr(request.user, 'managed_school'):
        messages.error(request, "You do not manage any school.")
        return redirect("account:home")

    school = request.user.managed_school

    if pk:
        announcement = get_object_or_404(Announcement, id=pk, school=school)
    else:
        announcement = Announcement(school=school, author=request.user)

    if request.method == "POST":
        form = AnnouncementForm(request.POST, request.FILES, instance=announcement, school=school)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.school = school
            announcement.author = request.user
            
            # Check if announcement is being published (status changed from draft to published)
            is_newly_published = not announcement.published and form.cleaned_data.get('published', False)
            announcement.published = form.cleaned_data.get('published', False)
            
            # Set publish date if being published for the first time
            if is_newly_published and not announcement.publish_date:
                announcement.publish_date = timezone.now()
            
            announcement.save()

            # Send notifications if published
            if announcement.published:
                try:
                    # Get target audience from the form
                    target_audience = form.cleaned_data.get('target_audience', 'all')
                    
                    # Send targeted notifications based on audience
                    if target_audience == 'all':
                        results = send_announcement_via_email_and_sms_async(announcement)
                    else:
                        results = send_targeted_announcement(announcement, target_audience)
                    
                    # Handle notification results
                    if results and results.get('errors'):
                        error_count = len(results['errors'])
                        if error_count > 0:
                            messages.warning(
                                request,
                                f"Announcement published! But {error_count} notification(s) failed. "
                                f"Check logs for details."
                            )
                        else:
                            messages.success(request, "Announcement published successfully!")
                    
                    elif results:
                        notifications_created = results.get('notifications_created', 0)
                        emails_sent = results.get('emails_queued', 0)
                        sms_sent = results.get('sms_sent', 0)
                        
                        # Create detailed success message
                        success_parts = []
                        if notifications_created > 0:
                            success_parts.append(f"{notifications_created} in-app notifications")
                        if emails_sent > 0:
                            success_parts.append(f"{emails_sent} emails")
                        if sms_sent > 0:
                            success_parts.append(f"{sms_sent} SMS")
                        
                        if success_parts:
                            success_message = f"Announcement published! Sent: {', '.join(success_parts)}"
                        else:
                            success_message = "Announcement published! (No recipients found for selected audience)"
                            
                        messages.success(request, success_message)
                        
                    else:
                        messages.success(request, "Announcement published!")
                    
                    logger.info(f"Announcement {announcement.id} sent to {target_audience}. Results: {results}")
                    
                except Exception as e:
                    logger.error(f"Failed to send announcement notifications: {str(e)}", exc_info=True)
                    messages.warning(
                        request,
                        f"Announcement published but notification system encountered an error. "
                        f"Some recipients may not have been notified."
                    )
            else:
                messages.success(request, "Announcement saved as draft.")
                
            return redirect("adminservices:announcement_list")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AnnouncementForm(instance=announcement, school=school)

    return render(request, "adminservices/annoucement_form.html", {
        "form": form,
        "announcement": announcement,
        "is_edit": pk is not None,
    })
    
    
@login_required(login_url='account:login')
def list_announcements(request):
    """Display all announcements for the current admin's school"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to manage announcements.")
        return redirect("account:home")

    if not hasattr(request.user, 'managed_school'):
        messages.error(request, "You do not manage any school.")
        return redirect("account:home")

    school = request.user.managed_school
    announcements = Announcement.objects.filter(school=school).select_related('author').order_by('-created_at')

    return render(request, "adminservices/list_announcements.html", {
        "announcements": announcements
    })

@login_required(login_url='account:login')
def announcement_delete(request, announcement_id):
    """Delete an announcement"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to manage announcements.")
        return redirect("account:home")

    if not hasattr(request.user, 'managed_school'):
        messages.error(request, "You do not manage any school.")
        return redirect("account:home")

    school = request.user.managed_school
    announcement = get_object_or_404(Announcement, id=announcement_id, school=school)
    
    announcement_title = announcement.title
    announcement.delete()
    
    messages.success(request, f"Announcement '{announcement_title}' successfully deleted")
    return redirect("adminservices:announcement_list")

# ===== HELPER FUNCTIONS =====

def _get_academic_year(school):
    """Helper to safely get academic year."""
    return school.get_current_academic_year() if hasattr(school, 'get_current_academic_year') else "2024/2025"

# ===== PRINTING & PDF GENERATION VIEWS =====

@login_required(login_url='account:login')
def print_fee_receipt(request, fee_id):
    """Render HTML version of the fee receipt for printing."""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("adminservices:list-fees")

    school = request.user.managed_school
    fee = get_object_or_404(Fees, id=fee_id, student__school=school)

    # Use existing receipt_number or generate a safe fallback
    receipt_number = fee.receipt_number or f"RCP-{fee.id.hex[:8].upper()}"
    issue_date = timezone.now().strftime('%B %d, %Y')
    academic_year = _get_academic_year(school)
    payment_method = fee.get_payment_method_display() or "Cash" # type: ignore

    context = {
        'school': school,
        'fee': fee,
        'receipt_number': receipt_number,
        'issue_date': issue_date,
        'academic_year': academic_year,
        'payment_method': payment_method,
    }

    return render(request, 'adminservices/fee_receipt.html', context)


@login_required(login_url='account:login')
def print_admission_form(request, student_id):
    """Render HTML version of the admission form for printing."""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("adminservices:list-students")

    school = request.user.managed_school
    student = get_object_or_404(Student, id=student_id, school=school)

    # Use admission_number (e.g., "2025-0042") for traceability
    form_number = f"ADM{timezone.now().strftime('%Y%m%d')}-{student.admission_number}"
    generated_date = timezone.now().strftime('%B %d, %Y')
    academic_year = "2024/2025"

    context = {
        'school': school,
        'student': student,
        'form_number': form_number,
        'generated_date': generated_date,
        'academic_year': academic_year,
    }

    return render(request, 'adminservices/admission_form.html', context)


@login_required(login_url='account:login')
def download_fee_receipt_pdf(request, fee_id):
    """Generate and download a PDF version of the fee receipt."""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("adminservices:list-fees")

    school = request.user.managed_school
    fee = get_object_or_404(Fees, id=fee_id, student__school=school)

    receipt_number = fee.receipt_number or f"RCP-{fee.id.hex[:8].upper()}"
    issue_date = timezone.now().strftime('%B %d, %Y')
    academic_year = "2024/2025"
    payment_method = fee.get_payment_method_display() or "Cash" # type: ignore

    context = {
        'school': school,
        'fee': fee,
        'receipt_number': receipt_number,
        'issue_date': issue_date,
        'academic_year': academic_year,
        'payment_method': payment_method,
    }

    if HTML is None:
        messages.info(request, "PDF generation is not available. Please install WeasyPrint.")
        return redirect('adminservices:print-fee-receipt', fee_id=fee_id)

    try:
        html_string = render_to_string('adminservices/fee_receipt.html', context)
        pdf_file = HTML(string=html_string).write_pdf()

        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="fee_receipt_{receipt_number}.pdf"'
        return response

    except Exception as e:
        messages.error(request, f"Failed to generate PDF: {str(e)}")
        return redirect('adminservices:print-fee-receipt', fee_id=fee_id)


@login_required(login_url='account:login')
def download_admission_form_pdf(request, student_id):
    """Generate and download a PDF version of the admission form."""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("adminservices:list-students")

    school = request.user.managed_school
    student = get_object_or_404(Student, id=student_id, school=school)

    form_number = f"ADM{timezone.now().strftime('%Y%m%d')}-{student.admission_number}"
    generated_date = timezone.now().strftime('%B %d, %Y')
    academic_year = "2024/2025"

    context = {
        'school': school,
        'student': student,
        'form_number': form_number,
        'generated_date': generated_date,
        'academic_year': academic_year,
    }
    

    if HTML is None:
        messages.info(request, "PDF generation is not available. Please install WeasyPrint.")
        return redirect('adminservices:print-admission-form', student_id=student_id)

    try:
        html_string = render_to_string('adminservices/admission_form.html', context)
        pdf_file = HTML(string=html_string).write_pdf()

        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="admission_form_{form_number}.pdf"'
        return response

    except Exception as e:
        messages.error(request, f"Failed to generate PDF: {str(e)}")
        return redirect('adminservices:print-admission-form', student_id=student_id)