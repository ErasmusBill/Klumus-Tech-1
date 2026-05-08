from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.core.cache import cache  # Added for cache management
from .models import (
    Announcement, CustomUser, Department, Enrollment, Fees,
    Package, Parent, ResultSheet, School, SchoolOnboardingRequest,
    Student, Subject, Teacher, Subscription, Transaction,
    SubscriptionHistory, ClassFee
)


# --- HELPER FUNCTIONS ---

def clear_portal_cache(student):
    """Helper to clear a specific student's portal cache when data changes."""
    cache_key = f"student_portal:{student.school_id}:courses:{student.id}"
    cache.delete(cache_key)


# --- ADMIN CLASSES ---

@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    """
    Prevents the 'hidden subjects' issue by showing active status and
    clearing cache on save.
    """
    list_display = ("student", "subject", "is_active", "enrollment_date", "get_student_class")
    list_filter = ("is_active", "subject__subject_class", "subject__school")
    search_fields = ("student__student_id", "student__user__first_name", "subject__name")
    list_editable = ("is_active",)  # Fix issues directly from the list view
    autocomplete_fields = ["student", "subject"]

    def get_student_class(self, obj):
        return obj.student.get_student_class_display()

    get_student_class.short_description = "Student Class"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_portal_cache(obj.student)  # Ensure dashboard updates immediately


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("student_id", "get_full_name", "student_class", "school", "is_active")
    list_filter = ("student_class", "school", "is_active")
    search_fields = ("student_id", "user__first_name", "user__last_name", "admission_number")
    readonly_fields = ("student_id",)

    def get_full_name(self, obj):
        return obj.user.get_full_name()

    get_full_name.short_description = "Name"


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name","subject_class", "department", "teacher")
    list_filter = ("subject_class", "department", "school")
    search_fields = ("name",)
    autocomplete_fields = ["teacher", "department"]


@admin.register(SchoolOnboardingRequest)
class SchoolOnboardingRequestAdmin(admin.ModelAdmin):
    list_display = (
        "school_name", "contact_full_name", "status",
        "preferred_package", "created_at", "provision_link",
    )
    list_filter = ("status", "school_size", "preferred_package", "created_at")
    search_fields = ("school_name", "contact_full_name", "contact_email")
    readonly_fields = ("created_at", "updated_at", "reviewed_at", "provisioned_school")

    @admin.display(description="Provision")
    def provision_link(self, obj):
        if obj.provisioned_school_id:
            return format_html('<span style="color: green;">✔ Provisioned</span>')
        url = reverse("account:provision-school", kwargs={"inquiry_id": obj.id})
        return format_html(
            '<a class="button" style="background: #79aec8; color: white; padding: 4px 8px; border-radius: 4px;" href="{}">Create Workspace</a>',
            url)


# --- BASIC REGISTRATIONS ---

@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "role", "is_staff")
    list_filter = ("role", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ("user", "school", "department")
    search_fields = ("user__first_name", "user__last_name")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "head_of_department")
    search_fields = ("name",)


# --- REMAINING MODELS ---
admin.site.register(School)
admin.site.register(Package)
admin.site.register(Parent)
admin.site.register(ResultSheet)
admin.site.register(Fees)
admin.site.register(Announcement)
admin.site.register(Subscription)
admin.site.register(SubscriptionHistory)
admin.site.register(Transaction)
admin.site.register(ClassFee)