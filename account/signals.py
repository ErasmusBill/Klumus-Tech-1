# signals.py
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.db import transaction
from django.db.models import Q
from .models import Student, Enrollment, Subject

def auto_enroll_class_students(subject):
    """
    Utility function to automatically enroll all students in a class
    when a subject is added or updated.
    """
    # Get all students in the same school and class as the subject
    students = Student.objects.filter(school=subject.school,student_class=subject.subject_class,is_active=True)
    
    enrolled_count = 0
    
    with transaction.atomic():
        for student in students:
            enrollment, created = Enrollment.objects.get_or_create(student=student,subject=subject,defaults={'is_active': True})
            
            if not created:
                enrollment.is_active = True
                enrollment.save()
            
            enrolled_count += 1
    
    return enrolled_count

def auto_enroll_student(student):
    """
    Utility function to automatically enroll a student in all subjects 
    for their class.
    """
    # Deactivate existing enrollments for this student
    Enrollment.objects.filter(student=student).update(is_active=False)
    
    # Get all subjects for student's class
    subjects = Subject.objects.filter(
        school=student.school,
        subject_class=student.student_class
    )
    
    enrolled_count = 0
    
    with transaction.atomic():
        for subject in subjects:
            enrollment, created = Enrollment.objects.get_or_create(
                student=student,
                subject=subject,
                defaults={'is_active': True}
            )
            
            if not created:
                enrollment.is_active = True
                enrollment.save()
            
            enrolled_count += 1
    
    return enrolled_count

@receiver(post_save, sender=Subject)
def auto_enroll_students_on_subject_creation(sender, instance, created, **kwargs):
    """
    Automatically enroll all students in the class when a new subject is added.
    Also handles updates if the subject's class changes.
    """
    if created:
        # New subject created - enroll all students in that class
        print(f"New subject '{instance.name}' created. Auto-enrolling students...")
        count = auto_enroll_class_students(instance)
        print(f"Auto-enrolled {count} students in subject '{instance.name}'")
    
    elif instance.pk and not created:
        # Existing subject updated - check if class changed
        try:
            old_instance = Subject.objects.get(pk=instance.pk)
            if old_instance.subject_class != instance.subject_class:
                # Subject class changed - re-enroll students
                print(f"Subject '{instance.name}' class changed from {old_instance.subject_class} to {instance.subject_class}. Re-enrolling students...")
                
                # Deactivate old enrollments
                Enrollment.objects.filter(subject=instance).update(is_active=False)
                
                # Enroll new students
                count = auto_enroll_class_students(instance)
                print(f"Re-enrolled {count} students in subject '{instance.name}'")
                
        except Subject.DoesNotExist:
            pass

@receiver(post_delete, sender=Subject)
def handle_subject_deletion(sender, instance, **kwargs):
    """
    Handle subject deletion by deactivating related enrollments.
    """
    print(f"Subject '{instance.name}' deleted. Deactivating related enrollments...")
    enrollments_count = Enrollment.objects.filter(subject=instance).update(is_active=False)
    print(f"Deactivated {enrollments_count} enrollments for subject '{instance.name}'")

@receiver(post_save, sender=Student)
def auto_enroll_student_on_class_change(sender, instance, created, **kwargs):
    """
    Automatically enroll student in subjects when:
    - New student is created with a class
    - Existing student's class is changed
    """
    if created and instance.student_class:
        # New student with class - enroll them
        print(f"New student '{instance.user.get_full_name()}' created in class {instance.student_class}. Auto-enrolling in subjects...")
        count = auto_enroll_student(instance)
        print(f"Auto-enrolled student '{instance.user.get_full_name()}' in {count} subjects")
    
    elif instance.pk and not created:
        # Existing student - check if class changed
        try:
            old_instance = Student.objects.get(pk=instance.pk)
            if old_instance.student_class != instance.student_class:
                # Class changed - re-enroll
                print(f"Student '{instance.user.get_full_name()}' class changed from {old_instance.student_class} to {instance.student_class}. Re-enrolling in subjects...")
                count = auto_enroll_student(instance)
                print(f"Re-enrolled student '{instance.user.get_full_name()}' in {count} subjects")
                
        except Student.DoesNotExist:
            pass

@receiver(pre_save, sender=Student)
def track_student_class_change(sender, instance, **kwargs):
    """
    Store the original class before saving to detect changes.
    This helps in the post_save signal to determine if class changed.
    """
    if instance.pk:
        try:
            original = Student.objects.get(pk=instance.pk)
            instance._original_student_class = original.student_class
        except Student.DoesNotExist:
            instance._original_student_class = None
    else:
        instance._original_student_class = None

# Additional signal for bulk operations
@receiver(post_save, sender=Student)
def handle_student_reactivation(sender, instance, created, **kwargs):
    """
    Handle student reactivation by re-enrolling them in current class subjects.
    """
    if not created and instance.is_active:
        try:
            old_instance = Student.objects.get(pk=instance.pk)
            if not old_instance.is_active and instance.is_active:
                # Student was reactivated - re-enroll them
                print(f"Student '{instance.user.get_full_name()}' reactivated. Re-enrolling in subjects...")
                count = auto_enroll_student(instance)
                print(f"Re-enrolled reactivated student '{instance.user.get_full_name()}' in {count} subjects")
        except Student.DoesNotExist:
            pass

# Signal to handle student deactivation
@receiver(pre_save, sender=Student)
def handle_student_deactivation(sender, instance, **kwargs):
    """
    Handle student deactivation by deactivating their enrollments.
    """
    if instance.pk and not instance.is_active:
        try:
            original = Student.objects.get(pk=instance.pk)
            if original.is_active and not instance.is_active:
                # Student is being deactivated - deactivate enrollments
                print(f"Student '{instance.user.get_full_name()}' deactivated. Deactivating enrollments...")
                enrollments_count = Enrollment.objects.filter(student=instance).update(is_active=False)
                print(f"Deactivated {enrollments_count} enrollments for student '{instance.user.get_full_name()}'")
        except Student.DoesNotExist:
            pass