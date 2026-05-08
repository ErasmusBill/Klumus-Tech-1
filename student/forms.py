from django import forms
from django.db import transaction
from django.db.models import F
from account.models import AssignmentSubmission, Student, Subject, Enrollment, School


class StudentEnrollmentForm(forms.ModelForm):
    """
    Standardizes class updates and subject auto-enrollment.
    Optimized to handle reactivation and new enrollments in a single atomic block.
    """

    class Meta:
        model = Student
        fields = ['student_class']
        widgets = {
            'student_class': forms.Select(attrs={
                'class': 'form-select form-control-lg',
                'data-placeholder': 'Select New Class'
            })
        }
        labels = {'student_class': 'Academic Class Assignment'}

    def __init__(self, *args, **kwargs):
        self.student = kwargs.pop('student', None)
        super().__init__(*args, **kwargs)
        self.fields['student_class'].help_text = (
            "⚠️ Note: Changing class deactivates previous enrollments and assigns all subjects for the new class."
        )

    def save(self, commit=True):
        student = super().save(commit=False)
        if commit:
            with transaction.atomic():
                student.save()
                self._process_enrollments(student)
        return student

    def _process_enrollments(self, student):
        """Logic separated for cleaner maintenance."""
        # Step 1: Deactivate existing
        Enrollment.objects.filter(student=student, is_active=True).update(is_active=False)

        # Step 2: Identify subjects for new class
        target_subjects = Subject.objects.filter(
            school=student.school,
            subject_class=student.student_class
        )

        # Step 3: Batch update/create for performance
        for subject in target_subjects:
            Enrollment.objects.update_or_create(
                student=student,
                subject=subject,
                defaults={'is_active': True}
            )


class BulkStudentEnrollmentForm(forms.Form):
    """
    Intuitive bulk action form for Admins.
    Uses descriptive querysets to prevent cross-school enrollment errors.
    """
    student_class = forms.ChoiceField(
        choices=Student.CLASS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Target Class Level'
    )

    school = forms.ModelChoiceField(
        queryset=School.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False,
        label='Target Institution'
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if self.user and self.user.role == 'admin':
            # Strictly limit to schools managed by this admin
            self.fields['school'].queryset = School.objects.filter(admin=self.user)
            self.fields['school'].initial = getattr(self.user, 'managed_school', None)
        else:
            self.fields['school'].widget = forms.HiddenInput()

    def enroll_students(self):
        """Processes bulk enrollments with a summary return."""
        data = self.cleaned_data
        school = data.get('school') or getattr(self.user, 'managed_school', None)
        target_class = data['student_class']

        if not school:
            raise forms.ValidationError("Institution context is missing.")

        students = Student.objects.filter(school=school, student_class=target_class, is_active=True)
        subjects = Subject.objects.filter(school=school, subject_class=target_class)

        with transaction.atomic():
            # Deactivate all active enrollments for affected students
            Enrollment.objects.filter(student__in=students, is_active=True).update(is_active=False)

            # Re-enroll or create new
            total_processed = 0
            for student in students:
                for subject in subjects:
                    Enrollment.objects.update_or_create(
                        student=student,
                        subject=subject,
                        defaults={'is_active': True}
                    )
                    total_processed += 1

        return {
            'students_impacted': students.count(),
            'subjects_assigned': subjects.count(),
            'total_enrollments': total_processed
        }


class AssignmentSubmissionForm(forms.ModelForm):
    """
    Cleaned up submission form with better validation and modern styling.
    """

    class Meta:
        model = AssignmentSubmission
        fields = ['submission_file', 'submission_text']
        widgets = {
            'submission_file': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.doc,.docx,.jpg,.png'
            }),
            'submission_text': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 6,
                'placeholder': 'Type your submission content or any additional notes here...'
            }),
        }

    def clean(self):
        """Ensure the student actually provided something."""
        cleaned_data = super().clean()
        file = cleaned_data.get('submission_file')
        text = cleaned_data.get('submission_text')

        if not file and (not text or len(text.strip()) == 0):
            raise forms.ValidationError(
                "Submission Error: Please either upload a file or provide a text response."
            )
        return cleaned_data