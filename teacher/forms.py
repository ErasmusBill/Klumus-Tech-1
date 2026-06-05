from django import forms
from django.core.validators import MinValueValidator, MaxValueValidator
from account.models import Assignment, Attendance, ResultSheet, Student, Teacher,Subject
from datetime import datetime
from django.utils import timezone


class BulkResultForm(forms.Form):
    """Form for teachers to bulk input student results."""

    exam_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        label="Exam Date"
    )

    academic_year = forms.CharField(
        max_length=20,
        initial=f"{datetime.now().year}/{datetime.now().year + 1}",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 2024/2025'}),
        label="Academic Year"
    )

    term = forms.ChoiceField(
        choices=ResultSheet.TERM_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Term"
    )

    def __init__(self, *args, **kwargs):
        students = kwargs.pop('students', None)
        kwargs.pop('school', None)
        super().__init__(*args, **kwargs)

        if students:
            for student in students:
                # Class score input
                self.fields[f'class_score_{student.id}'] = forms.DecimalField(
                    required=False,
                    max_digits=5,
                    decimal_places=2,
                    validators=[MinValueValidator(0), MaxValueValidator(20)],
                    widget=forms.NumberInput(attrs={
                        'class': 'form-control text-center',
                        'placeholder': '0 - 20',
                    }),
                    label="Class Score"
                )

                # Mid-semester input
                self.fields[f'mid_semester_{student.id}'] = forms.DecimalField(
                    required=False,
                    max_digits=5,
                    decimal_places=2,
                    validators=[MinValueValidator(0), MaxValueValidator(30)],
                    widget=forms.NumberInput(attrs={
                        'class': 'form-control text-center',
                        'placeholder': '0 - 30',
                    }),
                    label="Mid-Semester"
                )
                
                # End of Term Exams input (ADD THIS FIELD)
                self.fields[f'end_of_term_exams_{student.id}'] = forms.DecimalField(
                    required=False,
                    max_digits=5,
                    decimal_places=2,
                    validators=[MinValueValidator(0), MaxValueValidator(50)],
                    widget=forms.NumberInput(attrs={
                        'class': 'form-control text-center',
                        'placeholder': '0 - 50',
                    }),
                    label="End of Term Exams"
                )


class EditResultForm(forms.ModelForm):
    class Meta:
        model = ResultSheet
        fields = ['class_score', 'mid_semester', 'end_of_term_exams', 'teacher_comment']  # FIXED: end_of_term_exams
        widgets = {
            'class_score': forms.NumberInput(attrs={
                'class': 'form-control', 
                'step': '0.01',
                'min': '0',
                'max': '20'
            }),
            'mid_semester': forms.NumberInput(attrs={
                'class': 'form-control', 
                'step': '0.01',
                'min': '0',
                'max': '30'
            }),
            'end_of_term_exams': forms.NumberInput(attrs={
                'class': 'form-control', 
                'step': '0.01',
                'min': '0',
                'max': '50'
            }),
            'teacher_comment': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 2, 
                'placeholder': 'Optional comments'
            }),
        }


class AttendanceForm(forms.ModelForm):
    class Meta:
        model = Attendance
        fields = [
            'attendance_type',
            'student',
            'teacher',
            'class_attendance',
            'date',
            'status',
            'remarks'
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'attendance_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_attendance_type'}),
            'student': forms.Select(attrs={'class': 'form-select'}),
            'teacher': forms.Select(attrs={'class': 'form-select'}),
            'class_attendance': forms.Select(attrs={'class': 'form-select'}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, school=None, teacher=None, *args, **kwargs):
        self.school = school
        self.teacher_profile = teacher
        super().__init__(*args, **kwargs)

        self.restricted_to_class_teacher = bool(self.teacher_profile and self.teacher_profile.can_take_attendance)
        self.assigned_class = self.teacher_profile.class_teacher_class if self.restricted_to_class_teacher else None
        self.assigned_class_display = (
            self.teacher_profile.get_class_teacher_class_display()
            if self.restricted_to_class_teacher and self.teacher_profile
            else None
        )

        if school:
            student_queryset = Student.objects.filter(school=school, is_active=True).select_related('user')  # type: ignore
            teacher_queryset = Teacher.objects.filter(school=school, is_active=True).select_related('user')  # type: ignore
        else:
            student_queryset = Student.objects.none()  # type: ignore
            teacher_queryset = Teacher.objects.none()  # type: ignore

        if self.restricted_to_class_teacher:
            student_queryset = student_queryset.filter(student_class=self.assigned_class)
            self.fields['attendance_type'].choices = [('student', 'Student')]
            self.fields['attendance_type'].initial = 'student'
            self.fields['attendance_type'].required = False
            self.fields['attendance_type'].widget = forms.HiddenInput()
            self.fields['teacher'].required = False
            self.fields['teacher'].widget = forms.HiddenInput()
            self.fields['teacher'].queryset = Teacher.objects.none()  # type: ignore
            self.fields['student'].required = True
            self.fields['class_attendance'].required = False
            self.fields['class_attendance'].initial = self.assigned_class
            self.fields['class_attendance'].widget = forms.HiddenInput()
            if self.assigned_class_display:
                self.fields['student'].help_text = f"Attendance is restricted to {self.assigned_class_display}."

        self.fields['student'].queryset = student_queryset  # type: ignore
        if not self.restricted_to_class_teacher:
            self.fields['teacher'].queryset = teacher_queryset  # type: ignore

    def clean(self):
        cleaned_data = super().clean()

        if self.teacher_profile and not self.teacher_profile.can_take_attendance:
            raise forms.ValidationError("Only class teachers assigned to a class can record attendance.")

        attendance_type = cleaned_data.get('attendance_type')
        student = cleaned_data.get('student')
        teacher = cleaned_data.get('teacher')

        if self.restricted_to_class_teacher:
            cleaned_data['attendance_type'] = 'student'
            cleaned_data['teacher'] = None
            cleaned_data['class_attendance'] = self.assigned_class
            if student and self.assigned_class and student.student_class != self.assigned_class:
                self.add_error('student', f"Select a student from {self.assigned_class_display}.")
            elif not student and 'student' not in self.errors:
                self.add_error('student', "Select a student from your assigned class.")
        else:
            if attendance_type == 'student':
                cleaned_data['teacher'] = None
                if not student and 'student' not in self.errors:
                    self.add_error('student', 'Select a student for student attendance.')
            elif attendance_type == 'teacher':
                cleaned_data['student'] = None
                if not teacher and 'teacher' not in self.errors:
                    self.add_error('teacher', 'Select a teacher for staff attendance.')
            


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = [
            'title', 'subject', 'student_class', 'description',
            'instructions', 'due_date', 'total_marks', 'attachment'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'subject': forms.Select(attrs={'class': 'form-select'}),
            'student_class': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'instructions': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'total_marks': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'attachment': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, school=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if school:
            self.fields['subject'].queryset = Subject.objects.filter(school=school) # type: ignore
        else:
            self.fields['subject'].queryset = Subject.objects.none() # type: ignore
