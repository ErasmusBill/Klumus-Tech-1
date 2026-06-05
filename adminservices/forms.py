from dataclasses import field
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.forms import ModelForm
from account.models import Announcement, CustomUser, Department, Fees, Parent, Student, Subject, Teacher, ClassFee
from .utils import generate_default_password
from django.core.exceptions import ObjectDoesNotExist
from django_select2.forms import Select2Widget

GENDER_CHOICES = [
    ("male", "Male"),
    ("female", "Female"),
    ("other", "Other"),
]


class AddTeacherForm(forms.ModelForm):
    # User fields
    first_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'})
    )
    last_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email Address'})
    )
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}, render_value=True),
        required=False
    )
    gender = forms.ChoiceField(
        choices=GENDER_CHOICES,
        required=True,

        widget=forms.Select(attrs={'class': 'form-control'})
    )
    date_of_birth = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", 'class': 'form-control'}),
        required=True
    )
    address = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address'}),
        required=True
    )
    phone_number = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Mobile Number'})
    )
    profile_picture = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    class Meta:
        model = Teacher
        fields = [  
            "qualification",
            "specialization", 
            "experience_years",
            "hire_date",
            "department",
            "employment_type",
            "salary",
            "bio",
            "image",
            "is_class_teacher",
            "class_teacher_class"
        ]
        widgets = {
            "qualification": forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., BSc, MSc, PhD'}),
            "specialization": forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Mathematics, Physics'}),
            "hire_date": forms.DateInput(attrs={"type": "date", 'class': 'form-control'}),
            "experience_years": forms.NumberInput(attrs={"min": 0, 'class': 'form-control', 'placeholder': 'Years'}),
            "department": forms.Select(attrs={'class': 'form-control'}),
            "employment_type": forms.Select(attrs={'class': 'form-control'}),
            "salary": forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Salary'}),
            "bio": forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Brief biography'}),
            "image": forms.FileInput(attrs={'class': 'form-control'}),
            "is_class_teacher": forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            "class_teacher_class": forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.school = kwargs.pop('school', None)
        super().__init__(*args, **kwargs)

     
        if not self.school:
            raise ValueError("School is required for Teacher form")
        
        # Filter department queryset by school
        self.fields['department'].queryset = self.school.departments.all() # type: ignore
        
        if not self.school.departments.exists():
            self.fields['department'].widget.attrs['disabled'] = True
            self.fields['department'].help_text = "No departments available. Please create one first."
        
        # Set password required only on creation
        if self.instance and self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            # Editing existing teacher
            self.fields['password'].required = False
            self.fields['password'].help_text = "Leave blank to keep current password."
            for field_name in [
                'first_name', 'last_name', 'email', 'username', 'gender',
                'date_of_birth', 'address', 'phone_number', 'qualification',
                'specialization', 'experience_years', 'hire_date', 'department',
                'employment_type', 'salary', 'bio', 'image', 'profile_picture',
            ]:
                if field_name in self.fields:
                    self.fields[field_name].required = False
            
            # Populate initial values from linked user
            user = self.instance.user
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            self.fields['email'].initial = user.email
            self.fields['username'].initial = user.username
            self.fields['phone_number'].initial = user.phone_number
            self.fields['address'].initial = user.address
            self.fields['gender'].initial = user.gender
            self.fields['date_of_birth'].initial = user.date_of_birth
            self.fields['profile_picture'].initial = user.profile_picture
        else:
            # Creating new teacher
            self.fields['password'].required = False
            self.fields['password'].help_text = "Password will be generated automatically."
            self.fields['password'].initial = generate_default_password()

        # Filter department queryset by school
        if self.school:
            self.fields['department'].queryset = self.school.departments.all()
            if not self.school.departments.exists():
                self.fields['department'].widget.attrs['disabled'] = True
                self.fields['department'].help_text = "No departments available. Please create one first."
        else:
            self.fields['department'].queryset = Department.objects.none()
            self.fields['department'].widget.attrs['disabled'] = True

        self.fields['is_class_teacher'].required = False
        self.fields['class_teacher_class'].required = False
        self.fields['class_teacher_class'].help_text = "Required only when this teacher will take attendance."

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not email:
            return self.instance.user.email if self.instance.pk and hasattr(self.instance, 'user') and self.instance.user else email
        
        # Exclude current user's email during update
        query = CustomUser.objects.filter(email=email)
        if self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            query = query.exclude(id=self.instance.user.id)
        
        if query.exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if not username:
            return self.instance.user.username if self.instance.pk and hasattr(self.instance, 'user') and self.instance.user else username

        # Exclude current user during update
        query = CustomUser.objects.filter(username=username)
        if self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            query = query.exclude(id=self.instance.user.id)

        if query.exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            validate_password(password)
        return password

    def clean_hire_date(self):
        hire_date = self.cleaned_data.get('hire_date')
        date_of_birth = self.cleaned_data.get('date_of_birth')

        if hire_date and date_of_birth:
            age_at_hire = (hire_date - date_of_birth).days / 365.25
            if age_at_hire < 18:
                raise forms.ValidationError("Teacher must be at least 18 years old at hire date.")
        return hire_date

    def clean(self):
        cleaned_data = super().clean()
        is_class_teacher = cleaned_data.get("is_class_teacher")
        class_teacher_class = cleaned_data.get("class_teacher_class")

        if is_class_teacher and not class_teacher_class:
            self.add_error("class_teacher_class", "Select the class assigned to this class teacher.")
        if not is_class_teacher:
            cleaned_data["class_teacher_class"] = None

        return cleaned_data

    def save(self, commit=True):
        """
        Save both Teacher and associated CustomUser.
        """
        # Create or get the teacher instance
        teacher = super().save(commit=False)
        
        # Check if we're creating a new teacher or updating existing
        if self.instance and self.instance.pk:
            # Updating existing teacher
            user = teacher.user
        else:
            # Creating new teacher - create user
            user = CustomUser(role='teacher')
        
        # Update user fields
        user.first_name = self.cleaned_data.get('first_name') or user.first_name
        user.last_name = self.cleaned_data.get('last_name') or user.last_name
        user.email = self.cleaned_data.get('email') or user.email
        user.username = self.cleaned_data.get('username') or user.username
        user.phone_number = self.cleaned_data.get('phone_number', user.phone_number or '')
        user.address = self.cleaned_data.get('address') or user.address
        user.gender = self.cleaned_data.get('gender') or user.gender
        user.date_of_birth = self.cleaned_data.get('date_of_birth') or user.date_of_birth

        # Handle password
        password = self.cleaned_data.get('password')
        if password and user.pk:
            user.set_password(password)
        elif not user.pk:
            user.set_password(generate_default_password())

        # Keep user profile and teacher image in sync when an upload is provided.
        profile_picture = self.files.get("profile_picture")
        teacher_image = self.files.get("image")
        uploaded_image = teacher_image or profile_picture

        if uploaded_image:
            user.profile_picture = uploaded_image

        # Save the user
        user.save()
        
        # Link user to teacher and set school
        teacher.user = user
        teacher.school = self.school
        if uploaded_image:
            teacher.image = uploaded_image
        
        if commit:
            teacher.save()
        
        return teacher
    
class AddDepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "code", "description", "head_of_department"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Name Of Department"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Departmenet code"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Optional description"}),
            "head_of_department": forms.TextInput(attrs={"class": "form-control", "placeholder": "Full name of HOD"}),
        }
    
    def __init__(self, *args, **kwargs):
        self.school = kwargs.pop('school', None)
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data['name']
        query = Department.objects.filter(school=self.school, name=name) if self.school else Department.objects.none()
        if self.instance and self.instance.pk:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise forms.ValidationError(f"A department named '{name}' already exists in your school.")
        return name
    
    


class AddStudentForm(forms.ModelForm):
    # User fields
    first_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'})
    )
    last_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'})
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email Address'})
    )
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}, render_value=True),
        required=False,
        help_text="Password will be generated automatically for new students."
    )
    gender = forms.ChoiceField(
        choices=GENDER_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    date_of_birth = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", 'class': 'form-control'}),
        required=True
    )
    address = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address'}),
        required=True
    )
    phone_number = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Mobile Number'})
    )
    profile_picture = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )

    # Parent/Guardian fields
    father_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Father's Name"})
    )
    mother_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Mother's Name"})
    )
    father_occupation = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Father's Occupation"})
    )
    mother_occupation = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Mother's Occupation"})
    )
    father_email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': "Father's Email"})
    )
    mother_email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': "Mother's Email"})
    )
    father_phone = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Father's Phone"})
    )
    mother_phone = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Mother's Phone"})
    )

    class Meta:
        model = Student
        fields = [
            "student_class",
            "joining_date",
            "allergies",
            "medical_conditions",
            "notes",
            "is_active"
        ]
        widgets = {
            "student_class": forms.Select(attrs={'class': 'form-control'}),
            "joining_date": forms.DateInput(attrs={"type": "date", 'class': 'form-control'}),
            "allergies": forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'List any allergies'}),
            "medical_conditions": forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'List any medical conditions'}),
            "notes": forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Additional notes'}),
        }

    def __init__(self, *args, **kwargs):
        self.school = kwargs.pop('school', None)
        super().__init__(*args, **kwargs)
        
        # Only populate fields if editing an existing student
        if self.instance.pk and hasattr(self.instance, 'user'):
            try:
                user = self.instance.user
                for field_name in [
                    'first_name', 'last_name', 'email', 'username', 'password', 'gender',
                    'date_of_birth', 'address', 'phone_number', 'profile_picture',
                    'father_name', 'mother_name', 'father_occupation', 'mother_occupation',
                    'father_email', 'mother_email', 'father_phone', 'mother_phone',
                    'student_class', 'joining_date', 'allergies', 'medical_conditions',
                    'notes', 'is_active',
                ]:
                    if field_name in self.fields:
                        self.fields[field_name].required = False
                
                # Populate user fields
                self.fields['first_name'].initial = user.first_name
                self.fields['last_name'].initial = user.last_name
                self.fields['email'].initial = user.email
                self.fields['username'].initial = user.username
                self.fields['phone_number'].initial = user.phone_number or ''
                self.fields['address'].initial = user.address
                self.fields['gender'].initial = user.gender
                self.fields['date_of_birth'].initial = user.date_of_birth
                if user.profile_picture:
                    self.fields['profile_picture'].initial = user.profile_picture

                # Populate parent fields if parent exists
                if hasattr(self.instance, 'parent') and self.instance.parent:
                    parent = self.instance.parent
                    self.fields['father_name'].initial = parent.father_name or ''
                    self.fields['mother_name'].initial = parent.mother_name or ''
                    self.fields['father_occupation'].initial = parent.father_occupation or ''
                    self.fields['mother_occupation'].initial = parent.mother_occupation or ''
                    self.fields['father_email'].initial = parent.father_email or ''
                    self.fields['mother_email'].initial = parent.mother_email or ''
                    self.fields['father_phone'].initial = parent.father_phone or ''
                    self.fields['mother_phone'].initial = parent.mother_phone or ''

                # Make password optional for editing
                self.fields['password'].required = False
                self.fields['password'].help_text = "Leave blank to keep current password."
                
            except (AttributeError, ObjectDoesNotExist):
                # Handle case where related objects don't exist
                pass
        else:
            # New student: show the default password in the form
            self.fields['password'].initial = generate_default_password()
            
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not email and self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            return self.instance.user.email
        exclude_kwargs = {}
        if self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            exclude_kwargs['id'] = self.instance.user.id
        if CustomUser.objects.exclude(**exclude_kwargs).filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if not username and self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            return self.instance.user.username
        exclude_kwargs = {}
        if self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            exclude_kwargs['id'] = self.instance.user.id
        if CustomUser.objects.exclude(**exclude_kwargs).filter(username=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            validate_password(password)
        return password

    def save(self, commit=True):
        # Check if student actually exists in database (not just has a UUID assigned)
        is_update = self.instance.pk and Student.objects.filter(pk=self.instance.pk).exists()
        
        if is_update:
            # Editing existing student
            student = self.instance
            user = student.user
            parent = student.parent
        else:
            # Creating new student - create user and parent first
            user = CustomUser(role='student')
            parent = Parent()
            parent.school = self.school

        # Update user fields
        user.first_name = self.cleaned_data.get('first_name') or user.first_name
        user.last_name = self.cleaned_data.get('last_name') or user.last_name
        user.email = self.cleaned_data.get('email') or user.email
        user.username = self.cleaned_data.get('username') or user.username
        user.phone_number = self.cleaned_data.get('phone_number', user.phone_number or '')
        user.address = self.cleaned_data.get('address') or user.address
        user.gender = self.cleaned_data.get('gender') or user.gender
        user.date_of_birth = self.cleaned_data.get('date_of_birth') or user.date_of_birth

        # Handle password
        password = self.cleaned_data.get('password')
        generated_password = None
        if password and is_update:
            user.set_password(password)
        elif not is_update:
            generated_password = password or generate_default_password()
            user.set_password(generated_password)

        # Keep legacy/new student image fields synchronized.
        profile_picture = self.files.get("profile_picture")
        if profile_picture:
            user.profile_picture = profile_picture

        if commit:
            # Save user first (must exist before linking to student)
            user.save()
            
            # Update and save parent
            parent.father_name = self.cleaned_data.get('father_name') or parent.father_name
            parent.mother_name = self.cleaned_data.get('mother_name') or parent.mother_name
            parent.father_occupation = self.cleaned_data.get('father_occupation') or parent.father_occupation
            parent.mother_occupation = self.cleaned_data.get('mother_occupation') or parent.mother_occupation
            parent.father_email = self.cleaned_data.get('father_email') or parent.father_email
            parent.mother_email = self.cleaned_data.get('mother_email') or parent.mother_email
            parent.father_phone = self.cleaned_data.get('father_phone', parent.father_phone or '')
            parent.mother_phone = self.cleaned_data.get('mother_phone', parent.mother_phone or '')
            parent.save()

            if is_update:
                # Update existing student
                student.student_class = self.cleaned_data.get('student_class') or student.student_class  # type: ignore
                student.joining_date = self.cleaned_data.get('joining_date') or student.joining_date  # type: ignore
                student.allergies = self.cleaned_data.get('allergies', student.allergies or '')  # type: ignore
                student.medical_conditions = self.cleaned_data.get('medical_conditions', student.medical_conditions or '')  # type: ignore
                student.notes = self.cleaned_data.get('notes', student.notes or '')  # type: ignore
                student.is_active = self.cleaned_data.get('is_active', student.is_active)  # type: ignore
                student.mobile_number = self.cleaned_data.get('phone_number', student.mobile_number or '')  # type: ignore
                if profile_picture:
                    student.student_image = profile_picture  # type: ignore
                student.save()   # type: ignore
            else:
                # Create new student with all required fields
                student = Student.objects.create(
                    user=user,
                    parent=parent,
                    school=self.school,
                    student_class=self.cleaned_data['student_class'],
                    joining_date=self.cleaned_data.get('joining_date'),
                    allergies=self.cleaned_data.get('allergies', ''),
                    medical_conditions=self.cleaned_data.get('medical_conditions', ''),
                    notes=self.cleaned_data.get('notes', ''),
                    mobile_number=self.cleaned_data.get('phone_number', ''),
                    student_image=profile_picture,
                    is_active=True
                )

        if not is_update:
            student.generated_password = generated_password  # type: ignore[attr-defined]
        return student   # type: ignore


class ClassFeeForm(forms.ModelForm):
    class Meta:
        model = ClassFee
        fields = ['student_class', 'fee_type', 'amount', 'academic_year', 'term']
        widgets = {
            'student_class': forms.Select(attrs={'class': 'form-control'}),
            'fee_type': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Fetches automatically',
                'step': '0.01',
                'inputmode': 'decimal',
                'autocomplete': 'off',
            }),
            'academic_year': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 2025/2026'}),
            'term': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.school = kwargs.pop('school', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        if self.school:
            exists = ClassFee.objects.filter(
                school=self.school,
                student_class=cleaned_data.get('student_class'),
                fee_type=cleaned_data.get('fee_type'),
                academic_year=cleaned_data.get('academic_year'),
                term=cleaned_data.get('term')
            ).exclude(pk=self.instance.pk).exists()
            if exists:
                raise forms.ValidationError("This fee structure template already exists.")
        return cleaned_data


class AddFeesForm(forms.ModelForm):
    student = forms.ModelChoiceField(
        queryset=Student.objects.none(),
        widget=forms.Select(attrs={'class': 'form-control select2-search'}),
    )
    fee_structure = forms.ModelChoiceField(
        queryset=ClassFee.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control border-primary'}),
        label="Standard Fee Template",
    )

    class Meta:
        model = Fees
        fields = ['student', 'fee_structure', 'fee_type', 'amount_required', 'discount', 'amount_paid', 'due_date',
                  'notes']
        widgets = {
            'fee_type': forms.Select(attrs={'class': 'form-select'}),
            'amount_required': forms.NumberInput(attrs={'class': 'form-control fw-bold', 'step': '0.01'}),
            'discount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'amount_paid': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        school = kwargs.pop('school', None)
        super().__init__(*args, **kwargs)
        if school:
            self.fields['student'].queryset = Student.objects.filter(school=school, is_active=True)
            self.fields['fee_structure'].queryset = ClassFee.objects.filter(school=school)

            self.fields['student'].label_from_instance = lambda obj: f"{obj.user.get_full_name()} ({obj.student_class})"
            self.fields['fee_structure'].label_from_instance = lambda \
                obj: f"{obj.student_class}: {obj.get_fee_type_display()} (₵{obj.amount})"

class AddSubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['teacher', 'name', 'department','subject_class']
        widgets = {
            'teacher': forms.Select(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Mathematics'}),
            'department': forms.Select(attrs={'class': 'form-control'}),
            'subject_class':forms.Select(attrs={'class':'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        school = kwargs.pop('school', None)
        super().__init__(*args, **kwargs)

        if school:
            # Filter teachers and departments by school
            self.fields['teacher'].queryset = Teacher.objects.filter(school=school).select_related('user') # type: ignore
            self.fields['department'].queryset = Department.objects.filter(school=school)  # type: ignore
        else:
            self.fields['teacher'].queryset = Teacher.objects.none()  # type: ignore
            self.fields['department'].queryset = Department.objects.none()  # type: ignore

        # Optional: Improve UX
        self.fields['teacher'].empty_label = "Select Teacher"  # type: ignore
        self.fields['department'].empty_label = "Select Department"  # type: ignore
        
class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = [
            "title",
            "content",
            "priority",
            "target_audience",
            "published",
            "publish_date",
            "expiry_date",
            "attachment"
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'priority': forms.Select(attrs={'class': 'form-control'}),
            'target_audience': forms.Select(attrs={'class': 'form-control'}),
            'published': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'publish_date': forms.DateTimeInput(
                attrs={'class': 'form-control', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M'
            ),
            'expiry_date': forms.DateTimeInput(
                attrs={'class': 'form-control', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M'
            ),
            'attachment': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        school = kwargs.pop('school', None)
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.publish_date:
            self.fields['publish_date'].initial = self.instance.publish_date.strftime('%Y-%m-%dT%H:%M')
        if self.instance and self.instance.expiry_date:
            self.fields['expiry_date'].initial = self.instance.expiry_date.strftime('%Y-%m-%dT%H:%M')
