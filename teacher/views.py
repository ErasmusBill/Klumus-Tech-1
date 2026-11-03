from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from .forms import BulkResultForm, EditResultForm,AttendanceForm,AssignmentForm
from account.models import ResultSheet, Subject, Student, Teacher, Attendance, Assignment, AssignmentSubmission, PromotionHistory, Enrollment, SchoolClass, Timetable
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.db import models
from django.db.models import Q, Avg, Count, Max, Min
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import HttpResponse
from django.urls import reverse
from django.core.cache import cache
import os
from ai_predictor.models import PredictedPerformance
from django.http import JsonResponse
from adminservices.utils import create_bulk_in_app_notifications, create_in_app_notification
from account.cache_utils import make_cache_key, should_cache


def _get_attendance_teacher(request):
    try:
        teacher = request.user.teacher_profile
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found.")
        return None, redirect("account:login")

    if not teacher.can_take_attendance:
        messages.error(request, "Only class teachers assigned to a class can take attendance.")
        return None, redirect("teacher:teacher-dashboard")

    return teacher, None


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

    cache_key = make_cache_key(
        "teacher_portal",
        school.id,
        f"dashboard:{teacher.id}:{teacher.is_class_teacher}:{teacher.class_teacher_class_id or 'none'}",
    )
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    # Get teacher's subjects
    subjects = Subject.objects.filter(teacher=teacher, school=school).select_related('subject_class', 'department')
    subject_count = subjects.count()
    
    # Get assignments created by teacher
    assignments = Assignment.objects.filter(teacher=teacher, subject__school=school)
    assignment_count = assignments.count()
    
    now = timezone.now()
    now_date = now.date()

    # Active assignments count
    active_assignments_count = assignments.filter(
        due_date__gte=now_date
    ).exclude(status='closed').count()

    # Recent assignments with submission counts
    recent_assignments = assignments.select_related('subject', 'student_class').annotate(
        submission_count=Count('submissions')
    ).order_by('-created_at')[:6]

    # Upcoming deadlines
    upcoming_deadlines = assignments.filter(
        due_date__gte=now_date
    ).exclude(status='closed').select_related('subject', 'student_class').order_by('due_date')[:5]

    # Pending submissions to grade
    pending_submissions = AssignmentSubmission.objects.filter(
        assignment__teacher=teacher,
        status__in=['submitted', 'late']
    ).select_related('student__user', 'assignment__subject', 'assignment__student_class').order_by('-submission_date')[:6]
    
    pending_grading_count = AssignmentSubmission.objects.filter(
        assignment__teacher=teacher,
        status__in=['submitted', 'late']
    ).count()
    
    # Simple class count (distinct classes from subjects)
    class_count = subjects.values('subject_class').distinct().count()
    
    # Students enrolled in teacher's subjects
    students_qs = Student.objects.filter(
        enrollments__subject__in=subjects,
        is_active=True
    ).distinct()
    student_count = students_qs.count()

    # Predictor students for easy dropdown selection
    predictor_students = students_qs.select_related('user', 'student_class').order_by('student_class__name', 'user__first_name')[:80]

    # Teacher classes
    class_ids = set(subjects.values_list('subject_class_id', flat=True))
    if teacher.is_class_teacher and teacher.class_teacher_class_id:
        class_ids.add(teacher.class_teacher_class_id)
    
    classes_qs = SchoolClass.objects.filter(id__in=class_ids).order_by('name')
    teacher_classes = []
    for c in classes_qs:
        c_students_count = Student.objects.filter(student_class=c, is_active=True).count()
        c_subjects = subjects.filter(subject_class=c)
        teacher_classes.append({
            'class_obj': c,
            'class_display': str(c),
            'student_count': c_students_count,
            'subject_count': c_subjects.count(),
            'subjects': c_subjects,
            'is_class_teacher': bool(teacher.is_class_teacher and teacher.class_teacher_class_id == c.id),
        })

    # Today's attendance status
    today_attendance_taken = False
    today_attendance_summary = None
    if teacher.can_take_attendance and teacher.class_teacher_class:
        today_attendance = Attendance.objects.filter(
            class_attendance=teacher.class_teacher_class,
            date=now_date,
            attendance_type='student'
        )
        if today_attendance.exists():
            today_attendance_taken = True
            today_attendance_summary = {
                'present': today_attendance.filter(status='present').count(),
                'absent': today_attendance.filter(status='absent').count(),
                'late': today_attendance.filter(status='late').count(),
                'total': today_attendance.count(),
            }

    greeting_time = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 17 else "Good evening"

    # Timetable for Teacher
    today_day_str = timezone.now().strftime('%A').lower()
    now_time = timezone.now().time()
    
    teacher_timetables_today = Timetable.objects.filter(
        teacher=teacher,
        school=school,
        day_of_week=today_day_str,
        is_active=True
    ).select_related('subject', 'student_class').order_by('start_time')

    today_schedule = []
    for item in teacher_timetables_today:
        if item.start_time <= now_time <= item.end_time:
            time_status = "current"
        elif now_time < item.start_time:
            time_status = "upcoming"
        else:
            time_status = "completed"
        today_schedule.append({
            'entry': item,
            'status': time_status,
        })

    weekly_timetables_count = Timetable.objects.filter(
        teacher=teacher,
        school=school,
        is_active=True
    ).count()

    context = {
        "teacher": teacher,
        "greeting_time": greeting_time,
        "today_schedule": today_schedule,
        "today_day_name": timezone.now().strftime('%A'),
        "weekly_timetables_count": weekly_timetables_count,
        "subject_count": subject_count,
        "class_count": class_count,
        "student_count": student_count,
        "assignment_count": assignment_count,
        "active_assignments_count": active_assignments_count,
        "recent_assignments": recent_assignments,
        "upcoming_deadlines": upcoming_deadlines,
        "pending_submissions": pending_submissions,
        "pending_grading_count": pending_grading_count,
        "teacher_classes": teacher_classes,
        "teacher_is_class_teacher": teacher.is_class_teacher,
        "can_take_attendance": teacher.can_take_attendance,
        "today_attendance_taken": today_attendance_taken,
        "today_attendance_summary": today_attendance_summary,
        "predictor_students": predictor_students,
        "today_date": now_date,
    }
    
    response = render(request, "teacher/teacher_dashboard.html", context)
    if should_cache(request):
        cache.set(cache_key, response, 180)
    return response

def my_subjects(request):
    """View that shows teacher's assigned subjects and grading hub"""
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")

    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found.")
        return redirect("account:login")

    search_query = request.GET.get('search', '').strip()

    sanitized_class = str(teacher.class_teacher_class or "none").replace(" ", "_")
    sanitized_search = search_query.replace(" ", "_")
    cache_key = make_cache_key(
        "teacher_portal",
        school.id,
        f"my-subjects:{teacher.id}:{teacher.is_class_teacher}:{sanitized_class}:{sanitized_search}",
    )
    if should_cache(request) and not search_query:
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response
    
    # Get subjects with student counts and results
    subjects = Subject.objects.filter(
        teacher=teacher, 
        school=school
    ).select_related('department').prefetch_related('enrollments', 'results')

    if search_query:
        subjects = subjects.filter(
            Q(name__icontains=search_query) |
            Q(department__name__icontains=search_query) |
            Q(subject_class__icontains=search_query)
        )

    # Attach stats to each subject
    total_enrollments = 0
    for subj in subjects:
        subj.enrolled_count = subj.enrollments.count()
        subj.results_count = subj.results.filter(student__school=school).count()
        total_enrollments += subj.enrolled_count

    total_results_count = ResultSheet.objects.filter(
        subject__teacher=teacher,
        student__school=school
    ).count()

    response = render(request, "teacher/my_subjects.html", {
        "subjects": subjects,
        "total_subjects": subjects.count(),
        "total_enrollments": total_enrollments,
        "total_results_count": total_results_count,
        "teacher_is_class_teacher": teacher.is_class_teacher,
        "search_query": search_query,
        "title": "My Subjects & Grading Hub"
    })
    if should_cache(request) and not search_query:
        cache.set(cache_key, response, 180)
    return response

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
    students = Student.objects.filter(
        school=school,
        enrollments__subject=subject,
        is_active=True
    ).select_related('user', 'parent').order_by('user__last_name', 'user__first_name').distinct()

    if not students.exists():
        messages.warning(request, f"No students are currently enrolled in {subject.name}.")
        return redirect("teacher:my-subjects")

    current_year = timezone.now().year
    default_academic_year = f"{current_year}/{current_year + 1}"
    selected_term = request.GET.get('term') or "1"
    selected_academic_year = request.GET.get('academic_year') or default_academic_year

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
                        comment = request.POST.get(f'comment_{student.id}', '').strip()

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

                        # Clamp values
                        class_score = max(Decimal('0'), min(Decimal('20'), class_score))
                        mid_semester = max(Decimal('0'), min(Decimal('30'), mid_semester))
                        end_of_term_exams = max(Decimal('0'), min(Decimal('50'), end_of_term_exams))

                        has_scores = (class_score > 0 or mid_semester > 0 or end_of_term_exams > 0)
                        
                        existing_res = ResultSheet.objects.filter(
                            student=student,
                            subject=subject,
                            term=term,
                            academic_year=academic_year
                        ).first()

                        # Only save if at least one score is provided or updating existing
                        if has_scores or (existing_res and (comment or class_score == 0)):
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

                    # Create in-app notifications for students
                    for item in results_created:
                        try:
                            st = item['student']
                            result_obj = item['result']
                            create_in_app_notification(
                                user=st.user,
                                title=f"Result posted: {subject.name}",
                                message=f"Your {subject.name} result for {term} {academic_year} is available.",
                                notification_type="result",
                                related_object=result_obj,
                                link=reverse("student:view-result", args=[st.id]),
                            )
                        except Exception:
                            continue

                    # Success message
                    if created_count > 0 or updated_count > 0:
                        messages.success(
                            request,
                            f"Grades successfully saved for {subject.name} (Term {term}, {academic_year})! "
                            f"{created_count} added, {updated_count} updated. "
                            f"{emails_sent} parent notification(s) sent."
                        )
                    else:
                        messages.info(request, "No grades were changed (all scores were zero).")

                    return redirect(f"{reverse('teacher:list-result')}?subject={subject.id}&term={term}&academic_year={academic_year}")

            except Exception as e:
                messages.error(request, f"An error occurred while saving grades: {str(e)}")
        else:
            messages.error(request, "Please correct the errors in the form.")
    else:
        # GET request - initialize form with selected term & year
        form = BulkResultForm(
            students=students,
            initial={
                'exam_date': timezone.now().date(),
                'term': selected_term,
                'academic_year': selected_academic_year
            }
        )
        
        existing_results_map = {
            res.student_id: res
            for res in ResultSheet.objects.filter(
                subject=subject,
                term=selected_term,
                academic_year=selected_academic_year
            )
        }

        for student in students:
            existing_result = existing_results_map.get(student.id)
            if existing_result:
                form.fields[f'class_score_{student.id}'].initial = float(existing_result.class_score)
                form.fields[f'mid_semester_{student.id}'].initial = float(existing_result.mid_semester)
                form.fields[f'end_of_term_exams_{student.id}'].initial = float(existing_result.end_of_term_exams)

    # Prepare students data with existing results for display
    active_term = selected_term if request.method == "GET" else request.POST.get('term', selected_term)
    active_year = selected_academic_year if request.method == "GET" else request.POST.get('academic_year', selected_academic_year)
    
    current_results = {
        res.student_id: res
        for res in ResultSheet.objects.filter(
            subject=subject,
            term=active_term,
            academic_year=active_year
        )
    }

    students_data = []
    total_graded = 0
    score_sum = Decimal('0')
    highest_score = Decimal('0')
    lowest_score = Decimal('100')

    for student in students:
        res = current_results.get(student.id)
        has_entry = False
        if res and (res.class_score > 0 or res.mid_semester > 0 or res.end_of_term_exams > 0):
            has_entry = True
            total_graded += 1
            score_sum += res.total_marks
            if res.total_marks > highest_score:
                highest_score = res.total_marks
            if res.total_marks < lowest_score:
                lowest_score = res.total_marks

        students_data.append({
            'student': student,
            'result': res,
            'has_entry': has_entry,
            'class_score': float(res.class_score) if res else 0,
            'mid_semester': float(res.mid_semester) if res else 0,
            'end_of_term_exams': float(res.end_of_term_exams) if res else 0,
            'total_marks': float(res.total_marks) if res else 0,
            'percentage': float(res.percentage) if res else 0,
            'grade': res.grade if res else '-',
            'remark': res.get_remark_display() if res else '-',
            'comment': res.teacher_comment if res else '',
        })

    class_avg = round(score_sum / total_graded, 1) if total_graded > 0 else 0
    if total_graded == 0:
        lowest_score = Decimal('0')

    context = {
        "form": form,
        "subject": subject,
        "students": students,
        "students_data": students_data,
        "total_students": students.count(),
        "total_graded": total_graded,
        "class_avg": class_avg,
        "highest_score": highest_score,
        "lowest_score": lowest_score,
        "selected_term": active_term,
        "selected_academic_year": active_year,
        "term_choices": ResultSheet.TERM_CHOICES,
        "title": f"Grade Entry: {subject.name}",
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

    result = get_object_or_404(
        ResultSheet,
        id=result_id,
        subject__teacher=teacher,
        student__school=school
    )

    if request.method == "POST":
        form = EditResultForm(request.POST, instance=result)
        if form.is_valid():
            saved_result = form.save()
            messages.success(request, f"Result for {result.student.user.get_full_name()} ({result.subject.name}) updated successfully.")
            return redirect(f"{reverse('teacher:list-result')}?subject={result.subject.id}")
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
    """Modernized student results hub with rich filters, KPIs, and grading actions"""
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("account:login")
    
    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found")
        return redirect("account:login")

    # Base query: Results belonging to teacher's subjects and school
    queryset = ResultSheet.objects.filter(
        student__school=school,
        subject__teacher=teacher
    ).select_related(
        'student__user',
        'student__school',
        'subject',
        'subject__department'
    )

    # Filter parameters
    search_query = request.GET.get('search', '').strip()
    subject_id = request.GET.get('subject', '').strip()
    class_filter = request.GET.get('class', '').strip()
    term_filter = request.GET.get('term', '').strip()
    year_filter = request.GET.get('academic_year', '').strip()
    grade_filter = request.GET.get('grade', '').strip()

    if search_query:
        queryset = queryset.filter(
            Q(student__user__first_name__icontains=search_query) |
            Q(student__user__last_name__icontains=search_query) |
            Q(student__student_id__icontains=search_query) |
            Q(student__admission_number__icontains=search_query) |
            Q(subject__name__icontains=search_query)
        )

    if subject_id:
        queryset = queryset.filter(subject_id=subject_id)

    if class_filter:
        queryset = queryset.filter(student__student_class=class_filter)

    if term_filter:
        queryset = queryset.filter(term=term_filter)

    if year_filter:
        queryset = queryset.filter(academic_year=year_filter)

    if grade_filter:
        queryset = queryset.filter(grade__iexact=grade_filter)

    # Sort
    results = queryset.order_by('-exam_date', 'student__user__last_name', 'student__user__first_name')

    # Top KPI Metrics on the filtered dataset
    total_results = results.count()
    if total_results > 0:
        avg_score = results.aggregate(avg=Avg('percentage'))['avg'] or 0
        passed_count = results.filter(percentage__gte=40).count()
        pass_rate = round((passed_count / total_results) * 100, 1)
        top_count = results.filter(percentage__gte=75).count()
        distinction_rate = round((top_count / total_results) * 100, 1)
        
        # Grade distribution breakdown
        a_count = results.filter(grade__startswith='A').count()
        b_count = results.filter(grade__startswith='B').count()
        c_count = results.filter(grade__startswith='C').count()
        d_count = results.filter(grade__startswith='D').count()
        f_count = results.filter(grade='F').count()
    else:
        avg_score = 0
        pass_rate = 0
        distinction_rate = 0
        a_count = b_count = c_count = d_count = f_count = 0

    # Filter dropdown options
    teacher_subjects = Subject.objects.filter(teacher=teacher, school=school).order_by('name')
    classes = SchoolClass.objects.filter(school=school).order_by('name')
    academic_years = ResultSheet.objects.filter(
        student__school=school, 
        subject__teacher=teacher
    ).values_list('academic_year', flat=True).distinct().order_by('-academic_year')

    # Pagination: 25 items per page
    paginator = Paginator(results, 25)
    page_number = request.GET.get('page')
    try:
        page_obj = paginator.get_page(page_number)
    except Exception:
        page_obj = paginator.get_page(1)

    # Build query string for pagination links
    params = request.GET.copy()
    if 'page' in params:
        del params['page']
    pagination_query = params.urlencode()

    context = {
        "results": page_obj,
        "page_obj": page_obj,
        "paginator": paginator,
        "total_results": total_results,
        "avg_score": round(avg_score, 1),
        "pass_rate": pass_rate,
        "distinction_rate": distinction_rate,
        "grade_distribution": {
            "A": a_count,
            "B": b_count,
            "C": c_count,
            "D": d_count,
            "F": f_count,
        },
        "teacher_subjects": teacher_subjects,
        "classes": classes,
        "academic_years": academic_years,
        "term_choices": ResultSheet.TERM_CHOICES,
        "grade_choices": ResultSheet.GRADE_CHOICES,
        "selected_search": search_query,
        "selected_subject": subject_id,
        "selected_class": class_filter,
        "selected_term": term_filter,
        "selected_year": year_filter,
        "selected_grade": grade_filter,
        "pagination_query": pagination_query,
        "title": "Student Results & Academic Records"
    }

    return render(request, "teacher/list-result.html", context)


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
    
    result = get_object_or_404(
        ResultSheet,
        id=result_id,
        student__school=school,
        subject__teacher=teacher
    )
    
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("teacher:list-result")

    student_name = result.student.user.get_full_name()
    subject_name = result.subject.name
    result.delete()
    messages.success(request, f"Successfully deleted result for {student_name} ({subject_name})")
    return redirect("teacher:list-result")

    result.delete()
    messages.success(request, "You have successfully deleted the result")
    return redirect("teacher:list-result")

def mark_attendance(request):
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "You are not authorized to perform this action")
        return redirect("account:login")
    
    teacher, response = _get_attendance_teacher(request)
    if response:
        return response

    school = teacher.school
    assigned_class = teacher.class_teacher_class

    # Determine selected date
    date_str = request.GET.get('date') or request.POST.get('date')
    if date_str:
        try:
            from datetime import datetime
            selected_date = datetime.strptime(str(date_str).strip(), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            selected_date = timezone.now().date()
    else:
        selected_date = timezone.now().date()
    
    if request.method == 'POST':
        # Batch Class Roster Attendance submission
        if request.POST.get('bulk_attendance') == '1':
            student_ids = request.POST.getlist('student_ids')
            if not student_ids:
                messages.error(request, "No students found to record attendance.")
                return redirect(f"{reverse('teacher:mark-attendance')}?date={selected_date.strftime('%Y-%m-%d')}")

            saved_count = 0
            with transaction.atomic():
                for s_id in student_ids:
                    status = request.POST.get(f'status_{s_id}', 'present')
                    remarks = request.POST.get(f'remarks_{s_id}', '').strip()
                    student = get_object_or_404(Student, id=s_id, school=school, student_class=assigned_class)

                    Attendance.objects.update_or_create(
                        student=student,
                        date=selected_date,
                        defaults={
                            'attendance_type': 'student',
                            'teacher': None,
                            'class_attendance': assigned_class,
                            'status': status,
                            'remarks': remarks,
                            'marked_by': teacher.user,
                        }
                    )
                    saved_count += 1

            messages.success(request, f"Attendance recorded successfully for {saved_count} students in {assigned_class} on {selected_date.strftime('%b %d, %Y')}.")
            return redirect('teacher:attendance-list')

        # Single AttendanceForm submission
        form = AttendanceForm(school=school, teacher=teacher, data=request.POST)
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
                return render(request, 'teacher/add_attendance.html', {'form': form, 'title': 'Add Attendance'})
            if attendance.teacher and attendance.teacher.school != school:
                messages.error(request, "Selected teacher does not belong to your school.")
                return render(request, 'teacher/add_attendance.html', {'form': form, 'title': 'Add Attendance'})

            try:
                if attendance.student:
                    Attendance.objects.update_or_create(
                        student=attendance.student,
                        date=attendance.date,
                        defaults={
                            'attendance_type': 'student',
                            'teacher': None,
                            'class_attendance': attendance.class_attendance or assigned_class,
                            'status': attendance.status,
                            'remarks': attendance.remarks,
                            'marked_by': teacher.user,
                        }
                    )
                else:
                    attendance.save()

                messages.success(request, "Attendance record created successfully.")
                return redirect('teacher:attendance-list')
            except Exception as e:
                messages.error(request, f"Error saving attendance: {e}")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AttendanceForm(school=school, teacher=teacher, initial={'date': selected_date})

    # Prepare roster data for class teacher
    roster_students = []
    class_students_count = 0
    stats = {'present': 0, 'absent': 0, 'late': 0, 'excused': 0, 'total_marked': 0}

    if teacher.can_take_attendance and assigned_class:
        students_qs = Student.objects.filter(
            student_class=assigned_class,
            school=school,
            is_active=True
        ).select_related('user').order_by('user__first_name', 'user__last_name')

        class_students_count = students_qs.count()

        existing_qs = Attendance.objects.filter(
            class_attendance=assigned_class,
            date=selected_date,
            attendance_type='student'
        )
        existing_attendance_map = {att.student_id: att for att in existing_qs}

        for s in students_qs:
            existing_rec = existing_attendance_map.get(s.id)
            current_status = existing_rec.status if existing_rec else 'present'
            current_remarks = existing_rec.remarks if existing_rec else ''
            is_marked = existing_rec is not None

            if is_marked:
                stats['total_marked'] += 1
                if current_status in stats:
                    stats[current_status] += 1

            roster_students.append({
                'student': s,
                'status': current_status,
                'remarks': current_remarks,
                'is_marked': is_marked,
            })

    context = {
        'form': form,
        'title': 'Mark Class Attendance',
        'teacher': teacher,
        'assigned_class': assigned_class,
        'selected_date': selected_date,
        'selected_date_str': selected_date.strftime('%Y-%m-%d'),
        'roster_students': roster_students,
        'class_students_count': class_students_count,
        'stats': stats,
        'is_already_marked': stats['total_marked'] > 0,
    }
    return render(request, 'teacher/add_attendance.html', context)


@login_required
def attendance_update(request, attendance_id):
    attendance = get_object_or_404(Attendance, id=attendance_id)
    user = request.user

    school = None
    teacher = None
    if user.role == "teacher":
        teacher, response = _get_attendance_teacher(request)
        if response:
            return response
        school = teacher.school
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
    if teacher and (
        attendance.attendance_type != "student"
        or attendance.class_attendance != teacher.class_teacher_class
        or (attendance.student and attendance.student.student_class != teacher.class_teacher_class)
    ):
        raise Http404

    if request.method == 'POST':
        form = AttendanceForm(school=school, teacher=teacher, data=request.POST, instance=attendance)
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
        form = AttendanceForm(school=school, teacher=teacher, instance=attendance)

    return render(request, 'teacher/add_attendance.html', {
        'form': form,
        'title': 'Edit Attendance Record',
        'attendance': attendance,
        'is_edit_mode': True,
        'teacher': teacher,
    })


@login_required
def attendance_delete(request, attendance_id):
    attendance = get_object_or_404(Attendance, id=attendance_id)
    user = request.user

    school = None
    teacher = None
    if user.role == "teacher":
        teacher, response = _get_attendance_teacher(request)
        if response:
            return response
        school = teacher.school
    elif user.role == "admin":
        school = getattr(user, 'managed_school', None)

    if not school:
        raise Http404

    if (attendance.student and attendance.student.school != school) or        (attendance.teacher and attendance.teacher.school != school):
        raise Http404
    if teacher and (
        attendance.attendance_type != "student"
        or attendance.class_attendance != teacher.class_teacher_class
        or (attendance.student and attendance.student.student_class != teacher.class_teacher_class)
    ):
        raise Http404

    if request.method == 'POST':
        attendance.delete()
        messages.success(request, "Attendance record deleted.")
        return redirect('teacher:attendance-list')

    return render(request, 'teacher/attendance_confirm_delete.html', {'attendance': attendance})


@login_required
def attendance_list(request):
    user = request.user
    school = None
    teacher = None
    if user.role == "admin":
        school = getattr(user, 'managed_school', None)
        if not school:
            messages.error(request, "Admin school not found.")
            return redirect("account:dashboard")
        attendances = Attendance.objects.filter(Q(student__school=school) | Q(teacher__school=school))
    elif user.role == "teacher":
        teacher, response = _get_attendance_teacher(request)
        if response:
            return response
        school = teacher.school
        attendances = Attendance.objects.filter(
            student__school=school,
            attendance_type="student",
            class_attendance=teacher.class_teacher_class,
            student__student_class=teacher.class_teacher_class,
        )
    elif user.role == "student":
        attendances = Attendance.objects.filter(student__user=user)
    else:
        messages.error(request, "You don't have permission to view attendance.")
        return redirect("account:dashboard")

    # Filters
    date_filter = request.GET.get('date', '').strip()
    status_filter = request.GET.get('status', '').strip()
    search_query = request.GET.get('q', '').strip()

    if date_filter:
        try:
            from datetime import datetime
            filter_date_obj = datetime.strptime(date_filter, '%Y-%m-%d').date()
            attendances = attendances.filter(date=filter_date_obj)
        except ValueError:
            pass

    if status_filter:
        attendances = attendances.filter(status=status_filter)

    if search_query:
        attendances = attendances.filter(
            Q(student__user__first_name__icontains=search_query) |
            Q(student__user__last_name__icontains=search_query) |
            Q(student__student_id__icontains=search_query) |
            Q(teacher__user__first_name__icontains=search_query) |
            Q(teacher__user__last_name__icontains=search_query)
        )

    attendances = attendances.select_related('student__user', 'teacher__user', 'marked_by', 'class_attendance').order_by('-date', 'student__user__first_name')

    # Metrics computation
    now_date = timezone.now().date()
    today_records = attendances.filter(date=now_date)
    today_present = today_records.filter(status='present').count()
    today_absent = today_records.filter(status='absent').count()
    today_late = today_records.filter(status='late').count()
    today_total = today_records.count()
    today_rate = round((today_present / today_total * 100), 1) if today_total > 0 else 0

    context = {
        'attendances': attendances,
        'teacher': teacher,
        'date_filter': date_filter,
        'status_filter': status_filter,
        'search_query': search_query,
        'today_records_count': today_total,
        'today_present': today_present,
        'today_absent': today_absent,
        'today_late': today_late,
        'today_rate': today_rate,
        'today_date': now_date,
    }

    if user.role in {"admin", "teacher"} and school:
        cache_suffix = f"attendance:{user.id}"
        if user.role == "teacher":
            cache_suffix = f"attendance:{user.id}:{teacher.class_teacher_class_id or 'none'}:{teacher.is_class_teacher}:{date_filter}:{status_filter}:{search_query}"
        cache_key = make_cache_key("teacher_portal", school.id, cache_suffix)
        if should_cache(request):
            cached_response = cache.get(cache_key)
            if cached_response:
                return cached_response
        response = render(request, 'teacher/attendance_list.html', context)
        if should_cache(request):
            cache.set(cache_key, response, 120)
        return response

    return render(request, 'teacher/attendance_list.html', context)





@login_required
def teacher_students(request):
    """
    Modernized student directory for teacher:
    - Lists all students taught across assigned subjects with user, parent, and enrollment prefetching
    - Multi-filter by subject and class
    - Search by student name, ID, admission number, parent name/phone
    - Top KPI cards: Total Students, Subjects Taught, Active Classes, Class Teacher Role
    - Direct actions: View Academic Report, Enter Grades, Contact Parent
    """
    if not hasattr(request.user, 'teacher_profile'):
        messages.error(request, "Access denied. Teacher profile required.")
        return redirect('account:login')
    
    try:
        teacher = get_object_or_404(Teacher, user=request.user)
        school = teacher.school
        
        # Get all subjects taught by this teacher in this school
        subjects_taught = Subject.objects.filter(
            teacher=teacher,
            school=school
        ).select_related('department').order_by('name')
        
        # Query params
        search_query = request.GET.get('search', '').strip()
        selected_subject_id = request.GET.get('subject', '').strip()
        selected_class = request.GET.get('class', '').strip()

        # Base students queryset
        students_qs = Student.objects.filter(
            school=school,
            enrollments__subject__in=subjects_taught,
            enrollments__is_active=True
        ).distinct().select_related('user', 'parent', 'school').order_by('user__last_name', 'user__first_name')

        if selected_subject_id:
            students_qs = students_qs.filter(enrollments__subject_id=selected_subject_id)

        if selected_class:
            students_qs = students_qs.filter(student_class=selected_class)

        if search_query:
            students_qs = students_qs.filter(
                Q(user__first_name__icontains=search_query) |
                Q(user__last_name__icontains=search_query) |
                Q(student_id__icontains=search_query) |
                Q(admission_number__icontains=search_query) |
                Q(user__email__icontains=search_query) |
                Q(parent__father_name__icontains=search_query) |
                Q(parent__mother_name__icontains=search_query) |
                Q(parent__father_phone__icontains=search_query) |
                Q(parent__mother_phone__icontains=search_query)
            )

        # Unfiltered scope counts for KPI cards
        all_teacher_students = Student.objects.filter(
            school=school,
            enrollments__subject__in=subjects_taught,
            enrollments__is_active=True
        ).distinct()
        total_students_count = all_teacher_students.count()
        total_subjects_count = subjects_taught.count()
        total_classes_count = all_teacher_students.values_list('student_class', flat=True).distinct().count()

        # Map teacher's subjects per student
        enrollments = Enrollment.objects.filter(
            student__in=students_qs,
            subject__in=subjects_taught,
            is_active=True
        ).select_related('subject')

        student_subjects_map = {}
        for enr in enrollments:
            if enr.student_id not in student_subjects_map:
                student_subjects_map[enr.student_id] = []
            student_subjects_map[enr.student_id].append(enr.subject)

        # Build list of student objects with teacher_subjects attached
        students_list = list(students_qs)
        for st in students_list:
            st.teacher_subjects = student_subjects_map.get(st.id, [])

        # Pagination: 25 per page
        paginator = Paginator(students_list, 25)
        page_number = request.GET.get('page')
        try:
            page_obj = paginator.get_page(page_number)
        except Exception:
            page_obj = paginator.get_page(1)

        # Pagination query string
        params = request.GET.copy()
        if 'page' in params:
            del params['page']
        pagination_query = params.urlencode()

        available_classes = SchoolClass.objects.filter(school=school).order_by('name')

        context = {
            'teacher': teacher,
            'school': school,
            'students': page_obj,
            'page_obj': page_obj,
            'paginator': paginator,
            'filtered_count': len(students_list),
            'total_students_count': total_students_count,
            'total_subjects_count': total_subjects_count,
            'total_classes_count': total_classes_count,
            'subjects_taught': subjects_taught,
            'available_classes': available_classes,
            'selected_search': search_query,
            'selected_subject': selected_subject_id,
            'selected_class': selected_class,
            'pagination_query': pagination_query,
            'title': 'My Students Directory',
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
    Dedicated class roster view for a specific subject
    """
    if not hasattr(request.user, 'teacher_profile'):
        messages.error(request, "Access denied. Teacher profile required.")
        return redirect('account:login')
    
    try:
        teacher = get_object_or_404(Teacher, user=request.user)
        school = teacher.school
        
        if not subject_id:
            return redirect('teacher:teacher-students')

        subject = get_object_or_404(Subject, id=subject_id, teacher=teacher, school=school)
        
        search_query = request.GET.get('search', '').strip()
        students_qs = Student.objects.filter(
            school=school,
            enrollments__subject=subject,
            enrollments__is_active=True
        ).distinct().select_related('user', 'parent').order_by('user__last_name', 'user__first_name')
        
        if search_query:
            students_qs = students_qs.filter(
                Q(user__first_name__icontains=search_query) |
                Q(user__last_name__icontains=search_query) |
                Q(student_id__icontains=search_query) |
                Q(admission_number__icontains=search_query)
            )

        total_students = students_qs.count()
        results_count = ResultSheet.objects.filter(
            subject=subject,
            student__school=school
        ).count()
        
        context = {
            'teacher': teacher,
            'subject': subject,
            'students': students_qs,
            'subject_name': subject.name,
            'total_students': total_students,
            'results_count': results_count,
            'selected_search': search_query,
            'title': f"{subject.name} - Class Roster",
        }
        
        return render(request, 'teacher/teacher_students_list.html', context)
    
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found.")
        return redirect('teacher:teacher-dashboard')
    except Subject.DoesNotExist:
        messages.error(request, "Subject not found or you don't have permission to access it.")
        return redirect('teacher:teacher-students')

    
    
def view_result(request, student_id):
    """View student results with proper authorization, filtering, and summary statistics"""

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

    # Base results queryset
    queryset = ResultSheet.objects.filter(student=student).select_related(
        'subject', 'subject__department'
    ).order_by('-academic_year', '-term', 'subject__name')

    selected_year = request.GET.get('academic_year', '').strip()
    selected_term = request.GET.get('term', '').strip()

    if selected_year:
        queryset = queryset.filter(academic_year=selected_year)
    if selected_term:
        queryset = queryset.filter(term=selected_term)

    results = queryset

    # Available academic years and terms for filter dropdown
    all_student_results = ResultSheet.objects.filter(student=student)
    available_years = all_student_results.values_list('academic_year', flat=True).distinct().order_by('-academic_year')
    available_terms = ResultSheet.TERM_CHOICES

    # Calculate summary statistics
    total_subjects = results.count()
    if total_subjects > 0:
        avg_perc = results.aggregate(avg=Avg('percentage'))['avg'] or 0
        max_perc = results.aggregate(max_val=Max('percentage'))['max_val'] or 0
        min_perc = results.aggregate(min_val=Min('percentage'))['min_val'] or 0
        passed_subjects = results.filter(percentage__gte=40).count()
        pass_rate = round((passed_subjects / total_subjects) * 100, 1)
    else:
        avg_perc = max_perc = min_perc = pass_rate = 0
        passed_subjects = 0

    result_summary = {
        'total_subjects': total_subjects,
        'average_percentage': round(avg_perc, 2),
        'highest_score': round(max_perc, 2),
        'lowest_score': round(min_perc, 2),
        'passed_subjects': passed_subjects,
        'pass_rate': pass_rate,
    }
    
    return render(request, "teacher/view_result.html", {
        "results": results,
        "student": student,
        "result_summary": result_summary,
        "available_years": available_years,
        "available_terms": available_terms,
        "selected_year": selected_year,
        "selected_term": selected_term,
        "title": f"Result Sheet - {student.user.get_full_name()}"
    })



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
        form = AssignmentForm(school=school, teacher=teacher, data=request.POST, files=request.FILES)
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
    else:
        form = AssignmentForm(school=school, teacher=teacher)

    return render(request, 'teacher/add_assignment.html', {
        'form': form, 
        'title': 'Add Assignment',
        'subjects': subjects,
        'teacher': teacher,
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

    assignment = get_object_or_404(
        Assignment,
        id=assignment_id,
        teacher=teacher,
        subject__school=school  
    )

    if request.method == "POST":
        form = AssignmentForm(school=school, teacher=teacher, data=request.POST, files=request.FILES, instance=assignment)
        if form.is_valid():
            form.save()
            messages.success(request, "Assignment updated successfully.")
            return redirect("teacher:assignment-list")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AssignmentForm(school=school, teacher=teacher, instance=assignment)

    return render(request, 'teacher/add_assignment.html', {
        'form': form,
        'title': 'Edit Assignment',
        'assignment': assignment,
        'teacher': teacher,
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

    search_query = request.GET.get('q', '').strip()
    subject_filter = request.GET.get('subject', '').strip()
    class_filter = request.GET.get('class', '').strip()
    status_filter = request.GET.get('status', '').strip()

    all_assignments = Assignment.objects.filter(
        teacher=teacher,
        subject__school=school
    ).select_related('subject', 'student_class')

    teacher_subjects = Subject.objects.filter(teacher=teacher, school=school).distinct()
    class_ids = set(all_assignments.values_list('student_class_id', flat=True))
    teacher_classes = SchoolClass.objects.filter(id__in=class_ids).order_by('order', 'name') if class_ids else SchoolClass.objects.none()

    now_date = timezone.now().date()
    total_assignments_count = all_assignments.count()
    active_assignments_count = all_assignments.filter(due_date__gte=now_date).exclude(status='closed').count()

    all_submissions = AssignmentSubmission.objects.filter(assignment__teacher=teacher)
    total_submissions_count = all_submissions.count()
    pending_grading_count = all_submissions.filter(status__in=['submitted', 'late']).count()
    graded_count = all_submissions.filter(status='graded').count()

    assignments_qs = all_assignments
    if search_query:
        assignments_qs = assignments_qs.filter(
            Q(title__icontains=search_query) | Q(description__icontains=search_query)
        )
    if subject_filter:
        assignments_qs = assignments_qs.filter(subject_id=subject_filter)
    if class_filter:
        assignments_qs = assignments_qs.filter(student_class_id=class_filter)
    if status_filter == 'active':
        assignments_qs = assignments_qs.filter(due_date__gte=now_date).exclude(status='closed')
    elif status_filter == 'overdue':
        assignments_qs = assignments_qs.filter(due_date__lt=now_date).exclude(status='closed')
    elif status_filter == 'closed':
        assignments_qs = assignments_qs.filter(status='closed')

    assignments = assignments_qs.annotate(
        submission_count=Count('submissions'),
        pending_sub_count=Count('submissions', filter=Q(submissions__status__in=['submitted', 'late']))
    ).order_by('-created_at')

    context = {
        'assignments': assignments,
        'total_assignments': total_assignments_count,
        'active_assignments': active_assignments_count,
        'total_submissions': total_submissions_count,
        'pending_grading_count': pending_grading_count,
        'graded_count': graded_count,
        'teacher_subjects': teacher_subjects,
        'teacher_classes': teacher_classes,
        'search_query': search_query,
        'subject_filter': subject_filter,
        'class_filter': class_filter,
        'status_filter': status_filter,
    }

    cache_key = make_cache_key(
        "teacher_portal",
        school.id,
        f"assignments:{teacher.id}:{search_query}:{subject_filter}:{class_filter}:{status_filter}"
    )
    if should_cache(request):
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

    response = render(request, 'teacher/assignment_list.html', context)
    if should_cache(request):
        cache.set(cache_key, response, 180)
    return response


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

    assignment = get_object_or_404(Assignment, id=assignment_id, teacher=teacher, subject__school=school)

    if request.method != 'POST':
        return render(request, 'teacher/assignment_confirm_delete.html', {
            'assignment': assignment
        })

    assignment.delete()
    messages.success(request, "Assignment deleted successfully.")
    return redirect('teacher:assignment-list')


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

    assignment = get_object_or_404(Assignment, id=assignment_id, teacher=teacher, subject__school=school)

    status_filter = request.GET.get('status', '').strip()
    search_query = request.GET.get('q', '').strip()

    submissions_qs = AssignmentSubmission.objects.filter(assignment=assignment).select_related('student__user', 'student__student_class').order_by('-submission_date')

    if status_filter:
        submissions_qs = submissions_qs.filter(status=status_filter)
    if search_query:
        submissions_qs = submissions_qs.filter(
            Q(student__user__first_name__icontains=search_query) |
            Q(student__user__last_name__icontains=search_query) |
            Q(student__student_id__icontains=search_query)
        )

    all_subs = AssignmentSubmission.objects.filter(assignment=assignment)
    total_students = Student.objects.filter(student_class=assignment.student_class, school=school, is_active=True).count()

    submission_stats = {
        'total': total_students,
        'submitted': all_subs.filter(status__in=['submitted', 'graded', 'late']).count(),
        'graded': all_subs.filter(status='graded').count(),
        'pending': all_subs.filter(status__in=['submitted', 'late']).count(),
        'late': all_subs.filter(status='late').count(),
        'not_submitted': max(0, total_students - all_subs.filter(status__in=['submitted', 'graded', 'late']).count())
    }

    return render(request, 'teacher/assignment_submissions.html', {
        'assignment': assignment,
        'submissions': submissions_qs,
        'submission_stats': submission_stats,
        'total_students': total_students,
        'status_filter': status_filter,
        'search_query': search_query,
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
    
    next_submission = AssignmentSubmission.objects.filter(
        assignment=submission.assignment,
        status__in=['submitted', 'late']
    ).exclude(id=submission.id).first()

    return render(request, 'teacher/grade_assignment.html', {
        'submission': submission,
        'next_submission': next_submission,
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
    AI Academic Performance & Risk Forecasting Dashboard.
    Provides ML-driven performance predictions, risk classification,
    intervention recommendations, and multi-filtering.
    """
    if request.user.role not in {"teacher", "admin"}:
        messages.error(request, "You are not authorized to view AI insights.")
        return redirect("account:login")

    school = None
    teacher = None
    if request.user.role == "teacher":
        teacher = getattr(request.user, "teacher_profile", None)
        school = teacher.school if teacher else None
    else:
        school = getattr(request.user, "managed_school", None)

    if not school:
        messages.error(request, "School profile not found.")
        return redirect("account:login")

    # Filters
    search_query = request.GET.get("search", "").strip()
    selected_risk = request.GET.get("risk", "").strip()
    selected_class = request.GET.get("class", "").strip()
    selected_grade = request.GET.get("grade", "").strip()

    # Base query for all predictions in school
    all_preds_qs = PredictedPerformance.objects.filter(student__school=school)
    total_analyzed = all_preds_qs.count()
    high_risk_count = all_preds_qs.filter(risk_level__iexact="High").count()
    medium_risk_count = all_preds_qs.filter(risk_level__iexact="Medium").count()
    low_risk_count = all_preds_qs.filter(risk_level__iexact="Low").count()

    # Filtered query
    predictions_qs = (
        PredictedPerformance.objects
        .select_related("student", "student__user", "student__parent", "student__student_class")
        .filter(student__school=school)
        .order_by("-created_at")
    )

    if selected_risk:
        predictions_qs = predictions_qs.filter(risk_level__iexact=selected_risk)

    if selected_grade:
        predictions_qs = predictions_qs.filter(predicted_grade__iexact=selected_grade)

    if selected_class:
        predictions_qs = predictions_qs.filter(
            Q(student__student_class__code=selected_class) |
            Q(student__student_class__name=selected_class)
        )

    if search_query:
        predictions_qs = predictions_qs.filter(
            Q(student__user__first_name__icontains=search_query) |
            Q(student__user__last_name__icontains=search_query) |
            Q(student__student_id__icontains=search_query) |
            Q(student__admission_number__icontains=search_query)
        )

    predictions = list(predictions_qs)
    for p in predictions:
        avg_score = ResultSheet.objects.filter(student=p.student).aggregate(avg=models.Avg("percentage"))["avg"]
        p.actual_avg = round(avg_score, 1) if avg_score is not None else None
        p.results_count = ResultSheet.objects.filter(student=p.student).count()

    risk_summary = [
        {"risk_level": "High", "count": high_risk_count, "color": "#ef4444"},
        {"risk_level": "Medium", "count": medium_risk_count, "color": "#f59e0b"},
        {"risk_level": "Low", "count": low_risk_count, "color": "#10b981"},
    ]

    grade_distribution = [
        {"grade": "A", "count": all_preds_qs.filter(predicted_grade="A").count()},
        {"grade": "B", "count": all_preds_qs.filter(predicted_grade="B").count()},
        {"grade": "C", "count": all_preds_qs.filter(predicted_grade="C").count()},
        {"grade": "D", "count": all_preds_qs.filter(predicted_grade="D").count()},
        {"grade": "F", "count": all_preds_qs.filter(predicted_grade="F").count()},
    ]

    available_classes = _get_school_classes(school)
    total_school_students = Student.objects.filter(school=school, is_active=True).count()
    unpredicted_count = max(0, total_school_students - total_analyzed)

    context = {
        "teacher": teacher,
        "school": school,
        "data": predictions,
        "filtered_count": len(predictions),
        "total_analyzed": total_analyzed,
        "total_school_students": total_school_students,
        "unpredicted_count": unpredicted_count,
        "high_risk_count": high_risk_count,
        "medium_risk_count": medium_risk_count,
        "low_risk_count": low_risk_count,
        "risk_summary": risk_summary,
        "grade_distribution": grade_distribution,
        "available_classes": available_classes,
        "selected_risk": selected_risk,
        "selected_class": selected_class,
        "selected_grade": selected_grade,
        "selected_search": search_query,
        "title": "AI Academic Insights & Risk Forecasting",
    }

    return render(request, "teacher/dashboard.html", context)


def _get_school_classes(school):
    """Return all active classes available to this school, ordered by progression order."""
    return list(SchoolClass.objects.filter(
        Q(school=school) | Q(school__isnull=True),
        is_active=True
    ).order_by('order', 'name'))


def _resolve_class_identifier(school, class_name):
    """Resolve a class identifier (name, code, or UUID) to a SchoolClass instance"""
    if not class_name:
        return None
    if isinstance(class_name, SchoolClass):
        return class_name

    class_str = str(class_name).strip()
    qs = SchoolClass.objects.filter(
        Q(school=school) | Q(school__isnull=True),
        is_active=True
    )
    sc = qs.filter(Q(code__iexact=class_str) | Q(name__iexact=class_str)).first()
    if not sc:
        try:
            sc = qs.filter(id=class_str).first()
        except Exception:
            pass
    if not sc:
        from account.models import LEGACY_CLASS_MAP
        target = LEGACY_CLASS_MAP.get(class_str.upper())
        if target:
            sc = qs.filter(Q(name__iexact=target) | Q(code__iexact=target)).first()
    return sc


def _is_teacher_in_charge_of_class(teacher, class_identifier, school):
    """
    Check if the teacher is an authorized class teacher for the given class identifier.
    Class teachers are ONLY authorized to promote or edit promotions for their assigned class.
    """
    if not teacher or not getattr(teacher, 'is_class_teacher', False) or not getattr(teacher, 'class_teacher_class', None):
        return False

    assigned_class = teacher.class_teacher_class
    target_class = _resolve_class_identifier(school, class_identifier)
    if not target_class:
        target_str = str(class_identifier).strip().lower()
        assigned_name = str(assigned_class.name).strip().lower() if getattr(assigned_class, 'name', None) else ""
        assigned_code = str(assigned_class.code).strip().lower() if getattr(assigned_class, 'code', None) else ""
        return target_str in (assigned_name, assigned_code, str(assigned_class.id).lower())

    return (
        assigned_class.id == target_class.id or
        (assigned_class.code and target_class.code and assigned_class.code.lower() == target_class.code.lower()) or
        (assigned_class.name and target_class.name and assigned_class.name.lower() == target_class.name.lower())
    )


@login_required
def promotion_dashboard(request):
    """Main promotion management dashboard with class teacher permission indicators"""
    if request.user.role != "teacher" and request.user.role != "admin":
        messages.error(request, "You are not authorized to access this page.")
        return redirect("account:login")

    try:
        is_admin = (request.user.role == "admin")
        if not is_admin:
            teacher = request.user.teacher_profile
            school = teacher.school
        else:
            teacher = None
            school = request.user.managed_school
    except Exception as e:
        messages.error(request, "Profile not found.")
        return redirect("account:login")

    available_classes = _get_school_classes(school)
    classes_data = []

    assigned_class = getattr(teacher, 'class_teacher_class', None) if teacher else None
    is_class_teacher = bool(teacher and teacher.is_class_teacher and assigned_class)

    my_class_data = None

    for sc in available_classes:
        student_count = Student.objects.filter(
            school=school,
            student_class=sc,
            is_active=True
        ).count()
        promoted_count = Student.objects.filter(
            school=school,
            student_class=sc,
            promotion_status='promoted',
            is_active=True
        ).count()
        retained_count = Student.objects.filter(
            school=school,
            student_class=sc,
            promotion_status='retained',
            is_active=True
        ).count()
        pending_count = student_count - (promoted_count + retained_count)
        if pending_count < 0:
            pending_count = 0

        is_my_class = False
        if teacher and assigned_class:
            is_my_class = (
                sc.id == assigned_class.id or
                (sc.code and assigned_class.code and sc.code.lower() == assigned_class.code.lower()) or
                (sc.name and assigned_class.name and sc.name.lower() == assigned_class.name.lower())
            )

        can_manage = is_admin or is_my_class

        c_info = {
            'code': sc.code or str(sc.id),
            'name': sc.name,
            'student_count': student_count,
            'promoted_count': promoted_count,
            'retained_count': retained_count,
            'pending_count': pending_count,
            'id': sc.id,
            'is_my_class': is_my_class,
            'can_manage': can_manage,
        }
        classes_data.append(c_info)
        if is_my_class:
            my_class_data = c_info

    recent_promotions = PromotionHistory.objects.filter(
        student__school=school
    ).select_related('student__user', 'promoted_by', 'from_class', 'to_class').order_by('-promotion_date')[:10]

    student_class_keys = [(c.code or str(c.id), c.name) for c in available_classes]

    total_students_school = Student.objects.filter(school=school, is_active=True).count()
    total_promoted_school = PromotionHistory.objects.filter(student__school=school).count()

    context = {
        'teacher': teacher,
        'school': school,
        'is_admin': is_admin,
        'is_class_teacher': is_class_teacher,
        'assigned_class': assigned_class,
        'my_class_data': my_class_data,
        'classes': classes_data,
        'recent_promotions': recent_promotions,
        'student_class_keys': student_class_keys,
        'total_students_school': total_students_school,
        'total_promoted_school': total_promoted_school,
        'title': 'Student Promotion Management',
    }

    return render(request, "teacher/promotion_dashboard.html", context)


@login_required
def view_class_students(request, class_name):
    """View students in a specific class for promotion with strict class teacher enforcement"""
    if request.user.role != "teacher" and request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")

    try:
        is_admin = (request.user.role == "admin")
        if not is_admin:
            teacher = request.user.teacher_profile
            school = teacher.school
            if not teacher.is_class_teacher or not teacher.class_teacher_class:
                messages.error(request, "Access restricted: Only designated Class Teachers can manage student promotions.")
                return redirect("teacher:teacher-dashboard")
            if not _is_teacher_in_charge_of_class(teacher, class_name, school):
                messages.error(
                    request,
                    f"Access restricted: You are only authorized to manage promotions for your assigned class ({teacher.get_class_teacher_class_display()})."
                )
                if teacher.class_teacher_class:
                    own_class_code = teacher.class_teacher_class.code or str(teacher.class_teacher_class.id)
                    return redirect("teacher:view-class-students", class_name=own_class_code)
                return redirect("teacher:promotion-dashboard")
        else:
            teacher = None
            school = request.user.managed_school
    except Exception as e:
        messages.error(request, "Profile not found.")
        return redirect("account:login")

    school_class = _resolve_class_identifier(school, class_name)
    if school_class:
        students_qs = Student.objects.filter(
            school=school,
            student_class=school_class,
            is_active=True
        ).select_related('user', 'parent').order_by('user__last_name', 'user__first_name')
        current_display = school_class.name
    else:
        students_qs = Student.objects.filter(
            school=school,
            student_class=class_name,
            is_active=True
        ).select_related('user', 'parent').order_by('user__last_name', 'user__first_name')
        current_display = class_name

    available_classes = _get_school_classes(school)
    next_class = None
    next_class_name = "Graduation"
    if school_class and school_class in available_classes:
        curr_idx = available_classes.index(school_class)
        if curr_idx < len(available_classes) - 1:
            next_class_obj = available_classes[curr_idx + 1]
            next_class = next_class_obj.code or str(next_class_obj.id)
            next_class_name = next_class_obj.name

    students = list(students_qs)
    for st in students:
        avg_score = ResultSheet.objects.filter(student=st).aggregate(avg=models.Avg('percentage'))['avg']
        st.academic_avg = round(avg_score, 1) if avg_score is not None else None

    total_in_class = len(students)
    promoted_count = sum(1 for s in students if s.promotion_status == 'promoted')
    retained_count = sum(1 for s in students if s.promotion_status == 'retained')
    graduated_count = sum(1 for s in students if s.promotion_status == 'graduated')
    pending_count = total_in_class - (promoted_count + retained_count + graduated_count)

    context = {
        'teacher': teacher,
        'school': school,
        'school_class': school_class,
        'students': students,
        'current_class': class_name,
        'current_class_display': current_display,
        'next_class': next_class,
        'next_class_name': next_class_name,
        'is_final_class': next_class is None,
        'total_in_class': total_in_class,
        'promoted_count': promoted_count,
        'retained_count': retained_count,
        'graduated_count': graduated_count,
        'pending_count': pending_count,
        'is_admin': is_admin,
        'title': f"Students in {current_display}",
    }

    return render(request, "teacher/class_students.html", context)


@login_required
def bulk_promote_students(request, class_name):
    """Bulk promote students with strict class teacher authorization"""
    if request.user.role != "teacher" and request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")

    try:
        is_admin = (request.user.role == "admin")
        if not is_admin:
            teacher = request.user.teacher_profile
            school = teacher.school
            promoted_by = request.user
            if not teacher.is_class_teacher or not teacher.class_teacher_class:
                messages.error(request, "Access restricted: Only designated Class Teachers can manage student promotions.")
                return redirect("teacher:teacher-dashboard")
            if not _is_teacher_in_charge_of_class(teacher, class_name, school):
                messages.error(
                    request,
                    f"Access denied: You are only authorized to promote students in your assigned class ({teacher.get_class_teacher_class_display()})."
                )
                return redirect("teacher:promotion-dashboard")
        else:
            teacher = None
            school = request.user.managed_school
            promoted_by = request.user
    except Exception as e:
        messages.error(request, "Profile not found.")
        return redirect("account:login")

    school_class = _resolve_class_identifier(school, class_name)
    available_classes = _get_school_classes(school)
    next_class_obj = None
    if school_class and school_class in available_classes:
        curr_idx = available_classes.index(school_class)
        if curr_idx < len(available_classes) - 1:
            next_class_obj = available_classes[curr_idx + 1]

    if request.method == "POST":
        student_ids = request.POST.getlist('student_ids')
        promotion_action = request.POST.get('promotion_action', 'promote')
        academic_year = request.POST.get('academic_year', school.get_current_academic_year())
        bulk_remarks = request.POST.get('remarks', '').strip()

        if not student_ids:
            messages.error(request, "No students selected for promotion.")
            return redirect('teacher:bulk-promote', class_name=class_name)

        promoted_count = 0
        retained_count = 0
        graduated_count = 0

        try:
            with transaction.atomic():
                for student_id in student_ids:
                    student = Student.objects.get(id=student_id, school=school)

                    if promotion_action == 'promote' and next_class_obj:
                        student.previous_class = student.student_class
                        student.student_class = next_class_obj
                        student.promotion_status = 'promoted'
                        student.promoted_to = None
                        student.promotion_date = timezone.now().date()
                        student.save()

                        PromotionHistory.objects.create(
                            student=student,
                            from_class=school_class or student.previous_class,
                            to_class=next_class_obj,
                            academic_year=academic_year,
                            promotion_date=timezone.now().date(),
                            promoted_by=promoted_by,
                            remarks=bulk_remarks or f"Bulk promotion from {school_class.name if school_class else class_name} to {next_class_obj.name}"
                        )

                        auto_enroll_student_in_new_class(student, next_class_obj)
                        promoted_count += 1

                    elif promotion_action == 'retain':
                        student.promotion_status = 'retained'
                        student.promoted_to = None
                        student.promotion_date = timezone.now().date()
                        student.save()

                        PromotionHistory.objects.create(
                            student=student,
                            from_class=school_class or student.student_class,
                            to_class=school_class or student.student_class,
                            academic_year=academic_year,
                            promotion_date=timezone.now().date(),
                            promoted_by=promoted_by,
                            remarks=bulk_remarks or f"Retained in {school_class.name if school_class else class_name}"
                        )
                        retained_count += 1

                    elif promotion_action == 'graduate' and not next_class_obj:
                        student.promotion_status = 'graduated'
                        student.promoted_to = None
                        student.promotion_date = timezone.now().date()
                        student.is_active = False
                        student.save()

                        PromotionHistory.objects.create(
                            student=student,
                            from_class=school_class or student.student_class,
                            to_class=school_class or student.student_class,
                            academic_year=academic_year,
                            promotion_date=timezone.now().date(),
                            promoted_by=promoted_by,
                            remarks=bulk_remarks or "Graduated"
                        )
                        graduated_count += 1

                if promotion_action == 'promote':
                    target_name = next_class_obj.name if next_class_obj else "next class"
                    messages.success(request, f"Successfully promoted {promoted_count} students to {target_name}.")
                elif promotion_action == 'retain':
                    curr_name = school_class.name if school_class else class_name
                    messages.success(request, f"Successfully marked {retained_count} students as retained in {curr_name}.")
                elif promotion_action == 'graduate':
                    messages.success(request, f"Successfully graduated {graduated_count} students.")

                return redirect('teacher:view-class-students', class_name=class_name)

        except Exception as e:
            messages.error(request, f"An error occurred during bulk promotion: {str(e)}")
            return redirect('teacher:view-class-students', class_name=class_name)

    if school_class:
        students_qs = Student.objects.filter(
            school=school,
            student_class=school_class,
            is_active=True
        ).select_related('user').order_by('user__last_name', 'user__first_name')
        current_display = school_class.name
    else:
        students_qs = Student.objects.filter(
            school=school,
            student_class=class_name,
            is_active=True
        ).select_related('user').order_by('user__last_name', 'user__first_name')
        current_display = class_name

    students = list(students_qs)
    for st in students:
        avg_score = ResultSheet.objects.filter(student=st).aggregate(avg=models.Avg('percentage'))['avg']
        st.academic_avg = round(avg_score, 1) if avg_score is not None else None

    next_class_code = (next_class_obj.code or str(next_class_obj.id)) if next_class_obj else None
    next_class_name = next_class_obj.name if next_class_obj else "Graduation"

    context = {
        'teacher': teacher,
        'school': school,
        'school_class': school_class,
        'students': students,
        'current_class': class_name,
        'current_class_display': current_display,
        'next_class': next_class_code,
        'next_class_name': next_class_name,
        'is_final_class': next_class_obj is None,
        'academic_year': school.get_current_academic_year(),
        'title': f"Bulk Promote {current_display}",
    }

    return render(request, "teacher/bulk_promotion.html", context)


def auto_enroll_student_in_new_class(student, new_class):
    """Automatically enroll student in subjects for their new class"""
    try:
        new_subjects = Subject.objects.filter(
            school=student.school,
            subject_class=new_class
        )
        for subject in new_subjects:
            Enrollment.objects.get_or_create(
                student=student,
                subject=subject,
                defaults={'is_active': True}
            )

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
    """Promote or edit promotion for an individual student with strict class teacher authorization"""
    if request.user.role != "teacher" and request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")

    try:
        is_admin = (request.user.role == "admin")
        if not is_admin:
            teacher = request.user.teacher_profile
            school = teacher.school
            promoted_by = request.user
            if not teacher.is_class_teacher or not teacher.class_teacher_class:
                messages.error(request, "Access restricted: Only designated Class Teachers can manage student promotions.")
                return redirect("teacher:teacher-dashboard")
        else:
            teacher = None
            school = request.user.managed_school
            promoted_by = request.user
    except Exception as e:
        messages.error(request, "Profile not found.")
        return redirect("account:login")

    student = get_object_or_404(Student, id=student_id, school=school)

    # Class teacher check: Must be in charge of student's current class OR previous class (if already promoted/retained)
    if not is_admin:
        can_manage = _is_teacher_in_charge_of_class(teacher, student.student_class, school) or (
            student.previous_class and _is_teacher_in_charge_of_class(teacher, student.previous_class, school)
        )
        if not can_manage:
            messages.error(
                request,
                f"Access denied: You can only promote or edit promotions for students in your assigned class ({teacher.get_class_teacher_class_display()})."
            )
            return redirect("teacher:promotion-dashboard")

    available_classes = _get_school_classes(school)
    eval_class = student.student_class
    next_class_obj = None
    if eval_class and eval_class in available_classes:
        curr_idx = available_classes.index(eval_class)
        if curr_idx < len(available_classes) - 1:
            next_class_obj = available_classes[curr_idx + 1]

    if request.method == "POST":
        promotion_action = request.POST.get('promotion_action')
        academic_year = request.POST.get('academic_year', school.get_current_academic_year())
        remarks = request.POST.get('remarks', '').strip()

        try:
            with transaction.atomic():
                if promotion_action == 'promote' and next_class_obj:
                    student.previous_class = student.student_class
                    student.student_class = next_class_obj
                    student.promotion_status = 'promoted'
                    student.promoted_to = None
                    student.promotion_date = timezone.now().date()
                    student.save()

                    PromotionHistory.objects.create(
                        student=student,
                        from_class=student.previous_class,
                        to_class=next_class_obj,
                        academic_year=academic_year,
                        promotion_date=timezone.now().date(),
                        promoted_by=promoted_by,
                        remarks=remarks or f"Promoted to {next_class_obj.name}"
                    )

                    auto_enroll_student_in_new_class(student, next_class_obj)
                    messages.success(
                        request,
                        f"Successfully promoted {student.user.get_full_name()} to {next_class_obj.name}."
                    )

                elif promotion_action == 'retain':
                    student.promotion_status = 'retained'
                    student.promoted_to = None
                    student.promotion_date = timezone.now().date()
                    student.save()

                    PromotionHistory.objects.create(
                        student=student,
                        from_class=student.student_class,
                        to_class=student.student_class,
                        academic_year=academic_year,
                        promotion_date=timezone.now().date(),
                        promoted_by=promoted_by,
                        remarks=remarks or f"Retained in {student.get_student_class_display()}"
                    )
                    messages.success(
                        request,
                        f"Successfully marked {student.user.get_full_name()} as retained in {student.get_student_class_display()}."
                    )

                elif promotion_action == 'graduate' and not next_class_obj:
                    student.promotion_status = 'graduated'
                    student.promoted_to = None
                    student.promotion_date = timezone.now().date()
                    student.is_active = False
                    student.save()

                    PromotionHistory.objects.create(
                        student=student,
                        from_class=student.student_class,
                        to_class=student.student_class,
                        academic_year=academic_year,
                        promotion_date=timezone.now().date(),
                        promoted_by=promoted_by,
                        remarks=remarks or "Graduated"
                    )
                    messages.success(
                        request,
                        f"Successfully graduated {student.user.get_full_name()}."
                    )

                elif promotion_action == 'revert':
                    if student.previous_class:
                        orig_class = student.previous_class
                        curr_class = student.student_class
                        student.student_class = orig_class
                        student.previous_class = None
                        student.promotion_status = 'pending'
                        student.save()

                        auto_enroll_student_in_new_class(student, orig_class)

                        PromotionHistory.objects.create(
                            student=student,
                            from_class=curr_class,
                            to_class=orig_class,
                            academic_year=academic_year,
                            promotion_date=timezone.now().date(),
                            promoted_by=promoted_by,
                            remarks=remarks or f"Promotion reverted back to {orig_class.name}"
                        )
                        messages.success(
                            request,
                            f"Promotion reverted: {student.user.get_full_name()} restored to {orig_class.name}."
                        )
                    else:
                        student.promotion_status = 'pending'
                        student.save()
                        messages.success(
                            request,
                            f"Promotion decision reset to Pending for {student.user.get_full_name()}."
                        )

                elif promotion_action == 'edit_remarks':
                    latest_promo = PromotionHistory.objects.filter(student=student).first()
                    if latest_promo:
                        latest_promo.remarks = remarks
                        latest_promo.academic_year = academic_year
                        latest_promo.save()
                        messages.success(request, f"Promotion record updated for {student.user.get_full_name()}.")
                    else:
                        messages.info(request, "No prior promotion record to update.")

                redir_class = student.student_class.code if (student.student_class and student.student_class.code) else (str(student.student_class) if student.student_class else '')
                return redirect('teacher:view-class-students', class_name=redir_class)

        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
            return redirect('teacher:individual-promotion', student_id=student_id)

    recent_results = ResultSheet.objects.filter(
        student=student
    ).select_related('subject').order_by('-academic_year', '-term')[:10]

    average_percentage = recent_results.aggregate(avg=models.Avg('percentage'))['avg'] or 0
    next_class_name = next_class_obj.name if next_class_obj else "Graduation"

    student_promotions = PromotionHistory.objects.filter(
        student=student
    ).select_related('promoted_by', 'from_class', 'to_class').order_by('-promotion_date')

    context = {
        'teacher': teacher,
        'school': school,
        'student': student,
        'recent_results': recent_results,
        'average_percentage': round(average_percentage, 1),
        'next_class': (next_class_obj.code or str(next_class_obj.id)) if next_class_obj else None,
        'next_class_name': next_class_name,
        'can_graduate': next_class_obj is None,
        'academic_year': school.get_current_academic_year(),
        'student_promotions': student_promotions,
        'latest_promotion': student_promotions.first(),
        'can_revert': bool(student.previous_class or student.promotion_status in ['promoted', 'retained']),
        'title': f"Promote {student.user.get_full_name()}",
    }

    return render(request, "teacher/individual_promotion.html", context)


@login_required
def promotion_history(request, student_id=None):
    """View promotion history with permission context"""
    if request.user.role != "teacher" and request.user.role != "admin":
        messages.error(request, "You are not authorized.")
        return redirect("account:login")

    try:
        is_admin = (request.user.role == "admin")
        if not is_admin:
            teacher = request.user.teacher_profile
            school = teacher.school
        else:
            teacher = None
            school = request.user.managed_school
    except Exception as e:
        messages.error(request, "Profile not found.")
        return redirect("account:login")

    if student_id:
        student = get_object_or_404(Student, id=student_id, school=school)
        promotions = PromotionHistory.objects.filter(
            student=student
        ).select_related('promoted_by', 'from_class', 'to_class').order_by('-promotion_date')

        can_manage = is_admin or (
            teacher and teacher.is_class_teacher and (
                _is_teacher_in_charge_of_class(teacher, student.student_class, school) or
                (student.previous_class and _is_teacher_in_charge_of_class(teacher, student.previous_class, school))
            )
        )

        context = {
            'teacher': teacher,
            'school': school,
            'student': student,
            'promotions': promotions,
            'can_manage': can_manage,
            'title': f"Promotion History - {student.user.get_full_name()}"
        }
        return render(request, "teacher/student_promotion_history.html", context)
    else:
        promotions = PromotionHistory.objects.filter(
            student__school=school
        ).select_related('student__user', 'promoted_by', 'from_class', 'to_class').order_by('-promotion_date')

        context = {
            'teacher': teacher,
            'school': school,
            'promotions': promotions,
            'is_admin': is_admin,
            'is_class_teacher': bool(teacher and teacher.is_class_teacher),
            'title': 'School Promotion History'
        }
        return render(request, "teacher/school_promotion_history.html", context)


@login_required
def get_student_promotion_data(request, student_id):
    """AJAX endpoint to get student data for promotion decisions with class teacher authorization"""
    if request.user.role != "teacher" and request.user.role != "admin":
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    try:
        is_admin = (request.user.role == "admin")
        if not is_admin:
            teacher = request.user.teacher_profile
            school = teacher.school
            if not teacher.is_class_teacher or not teacher.class_teacher_class:
                return JsonResponse({'error': 'Class teacher profile required'}, status=403)
        else:
            teacher = None
            school = request.user.managed_school

        student = Student.objects.get(id=student_id, school=school)

        if not is_admin and not (
            _is_teacher_in_charge_of_class(teacher, student.student_class, school) or
            (student.previous_class and _is_teacher_in_charge_of_class(teacher, student.previous_class, school))
        ):
            return JsonResponse({'error': 'Access denied: Student not in your assigned class'}, status=403)

        results = ResultSheet.objects.filter(student=student)

        performance_data = {
            'total_subjects': results.count(),
            'average_percentage': results.aggregate(avg=models.Avg('percentage'))['avg'] or 0,
            'subjects_below_50': results.filter(percentage__lt=50).count(),
            'best_subject': results.order_by('-percentage').first(),
            'worst_subject': results.order_by('percentage').first(),
        }

        attendance_data = {
            'total_days': 0,
            'present_days': 0,
            'attendance_rate': 0,
        }

        return JsonResponse({
            'student': {
                'id': student.id,
                'name': student.user.get_full_name(),
                'current_class': student.get_student_class_display(),
                'admission_number': student.admission_number,
                'promotion_status': student.promotion_status,
            },
            'performance': performance_data,
            'attendance': attendance_data
        })

    except Student.DoesNotExist:
        return JsonResponse({'error': 'Student not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def teacher_timetable(request):
    """View complete weekly teaching schedule."""
    if not request.user.is_authenticated or request.user.role != "teacher":
        messages.error(request, "Access denied. Teachers only.")
        return redirect("account:login")

    try:
        teacher = request.user.teacher_profile
        school = teacher.school
    except Teacher.DoesNotExist:
        messages.error(request, "Teacher profile not found.")
        return redirect("account:login")

    all_entries = Timetable.objects.filter(
        teacher=teacher,
        school=school,
        is_active=True
    ).select_related('subject', 'student_class', 'department').order_by('start_time')

    DAYS = [
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
    ]
    days_schedule = {day_code: {'label': day_label, 'entries': []} for day_code, day_label in DAYS}
    for item in all_entries:
        if item.day_of_week in days_schedule:
            days_schedule[item.day_of_week]['entries'].append(item)

    today_day_str = timezone.now().strftime('%A').lower()

    context = {
        'teacher': teacher,
        'school': school,
        'days_schedule': days_schedule,
        'today_day': today_day_str,
        'total_periods': all_entries.count(),
        'distinct_classes': all_entries.values('student_class').distinct().count(),
    }
    return render(request, 'teacher/timetable.html', context)
