from dataclasses import field
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.forms import ModelForm
from django.db.models import Q
from account.models import Announcement, CustomUser, Department, Fees, Parent, Student, Subject, Teacher, ClassFee, SchoolClass, Timetable, School
from .utils import generate_default_password
from django.core.exceptions import ObjectDoesNotExist
from django_select2.forms import Select2Widget

GENDER_CHOICES = [
    ("male", "Male"),
    ("female", "Female"),
    ("other", "Other"),
]


class SchoolClassChoiceField(forms.ModelChoiceField):
    def to_python(self, value):
        if value in self.empty_values:
            return None
        try:
            return super().to_python(value)
        except forms.ValidationError:
            from account.models import _resolve_school_class
            sc = _resolve_school_class(value)
            if sc:
                return sc
            raise


class AddTeacherForm(forms.ModelForm):
    class_teacher_class = SchoolClassChoiceField(
        queryset=SchoolClass.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="Select Class"
    )
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
        if 'class_teacher_class' in self.fields:
            self.fields['class_teacher_class'].queryset = SchoolClass.for_school(self.school, active_only=True)

     
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
        if self.school:
            self.fields['class_teacher_class'].queryset = SchoolClass.objects.filter(
                Q(school=self.school) | Q(school__isnull=True), is_active=True
            ).order_by('order', 'name')
        else:
            self.fields['class_teacher_class'].queryset = SchoolClass.objects.filter(is_active=True).order_by('order', 'name')

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
    
class AddClassForm(forms.ModelForm):
    class Meta:
        model = SchoolClass
        fields = ["name", "code", "order", "description", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Primary 1, JHS 1"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., PRIMARY_1 (optional)"}),
            "order": forms.NumberInput(attrs={"class": "form-control", "placeholder": "e.g., 1, 2, 3"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Optional description"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, school=None, **kwargs):
        self.school = school
        super().__init__(*args, **kwargs)
        if 'is_active' in self.fields and not self.instance.pk:
            self.fields['is_active'].initial = True

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        if not name:
            raise forms.ValidationError("Class name is required.")
        qs = SchoolClass.objects.filter(name__iexact=name)
        if self.school:
            qs = qs.filter(Q(school=self.school) | Q(school__isnull=True)).exclude(excluded_schools=self.school)
        else:
            qs = qs.filter(school__isnull=True)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"A class with the name '{name}' already exists.")
        return name


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

    # Sibling / Existing Parent Link field
    existing_parent = forms.ModelChoiceField(
        queryset=Parent.objects.none(),
        required=False,
        empty_label="-- New Parent (Or auto-match by phone/email) --",
        widget=forms.Select(attrs={'class': 'form-control select2', 'id': 'id_existing_parent'}),
        label="Link Existing Parent (For Siblings)",
        help_text="If this student has siblings already in this school, select their parent here to link them together."
    )

    # Parent / Father fields
    father_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Father's Full Name"})
    )
    father_phone = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Father's Phone Number"})
    )
    father_occupation = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Father's Occupation"})
    )
    father_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': "Father's Email (Optional)"})
    )

    # Parent / Mother fields
    mother_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Mother's Full Name"})
    )
    mother_phone = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Mother's Phone Number"})
    )
    mother_occupation = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Mother's Occupation"})
    )
    mother_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': "Mother's Email (Optional)"})
    )

    # Guardian fields
    guardian_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Guardian's Full Name"})
    )
    guardian_relation = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Relationship (e.g. Uncle, Aunt, Grandparent)"})
    )
    guardian_phone = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Guardian's Phone Number"})
    )
    guardian_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': "Guardian's Email Address (Optional)"})
    )
    guardian_occupation = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Guardian's Occupation"})
    )

    # Emergency Contact fields
    emergency_contact_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Emergency Contact Person"})
    )
    emergency_contact_phone = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Emergency Contact Phone"})
    )
    emergency_contact_relation = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Relationship to Student"})
    )

    # Parent / Guardian Addresses
    present_address = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Residential / Present Address"})
    )
    permanent_address = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Permanent Home Address"})
    )

    # Academic
    previous_school = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Previous School Attended (if any)"})
    )

    class Meta:
        model = Student
        fields = [
            "student_class",
            "previous_class",
            "previous_school",
            "joining_date",
            "allergies",
            "medical_conditions",
            "notes",
            "is_active"
        ]
        widgets = {
            "student_class": forms.Select(attrs={'class': 'form-control'}),
            "previous_class": forms.Select(attrs={'class': 'form-control'}),
            "joining_date": forms.DateInput(attrs={"type": "date", 'class': 'form-control'}),
            "allergies": forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'List any allergies'}),
            "medical_conditions": forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'List any medical conditions'}),
            "notes": forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Additional notes'}),
        }

    def __init__(self, *args, **kwargs):
        self.school = kwargs.pop('school', None)
        super().__init__(*args, **kwargs)
        if self.school:
            class_qs = SchoolClass.objects.filter(
                Q(school=self.school) | Q(school__isnull=True), is_active=True
            ).order_by('order', 'name')
            if 'existing_parent' in self.fields:
                self.fields['existing_parent'].queryset = Parent.objects.filter(
                    students__school=self.school
                ).distinct().order_by('father_name', 'mother_name', 'guardian_name')
        else:
            class_qs = SchoolClass.objects.filter(is_active=True).order_by('order', 'name')
            if 'existing_parent' in self.fields:
                self.fields['existing_parent'].queryset = Parent.objects.all().order_by('father_name', 'mother_name', 'guardian_name')

        self.fields['student_class'].queryset = class_qs
        if 'previous_class' in self.fields:
            self.fields['previous_class'].queryset = class_qs
            self.fields['previous_class'].required = False
            self.fields['previous_class'].empty_label = "None (First Time Admission)"
        
        # Only populate fields if editing an existing student
        if self.instance.pk and hasattr(self.instance, 'user'):
            try:
                user = self.instance.user
                for field_name in [
                    'first_name', 'last_name', 'email', 'username', 'password', 'gender',
                    'date_of_birth', 'address', 'phone_number', 'profile_picture',
                    'father_name', 'mother_name', 'father_occupation', 'mother_occupation',
                    'father_email', 'mother_email', 'father_phone', 'mother_phone',
                    'guardian_name', 'guardian_relation', 'guardian_phone', 'guardian_email', 'guardian_occupation',
                    'emergency_contact_name', 'emergency_contact_phone', 'emergency_contact_relation',
                    'present_address', 'permanent_address', 'previous_school', 'previous_class',
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

                if 'previous_school' in self.fields:
                    self.fields['previous_school'].initial = self.instance.previous_school or ''

                # Populate parent fields if parent exists
                if hasattr(self.instance, 'parent') and self.instance.parent:
                    parent = self.instance.parent
                    if 'existing_parent' in self.fields:
                        self.fields['existing_parent'].initial = parent
                    self.fields['father_name'].initial = parent.father_name or ''
                    self.fields['mother_name'].initial = parent.mother_name or ''
                    self.fields['father_occupation'].initial = parent.father_occupation or ''
                    self.fields['mother_occupation'].initial = parent.mother_occupation or ''
                    self.fields['father_email'].initial = parent.father_email or ''
                    self.fields['mother_email'].initial = parent.mother_email or ''
                    self.fields['father_phone'].initial = parent.father_phone or ''
                    self.fields['mother_phone'].initial = parent.mother_phone or ''
                    self.fields['guardian_name'].initial = parent.guardian_name or ''
                    self.fields['guardian_relation'].initial = parent.guardian_relation or ''
                    self.fields['guardian_phone'].initial = parent.guardian_phone or ''
                    self.fields['guardian_email'].initial = parent.guardian_email or ''
                    self.fields['guardian_occupation'].initial = parent.guardian_occupation or ''
                    self.fields['emergency_contact_name'].initial = parent.emergency_contact_name or ''
                    self.fields['emergency_contact_phone'].initial = parent.emergency_contact_phone or ''
                    self.fields['emergency_contact_relation'].initial = parent.emergency_contact_relation or ''
                    self.fields['present_address'].initial = parent.present_address or ''
                    self.fields['permanent_address'].initial = parent.permanent_address or ''

                # Make password optional for editing
                self.fields['password'].required = False
                self.fields['password'].help_text = "Leave blank to keep current password."
                
            except (AttributeError, ObjectDoesNotExist):
                # Handle case where related objects don't exist
                pass
        else:
            # New student: show the default password in the form
            self.fields['password'].initial = generate_default_password()

    def clean(self):
        cleaned_data = super().clean()
        father_name = (cleaned_data.get('father_name') or '').strip()
        mother_name = (cleaned_data.get('mother_name') or '').strip()
        guardian_name = (cleaned_data.get('guardian_name') or '').strip()
        existing_parent = cleaned_data.get('existing_parent')

        if not existing_parent and not (father_name or mother_name or guardian_name):
            raise forms.ValidationError("Please provide contact details for at least one parent or guardian (Father, Mother, or Guardian), or select an existing parent for siblings.")

        if existing_parent:
            if not father_name and existing_parent.father_name:
                cleaned_data['father_name'] = existing_parent.father_name
            if not mother_name and existing_parent.mother_name:
                cleaned_data['mother_name'] = existing_parent.mother_name
            if not guardian_name and existing_parent.guardian_name:
                cleaned_data['guardian_name'] = existing_parent.guardian_name
        return cleaned_data

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if not email:
            if self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
                return self.instance.user.email or ""
            return ""
        exclude_kwargs = {}
        if self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            exclude_kwargs['id'] = self.instance.user.id
        if CustomUser.objects.exclude(**exclude_kwargs).filter(email__iexact=email).exists():
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
        existing_parent = self.cleaned_data.get('existing_parent')
        
        if is_update:
            # Editing existing student
            student = self.instance
            user = student.user
            parent = existing_parent or student.parent or Parent()
        else:
            # Creating new student - create user and parent first
            user = CustomUser(role='student')
            if existing_parent:
                parent = existing_parent
            else:
                # Auto-match existing parent in this school if father_phone, mother_phone, guardian_phone, or father_email matches
                f_phone = (self.cleaned_data.get('father_phone') or '').strip()
                m_phone = (self.cleaned_data.get('mother_phone') or '').strip()
                g_phone = (self.cleaned_data.get('guardian_phone') or '').strip()
                f_email = (self.cleaned_data.get('father_email') or '').strip()

                parent = None
                match_q = Q()
                if f_phone:
                    match_q |= Q(father_phone=f_phone) | Q(mother_phone=f_phone) | Q(guardian_phone=f_phone)
                if m_phone:
                    match_q |= Q(father_phone=m_phone) | Q(mother_phone=m_phone) | Q(guardian_phone=m_phone)
                if g_phone:
                    match_q |= Q(guardian_phone=g_phone) | Q(father_phone=g_phone) | Q(mother_phone=g_phone)
                if f_email:
                    match_q |= Q(father_email__iexact=f_email) | Q(mother_email__iexact=f_email) | Q(guardian_email__iexact=f_email)

                if match_q and self.school:
                    matched_parents = Parent.objects.filter(students__school=self.school).filter(match_q).distinct()
                    if matched_parents.exists():
                        parent = matched_parents.first()

                if not parent:
                    parent = Parent()

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
            # If parent was already existing, only overwrite fields if a non-empty value was entered
            is_parent_new = not parent.pk
            for field in [
                'father_name', 'father_phone', 'father_occupation', 'father_email',
                'mother_name', 'mother_phone', 'mother_occupation', 'mother_email',
                'guardian_name', 'guardian_relation', 'guardian_phone', 'guardian_email', 'guardian_occupation',
                'present_address', 'permanent_address'
            ]:
                val = self.cleaned_data.get(field)
                if val or is_parent_new:
                    setattr(parent, field, val or '')

            if self.cleaned_data.get('emergency_contact_name'):
                parent.emergency_contact_name = self.cleaned_data.get('emergency_contact_name')
            elif not parent.emergency_contact_name:
                parent.emergency_contact_name = (
                    self.cleaned_data.get('guardian_name')
                    or self.cleaned_data.get('father_name')
                    or self.cleaned_data.get('mother_name')
                    or ''
                )
            if self.cleaned_data.get('emergency_contact_phone'):
                parent.emergency_contact_phone = self.cleaned_data.get('emergency_contact_phone')
            elif not parent.emergency_contact_phone:
                parent.emergency_contact_phone = (
                    self.cleaned_data.get('guardian_phone')
                    or self.cleaned_data.get('father_phone')
                    or self.cleaned_data.get('mother_phone')
                    or ''
                )
            if self.cleaned_data.get('emergency_contact_relation'):
                parent.emergency_contact_relation = self.cleaned_data.get('emergency_contact_relation')
            elif not parent.emergency_contact_relation:
                parent.emergency_contact_relation = (
                    self.cleaned_data.get('guardian_relation')
                    or ''
                )
            if not parent.present_address and self.cleaned_data.get('address'):
                parent.present_address = self.cleaned_data.get('address')
            parent.save()

            previous_school = self.cleaned_data.get('previous_school') or ''
            previous_class = self.cleaned_data.get('previous_class')

            if is_update:
                # Update existing student
                student.parent = parent
                student.student_class = self.cleaned_data.get('student_class') or student.student_class
                if previous_class is not None:
                    student.previous_class = previous_class
                student.previous_school = previous_school
                student.joining_date = self.cleaned_data.get('joining_date') or student.joining_date
                student.allergies = self.cleaned_data.get('allergies', student.allergies or '')
                student.medical_conditions = self.cleaned_data.get('medical_conditions', student.medical_conditions or '')
                student.notes = self.cleaned_data.get('notes', student.notes or '')
                student.is_active = self.cleaned_data.get('is_active', student.is_active)
                student.mobile_number = self.cleaned_data.get('phone_number', student.mobile_number or '')
                if profile_picture:
                    student.student_image = profile_picture
                student.save()
            else:
                # Create new student with all required fields
                student = Student.objects.create(
                    user=user,
                    parent=parent,
                    school=self.school,
                    student_class=self.cleaned_data['student_class'],
                    previous_class=previous_class,
                    previous_school=previous_school,
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
            'academic_year': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 2026/2027',
                'autocomplete': 'off',
                'list': 'academic_year_suggestions',
            }),
            'term': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.school = kwargs.pop('school', None)
        super().__init__(*args, **kwargs)
        if self.school:
            self.fields['student_class'].queryset = SchoolClass.objects.filter(
                Q(school=self.school) | Q(school__isnull=True), is_active=True
            ).order_by('order', 'name')
        else:
            self.fields['student_class'].queryset = SchoolClass.objects.filter(is_active=True).order_by('order', 'name')

        if not self.initial.get('academic_year'):
            if self.school:
                self.initial['academic_year'] = self.school.get_current_academic_year()
            else:
                from django.utils import timezone
                now_y = timezone.now().year
                self.initial['academic_year'] = f"{now_y}/{now_y + 1}"

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
            self.fields['subject_class'].queryset = SchoolClass.objects.filter(
                Q(school=school) | Q(school__isnull=True), is_active=True
            ).order_by('order', 'name')
        else:
            self.fields['teacher'].queryset = Teacher.objects.none()  # type: ignore
            self.fields['subject_class'].queryset = SchoolClass.objects.filter(is_active=True).order_by('order', 'name')
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


class TimetableForm(forms.ModelForm):
    student_class = SchoolClassChoiceField(
        queryset=SchoolClass.objects.none(),
        widget=forms.Select(attrs={'class': 'form-control select2'}),
        label="Target Class"
    )

    class Meta:
        model = Timetable
        fields = [
            'student_class',
            'subject',
            'teacher',
            'day_of_week',
            'start_time',
            'end_time',
            'room_number',
            'is_active',
        ]
        widgets = {
            'subject': forms.Select(attrs={'class': 'form-control select2'}),
            'teacher': forms.Select(attrs={'class': 'form-control select2'}),
            'day_of_week': forms.Select(attrs={'class': 'form-control select2'}),
            'start_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'room_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Room 102 or Science Lab'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.school = kwargs.pop('school', None)
        super().__init__(*args, **kwargs)

        if self.school:
            self.fields['student_class'].queryset = SchoolClass.for_school(self.school, active_only=True).order_by('order', 'name')
            self.fields['subject'].queryset = Subject.objects.filter(school=self.school).select_related('department', 'subject_class').order_by('name')
            self.fields['teacher'].queryset = Teacher.objects.filter(school=self.school).select_related('user', 'department').order_by('user__first_name', 'user__last_name')
        else:
            self.fields['student_class'].queryset = SchoolClass.objects.filter(is_active=True).order_by('order', 'name')
            self.fields['subject'].queryset = Subject.objects.all().order_by('name')
            self.fields['teacher'].queryset = Teacher.objects.all().order_by('user__first_name', 'user__last_name')

        self.fields['teacher'].label_from_instance = lambda obj: f"{obj.user.get_full_name()} ({obj.department.name if obj.department else 'General'})"
        self.fields['subject'].label_from_instance = lambda obj: f"{obj.name} ({obj.subject_class.name if obj.subject_class else 'All Classes'})"

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        day_of_week = cleaned_data.get('day_of_week')
        student_class = cleaned_data.get('student_class')
        teacher = cleaned_data.get('teacher')

        if start_time and end_time:
            if start_time >= end_time:
                self.add_error('end_time', "End time must be later than start time.")

        if self.school and day_of_week and start_time and end_time:
            # 1. Check for overlapping period for this class
            class_conflicts = Timetable.objects.filter(
                school=self.school,
                student_class=student_class,
                day_of_week=day_of_week,
                is_active=True,
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            if self.instance and self.instance.pk:
                class_conflicts = class_conflicts.exclude(pk=self.instance.pk)
            if class_conflicts.exists():
                conflict = class_conflicts.first()
                self.add_error(
                    'start_time',
                    f"Class conflict: {student_class} already has {conflict.subject.name} scheduled on {conflict.get_day_of_week_display()} from {conflict.start_time.strftime('%H:%M')} to {conflict.end_time.strftime('%H:%M')}."
                )

            # 2. Check for overlapping teaching period for this teacher
            if teacher:
                teacher_conflicts = Timetable.objects.filter(
                    school=self.school,
                    teacher=teacher,
                    day_of_week=day_of_week,
                    is_active=True,
                    start_time__lt=end_time,
                    end_time__gt=start_time,
                )
                if self.instance and self.instance.pk:
                    teacher_conflicts = teacher_conflicts.exclude(pk=self.instance.pk)
                if teacher_conflicts.exists():
                    conflict = teacher_conflicts.first()
                    self.add_error(
                        'teacher',
                        f"Teacher conflict: {teacher.user.get_full_name()} is already scheduled to teach {conflict.subject.name} for {conflict.student_class} on {conflict.get_day_of_week_display()} from {conflict.start_time.strftime('%H:%M')} to {conflict.end_time.strftime('%H:%M')}."
                    )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.school:
            instance.school = self.school
        if instance.subject and instance.subject.department:
            instance.department = instance.subject.department
        elif instance.teacher and instance.teacher.department:
            instance.department = instance.teacher.department
        if commit:
            instance.save()
        return instance


class SchoolSettingsForm(forms.ModelForm):
    class Meta:
        model = School
        fields = [
            "name",
            "logo",
            "phone_number",
            "email",
            "website",
            "location",
            "address",
            "postal_code",
            "academic_year_start",
            "academic_year_end",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Kiddo International Academy"}),
            "logo": forms.FileInput(attrs={"class": "form-control-file", "accept": "image/*", "id": "schoolLogoInput"}),
            "phone_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. +233 24 123 4567"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "e.g. info@school.edu"}),
            "website": forms.URLInput(attrs={"class": "form-control", "placeholder": "e.g. https://www.school.edu"}),
            "location": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. East Legon, Accra"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Full street / physical address"}),
            "postal_code": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. P.O. Box 1234"}),
            "academic_year_start": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "academic_year_end": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and hasattr(logo, "size"):
            # Check maximum size, e.g. 5MB
            if logo.size > 5 * 1024 * 1024:
                raise forms.ValidationError("Image file too large. Maximum allowed size is 5MB.")
            import os
            valid_extensions = [".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"]
            ext = os.path.splitext(logo.name)[1].lower()
            if ext not in valid_extensions:
                raise forms.ValidationError(f"Unsupported format ({ext}). Supported formats: {', '.join(valid_extensions)}.")
        return logo
