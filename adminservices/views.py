from django.contrib import messages
from django.shortcuts import get_object_or_404, render,redirect
from account.models import Subscription, Teacher,CustomUser,Department,School,Student,Parent,Fees,Subject,Announcement,Notification
from .forms import AddTeacherForm,AddDepartmentForm,AddStudentForm,AddFeesForm,AddSubjectForm,AnnouncementForm
from django.core.mail import send_mail
from django.conf import settings
from django.core.paginator import Paginator
from django.template.context_processors import request
from django.conf import settings
from django.db import transaction
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from .utils import *
from django.db.models import Q
# Create your views here.



@login_required
def admin_dashboard(request):
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("account:login")
    
    try:
        school = request.user.managed_school
    except School.DoesNotExist:
        messages.error(request, "You haven't registered for a school")
        return redirect("account:login")

    students_count = Student.objects.filter(school=school).count()
    teachers_count = Teacher.objects.filter(school=school).count()
    departments_count = Department.objects.filter(school=school).count()
    
    students = Student.objects.filter(school=school).select_related('user')
    search_query = None
    
    # Handle POST request for search
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

def add_teacher(request):
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform that action")
        return redirect("adminservices:list-teachers")

    
    school = getattr(request.user, 'managed_school', None)
    if not school:
        messages.error(request, "Your account is not linked to a school.")
        return redirect("adminservices:list-teachers")

    # subscription = Subscription.objects.filter(school=school, is_active=True).first()
    # if not subscription or not subscription.package:
    #     messages.error(request, "You need an active subscription to add teachers.")
    #     return redirect("adminservices:list-teachers")

    # teacher_count = Teacher.objects.filter(school=school, is_active=True).count()
    # max_teachers = subscription.package.max_teachers or float('inf')
    # if max_teachers != float('inf') and teacher_count >= max_teachers:
    #     messages.error(
    #         request,
    #         f"You have reached the teacher limit ({max_teachers}). Please upgrade your package."
    #     )
    #     return redirect("adminservices:upgrade_package", new_package_id=subscription.package.id)

    if request.method == "POST":
        form = AddTeacherForm(request.POST, request.FILES, school=school)
        
        if form.is_valid():
            
            try:
                
           
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
                
                # # Create Teacher profile
                # teacher = form.save(commit=False)
                # teacher.user = user
                # teacher.school = school
                # teacher.is_active = True
                # teacher.save()
                
                # teacher = form.save()
                # print(f"Teacher saved: {teacher}")
                # print(f"Teacher user: {teacher.user}")
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
                
                
                
                
                teacher_emails, teacher_phones = get_teacher_contacts(teacher)
                
                email_message = (
                    f'Hello {user.first_name},\n\n'
                    f'You have been added as a teacher at {school.name}.\n\n'
                    f'Your login details:\n'
                    f'Username: {user.username}\n'
                    f'Password: {form.cleaned_data.get("password", "the password you set")}\n\n'
                    f'Please log in and change your password after first login.\n\n'
                    f'Best regards,\n{school.name} Administration'
                )
                
                sms_message = (
                    f"Welcome to {school.name}! You've been added as a teacher. "
                    f"Username: {user.username}. Check your email for details."
                    f'Username: {user.username}\n'
                    f'Password: {form.cleaned_data.get("password", "the password you set")}\n\n'
                    f'Please log in and change your password after first login.\n\n'
                    f'Best regards,\n{school.name} Administration'
                )
                
                # Send both email and SMS
                notification_results = send_notification(
                    emails=teacher_emails,
                    phones=teacher_phones,
                    subject='Welcome to the School',
                    message=email_message
                )
                
                if not notification_results['email_sent'] and not notification_results['sms_sent']:
                    messages.warning(request, "Teacher added, but notifications could not be sent.")
                elif not notification_results['email_sent']:
                    messages.warning(request, "Teacher added, but email could not be sent.")
                elif not notification_results['sms_sent']:
                    messages.warning(request, "Teacher added, but SMS could not be sent.")
                
                messages.success(request, "Teacher added successfully!")
                return redirect("adminservices:list-teachers")
            
                
                # Send welcome email to the teacher
                # try:
                #     send_mail(
                #         subject='Welcome to the School',
                #         message=(
                #             f'Hello {user.first_name},\n\n'
                #             f'You have been added as a teacher at {school.name}.\n\n'
                #             f'Your login details:\n'
                #             f'Username: {user.username}\n'
                #             f'Password: {form.cleaned_data.get("password", "the password you set")}\n\n'
                #             f'Please log in and change your password after first login.\n\n'
                #             f'Best regards,\n{school.name} Administration'
                #         ),
                #         from_email=settings.DEFAULT_FROM_EMAIL,
                #         recipient_list=[teacher.user.email],
                #         fail_silently=False,
                #     )
                # except Exception as email_error:
                #     print(f"Email error: {email_error}")
                #     messages.warning(request, "Teacher added, but email could not be sent.")
                
                # messages.success(request, "Teacher added successfully!")
                # return redirect("adminservices:list-teachers")
            
            except Exception as e:
                # Rollback: If teacher creation failed but user was created, delete the user
                # if user and user.pk:
                #     try:
                #         user.delete()
                #         print(f"Rolled back user creation due to error: {str(e)}")
                #     except Exception as delete_error:
                #         print(f"Error deleting user during rollback: {delete_error}")   
                 # If user was created but teacher failed, delete the user
                if 'user' in locals() and user.pk: # type: ignore
                    user.delete() # type: ignore
                messages.error(request, f"An error occurred: {str(e)}")
                print(f"Full error details: {str(e)}")
                import traceback
                traceback.print_exc()
        else:
            # Display form validation errors
            messages.error(request, "Please correct the errors below.")
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = AddTeacherForm(school=school)
    
    return render(request, "adminservices/add_teacher.html", {"form": form})

def add_department(request):
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("adminservices:list-departments")


    try:
        school = request.user.managed_school
    except School.DoesNotExist:
        messages.error(request, "Your account is not linked to any school.")
        return redirect("adminservices:admin-dashboard")

    # Check subscription
    # subscription = Subscription.objects.filter(school=school, is_active=True).first()
    # if not subscription or not subscription.package:
    #     messages.error(request, "You need an active subscription to add departments.")
    #     return redirect("adminservices:select-package")


    # if hasattr(subscription.package, 'max_departments') and subscription.package.max_departments is not None: # type: ignore
    #     current_dept_count = Department.objects.filter(school=school).count()
    #     if current_dept_count >= subscription.package.max_departments:  # type: ignore
    #         messages.error(
    #             request,
    #             f"You have reached the department limit ({subscription.package.max_departments}). " # type: ignore
    #             "Please upgrade your subscription."
    #         )
    #         return redirect("adminservices:upgrade-package", new_package_id=subscription.package.id)

    # Handle form
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


def update_teacher(request, teacher_id):
    if request.user.role not in ["admin","teacher"]:
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

        # Make password optional during update
        form.fields['password'].required = False
        form.fields['password'].help_text = "Leave blank to keep current password."

        if form.is_valid():
            try:
              
                user.first_name = form.cleaned_data['first_name']
                user.last_name = form.cleaned_data['last_name']
                user.email = form.cleaned_data['email']
                user.username = form.cleaned_data['username']
                user.gender = form.cleaned_data['gender']
                user.date_of_birth = form.cleaned_data['date_of_birth']
                user.address = form.cleaned_data['address']
                user.phone_number = form.cleaned_data.get('phone_number', '')

           
                password = form.cleaned_data.get('password')
                if password:
                    user.set_password(password)

                if 'profile_picture' in request.FILES:
                    user.profile_picture = request.FILES['profile_picture']

                user.save()  

            
                updated_teacher = form.save(commit=False)
                updated_teacher.school = school 
                updated_teacher.save()

          
                try:
                    send_mail(
                        subject='Your Account Has Been Updated',
                        message=(
                            f"Hello {user.first_name},\n\n"
                            f"Your teacher account at {school.name} has been updated.\n"
                            f"If you changed your password, please use the new one to log in.\n\n"
                            f"Best regards,\n{school.name} Administration"
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                except Exception as email_error:
                    print(f"Email error: {email_error}")
                    messages.warning(request, "Teacher updated, but email could not be sent.")

                messages.success(request, "Teacher updated successfully!")
                return redirect("adminservices:list-teachers")

            except Exception as e:
                messages.error(request, f"An error occurred while saving: {str(e)}")
                print(f"Update teacher error: {str(e)}")
        else:
            messages.error(request, "Please correct the errors below.")
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        # Pre-fill form for GET request
        form = AddTeacherForm(instance=teacher, school=school)
        form.fields['password'].required = False
        form.fields['password'].help_text = "Leave blank to keep current password."
        form.fields['password'].initial = '' 

    return render(request, "adminservices/edit-teacher.html", {
        "form": form,
        "teacher": teacher
    })


def list_teachers(request):
    if request.user.role != "admin":
        messages.error(request,"You are not authorized to perform this action")
        return redirect("adminservices:list-teachers")
    
    school = request.user.managed_school
    
    teachers = Teacher.objects.filter(school=school, is_active=True).select_related('user', 'department')
    paginator = Paginator(teachers,50)
    page_number = request.GET.get("page_number")
    page_obj = paginator.get_page(page_number)
    
    return render(request,"adminservices/list-teachers.html",{"page_obj":page_obj})


def delete_teacher(request,teacher_id):
    if request.user.role != "admin":
        messages.error(request,"You are not authorized to perform this action")
        return redirect("adminservices:list-teachers")
    
    school = request.user.managed_school
    teacher = get_object_or_404(Teacher,id=teacher_id,school=school)
    teacher.delete()
    return redirect("adminservices:list-teachers")

def teacher_detail(request,teacher_id):
    if request.user.role != "admin" or request.user.role != "teacher":
        messages.error(request,"You are not authorized to perform this action")
        return redirect("adminservices:list-teachers")
    
    school = request.user.managed_school
    teacher = get_object_or_404(Teacher,id=teacher_id,school=school)
    return render(request,"adminservices/teacher_detail.html",{"teacher":teacher})
    
        
    
def list_departments(request):
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



def delete_department(request,department_id):
    if request.user.role != "admin":
        messages.error(request,"You are not authorized to perform this action")
        return redirect("adminservices:list-teachers")
    
    school = request.user.managed_school
    
    department = get_object_or_404(Department,id=department_id,school=school)
    department.delete()
    return redirect("adminservices:list-departments")

def edit_department(request,department_id):
    if request.user.role != "admin":
        messages.error(request,"You are not authorized to perform this action")
        return redirect("adminservices:list-department")
    
    school = request.user.managed_school
    
    department = get_object_or_404(Department,id=department_id,school=school)
    
    if request.method == "POST":
        form = AddDepartmentForm(request.POST,instance=department,school=school)
        if form.is_valid():
            department = form.save(commit=False)
            department.school = school
            department.save()
            messages.success(request, f"Department '{department.name}' updated successfully!")
            return redirect("adminservices:list-departments")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AddDepartmentForm(instance=department,school=school)

    return render(request, "adminservices/edit_department.html", {"form": form})


def department_detail(request,department_id):
    if request.user.role != "admin":
        messages.error(request,"You are not authorized to perform this action")
        return redirect("adminservices:list-teachers")
    
    school = request.user.managed_school
    
    department = get_object_or_404(Department,id=department_id,school=school)
    return render(request,"adminservices/department-detail.html",{"department":department})


def add_student(request):
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
                    
                    # Send email AND SMS to parents
                    from .utils import send_notification, get_student_parent_contacts
                    
                    parent_emails, parent_phones = get_student_parent_contacts(student)
                    
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
                    
                    sms_message = (
                        f"Your child {student.user.first_name} has been enrolled at {school.name}. "
                        f"Username: {student.user.username}. Check email for login details."
                    )
                    
                    notification_results = send_notification(
                        emails=parent_emails,
                        phones=parent_phones,
                        subject=f"Login Details for {student.user.get_full_name()} - {school.name}",
                        message=email_message
                    )
                    
                    if notification_results['email_sent'] or notification_results['sms_sent']:
                        messages.success(
                            request, 
                            f"Student '{student.user.get_full_name()}' added successfully! "
                            f"Login details have been sent to the parent(s)."
                        )
                    else:
                        messages.warning(
                            request,
                            f"Student '{student.user.get_full_name()}' created successfully, "
                            f"but we couldn't send the login details to the parent(s)."
                        )
                    
                    return redirect("adminservices:list-students")
            except Exception as e:
                import traceback
                print(f"[Add Student Error] {str(e)}")
                print(traceback.format_exc())
                messages.error(request, f"An error occurred while creating the student: {str(e)}")
    else:
        form = AddStudentForm(school=school)
 
    return render(request, "adminservices/add_student.html", {
        "form": form,
        "title": "Add New Student"
    })

def list_students(request):
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
    
def student_detail(request, student_id):
    student = get_object_or_404(Student, id=student_id, school=request.user.managed_school)
    return render(request, "adminservices/student_detail.html", {"student": student})


def edit_student(request, student_id):
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

def delete_student(request, student_id):
    if request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("adminservices:list-students")

    school = request.user.managed_school
    student = get_object_or_404(Student, id=student_id, school=school)
    student.delete()
    return redirect("adminservices:list-students")




def add_fees(request):
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

                    # Send fee notification via email AND SMS
                    from .utils import send_notification, get_student_parent_contacts
                    
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
                    
                    if notification_results['email_sent'] or notification_results['sms_sent']:
                        messages.success(request, f"Fee for '{student.user.get_full_name()}' added successfully and parents notified!")
                    else:
                        messages.warning(request, f"Fee added but notifications could not be sent.")
                    
                    return redirect("adminservices:list-fees")

            except Exception as e:
                messages.error(request, f"An error occurred while saving: {str(e)}")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AddFeesForm(school=school)
    students = Student.objects.filter(school=school, is_active=True).select_related('user')

    return render(request, "adminservices/add_fees.html", {"form": form, "students": students})

def edit_fees(request, fee_id):
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

def list_fees(request):
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "You are not authorized to perform this action.")
        return redirect("account:login")

    school = request.user.managed_school
    fees = Fees.objects.filter(student__school=school).select_related('student__user', 'student__parent').order_by('-created_at')

    paginator = Paginator(fees, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, "adminservices/list_fees.html", {"page_obj": page_obj})

def delete_fees(request, fee_id):
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



def add_subject(request):
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
            # 🔽 Print errors to console for debugging
            print("Form errors:", form.errors)  # Debug line
            messages.error(request, "Please correct the errors below.")
    else:
        form = AddSubjectForm(school=school)

    return render(request, "adminservices/add_subject.html", {"form": form})

def list_subjects(request):
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


def subject_detail(request, subject_id):
    school = getattr(request.user, 'managed_school', None)
    subject = get_object_or_404(Subject, id=subject_id, school=school)
    return render(request, "adminservices/subject_detail.html", {"subject": subject})


def edit_subject(request, subject_id):
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


def delete_subject(request, subject_id):
    if not request.user.is_authenticated or request.user.role != "admin":
        messages.error(request, "Unauthorized.")
        return redirect("account:login")

    school = getattr(request.user, 'managed_school', None)
    subject = get_object_or_404(Subject, id=subject_id, school=school)


    name = subject.name
    subject.delete()
    messages.success(request, f"Subject '{name}' deleted successfully.")
    return redirect("adminservices:list-subjects")



@login_required
def manage_announcement(request, pk=None):
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
        form = AnnouncementForm(request.POST, request.FILES, instance=announcement)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.school = school
            announcement.author = request.user
            announcement.save()

            if announcement.published:
                send_announcement_via_email_and_sms(announcement)

            messages.success(request, "Announcement saved successfully.")
            return redirect("adminservices:announcement_list")
    else:
        form = AnnouncementForm(instance=announcement,school=school)

    return render(request, "adminservices/annoucement_form.html", {
        "form": form,
        "announcement": announcement,
        "is_edit": pk is not None,
    })
    
    
@login_required
def list_announcements(request):
    """
    Display all announcements for the current admin's school.
    """
    # Authorization checks
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to manage announcements.")
        return redirect("account:home")

    if not hasattr(request.user, 'managed_school'):
        messages.error(request, "You do not manage any school.")
        return redirect("account:home")

    school = request.user.managed_school

    # Fetch announcements for this school, ordered by creation date (newest first)
    announcements = Announcement.objects.filter(school=school).select_related('author').order_by('-created_at')

    return render(request, "adminservices/list_announcements.html", {
        "announcements": announcements
    })
    
    
@login_required
def announcement_delete(request,announcement_id):
    if request.user.role != "admin":
        messages.error(request, "You are not authorized to manage announcements.")
        return redirect("account:home")

    if not hasattr(request.user, 'managed_school'):
        messages.error(request, "You do not manage any school.")
        return redirect("account:home")

    school = request.user.managed_school

    announcement = get_object_or_404(Announcement,id=announcement_id,school=school)
    announcement.delete()
    messages.success(request,"Annoucement successfully deleted")
    return redirect("adminservices:announcement_list")
    