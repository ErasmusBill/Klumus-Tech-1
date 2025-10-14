from django.db import transaction
from account.models import Student, Subject, Enrollment


def auto_enroll_student(student):
    """
    Utility function to automatically enroll a student in all subjects 
    for their class. Can be called when a student is created or class is changed.
    
    Args:
        student: Student instance
    
    Returns:
        int: Number of enrollments created
    """
    # Deactivate existing enrollments
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


def auto_enroll_class(school, student_class):
    """
    Utility function to automatically enroll all students in a specific class 
    to their subjects.
    
    Args:
        school: School instance
        student_class: Class choice (e.g., 'JHS_1')
    
    Returns:
        dict: Summary of enrollments
    """
    students = Student.objects.filter(
        school=school,
        student_class=student_class,
        is_active=True
    )
    
    subjects = Subject.objects.filter(
        school=school,
        subject_class=student_class
    )
    
    total_enrollments = 0
    
    with transaction.atomic():
        for student in students:
            # Deactivate old enrollments
            Enrollment.objects.filter(student=student).update(is_active=False)
            
            # Create new enrollments
            for subject in subjects:
                enrollment, created = Enrollment.objects.get_or_create(
                    student=student,
                    subject=subject,
                    defaults={'is_active': True}
                )
                
                if not created:
                    enrollment.is_active = True
                    enrollment.save()
                
                total_enrollments += 1
    
    return {
        'students_enrolled': students.count(),
        'subjects_count': subjects.count(),
        'total_enrollments': total_enrollments
    }


def sync_class_enrollments(school):
    """
    Sync all students' enrollments with their current class subjects.
    Useful for ensuring data consistency.
    
    Args:
        school: School instance
    
    Returns:
        dict: Summary of sync operation
    """
    students = Student.objects.filter(school=school, is_active=True)
    total_synced = 0
    
    for student in students:
        enrolled = auto_enroll_student(student)
        total_synced += enrolled
    
    return {
        'total_students': students.count(),
        'total_enrollments': total_synced
    }