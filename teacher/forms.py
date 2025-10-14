from django import forms
from django.core.validators import MinValueValidator, MaxValueValidator
from account.models import Attendance, ResultSheet, Teacher, Student
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

    def __init__(self, school=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if school:
            self.fields['student'].queryset = Student.objects.filter(school=school, is_active=True).select_related('user')  # type: ignore
            self.fields['teacher'].queryset = Teacher.objects.filter(school=school, is_active=True).select_related('user')  # type: ignore
        else:
            self.fields['student'].queryset = Student.objects.none()  # type: ignore
            self.fields['teacher'].queryset = Teacher.objects.none()  # type: ignore