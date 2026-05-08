from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    Announcement,
    CustomUser,
    Department,
    Enrollment,
    Fees,
    Package,
    Parent,
    ResultSheet,
    School,
    SchoolOnboardingRequest,
    Student,
    Subject,
    Teacher,
    Subscription, Transaction, SubscriptionHistory, ClassFee
)


@admin.register(SchoolOnboardingRequest)
class SchoolOnboardingRequestAdmin(admin.ModelAdmin):
    list_display = (
        "school_name",
        "contact_full_name",
        "contact_email",
        "status",
        "preferred_package",
        "created_at",
        "provision_link",
    )
    list_filter = ("status", "school_size", "preferred_package", "created_at")
    search_fields = ("school_name", "contact_full_name", "contact_email", "contact_phone")
    readonly_fields = ("created_at", "updated_at", "reviewed_at", "provisioned_school")

    @admin.display(description="Provision")
    def provision_link(self, obj):
        if obj.provisioned_school_id:
            return format_html("Provisioned")
        url = reverse("account:provision-school", kwargs={"inquiry_id": obj.id})
        return format_html('<a class="button" href="{}">Create Workspace</a>', url)


admin.site.register(School)
admin.site.register(CustomUser)
admin.site.register(Package)
admin.site.register(Student)
admin.site.register(Teacher)
admin.site.register(Department)
admin.site.register(Parent)
admin.site.register(Subject)
admin.site.register(ResultSheet)
admin.site.register(Fees)
admin.site.register(Enrollment)
admin.site.register(Announcement)
admin.site.register(Subscription)
admin.site.register(SubscriptionHistory)
admin.site.register(Transaction)
admin.site.register(ClassFee)
