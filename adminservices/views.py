# adminservices/views.py
import logging
from decimal import Decimal

from django.contrib import messages
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Count, Sum, ProtectedError, Avg, F
from django.conf import settings
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.core.cache import cache

from account.models import (
    Teacher, CustomUser, Department, School,
    Student, Parent, Fees, Subject, Announcement, Notification, ClassFee,
    Attendance, Timetable, Leave, SchoolClass, Enrollment, ResultSheet
)
from .forms import (
    AddTeacherForm, AddDepartmentForm, AddStudentForm,
    AddFeesForm, AddSubjectForm, AnnouncementForm, ClassFeeForm, AddClassForm, TimetableForm, SchoolSettingsForm
)
from .utils import *
from .utils import send_announcement_via_email_and_sms
from django.template.loader import render_to_string
from django.http import HttpResponse, JsonResponse    
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
import csv
from django.template.loader import render_to_string
from django.utils import timezone
try:
    from weasyprint import HTML
except Exception:
    # On Windows, WeasyPrint can fail with OSError if GTK/Pango libraries are missing.
    HTML = None

logger = logging.getLogger(__name__)

# ===== CACHE HELPERS =====


def _build_partial_bound_form(form_class, request, *, instance=None, **form_kwargs):
    seed_form = form_class(instance=instance, **form_kwargs)
    data = request.POST.copy()

    for field_name in seed_form.fields:
        if field_name in data:
            continue
        value = seed_form[field_name].value()
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            data.setlist(field_name, [str(item) for item in value if item is not None])
        else:
            data[field_name] = str(value)

    return form_class(data, request.FILES, instance=instance, **form_kwargs)

def _cache_version_key(school_id, section: str) -> str:
    return f"cache_version:{section}:{school_id}"

def get_cache_version(school_id, section: str) -> int:
    return cache.get(_cache_version_key(school_id, section), 1)

def bump_cache_version(school_id, section: str) -> None:
    key = _cache_version_key(school_id, section)
    try:
        cache.incr(key)
    except Exception:
        current = cache.get(key, 1)
        cache.set(key, current + 1, None)

def make_cache_key(section: str, school_id, suffix: str = "") -> str:
    version = get_cache_version(school_id, section)
    return f"{section}:{school_id}:v{version}:{suffix}"

def should_cache(request) -> bool:
    return request.method == "GET" and not request.session.get("_messages")

# ===== DASHBOARD VIEWS =====

@login_required(login_url='account:login')
@login_required(login_url='account:login')
def admin_dashboard(request):
    """Admin dashboard with school overview, key metrics, and student search"""
    if getattr(request.user, 'role', None) != "admin":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("account:login")
    
    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "You haven't registered for a school")
        return redirect("account:login")

    search_query = (request.GET.get("search") or request.POST.get("search") or "").strip()
    cache_key = make_cache_key("admin_dashboard", school.id, "default")
    if not search_query and request.method != "POST" and should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    # Core academic & operational counts
    students_count = Student.objects.filter(school=school, is_active=True).count()
    teachers_count = Teacher.objects.filter(school=school, is_active=True).count()
    classes_count = SchoolClass.for_school(school, active_only=True).count()
    subjects_count = Subject.objects.filter(school=school).count()
    departments_count = Department.objects.filter(school=school).count()
    published_announcements_count = Announcement.objects.filter(school=school, published=True).count()
    academic_year = school.get_current_academic_year()

    # Fee collection metrics
    fees_agg = Fees.objects.filter(school=school).aggregate(
        total_collected=Sum('amount_paid'),
        total_required=Sum('amount_required')
    )
    total_fees_collected = fees_agg['total_collected'] or Decimal('0.00')
    total_fees_required = fees_agg['total_required'] or Decimal('0.00')

    # Student distribution by class
    class_counts = (
        Student.objects.filter(school=school, student_class__isnull=False, is_active=True)
        .values("student_class__name")
        .annotate(total=Count("id"))
        .order_by("student_class__order", "student_class__name")
    )
    distribution_labels = [row["student_class__name"] for row in class_counts]
    distribution_data = [row["total"] for row in class_counts]

    # Classes summary for dashboard quick view
    active_classes = SchoolClass.for_school(school, active_only=True)
    classes_summary = []
    for c in active_classes:
        s_count = c.students.filter(school=school, is_active=True).count()
        subj_count = c.subjects.filter(school=school).count()
        classes_summary.append({
            "id": c.id,
            "name": c.name,
            "code": c.code or "-",
            "order": c.order,
            "student_count": s_count,
            "subject_count": subj_count,
            "is_custom": bool(c.school_id),
        })

    # Student search
    students = Student.objects.filter(school=school).select_related('user')
    search_results_count = None

    if search_query:
        students = students.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(student_id__icontains=search_query) |
            Q(admission_number__icontains=search_query) |
            Q(student_class__name__icontains=search_query)
        )
        if not students.exists():
            messages.info(request, f"No students found matching '{search_query}'")
        search_results_count = students.count()

    recent_students = (
        Student.objects.filter(school=school)
        .select_related("user", "student_class")
        .order_by("-created_at")[:6]
    )
    recent_announcements = (
        Announcement.objects.filter(school=school, published=True)
        .select_related("author")
        .order_by("-created_at")[:5]
    )

    context = {
        "school": school,
        "academic_year": academic_year,
        "today_date": timezone.now().strftime("%A, %d %B %Y"),
        "students_count": students_count,
        "teachers_count": teachers_count,
        "classes_count": classes_count,
        "subjects_count": subjects_count,
        "departments_count": departments_count,
        "published_announcements_count": published_announcements_count,
        "total_fees_collected": total_fees_collected,
        "total_fees_required": total_fees_required,
        "classes_summary": classes_summary,
        "students": students,
        "search_query": search_query,
        "search_results_count": search_results_count,
        "distribution_labels": distribution_labels,
        "distribution_data": distribution_data,
        "recent_students": recent_students,
        "recent_announcements": recent_announcements,
    }

    response = render(request, 'adminservices/admin_dashboard.html', context)
    if request.method != "POST" and should_cache(request):
        cache.set(cache_key, response, 300)
    return response


@login_required(login_url='account:login')
def download_admin_report(request):
    if request.user.role != "admin":
        messages.error(request, "Unauthorized.")
        return redirect("account:login")

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "No school assigned.")
        return redirect("adminservices:admin-dashboard")

    students = Student.objects.filter(school=school).select_related("user")
    teachers = Teacher.objects.filter(school=school).select_related("user")
    departments = Department.objects.filter(school=school).order_by("name")
    subjects = Subject.objects.filter(school=school)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="admin_report_{school.slug or "school"}.csv"'

    writer = csv.writer(response)
    writer.writerow(["Report", "Admin Dashboard Export"])
    writer.writerow(["School", school.name])
    writer.writerow(["Generated At", timezone.now().isoformat()])
    writer.writerow([])

    writer.writerow(["Summary"])
    writer.writerow(["Students", students.count()])
    writer.writerow(["Teachers", teachers.count()])
    writer.writerow(["Departments", departments.count()])
    writer.writerow(["Subjects", subjects.count()])
    writer.writerow([])

    writer.writerow(["Students"])
    writer.writerow(["Full Name", "Student ID", "Admission Number", "Class", "Email"])
    for s in students:
        writer.writerow([
            s.user.get_full_name(),
            s.student_id,
            s.admission_number,
            s.get_student_class_display(),
            s.user.email,
        ])
    writer.writerow([])

    writer.writerow(["Teachers"])
    writer.writerow(["Full Name", "Department", "Email"])
    for t in teachers:
        writer.writerow([
            t.user.get_full_name(),
            t.department.name if t.department else "",
            t.user.email,
        ])
    writer.writerow([])

    writer.writerow(["Departments"])
    writer.writerow(["Name", "Code", "Head"])
    for d in departments:
        writer.writerow([d.name, d.code, d.head_of_department])
    writer.writerow([])

    writer.writerow(["Subjects"])
    writer.writerow(["Name", "Department", "Teacher", "Class"])
    for sub in subjects:
        writer.writerow([
            sub.name,
            sub.department.name if sub.department else "",
            sub.teacher.user.get_full_name() if sub.teacher else "",
            sub.get_subject_class_display(),
        ])

    return response

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
                    default_password = generate_default_password()
                    user = CustomUser.objects.create_user(
                        username=form.cleaned_data['username'],
                        email=form.cleaned_data['email'],
                        password=default_password,
                        first_name=form.cleaned_data['first_name'],
                        last_name=form.cleaned_data['last_name'],
                        role="teacher",
                        gender=form.cleaned_data['gender'],
                        date_of_birth=form.cleaned_data['date_of_birth'],
                        address=form.cleaned_data['address'],
                        phone_number=form.cleaned_data.get('phone_number', ''),
                    )
                    
                    # Keep user profile and teacher image aligned for templates that use either field.
                    profile_picture = form.cleaned_data.get("profile_picture")
                    teacher_image = form.cleaned_data.get("image")
                    uploaded_image = teacher_image or profile_picture
                    if uploaded_image:
                        user.profile_picture = uploaded_image
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
                        is_class_teacher=form.cleaned_data.get('is_class_teacher', False),
                        class_teacher_class=form.cleaned_data.get('class_teacher_class') if form.cleaned_data.get('is_class_teacher') else None,
                        is_active=True
                    )
                    
                    if uploaded_image:
                        teacher.image = uploaded_image
                    teacher.save()
                    
                    # Send welcome notifications (ASYNC - Won't block)
                    teacher_emails, teacher_phones = get_teacher_contacts(teacher)
                    password = default_password
                    
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
                            users=[user],
                            subject='Welcome to the School',
                            message=email_message,
                            notification_type="system"
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
                    
                    bump_cache_version(school.id, "teachers")
                    bump_cache_version(school.id, "admin_dashboard")
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
    page_number = request.GET.get("page") or 1
    cache_key = make_cache_key("teachers", school.id, f"page:{page_number}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    teachers = Teacher.objects.filter(school=school, is_active=True).select_related('user', 'department')
    
    paginator = Paginator(teachers, 50)
    page_obj = paginator.get_page(page_number)
    
    response = render(request, "adminservices/list-teachers.html", {"page_obj": page_obj})
    if should_cache(request):
        cache.set(cache_key, response, 300)
    return response

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
        form = _build_partial_bound_form(AddTeacherForm, request, school=school, instance=teacher)
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

                uploaded_image = request.FILES.get('image') or request.FILES.get('profile_picture')
                if uploaded_image:
                    user.profile_picture = uploaded_image

                user.save()

                # Update teacher profile
                updated_teacher = form.save(commit=False)
                updated_teacher.school = school
                if uploaded_image:
                    updated_teacher.image = uploaded_image
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
                        users=[user],
                        subject='Your Account Has Been Updated',
                        message=email_message,
                        notification_type="system"
                    )

                    if notification_results.get('email_sent') or notification_results.get('sms_sent'): # type: ignore
                        messages.success(request, "Teacher updated successfully! Notification sent.")
                    else:
                        messages.success(request, "Teacher updated successfully!")
                        
                except Exception as e:
                    logger.error(f"Notification error: {str(e)}")
                    messages.success(request, "Teacher updated successfully!")

                bump_cache_version(school.id, "teachers")
                bump_cache_version(school.id, "admin_dashboard")
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
    
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("adminservices:list-teachers")

    teacher_name = teacher.user.get_full_name() or teacher.user.username
    user = teacher.user
    teacher.delete()
    if user:
        try:
            user.delete()
        except Exception:
            pass

    bump_cache_version(school.id, "teachers")
    bump_cache_version(school.id, "admin_dashboard")
    messages.success(request, f"Teacher '{teacher_name}' deleted successfully")
    return redirect("adminservices:list-teachers")

@login_required
def teacher_detail(request, teacher_id):
    """View teacher details"""
    if request.user.role not in ["admin", "teacher"]:
        messages.error(request, "You are not authorized to perform this action")
        return redirect("adminservices:list-teachers")

    teacher_profile = getattr(request.user, "teacher_profile", None)

    if request.user.role == "admin":
        try:
            school = request.user.managed_school
        except School.DoesNotExist:
            messages.error(request, "You are an admin but have no school assigned.")
            return redirect("adminservices:admin-dashboard")
        back_url = reverse("adminservices:list-teachers")
        back_label = "Teachers"
        show_edit_button = True
        show_salary = True
    elif request.user.role == "teacher":
        if not teacher_profile:
            messages.error(request, "Teacher profile not found.")
            return redirect("teacher:teacher-dashboard")

        if teacher_profile.id != teacher_id:
            messages.error(request, "You can only view your own profile.")
            return redirect("adminservices:teacher-detail", teacher_id=teacher_profile.id)

        school = teacher_profile.school
        back_url = reverse("teacher:teacher-dashboard")
        back_label = "Dashboard"
        show_edit_button = False
        show_salary = False
    else:
        messages.error(request, "You are not authorized to perform this action")
        return redirect("adminservices:list-teachers")

    teacher = get_object_or_404(
        Teacher.objects.select_related("user", "department", "school"),
        id=teacher_id,
        school=school,
    )

    subjects_qs = teacher.subjects.select_related("department").order_by("-created_at")
    timetables_qs = teacher.timetables.select_related("subject", "department").order_by("day_of_week", "start_time")
    attendance_qs = teacher.attendance.select_related("marked_by").order_by("-date", "-created_at")
    leaves_qs = teacher.leaves.select_related("approved_by").order_by("-created_at")

    subject_count = subjects_qs.count()
    timetable_count = timetables_qs.count()
    class_count = timetables_qs.values("student_class").distinct().count()
    attendance_total = attendance_qs.count()
    present_count = attendance_qs.filter(status="present").count()
    absent_count = attendance_qs.filter(status="absent").count()
    late_count = attendance_qs.filter(status="late").count()
    excused_count = attendance_qs.filter(status="excused").count()
    sick_count = attendance_qs.filter(status="sick").count()
    attendance_rate = round((present_count / attendance_total) * 100, 1) if attendance_total else 0
    leave_count = leaves_qs.count()
    pending_leave_count = leaves_qs.filter(status="pending").count()
    approved_leave_count = leaves_qs.filter(status="approved").count()
    
    return render(request, "adminservices/teacher_detail.html", {
        "teacher": teacher,
        "school": school,
        "back_url": back_url,
        "back_label": back_label,
        "show_edit_button": show_edit_button,
        "show_salary": show_salary,
        "subject_count": subject_count,
        "timetable_count": timetable_count,
        "class_count": class_count,
        "attendance_total": attendance_total,
        "attendance_rate": attendance_rate,
        "present_count": present_count,
        "absent_count": absent_count,
        "late_count": late_count,
        "excused_count": excused_count,
        "sick_count": sick_count,
        "leave_count": leave_count,
        "pending_leave_count": pending_leave_count,
        "approved_leave_count": approved_leave_count,
        "recent_subjects": subjects_qs[:6],
        "recent_timetables": timetables_qs[:8],
        "recent_attendance": attendance_qs[:6],
        "recent_leaves": leaves_qs[:5],
    })

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
            
            bump_cache_version(school.id, "departments")
            bump_cache_version(school.id, "admin_dashboard")
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

    page_number = request.GET.get("page") or 1
    cache_key = make_cache_key("departments", school.id, f"page:{page_number}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    departments = Department.objects.filter(school=school).order_by("name")
    paginator = Paginator(departments, 25)
    page_obj = paginator.get_page(page_number)

    response = render(request, "adminservices/list_department.html", {"page_obj": page_obj})
    if should_cache(request):
        cache.set(cache_key, response, 300)
    return response

@login_required(login_url='account:login')
def edit_department(request, department_id):
    """Edit department information"""
    if getattr(request.user, 'role', None) != "admin":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("adminservices:list-departments")
    
    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "No school linked to your account.")
        return redirect("adminservices:list-departments")

    department = get_object_or_404(Department, id=department_id, school=school)
    
    if request.method == "POST":
        form = _build_partial_bound_form(AddDepartmentForm, request, school=school, instance=department)
        if form.is_valid():
            department = form.save(commit=False)
            department.school = school
            department.save()
            
            bump_cache_version(school.id, "departments")
            bump_cache_version(school.id, "admin_dashboard")
            messages.success(request, f"Department '{department.name}' updated successfully!")
            return redirect("adminservices:list-departments")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AddDepartmentForm(instance=department, school=school)

    return render(request, "adminservices/edit_department.html", {"form": form, "department": department})

@login_required(login_url='account:login')
def delete_department(request, department_id):
    """Delete a department"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("adminservices:list-departments")
    
    school = request.user.managed_school
    department = get_object_or_404(Department, id=department_id, school=school)
    
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("adminservices:list-departments")

    department_name = department.name
    department.delete()

    bump_cache_version(school.id, "departments")
    bump_cache_version(school.id, "admin_dashboard")
    messages.success(request, f"Department '{department_name}' deleted successfully")
    return redirect("adminservices:list-departments")

@login_required(login_url='account:login')
def department_detail(request, department_id):
    """View department details"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "You are an admin but have no school assigned.")
        return redirect("adminservices:admin-dashboard")

    department = get_object_or_404(
        Department.objects.select_related('school'),
        id=department_id,
        school=school
    )

    teachers = department.teachers.select_related('user', 'class_teacher_class').order_by('user__first_name', 'user__last_name')
    subjects = department.subjects.select_related('teacher__user', 'subject_class').order_by('name')

    hod_teacher = None
    if department.head_of_department:
        hod_query = department.head_of_department.strip().lower()
        for t in teachers:
            full_name = t.user.get_full_name().strip().lower()
            if full_name and (full_name in hod_query or hod_query in full_name):
                hod_teacher = t
                break

    context = {
        "department": department,
        "teachers": teachers,
        "subjects": subjects,
        "hod_teacher": hod_teacher,
        "total_teachers": teachers.count(),
        "total_subjects": subjects.count(),
        "total_students": department.number_of_students,
    }

    return render(request, "adminservices/department_detail.html", context)

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
                    password = getattr(student, "generated_password", None) or "Please reset on first login"
                    
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
                                users=[student.user],
                                subject=f"Login Details for {student.user.get_full_name()} - {school.name}",
                                message=email_message,
                                notification_type="system"
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
                    
                    bump_cache_version(school.id, "students")
                    bump_cache_version(school.id, "admin_dashboard")
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
        return redirect("account:login")

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "No school assigned.")
        return redirect("adminservices:admin-dashboard")

    page_number = request.GET.get('page') or 1
    cache_key = make_cache_key("students", school.id, f"page:{page_number}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    students = Student.objects.filter(school=school).select_related('user', 'parent').order_by('-created_at')
    paginator = Paginator(students, 10)
    page_obj = paginator.get_page(page_number)

    response = render(request, "adminservices/list_students.html", {
        "page_obj": page_obj,
        "year": timezone.now().year,
    })
    if should_cache(request):
        cache.set(cache_key, response, 300)
    return response

@login_required(login_url='account:login')
def student_detail(request, student_id):
    """View student details with full academic and financial profile"""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")
    student = get_object_or_404(
        Student.objects.select_related('user', 'parent', 'school', 'student_class', 'previous_class'),
        id=student_id,
        school=request.user.managed_school
    )

    # Enrollments
    enrollments = Enrollment.objects.filter(student=student, is_active=True).select_related('subject__teacher__user', 'subject__department')
    enrollments_count = enrollments.count()

    # Attendance
    total_attendance = Attendance.objects.filter(student=student).count()
    present_count = Attendance.objects.filter(student=student, status='present').count()
    attendance_rate = (present_count / total_attendance * 100) if total_attendance > 0 else 0

    # Financial status
    pending_fees = Fees.objects.filter(student=student, status__in=['unpaid', 'partial', 'overdue']).order_by('due_date')
    fee_aggregate = pending_fees.aggregate(total=Sum(F('amount_required') - F('discount') - F('amount_paid')))
    total_pending_fees = fee_aggregate['total'] or 0

    # Recent Results
    recent_results = ResultSheet.objects.filter(student=student).select_related('subject').order_by('-exam_date')[:6]
    average_grade = recent_results.aggregate(Avg('percentage'))['percentage__avg']

    return render(request, "adminservices/student_detail.html", {
        "student": student,
        "enrollments_count": enrollments_count,
        "enrolled_courses": enrollments[:6],
        "attendance_rate": round(attendance_rate, 1),
        "total_attendance": total_attendance,
        "present_count": present_count,
        "pending_fees": pending_fees[:5],
        "total_pending_fees": total_pending_fees,
        "recent_results": recent_results,
        "average_grade": round(average_grade, 1) if average_grade else None,
    })


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
        form = _build_partial_bound_form(AddStudentForm, request, school=school, instance=student)
        if form.is_valid():
            form.save()
            bump_cache_version(school.id, "students")
            bump_cache_version(school.id, "admin_dashboard")
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
    
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("adminservices:list-students")

    student_name = student.user.get_full_name()
    student.delete()

    bump_cache_version(school.id, "students")
    bump_cache_version(school.id, "admin_dashboard")
    messages.success(request, f"Student '{student_name}' deleted successfully")
    return redirect("adminservices:list-students")

# ===== FEES MANAGEMENT VIEWS =====
@login_required(login_url='account:login')
def create_fee_structure(request):
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    # Use 'managed_school' which is the correct attribute for your CustomUser
    school = getattr(request.user, 'managed_school', None)

    if not school:
        messages.error(request, "Your account is not linked to a school.")
        return redirect("adminservices:admin-dashboard")

    current_academic_year = school.get_current_academic_year()
    fee_structures_count = ClassFee.objects.filter(school=school).count()
    recent_structures = (
        ClassFee.objects.filter(school=school)
        .order_by("-academic_year", "student_class", "fee_type")[:6]
    )

    if request.method == 'POST':
        # Change request.user.school to school
        form = ClassFeeForm(request.POST, school=school)
        if form.is_valid():
            fee_struct = form.save(commit=False)
            fee_struct.school = school  # Change request.user.school to school
            fee_struct.save()
            messages.success(request, "Fee structure created successfully!")
            return redirect('adminservices:fee_structure_list')
    else:
        # Change request.user.school to school
        form = ClassFeeForm(school=school, initial={'academic_year': current_academic_year})

    return render(request, 'adminservices/fees_configuration.html', {
        'form': form,
        'school': school,
        'current_academic_year': current_academic_year,
        'fee_structures_count': fee_structures_count,
        'recent_structures': recent_structures,
    })


@login_required(login_url='account:login')
@require_GET
def fetch_fee_structure_amount(request):
    if request.user.role != "admin":
        return JsonResponse({"found": False, "message": "Unauthorized."}, status=403)

    school = getattr(request.user, 'managed_school', None)
    if not school:
        return JsonResponse({"found": False, "message": "School context not found."}, status=400)

    student_class = request.GET.get("student_class")
    fee_type = request.GET.get("fee_type")

    if not student_class or not fee_type:
        return JsonResponse({
            "found": False,
            "message": "Select a class and fee type first.",
        }, status=400)

    class_fee = (
        ClassFee.objects.filter(
            school=school,
            student_class=student_class,
            fee_type=fee_type,
        )
        .order_by("-academic_year", "-term", "-id")
        .first()
    )

    if class_fee:
        return JsonResponse({
            "found": True,
            "amount": str(class_fee.amount),
            "source": "class_fee",
            "source_label": f"{class_fee.get_student_class_display()} - {class_fee.get_fee_type_display()}",
            "academic_year": class_fee.academic_year,
            "term": class_fee.get_term_display(),
        })

    fee_record = (
        Fees.objects.filter(
            school=school,
            student_class=student_class,
            fee_type=fee_type,
        )
        .order_by("-created_at", "-id")
        .first()
    )

    if fee_record:
        return JsonResponse({
            "found": True,
            "amount": str(fee_record.amount_required),
            "source": "fee_record",
            "source_label": f"{fee_record.get_fee_type_display()} bill",
            "academic_year": fee_record.academic_year,
            "term": fee_record.get_term_display(),
        })

    return JsonResponse({
        "found": False,
        "message": "No saved amount found for this class and fee type.",
    })


from django.utils import timezone


@login_required(login_url='account:login')
def add_fees(request):
    """Add or update fees with strict Decimal math for installment support."""
    if request.user.role != "admin":
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
                    # 1. Strict Data Extraction
                    student = form.cleaned_data['student']
                    fee_structure = form.cleaned_data.get('fee_structure')
                    fee_type = form.cleaned_data['fee_type']

                    # Prevent Decimal vs Float crash by casting explicitly
                    new_payment = Decimal(str(form.cleaned_data.get('amount_paid') or 0))
                    req_amt = Decimal(str(form.cleaned_data.get('amount_required') or 0))
                    discount = Decimal(str(form.cleaned_data.get('discount') or 0))

                    # Logic for Academic Year/Term
                    academic_year = fee_structure.academic_year if fee_structure else "2025/2026"
                    term = fee_structure.term if fee_structure else "Term 1"

                    # 2. INSTALLMENT LOGIC
                    # We use get_or_create to find if this specific fee (e.g. Tuition for Term 1) exists
                    fee, created = Fees.objects.get_or_create(
                        school=school,
                        student=student,
                        fee_type=fee_type,
                        academic_year=academic_year,
                        term=term,
                        defaults={
                            'fee_structure': fee_structure,
                            'amount_required': req_amt,
                            'discount': discount,
                            'due_date': form.cleaned_data.get('due_date') or timezone.now().date(),
                            'notes': form.cleaned_data.get('notes') or "Initial record."
                        }
                    )

                    if not created:
                        # INSTALLMENT: Add the new payment to the existing total
                        # This prevents duplicate rows in your database
                        fee.amount_paid += new_payment

                        payment_note = form.cleaned_data.get('notes') or "Installment payment"
                        fee.notes += f"\n[{timezone.now().date()}] Paid ₵{new_payment}: {payment_note}"

                        # Optionally update due_date or discount if changed in form
                        if form.cleaned_data.get('due_date'):
                            fee.due_date = form.cleaned_data.get('due_date')
                    else:
                        # NEW RECORD
                        fee.amount_paid = new_payment

                    # Save triggers the status calculation (Paid, Partial, Unpaid) in the model
                    fee.save()

                    # 3. Parent Notification Logic
                    try:
                        parent_emails, parent_phones = get_student_parent_contacts(student)

                        # Context-aware messaging
                        subject_line = f"Payment Received: {student.user.get_full_name()}" if new_payment > 0 else f"New Fee Assigned: {student.user.get_full_name()}"

                        email_message = (
                            f"Dear Parent/Guardian,\n\n"
                            f"A transaction has been recorded for {student.user.get_full_name()}.\n\n"
                            f"Fee Category: {fee.get_fee_type_display()}\n"
                            f"Total Bill: ₵{fee.amount_required - fee.discount:.2f}\n"
                            f"Payment Made Today: ₵{new_payment:.2f}\n"
                            f"Total Paid to Date: ₵{fee.amount_paid:.2f}\n"
                            f"--- REMAINING BALANCE: ₵{fee.balance:.2f} ---\n\n"
                            f"Due Date: {fee.due_date}\n"
                            f"Status: {fee.get_status_display()}\n\n"
                            f"Thank you,\n{school.name} Finance Dept."
                        )

                        send_notification(
                            emails=parent_emails,
                            phones=parent_phones,
                            users=[student.user],
                            subject=subject_line,
                            message=email_message,
                            notification_type="fee"
                        )

                    except Exception as noti_err:
                        # Log but don't crash the transaction if email fails
                        logger.error(f"Notification failed: {str(noti_err)}")

                    messages.success(request,
                                     f"Successfully recorded ₵{new_payment} for {student.user.get_full_name()}.")
                    return redirect("adminservices:list-fees")

            except Exception as e:
                logger.error(f"Error in add_fees: {str(e)}", exc_info=True)
                messages.error(request, f"Database Error: {str(e)}")
    else:
        form = AddFeesForm(school=school)

    return render(request, "adminservices/add_fees.html", {"form": form})

@login_required(login_url='account:login')
def edit_fees(request, fee_id):
    """Edit existing fee and recalculate balances"""
    school = request.user.managed_school
    # Ensure the fee belongs to this school
    fee = get_object_or_404(Fees, id=fee_id, school=school)

    if request.method == "POST":
        form = AddFeesForm(request.POST, instance=fee, school=school)
        if form.is_valid():
            form.save() # This triggers the model logic to update status/balance
            bump_cache_version(school.id, "fees")
            messages.success(request, f"Fee for {fee.student.user.get_full_name()} updated.")
            return redirect("adminservices:list-fees")
    else:
        form = AddFeesForm(instance=fee, school=school)

    return render(request, "adminservices/edit_fees.html", {"form": form, "fee": fee})


from django.db.models import Sum, F

@login_required(login_url='account:login')
def list_fee_structures(request):
    """List all standard fee templates created for the school"""
    if request.user.role != "admin":
        messages.error(request, "Access denied.")
        return redirect("account:login")

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "No school associated with this account.")
        return redirect("adminservices:admin-dashboard")

    # Fetch all structures, ordering by year and class for readability
    structures = ClassFee.objects.filter(school=school).order_by('-academic_year', 'student_class')

    return render(request, 'adminservices/list_fee_structures.html', {
        'structures': structures,
        'school': school
    })


@login_required(login_url='account:login')
def list_fees(request):
    """List all fees with grouped class totals, summary KPI cards, filtering, and pagination"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "You are an admin but have no school assigned.")
        return redirect("adminservices:admin-dashboard")

    # 1. Calculate Grouped Stats (Totals per Class) with human-readable class names
    raw_class_summaries = (
        Fees.objects.filter(school=school)
        .values('student_class__id', 'student_class__name', 'student_class__code', 'student_class__order')
        .annotate(
            total_billed=Sum(F('amount_required') - F('discount')),
            total_paid=Sum('amount_paid'),
            total_owing=Sum(F('amount_required') - F('discount') - F('amount_paid')),
            student_count=Count('student', distinct=True)
        )
        .order_by('student_class__order', 'student_class__name')
    )

    class_summaries = []
    total_billed_all = Decimal('0.00')
    total_paid_all = Decimal('0.00')
    total_owing_all = Decimal('0.00')

    for s in raw_class_summaries:
        billed = s.get('total_billed') or Decimal('0.00')
        paid = s.get('total_paid') or Decimal('0.00')
        owing = s.get('total_owing') or Decimal('0.00')
        rate = round((paid / billed * 100) if billed > 0 else Decimal('0.00'), 1)
        name = s.get('student_class__name') or "General / Unassigned"

        class_summaries.append({
            'class_id': str(s.get('student_class__id') or ''),
            'class_name': name,
            'class_code': s.get('student_class__code') or "",
            'total_billed': billed,
            'total_paid': paid,
            'total_owing': owing,
            'collection_rate': rate,
            'student_count': s.get('student_count') or 0,
        })

        total_billed_all += billed
        total_paid_all += paid
        total_owing_all += owing

    overall_rate = round((total_paid_all / total_billed_all * 100) if total_billed_all > 0 else Decimal('0.00'), 1)

    # 2. Filters & Search
    status_filter = request.GET.get('status', '').strip().lower()
    search_query = request.GET.get('q', '').strip()
    class_filter = request.GET.get('class_id', '').strip()

    fees_qs = Fees.objects.filter(school=school).select_related(
        'student__user', 'student__student_class', 'fee_structure', 'student_class'
    )

    if status_filter:
        fees_qs = fees_qs.filter(status=status_filter)
    if class_filter:
        fees_qs = fees_qs.filter(student_class_id=class_filter)
    if search_query:
        fees_qs = fees_qs.filter(
            Q(student__user__first_name__icontains=search_query) |
            Q(student__user__last_name__icontains=search_query) |
            Q(student__student_id__icontains=search_query) |
            Q(fee_type__icontains=search_query)
        )

    fees_list = fees_qs.order_by('-created_at')

    # Pagination
    paginator = Paginator(fees_list, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    available_classes = school.classes.filter(is_active=True).order_by('order', 'name')

    context = {
        "page_obj": page_obj,
        "class_summaries": class_summaries,
        "total_billed_all": total_billed_all,
        "total_paid_all": total_paid_all,
        "total_owing_all": total_owing_all,
        "overall_rate": overall_rate,
        "available_classes": available_classes,
        "selected_status": status_filter,
        "selected_class": class_filter,
        "search_query": search_query,
    }
    return render(request, "adminservices/list_fees.html", context)
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
        bump_cache_version(school.id, "fees")
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
            
            bump_cache_version(school.id, "subjects")
            bump_cache_version(school.id, "admin_dashboard")
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

    page_number = request.GET.get('page') or 1
    cache_key = make_cache_key("subjects", school.id, f"page:{page_number}")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    subjects = Subject.objects.filter(school=school).select_related('teacher__user', 'department').order_by('-created_at')
    paginator = Paginator(subjects, 10)
    page_obj = paginator.get_page(page_number)

    response = render(request, "adminservices/list_subjects.html", {"page_obj": page_obj})
    if should_cache(request):
        cache.set(cache_key, response, 300)
    return response

@login_required(login_url='account:login')
def subject_detail(request, subject_id):
    """View subject details"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "You are an admin but have no school assigned.")
        return redirect("adminservices:admin-dashboard")

    subject = get_object_or_404(
        Subject.objects.select_related('department', 'teacher__user', 'subject_class', 'school'),
        id=subject_id,
        school=school
    )

    enrollments = (
        subject.enrollments.filter(is_active=True)
        .select_related('student__user', 'student__student_class')
        .order_by('student__user__first_name', 'student__user__last_name')
    )

    assignments = (
        subject.assignments.all()
        .select_related('teacher__user')
        .order_by('-created_at')[:20]
    )

    timetables = (
        subject.timetables.filter(school=school)
        .order_by('day_of_week', 'start_time')
    )

    results_count = subject.results.count()

    context = {
        "subject": subject,
        "enrollments": enrollments,
        "enrolled_count": enrollments.count(),
        "assignments": assignments,
        "assignments_count": subject.assignments.count(),
        "timetables": timetables,
        "timetables_count": timetables.count(),
        "results_count": results_count,
    }
    return render(request, "adminservices/subject_detail.html", context)

@login_required(login_url='account:login')
def edit_subject(request, subject_id):
    """Edit subject information"""
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")
    
    school = getattr(request.user, 'managed_school', None)
    subject = get_object_or_404(Subject, id=subject_id, school=school)

    if request.method == "POST":
        form = _build_partial_bound_form(AddSubjectForm, request, school=school, instance=subject)
        if form.is_valid():
            form.save()
            bump_cache_version(school.id, "subjects")
            bump_cache_version(school.id, "admin_dashboard")
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

    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("adminservices:list-subjects")

    name = subject.name
    subject.delete()

    bump_cache_version(school.id, "subjects")
    bump_cache_version(school.id, "admin_dashboard")
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
        form = _build_partial_bound_form(AnnouncementForm, request, school=school, instance=announcement)
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
                        results = send_announcement_via_email_and_sms(announcement)
                    else:
                        results = send_targeted_announcement(announcement, target_audience)
                    
                    # Handle notification results
                    if results and results.get('errors'):
                        error_count = len(results['errors'])
                        if error_count > 0:
                            logger.warning(
                                "Announcement notification errors: %s",
                                "; ".join(results['errors'])
                            )
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

            bump_cache_version(school.id, "announcements")
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
    cache_key = make_cache_key("announcements", school.id, "list")
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    announcements = Announcement.objects.filter(school=school).select_related('author').order_by('-created_at')

    response = render(request, "adminservices/list_announcements.html", {
        "announcements": announcements
    })
    if should_cache(request):
        cache.set(cache_key, response, 300)
    return response

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
    
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("adminservices:announcement_list")

    announcement_title = announcement.title
    announcement.delete()

    bump_cache_version(school.id, "announcements")
    messages.success(request, f"Announcement '{announcement_title}' successfully deleted")
    return redirect("adminservices:announcement_list")

# ===== HELPER FUNCTIONS =====

def _get_academic_year(school):
    """Helper to safely get academic year."""
    if hasattr(school, "get_current_academic_year"):
        return school.get_current_academic_year()
    current_year = timezone.now().year
    return f"{current_year}/{current_year + 1}"

# ===== PRINTING & PDF GENERATION VIEWS =====

@login_required(login_url='account:login')
@login_required(login_url='account:login')
def print_fee_receipt(request, fee_id):
    """Render HTML version of the fee receipt for printing."""
    fee = get_object_or_404(Fees.objects.select_related('school', 'student__user'), id=fee_id)
    school = fee.school

    if request.user.role == "admin":
        if getattr(request.user, 'managed_school', None) != school:
            messages.error(request, "You are not authorized to perform this action.")
            return redirect("adminservices:list-fees")
    elif request.user.role == "student":
        if not hasattr(request.user, 'student_profile') or request.user.student_profile.id != fee.student.id:
            messages.error(request, "You are not authorized to view this receipt.")
            return redirect("student:student-dashboard")
    else:
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    receipt_number = fee.receipt_number or f"RCP-{fee.id.hex[:8].upper()}"

    context = {
        'school': school,
        'fee': fee,
        'receipt_number': receipt_number,
        'issue_date': (fee.payment_date or fee.created_at).strftime('%B %d, %Y'),
        'academic_year': fee.academic_year,
        'payment_method': fee.get_payment_method_display() if fee.payment_method else "Cash",
    }

    return render(request, 'adminservices/fee_receipt.html', context)


@login_required(login_url='account:login')
def print_admission_form(request, student_id):
    """Render HTML version of the admission form for printing."""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("adminservices:list-students")

    school = request.user.managed_school
    student = get_object_or_404(
        Student.objects.select_related('user', 'parent', 'school', 'student_class', 'previous_class'),
        id=student_id,
        school=school
    )

    # Use admission_number (e.g., "2025-0042") for traceability
    form_number = f"ADM{timezone.now().strftime('%Y%m%d')}-{student.admission_number}"
    generated_date = timezone.now().strftime('%B %d, %Y')
    academic_year = _get_academic_year(school)

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
    fee = get_object_or_404(Fees.objects.select_related('school', 'student__user'), id=fee_id)
    school = fee.school

    if request.user.role == "admin":
        if getattr(request.user, 'managed_school', None) != school:
            messages.error(request, "You are not authorized to perform this action.")
            return redirect("adminservices:list-fees")
    elif request.user.role == "student":
        if not hasattr(request.user, 'student_profile') or request.user.student_profile.id != fee.student.id:
            messages.error(request, "You are not authorized to download this receipt.")
            return redirect("student:student-dashboard")
    else:
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

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

    if HTML is None:
        messages.info(request, "PDF generation is not available. Please install WeasyPrint.")
        return redirect('adminservices:print-fee-receipt', fee_id=fee_id)

    try:
        base_url = request.build_absolute_uri('/')
        html_string = render_to_string('adminservices/fee_receipt.html', context)
        pdf_file = HTML(string=html_string, base_url=base_url).write_pdf()

        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="fee_receipt_{receipt_number}.pdf"'
        return response

    except Exception as e:
        messages.error(request, f"Failed to generate PDF: {str(e)}")
        return redirect('adminservices:print-fee-receipt', fee_id=fee_id)


@login_required(login_url='account:login')
def download_admission_form_pdf(request, student_id):
    """Generate and download a PDF version of the admission form."""
    if getattr(request.user, 'role', None) != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("adminservices:list-students")

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "No school linked to your account.")
        return redirect("adminservices:list-students")

    student = get_object_or_404(
        Student.objects.select_related('user', 'parent', 'school', 'student_class', 'previous_class'),
        id=student_id,
        school=school
    )

    form_number = f"ADM{timezone.now().strftime('%Y%m%d')}-{student.admission_number}"
    generated_date = timezone.now().strftime('%B %d, %Y')
    academic_year = _get_academic_year(school)

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
        base_url = request.build_absolute_uri('/')
        html_string = render_to_string('adminservices/admission_form.html', context)
        pdf_file = HTML(string=html_string, base_url=base_url).write_pdf()

        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="admission_form_{form_number}.pdf"'
        return response

    except Exception as e:
        messages.error(request, f"Failed to generate PDF: {str(e)}")
        return redirect('adminservices:print-admission-form', student_id=student_id)


@login_required(login_url='account:login')
def add_class(request):
    """Add a new school class"""
    if request.user.role != "admin" and not request.user.is_superuser:
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("adminservices:admin-dashboard")

    school = getattr(request.user, 'managed_school', None)
    if not school and not request.user.is_superuser:
        messages.error(request, "Your account is not linked to any school.")
        return redirect("adminservices:admin-dashboard")

    if request.method == "POST":
        form = AddClassForm(request.POST, school=school)
        if form.is_valid():
            name = form.cleaned_data.get('name', '').strip()
            global_class = SchoolClass.objects.filter(school__isnull=True, name__iexact=name).first()
            if global_class and school and global_class.excluded_schools.filter(id=school.id).exists():
                global_class.excluded_schools.remove(school)
                school_class = global_class
            else:
                school_class = form.save(commit=False)
                if school:
                    school_class.school = school
                school_class.save()
            if school:
                bump_cache_version(school.id, "classes")
                bump_cache_version(school.id, "admin_dashboard")
            messages.success(request, f"Class '{school_class.name}' created successfully!")
            return redirect("adminservices:list-classes")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AddClassForm(school=school)

    return render(request, "adminservices/add_class.html", {"form": form})


@login_required(login_url='account:login')
def list_classes(request):
    """List all classes available to the school (both school-specific and global)"""
    if request.user.role != "admin" and not request.user.is_superuser:
        messages.error(request, "Not authorized.")
        return redirect("adminservices:admin-dashboard")

    school = getattr(request.user, 'managed_school', None)
    if not school and not request.user.is_superuser:
        messages.error(request, "No school linked to your account.")
        return redirect("adminservices:admin-dashboard")

    page_number = request.GET.get("page") or 1
    if school:
        classes = SchoolClass.for_school(school, active_only=True)
    else:
        classes = SchoolClass.objects.filter(is_active=True).order_by("order", "name")

    classes_with_counts = []
    for c in classes:
        student_count = c.students.filter(school=school, is_active=True).count() if school else c.students.filter(is_active=True).count()
        subject_count = c.subjects.filter(school=school).count() if school else c.subjects.count()
        classes_with_counts.append({
            "obj": c,
            "student_count": student_count,
            "subject_count": subject_count,
            "is_custom": bool(c.school_id),
        })

    paginator = Paginator(classes_with_counts, 25)
    page_obj = paginator.get_page(page_number)

    return render(request, "adminservices/list_classes.html", {"page_obj": page_obj})


@login_required(login_url='account:login')
def edit_class(request, class_id):
    """Edit class details"""
    if request.user.role != "admin" and not request.user.is_superuser:
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("adminservices:list-classes")

    school = getattr(request.user, 'managed_school', None)
    if request.user.is_superuser:
        school_class = get_object_or_404(SchoolClass, id=class_id)
    else:
        school_class = get_object_or_404(
            SchoolClass,
            Q(school=school) | Q(school__isnull=True),
            id=class_id
        )
        if school_class.school and school_class.school != school:
            messages.error(request, "You cannot edit another school's class.")
            return redirect("adminservices:list-classes")

    if request.method == "POST":
        form = AddClassForm(request.POST, instance=school_class, school=school)
        if form.is_valid():
            school_class = form.save(commit=False)
            if not request.user.is_superuser and not school_class.school and school:
                import uuid
                school_class.pk = None
                school_class.id = uuid.uuid4()
                school_class.school = school
            school_class.save()
            if school:
                bump_cache_version(school.id, "classes")
                bump_cache_version(school.id, "admin_dashboard")
            messages.success(request, f"Class '{school_class.name}' updated successfully!")
            return redirect("adminservices:list-classes")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AddClassForm(instance=school_class, school=school)

    return render(request, "adminservices/edit_class.html", {"form": form, "school_class": school_class})


@login_required(login_url='account:login')
def delete_class(request, class_id):
    """Delete a class with support for GET (confirmation preview) and POST (execution)."""
    if request.user.role != "admin" and not request.user.is_superuser:
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("adminservices:list-classes")

    school = getattr(request.user, 'managed_school', None)
    if not school and not request.user.is_superuser:
        messages.error(request, "No school linked to your account.")
        return redirect("adminservices:admin-dashboard")

    if request.user.is_superuser:
        school_class = get_object_or_404(SchoolClass, id=class_id)
    else:
        school_class = get_object_or_404(
            SchoolClass,
            Q(school=school) | Q(school__isnull=True),
            id=class_id
        )

    # Check dependencies for this school
    if school:
        student_count = Student.objects.filter(student_class=school_class, school=school).count()
        subject_count = Subject.objects.filter(subject_class=school_class, school=school).count()
        fees_count = Fees.objects.filter(student_class=school_class, school=school).count()
    else:
        student_count = Student.objects.filter(student_class=school_class).count()
        subject_count = Subject.objects.filter(subject_class=school_class).count()
        fees_count = Fees.objects.filter(student_class=school_class).count()

    can_delete = (student_count == 0 and subject_count == 0)

    # GET request: render confirmation template
    if request.method == "GET":
        return render(request, "adminservices/confirm_delete.html", {
            "object": school_class,
            "school_class": school_class,
            "student_count": student_count,
            "subject_count": subject_count,
            "fees_count": fees_count,
            "can_delete": can_delete,
            "school": school,
        })

    # POST request: execute deletion
    if not can_delete:
        messages.error(
            request,
            f"Cannot delete class '{school_class.name}' because {student_count} student(s) and {subject_count} subject(s) are currently assigned to it in your school. Please reassign or remove them first."
        )
        return redirect("adminservices:list-classes")

    class_name = school_class.name
    try:
        with transaction.atomic():
            # Clean up fee structures and timetables for this school
            if school:
                ClassFee.objects.filter(school=school, student_class=school_class).delete()
                Timetable.objects.filter(school=school, student_class=school_class).delete()
                Teacher.objects.filter(school=school, class_teacher_class=school_class).update(
                    class_teacher_class=None, is_class_teacher=False
                )
            else:
                ClassFee.objects.filter(student_class=school_class).delete()
                Timetable.objects.filter(student_class=school_class).delete()
                Teacher.objects.filter(class_teacher_class=school_class).update(
                    class_teacher_class=None, is_class_teacher=False
                )

            if school_class.school == school or (request.user.is_superuser and school_class.school is None):
                # Custom class belonging to this school or superuser deleting global class
                school_class.delete()
            else:
                # Global class being deleted/removed from this school:
                # Exclude it so it no longer appears in this school's curriculum, lists, or dropdowns
                if school and hasattr(school_class, 'excluded_schools'):
                    school_class.excluded_schools.add(school)
                else:
                    school_class.is_active = False
                    school_class.save(update_fields=['is_active'])

        if school:
            bump_cache_version(school.id, "classes")
            bump_cache_version(school.id, "admin_dashboard")
            bump_cache_version(school.id, "teachers")

        messages.success(request, f"Class '{class_name}' deleted successfully.")
    except ProtectedError as e:
        messages.error(
            request,
            f"Cannot delete class '{class_name}' due to protected database dependencies: {e}"
        )
    except Exception as e:
        messages.error(
            request,
            f"An error occurred while deleting class '{class_name}': {str(e)}"
        )

    return redirect("adminservices:list-classes")


@login_required(login_url='account:login')
def timetable_list(request):
    """View and manage class timetables weekly schedule."""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to view this page.")
        return redirect("account:login")

    school = request.user.managed_school
    classes = SchoolClass.for_school(school, active_only=True).order_by('order', 'name') if school else SchoolClass.objects.filter(is_active=True).order_by('order', 'name')

    selected_class_id = request.GET.get('class_id')
    selected_class = None
    if selected_class_id:
        selected_class = classes.filter(id=selected_class_id).first()
    if not selected_class and classes.exists():
        selected_class = classes.first()

    DAYS = [
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
    ]

    days_schedule = {day_code: {'label': day_label, 'entries': []} for day_code, day_label in DAYS}
    total_entries = 0
    total_teachers = 0
    total_subjects = 0

    if selected_class and school:
        timetables = Timetable.objects.filter(
            school=school,
            student_class=selected_class
        ).select_related('subject', 'teacher__user', 'student_class').order_by('start_time')

        total_entries = timetables.count()
        total_teachers = timetables.values('teacher').distinct().count()
        total_subjects = timetables.values('subject').distinct().count()

        for entry in timetables:
            if entry.day_of_week in days_schedule:
                days_schedule[entry.day_of_week]['entries'].append(entry)

    context = {
        'classes': classes,
        'selected_class': selected_class,
        'days_schedule': days_schedule,
        'total_entries': total_entries,
        'total_teachers': total_teachers,
        'total_subjects': total_subjects,
    }
    return render(request, 'adminservices/timetable_list.html', context)


@login_required(login_url='account:login')
def add_timetable(request):
    """Add a new timetable entry for a class."""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    school = request.user.managed_school
    if request.method == "POST":
        form = TimetableForm(request.POST, school=school)
        if form.is_valid():
            timetable = form.save()
            messages.success(
                request,
                f"Schedule entry for {timetable.subject.name} ({timetable.student_class}) created successfully."
            )
            return redirect(f"{reverse('adminservices:timetable-list')}?class_id={timetable.student_class_id}")
    else:
        initial = {}
        class_id = request.GET.get('class_id')
        day = request.GET.get('day')
        if class_id:
            initial['student_class'] = class_id
        if day:
            initial['day_of_week'] = day
        form = TimetableForm(school=school, initial=initial)

    context = {
        'form': form,
        'title': "Create Class Timetable Schedule",
        'button_text': "Save Schedule Entry",
    }
    return render(request, 'adminservices/add_timetable.html', context)


@login_required(login_url='account:login')
def edit_timetable(request, timetable_id):
    """Edit an existing timetable entry."""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    school = request.user.managed_school
    timetable = get_object_or_404(Timetable, id=timetable_id, school=school)

    if request.method == "POST":
        form = TimetableForm(request.POST, instance=timetable, school=school)
        if form.is_valid():
            timetable = form.save()
            messages.success(
                request,
                f"Schedule entry for {timetable.subject.name} ({timetable.student_class}) updated successfully."
            )
            return redirect(f"{reverse('adminservices:timetable-list')}?class_id={timetable.student_class_id}")
    else:
        form = TimetableForm(instance=timetable, school=school)

    context = {
        'form': form,
        'timetable': timetable,
        'title': "Edit Class Timetable Schedule",
        'button_text': "Update Schedule Entry",
    }
    return render(request, 'adminservices/add_timetable.html', context)


@login_required(login_url='account:login')
def delete_timetable(request, timetable_id):
    """Delete a timetable entry."""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    school = request.user.managed_school
    timetable = get_object_or_404(Timetable, id=timetable_id, school=school)
    class_id = timetable.student_class_id

    if request.method == "POST":
        timetable.delete()
        messages.success(request, "Timetable entry deleted successfully.")
        return redirect(f"{reverse('adminservices:timetable-list')}?class_id={class_id}")

    return redirect('adminservices:timetable-list')


@login_required(login_url='account:login')
def school_settings(request):
    """Manage school profile details, contact information, and institution logo."""
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to view this page.")
        return redirect("account:login")

    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "No managed school found for this administrator account.")
        return redirect("adminservices:admin-dashboard")

    if request.method == "POST":
        if "remove_logo" in request.POST:
            if school.logo:
                school.logo.delete(save=False)
                school.logo = None
                school.save(update_fields=['logo'])
                for section in ("school_profile", "admin_dashboard", "teacher_portal", "student_portal"):
                    bump_cache_version(school.id, section)
                messages.success(request, "School logo has been removed successfully.")
            return redirect("adminservices:school-settings")

        form = SchoolSettingsForm(request.POST, request.FILES, instance=school)
        if form.is_valid():
            school = form.save()
            for section in ("school_profile", "admin_dashboard", "teacher_portal", "student_portal"):
                bump_cache_version(school.id, section)
            messages.success(request, "School profile and logo updated successfully!")
            return redirect("adminservices:school-settings")
    else:
        form = SchoolSettingsForm(instance=school)

    context = {
        'school': school,
        'form': form,
    }
    return render(request, 'adminservices/school_settings.html', context)
