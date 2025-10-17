from django import forms
from django.db import transaction
from account.models import AssignmentSubmission, Student, Subject, Enrollment

class StudentEnrollmentForm(forms.ModelForm):
    """
    Form for updating student class.
    Automatically enrolls student in subjects for their new class.
    """
    class Meta:
        model = Student
        fields = ['student_class']
        widgets = {
            'student_class': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            })
        }
        labels = {
            'student_class': 'Select Class'
        }

    def __init__(self, *args, **kwargs):
        self.student = kwargs.pop('student', None)
        super().__init__(*args, **kwargs)
        
        # Add help text
        self.fields['student_class'].help_text = (
            "Note: Changing class will automatically enroll you in all subjects for the selected class"
        )

    def save(self, commit=True):
        student = super().save(commit=False)
        
        if commit:
            with transaction.atomic():
                # Save the student with new class
                student.save()
                
                # Auto-enroll in subjects for the new class
                self.auto_enroll_subjects(student)
        
        return student

    def auto_enroll_subjects(self, student):
        """
        Automatically enroll student in all subjects for their class.
        Deactivates old enrollments and creates new ones.
        """
        # Deactivate all current enrollments
        Enrollment.objects.filter(student=student).update(is_active=False)
        
        # Get all subjects for the student's class and school
        subjects = Subject.objects.filter(
            school=student.school,
            subject_class=student.student_class
        )
        
        # Create or reactivate enrollments
        enrolled_count = 0
        for subject in subjects:
            enrollment, created = Enrollment.objects.get_or_create(
                student=student,
                subject=subject,
                defaults={'is_active': True}
            )
            
            if not created:
                # Reactivate existing enrollment
                enrollment.is_active = True
                enrollment.save()
            
            enrolled_count += 1
        
        return enrolled_count


class BulkStudentEnrollmentForm(forms.Form):
    """
    Form for bulk enrollment of multiple students in a specific class.
    Admin can select a class and all students in that class will be 
    automatically enrolled in the class subjects.
    """
    student_class = forms.ChoiceField(
        choices=Student.CLASS_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': True
        }),
        label='Select Class'
    )
    
    school = forms.ModelChoiceField(
        queryset=None,
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': True
        }),
        label='Select School',
        required=False
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Set school queryset based on user role
        if self.user and self.user.role == 'admin':
            from account.models import School
            self.fields['school'].queryset = School.objects.filter( # type: ignore
                admin=self.user
            )
            self.fields['school'].initial = self.user.managed_school
        else:
            # Hide school field for non-admins
            self.fields['school'].widget = forms.HiddenInput()

    def enroll_students(self, school=None):
        """
        Enroll all students in the selected class to their respective subjects.
        """
        student_class = self.cleaned_data['student_class']
        
        if not school and self.user and self.user.role == 'admin':
            school = self.user.managed_school
        elif not school:
            school = self.cleaned_data.get('school')
        
        if not school:
            raise ValueError("School is required for enrollment")
        
        # Get all students in the selected class
        students = Student.objects.filter(
            school=school,
            student_class=student_class,
            is_active=True
        )
        
        # Get all subjects for this class
        subjects = Subject.objects.filter(
            school=school,
            subject_class=student_class
        )
        
        enrolled_count = 0
        
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
                    
                    enrolled_count += 1
        
        return {
            'students_count': students.count(),
            'subjects_count': subjects.count(),
            'enrollments_created': enrolled_count
        }


class AssignmentSubmissionForm(forms.ModelForm):
    class Meta:
        model = AssignmentSubmission
        fields = ['submission_file', 'submission_text']
        widgets = {
            'submission_file': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'submission_text': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Optional: Add your answers or notes here...'
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        file = cleaned_data.get('submission_file')
        text = cleaned_data.get('submission_text')

        if not file and not text:
            raise forms.ValidationError(
                "You must submit either a file or text response."
            )
        return cleaned_data