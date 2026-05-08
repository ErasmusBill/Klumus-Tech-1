from account.models import Enrollment
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache

@receiver([post_save, post_delete], sender=Enrollment)
def clear_student_dashboard_cache(sender, instance, **kwargs):
    # Construct the exact key used in your view
    # Format: student_portal:[school_id]:courses:[student_id]
    cache_key = f"student_portal:{instance.student.school_id}:courses:{instance.student.id}"
    cache.delete(cache_key)
    print(f"Cache cleared for student {instance.student.student_id}")