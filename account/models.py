from decimal import Decimal
from django.conf import settings
import uuid
from datetime import timedelta
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.forms import CharField
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.crypto import get_random_string
from django.core.mail import send_mail
from django.conf import settings
# from .signals import auto_enroll_class_students

def generate_generalized_integer():
    """Generate a secure random token string"""
    return get_random_string(length=50)


class CustomUser(AbstractUser):
    """Extended user model with role-based access"""
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("teacher", "Teacher"),
        ("student", "Student"),
        ("parent", "Parent"),
    ]
    GENDER_CHOICES = [
        ("male", "Male"),
        ("female", "Female"),
        ("other", "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="student")
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    profile_picture = models.ImageField(upload_to="profile_pictures/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"

    @property
    def age(self):
        """Calculate user's age"""
        if self.date_of_birth:
            today = timezone.now().date()
            return today.year - self.date_of_birth.year - (
                (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
            )
        return None


class RequestPasswordReset(models.Model):
    """Model to handle password reset requests"""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="password_resets")
    email = models.EmailField()
    token = models.CharField(max_length=50, default=generate_generalized_integer)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Password Reset for {self.user.username} ({'Used' if self.is_used else 'Pending'})"

    def save(self, *args, **kwargs):
        """Automatically set expiry time if not already set"""
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=1) 
        super().save(*args, **kwargs)

    def is_valid(self):
        """Check if token is still valid"""
        return not self.is_used and self.expires_at > timezone.now()

    def send_reset_email(self, domain=settings.DOMAIN_URL):
        """Send password reset email with token link"""
        reset_link = f"{domain}/reset-password/{self.token}/"
        subject = "Password Reset Request"
        message = f"""
        Hello {self.user.get_full_name() or self.user.username},

        You requested to reset your password. Click the link below to reset it:
        {reset_link}

        This link is valid for 1 hour.

        If you did not request this, please ignore this email.
        """
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,  
            [self.email],
            fail_silently=False,
        )
        return True

class Parent(models.Model):
    """Parent information model"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="parent_profile", null=True, blank=True)
    
    # Father's Information
    father_name = models.CharField(max_length=100)
    father_phone = models.CharField(max_length=15)
    father_occupation = models.CharField(max_length=100, blank=True)
    father_email = models.EmailField(blank=True)
    
    # Mother's Information
    mother_name = models.CharField(max_length=100)
    mother_phone = models.CharField(max_length=15)
    mother_occupation = models.CharField(max_length=100, blank=True)
    mother_email = models.EmailField(blank=True)
    
    # Address Information
    present_address = models.TextField()
    permanent_address = models.TextField(blank=True)
    
    # Emergency Contact
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=15, blank=True)
    emergency_contact_relation = models.CharField(max_length=50, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Parent"
        verbose_name_plural = "Parents"

    def __str__(self):
        return f"{self.father_name} & {self.mother_name}"


class School(models.Model):
    """School model with subscription management"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(unique=True, max_length=255, blank=True)
    logo = models.ImageField(upload_to="school_logos/", blank=True, null=True)
    location = models.CharField(max_length=255)
    address = models.TextField(blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    
    phone_number = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    
    admin = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="managed_school")
    verified = models.BooleanField(default=False)
    
    # Academic Settings
    grade_scale = models.JSONField(default=dict, help_text="Format: {\"A+\": [90, 100], \"A\": [80, 89], ...}")
    academic_year_start = models.DateField(null=True, blank=True)
    academic_year_end = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "School"
        verbose_name_plural = "Schools"
        ordering = ["name"]

    def get_default_grade_scale(self):
        """Default grading scale if none is set"""
        return {
            "A+": [97, 100],
            "A": [93, 96],
            "A-": [90, 92],
            "B+": [87, 89],
            "B": [83, 86],
            "B-": [80, 82],
            "C+": [77, 79],
            "C": [73, 76],
            "C-": [70, 72],
            "D+": [67, 69],
            "D": [65, 66],
            "F": [0, 64]
        }

    def get_current_academic_year(self):
        """Return the current academic year string like '2025/2026'."""
        if self.academic_year_start and self.academic_year_end:
            start_year = self.academic_year_start.year
            end_year = self.academic_year_end.year
            return f"{start_year}/{end_year}"
        
        # Fallback: infer from current date
        now = timezone.now().date()
        current_year = now.year
        # Assume academic year starts in September (adjust as needed)
        if now.month >= 9:  # Sept–Dec → academic year starts this year
            return f"{current_year}/{current_year + 1}"
        else:  # Jan–Aug → academic year started last year
            return f"{current_year - 1}/{current_year}"
    
    def save(self, *args, **kwargs):
        if not self.grade_scale:
            self.grade_scale = self.get_default_grade_scale()
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Package(models.Model):
    """Subscription package model"""
    PACKAGE_CHOICES = [
        ("bronze", "Bronze"),
        ("silver", "Silver"),
        ("gold", "Gold"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=20, choices=PACKAGE_CHOICES, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_days = models.IntegerField(default=30)
    max_students = models.PositiveIntegerField(default=50)
    max_teachers = models.PositiveIntegerField(default=10)
    features = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Package"
        verbose_name_plural = "Packages"

    def __str__(self):
        return f"{self.get_name_display()} Package - ₵{self.price}"


class Subscription(models.Model):
    """School subscription model"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="subscription")
    package = models.ForeignKey(Package, on_delete=models.SET_NULL, null=True, blank=True)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    is_trial = models.BooleanField(default=True)
    auto_renew = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Subscription"
        verbose_name_plural = "Subscriptions"

    def save(self, *args, **kwargs):
        if self.package and not self.end_date:
            self.end_date = self.start_date + timedelta(days=self.package.duration_days)
        super().save(*args, **kwargs)

    def is_expired(self):
        """Check if subscription has expired"""
        return self.end_date and timezone.now() > self.end_date

    def days_remaining(self):
        """Calculate days remaining in subscription"""
        if self.end_date:
            delta = self.end_date - timezone.now()
            return max(0, delta.days)
        return 0

    def __str__(self):
        pkg = self.package.get_name_display() if self.package else "Trial"
        return f"{self.school.name} - {pkg} ({'Active' if self.is_active else 'Inactive'})"


class SubscriptionHistory(models.Model):
    """Track subscription history"""
    STATUS_CHOICES = [
        ("active", "Active"),
        ("expired", "Expired"),
        ("cancelled", "Cancelled"),
        ("upgraded", "Upgraded"),
        ("downgraded", "Downgraded"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="subscription_history")
    package = models.ForeignKey(Package, on_delete=models.SET_NULL, null=True, blank=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Subscription History"
        verbose_name_plural = "Subscription Histories"
        ordering = ["-created_at"]

    def __str__(self):
        pkg = self.package.get_name_display() if self.package else "No Package"
        return f"{self.school.name} - {pkg} ({self.get_status_display()})"


class Department(models.Model):
    """Department/Class model"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, blank=True)
    description = models.TextField(blank=True)
    head_of_department = models.CharField(max_length=250, blank=True)
    number_of_students = models.PositiveIntegerField(default=0)
    max_departments = models.PositiveIntegerField(default=10)
    department_start_date = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Department"
        verbose_name_plural = "Departments"
        unique_together = ['school', 'name']

    def __str__(self):
        return f"{self.name} ({self.school.name})"


class Teacher(models.Model):
    """Teacher profile model"""
    EMPLOYMENT_TYPE_CHOICES = [
        ("full_time", "Full Time"),
        ("part_time", "Part Time"),
        ("contract", "Contract"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="teacher_profile")
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="teachers")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="teachers")
    
    
    qualification = models.CharField(max_length=255, blank=True)
    specialization = models.CharField(max_length=255, blank=True)
    experience_years = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to="teacher_images/", blank=True, null=True) 
    
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, default="full_time")
    hire_date = models.DateField(default=timezone.now)
    salary = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    
    bio = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Teacher"
        verbose_name_plural = "Teachers"
        ordering = ["-created_at"]

    def __str__(self):
        dept = self.department.name if self.department else "No Dept"
        return f"{self.user.get_full_name()} ({dept})"
    
class Subject(models.Model):
    """Subject model"""
    CLASS_CHOICES = [
        ("CRECHE", "Creche"),
        ("NURSERY_1", "Nursery 1"),
        ("NURSERY_2", "Nursery 2"),
        ("KINDERGARTEN", "Kindergarten"),
        ("UPPER_PRIMARY_4", "Upper Primary 4"),
        ("UPPER_PRIMARY_5", "Upper Primary 5"),
        ("UPPER_PRIMARY_6", "Upper Primary 6"),
        ("JHS_1", "JHS 1"),
        ("JHS_2", "JHS 2"),
        ("JHS_3", "JHS 3"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="subjects")
    teacher = models.ForeignKey(Teacher, on_delete=models.SET_NULL, null=True, blank=True, related_name="subjects")
    school = models.ForeignKey('School', on_delete=models.CASCADE, null=True) 
    name = models.CharField(max_length=100)
    subject_class = models.CharField(max_length=50, choices=CLASS_CHOICES)
    # code = models.CharField(max_length=20, blank=True)
    # description = models.TextField(blank=True)
    # credits = models.PositiveIntegerField(default=1)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Subject"
        verbose_name_plural = "Subjects"
        # unique_together = ['department', 'name']
        
    def enroll_class_students(self):
        """Manually enroll all students in this subject's class"""
        return auto_enroll_class_students(self)
    
    def get_enrolled_students(self):
        """Get all actively enrolled students"""
        return Student.objects.filter(
            enrollments__subject=self,
            enrollments__is_active=True
        ).distinct()

    def __str__(self):
        return f"{self.name} - {self.department.name}"


class Student(models.Model):
    """Student profile model with promotion tracking"""
    CLASS_CHOICES = [
        ("CRECHE", "Creche"),
        ("NURSERY_1", "Nursery 1"),
        ("NURSERY_2", "Nursery 2"),
        ("KINDERGARTEN", "Kindergarten"),
        ("UPPER_PRIMARY_4", "Upper Primary 4"),
        ("UPPER_PRIMARY_5", "Upper Primary 5"),
        ("UPPER_PRIMARY_6", "Upper Primary 6"),
        ("JHS_1", "JHS 1"),
        ("JHS_2", "JHS 2"),
        ("JHS_3", "JHS 3"),
    ]
    
    PROMOTION_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("promoted", "Promoted"),
        ("retained", "Retained"),
        ("graduated", "Graduated"),
    ]
    
   

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="student_profile")
    parent = models.ForeignKey(Parent, on_delete=models.CASCADE, related_name="students")
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="students")
    
    student_id = models.CharField(max_length=20, unique=True, editable=False)
    admission_number = models.CharField(max_length=20, unique=True, editable=False)
    student_class = models.CharField(max_length=50, choices=CLASS_CHOICES)
    previous_class = models.CharField(max_length=50, choices=CLASS_CHOICES, blank=True, null=True)
    
    # Promotion Fields
    promotion_status = models.CharField(
        max_length=20, 
        choices=PROMOTION_STATUS_CHOICES, 
        default="pending",
        help_text="Current promotion status of the student"
    )
    promoted_to = models.CharField(
        max_length=50, 
        choices=CLASS_CHOICES, 
        blank=True, 
        null=True,
        help_text="Class to which student will be promoted"
    )
    promotion_date = models.DateField(blank=True, null=True)
    
    joining_date = models.DateField(default=timezone.now)
    mobile_number = models.CharField(max_length=15)
    student_image = models.ImageField(upload_to="student_images/", blank=True, null=True)
    
    # Health Information
    allergies = models.TextField(blank=True)
    medical_conditions = models.TextField(blank=True)
    
    # Additional Information
    slug = models.SlugField(unique=True, max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Student"
        verbose_name_plural = "Students"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.student_id:
            self.student_id = f"STU-{get_random_string(6).upper()}"
        if not self.admission_number:
            year = timezone.now().year
            count = Student.objects.filter(school=self.school).count() + 1
            self.admission_number = f"{year}-{count:04d}"
        if not self.slug:
            base = slugify(f"{self.user.first_name}-{self.user.last_name}-{self.student_id}")
            self.slug = base[:100]
        super().save(*args, **kwargs)

    def promote_to_next_class(self):
        """Promote student to the next class"""
        class_progression = dict(self.CLASS_CHOICES)
        class_keys = list(class_progression.keys())
        
        try:
            current_index = class_keys.index(self.student_class)
            if current_index < len(class_keys) - 1:
                self.previous_class = self.student_class
                self.promoted_to = class_keys[current_index + 1]
                self.promotion_status = "promoted"
                self.promotion_date = timezone.now().date()
                return True
            else:
                self.promotion_status = "graduated"
                self.promotion_date = timezone.now().date()
                return False
        except ValueError:
            return False

    def confirm_promotion(self):
        """Confirm and apply promotion"""
        if self.promotion_status == "promoted" and self.promoted_to:
            self.student_class = self.promoted_to
            self.promoted_to = None
            self.save()
    
    def get_current_enrollments(self):
        """Get all active enrollments for the student"""
        return self.enrollments.filter(is_active=True)
    
    def enroll_in_class_subjects(self):
        """Manually enroll student in all subjects for their current class"""
        return auto_enroll_student(self)


    def __str__(self):
        return f"{self.user.get_full_name()} ({self.student_id}) - {self.get_student_class_display()}"


class Enrollment(models.Model):
    """Student enrollment in subjects"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="enrollments")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="enrollments")
    enrollment_date = models.DateField(default=timezone.now)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Enrollment"
        verbose_name_plural = "Enrollments"
        unique_together = ('student', 'subject')

    def __str__(self):
        return f"{self.student.user.get_full_name()} enrolled in {self.subject.name}"


class Assignment(models.Model):
    """Assignment model"""
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("published", "Published"),
        ("closed", "Closed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="assignments")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="assignments")
    student_class = models.CharField(
        max_length=50,
        choices=Student.CLASS_CHOICES,
        help_text="Select the class this assignment is for"
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    instructions = models.TextField(blank=True)
    attachment = models.FileField(upload_to="assignments/", blank=True, null=True)
    
    due_date = models.DateField()
    total_marks = models.PositiveIntegerField(default=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Assignment"
        verbose_name_plural = "Assignments"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} - {self.get_student_class_display()} ({self.subject.name})"

    def is_overdue(self):
        """Check if assignment is overdue"""
        return timezone.now().date() > self.due_date


class AssignmentSubmission(models.Model):
    """Track student assignment submissions"""
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("submitted", "Submitted"),
        ("graded", "Graded"),
        ("late", "Late Submission"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="submissions")
    
    submission_file = models.FileField(upload_to="submissions/", blank=True, null=True)
    submission_text = models.TextField(blank=True)
    submission_date = models.DateTimeField(auto_now_add=True)
    
    marks_obtained = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    feedback = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    graded_date = models.DateTimeField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Assignment Submission"
        verbose_name_plural = "Assignment Submissions"
        unique_together = ('assignment', 'student')

    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.assignment.title}"


class ResultSheet(models.Model):
    """Student result sheet for a subject in a specific term and academic year"""

    GRADE_CHOICES = [
        ("A+", "A+"), ("A", "A"), ("A-", "A-"),
        ("B+", "B+"), ("B", "B"), ("B-", "B-"),
        ("C+", "C+"), ("C", "C"), ("C-", "C-"),
        ("D+", "D+"), ("D", "D"), ("F", "F"),
    ]
    REMARK_CHOICES = [
        ("excellent", "Excellent"),
        ("very_good", "Very Good"),
        ("good", "Good"),
        ("fair", "Fair"),
        ("poor", "Poor"),
        ("fail", "Fail"),
    ]
    TERM_CHOICES = [
        ("1", "First Term"),
        ("2", "Second Term"),
        ("3", "Third Term"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="results")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="results")

    term = models.CharField(max_length=1, choices=TERM_CHOICES, default="1")
    academic_year = models.CharField(max_length=20, help_text="e.g., 2024/2025")

    # --- Components of Assessment ---
    class_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(20)],
        help_text="Score out of 20 marks (20%)",
        default=0
    )
    mid_semester = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(30)],
        help_text="Score out of 30 marks (30%)",
        default=0
    )
    end_of_term_exams = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="Enter the end of term exams score for the total to be calcualted automatically ",
        default=0
    )

    # --- Calculated Fields ---
    total_marks = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    grade = models.CharField(max_length=3, choices=GRADE_CHOICES, blank=True)
    remark = models.CharField(max_length=20, choices=REMARK_CHOICES, blank=True)
    teacher_comment = models.TextField(blank=True)

    exam_date = models.DateField(default=timezone.now)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Result Sheet"
        verbose_name_plural = "Result Sheets"
        unique_together = ('student', 'subject', 'term', 'academic_year')
        ordering = ["-exam_date"]

    # --- Helper Methods ---

    def calculate_total(self):
        """Compute total marks and derived fields."""
        # Simply sum all three manually entered components
        class_score = self.class_score if self.class_score else Decimal('0')
        mid_semester = self.mid_semester if self.mid_semester else Decimal('0')
        end_of_term_exams = self.end_of_term_exams if self.end_of_term_exams else Decimal('0')
        
        # Calculate total (sum of all three)
        self.total_marks = class_score + mid_semester + end_of_term_exams
        self.percentage = (self.total_marks / Decimal('100')) * Decimal('100')
        return self.total_marks

    def _determine_grade_and_remark(self):
        """Determine grade and remark based on percentage"""
        perc = self.percentage

        if perc >= 90:
            self.grade, self.remark = "A+", "excellent"
        elif perc >= 80:
            self.grade, self.remark = "A", "excellent"
        elif perc >= 75:
            self.grade, self.remark = "A-", "excellent"
        elif perc >= 70:
            self.grade, self.remark = "B+", "very_good"
        elif perc >= 65:
            self.grade, self.remark = "B", "very_good"
        elif perc >= 60:
            self.grade, self.remark = "B-", "very_good"
        elif perc >= 55:
            self.grade, self.remark = "C+", "good"
        elif perc >= 50:
            self.grade, self.remark = "C", "good"
        elif perc >= 45:
            self.grade, self.remark = "C-", "good"
        elif perc >= 40:
            self.grade, self.remark = "D", "fair"
        else:
            self.grade, self.remark = "F", "fail"

    def save(self, *args, **kwargs):
        """Auto-calculate total, percentage, grade, and remark"""
        self.calculate_total()
        self._determine_grade_and_remark()
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.subject.name} ({self.grade})"

class Fees(models.Model):
    """Student fees management"""
    FEE_TYPE_CHOICES = [
        ("tuition", "Tuition Fee"),
        ("admission", "Admission Fee"),
        ("exam", "Exam Fee"),
        ("transport", "Transport Fee"),
        ("library", "Library Fee"),
        ("sports", "Sports Fee"),
        ("other", "Other"),
    ]
    PAYMENT_METHOD_CHOICES = [
        ("cash", "Cash"),
        ("bank_transfer", "Bank Transfer"),
        ("mobile_money", "Mobile Money"),
        ("cheque", "Cheque"),
        ("online", "Online Payment"),
    ]
    STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('partial', 'Partially Paid'),
        ('paid', 'Fully Paid'),
        ('overdue', 'Overdue'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="school_fees")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="fees")
    fee_type = models.CharField(max_length=20, choices=FEE_TYPE_CHOICES, default="tuition")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    due_date = models.DateField()
    paid = models.BooleanField(default=False)
    payment_date = models.DateField(blank=True, null=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True)
    transaction_id = models.CharField(max_length=100, blank=True)
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="unpaid")
    
    receipt_number = models.CharField(max_length=50, blank=True, editable=False)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fee"
        verbose_name_plural = "Fees"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.status == 'paid':
            self.paid = True
            if not self.payment_date:
                self.payment_date = timezone.now().date()
        else:
            self.paid = False
            if self.payment_date:
                self.payment_date = None
        if self.paid and not self.receipt_number:
            self.receipt_number = f"RCP-{get_random_string(8).upper()}"
        super().save(*args, **kwargs)

    def net_amount(self):
        """Calculate net amount after discount"""
        return self.amount - self.discount

    def is_overdue(self):
        """Check if fee payment is overdue"""
        return not self.paid and timezone.now().date() > self.due_date

    def __str__(self):
        status = "Paid" if self.paid else "Unpaid"
        return f"{self.student.user.get_full_name()} - {self.get_fee_type_display()} - ₵{self.amount} ({status})"


class Attendance(models.Model):
    """Track student and teacher attendance"""
    ATTENDANCE_TYPE_CHOICES = [
        ("student", "Student"),
        ("teacher", "Teacher"),
    ]
    STATUS_CHOICES = [
        ("present", "Present"),
        ("absent", "Absent"),
        ("late", "Late"),
        ("excused", "Excused"),
        ("sick", "Sick Leave"),
    ]
    CLASS_CHOICES = [
        ("CRECHE", "Creche"),
        ("NURSERY_1", "Nursery 1"),
        ("NURSERY_2", "Nursery 2"),
        ("KINDERGARTEN", "Kindergarten"),
        ("UPPER_PRIMARY_4", "Upper Primary 4"),
        ("UPPER_PRIMARY_5", "Upper Primary 5"),
        ("UPPER_PRIMARY_6", "Upper Primary 6"),
        ("JHS_1", "JHS 1"),
        ("JHS_2", "JHS 2"),
        ("JHS_3", "JHS 3"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attendance_type = models.CharField(max_length=20, choices=ATTENDANCE_TYPE_CHOICES)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="attendance", blank=True, null=True)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="attendance", blank=True, null=True)
    class_attendance = models.CharField(max_length=50, choices=CLASS_CHOICES,default=0)
    date = models.DateField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="present")
    remarks = models.TextField(blank=True)
    marked_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name="marked_attendance")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Attendance"
        verbose_name_plural = "Attendance Records"
        unique_together = [['student', 'date'], ['teacher', 'date']]
        ordering = ["-date"]

    def __str__(self):
        if self.student:
            return f"{self.student.user.get_full_name()} - {self.date} ({self.get_status_display()})"
        elif self.teacher:
            return f"{self.teacher.user.get_full_name()} - {self.date} ({self.get_status_display()})"
        return f"Attendance - {self.date}"


class Announcement(models.Model):
    """School announcements and notices"""
    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("urgent", "Urgent"),
    ]
    TARGET_AUDIENCE_CHOICES = [
        ("all", "All"),
        ("students", "Students"),
        ("teachers", "Teachers"),
        ("parents", "Parents"),
        ("staff", "Staff"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="announcements")
    title = models.CharField(max_length=255)
    content = models.TextField()
    author = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name="announcements")
    
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="medium")
    target_audience = models.CharField(max_length=20, choices=TARGET_AUDIENCE_CHOICES, default="all")
    
    published = models.BooleanField(default=False)
    publish_date = models.DateTimeField(blank=True, null=True)
    expiry_date = models.DateTimeField(blank=True, null=True)
    
    attachment = models.FileField(upload_to="announcements/", blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Announcement"
        verbose_name_plural = "Announcements"
        ordering = ["-created_at"]

    def is_active(self):
        """Check if announcement is currently active"""
        now = timezone.now()
        if not self.published:
            return False
        if self.publish_date and now < self.publish_date:
            return False
        if self.expiry_date and now > self.expiry_date:
            return False
        return True

    def __str__(self):
        return f"{self.title} - {self.school.name}"


class Event(models.Model):
    """School events and activities"""
    EVENT_TYPE_CHOICES = [
        ("academic", "Academic"),
        ("sports", "Sports"),
        ("cultural", "Cultural"),
        ("meeting", "Meeting"),
        ("holiday", "Holiday"),
        ("exam", "Exam"),
        ("other", "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="events")
    title = models.CharField(max_length=255)
    description = models.TextField()
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES, default="other")
    
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    location = models.CharField(max_length=255, blank=True)
    
    organizer = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name="organized_events")
    participants = models.ManyToManyField(CustomUser, related_name="events", blank=True)
    
    is_public = models.BooleanField(default=True)
    max_participants = models.PositiveIntegerField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Event"
        verbose_name_plural = "Events"
        ordering = ["start_date"]

    def is_upcoming(self):
        """Check if event is upcoming"""
        return self.start_date > timezone.now()

    def is_ongoing(self):
        """Check if event is currently ongoing"""
        now = timezone.now()
        return self.start_date <= now <= self.end_date

    def __str__(self):
        return f"{self.title} - {self.start_date.strftime('%Y-%m-%d')}"


class Timetable(models.Model):
    """Class timetable/schedule"""
    DAY_CHOICES = [
        ("monday", "Monday"),
        ("tuesday", "Tuesday"),
        ("wednesday", "Wednesday"),
        ("thursday", "Thursday"),
        ("friday", "Friday"),
        ("saturday", "Saturday"),
        ("sunday", "Sunday"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="timetables")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="timetables")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="timetables")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="timetables")
    
    student_class = models.CharField(max_length=50, choices=Student.CLASS_CHOICES)
    day_of_week = models.CharField(max_length=20, choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    room_number = models.CharField(max_length=50, blank=True)
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Timetable"
        verbose_name_plural = "Timetables"
        ordering = ["day_of_week", "start_time"]
        unique_together = ['school', 'student_class', 'day_of_week', 'start_time']

    def __str__(self):
        return f"{self.get_student_class_display()} - {self.subject.name} - {self.get_day_of_week_display()} {self.start_time}"


class Leave(models.Model):
    """Leave application for teachers and staff"""
    LEAVE_TYPE_CHOICES = [
        ("sick", "Sick Leave"),
        ("casual", "Casual Leave"),
        ("annual", "Annual Leave"),
        ("maternity", "Maternity Leave"),
        ("paternity", "Paternity Leave"),
        ("unpaid", "Unpaid Leave"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="leaves")
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPE_CHOICES)
    
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    supporting_document = models.FileField(upload_to="leave_documents/", blank=True, null=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    approved_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_leaves")
    approval_date = models.DateTimeField(blank=True, null=True)
    rejection_reason = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Leave"
        verbose_name_plural = "Leaves"
        ordering = ["-created_at"]

    def total_days(self):
        """Calculate total leave days"""
        return (self.end_date - self.start_date).days + 1

    def __str__(self):
        return f"{self.teacher.user.get_full_name()} - {self.get_leave_type_display()} ({self.get_status_display()})"


class PromotionHistory(models.Model):
    """Track student promotion history"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="promotion_history")
    from_class = models.CharField(max_length=50, choices=Student.CLASS_CHOICES)
    to_class = models.CharField(max_length=50, choices=Student.CLASS_CHOICES)
    academic_year = models.CharField(max_length=20, help_text="e.g., 2024/2025")
    
    promotion_date = models.DateField(default=timezone.now)
    promoted_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name="promotions_made")
    
    average_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    remarks = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Promotion History"
        verbose_name_plural = "Promotion Histories"
        ordering = ["-promotion_date"]

    def __str__(self):
        return f"{self.student.user.get_full_name()} promoted from {self.get_from_class_display()} to {self.get_to_class_display()}"


class Notification(models.Model):
    """User notifications"""
    NOTIFICATION_TYPE_CHOICES = [
        ("announcement", "Announcement"),
        ("assignment", "Assignment"),
        ("fee", "Fee"),
        ("result", "Result"),
        ("attendance", "Attendance"),
        ("event", "Event"),
        ("promotion", "Promotion"),
        ("system", "System"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPE_CHOICES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    
    link = models.CharField(max_length=500, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ["-created_at"]

    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save()

    def __str__(self):
        return f"{self.user.username} - {self.title}"
    
