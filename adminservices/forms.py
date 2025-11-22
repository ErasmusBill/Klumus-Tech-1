from dataclasses import field
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.forms import ModelForm
from account.models import Announcement, CustomUser, Department, Fees, Parent, Student, Subject, Teacher
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
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}),
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
            "image" 
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
            self.fields['password'].required = True

        # Filter department queryset by school
        if self.school:
            self.fields['department'].queryset = self.school.departments.all()
            if not self.school.departments.exists():
                self.fields['department'].widget.attrs['disabled'] = True
                self.fields['department'].help_text = "No departments available. Please create one first."
        else:
            self.fields['department'].queryset = Department.objects.none()
            self.fields['department'].widget.attrs['disabled'] = True

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not email:
            raise forms.ValidationError("Email is required.")
        
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
            raise forms.ValidationError("Username is required.")

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
        elif not self.instance.pk:  # Only required on create
            raise forms.ValidationError("Password is required when creating a new teacher.")
        return password

    def clean_hire_date(self):
        hire_date = self.cleaned_data.get('hire_date')
        date_of_birth = self.cleaned_data.get('date_of_birth')

        if hire_date and date_of_birth:
            age_at_hire = (hire_date - date_of_birth).days / 365.25
            if age_at_hire < 18:
                raise forms.ValidationError("Teacher must be at least 18 years old at hire date.")
        return hire_date

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
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.email = self.cleaned_data['email']
        user.username = self.cleaned_data['username']
        user.phone_number = self.cleaned_data.get('phone_number', '')
        user.address = self.cleaned_data['address']
        user.gender = self.cleaned_data['gender']
        user.date_of_birth = self.cleaned_data['date_of_birth']

        # Handle password only if provided
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        elif not user.pk:  # New user must have password
            user.set_password('default123')  # Set a default password

        # Handle profile picture for user
        if 'profile_picture' in self.files:
            user.profile_picture = self.files['profile_picture']

        # Save the user
        user.save()
        
        # Link user to teacher and set school
        teacher.user = user
        teacher.school = self.school
        
        if commit:
            teacher.save()
        
        return teacher
    
class AddDepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "code", "description", "head_of_department"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Mathematics"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., MATH101"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Optional description"}),
            "head_of_department": forms.TextInput(attrs={"class": "form-control", "placeholder": "Full name of HOD"}),
        }
    
    def __init__(self, *args, **kwargs):
        self.school = kwargs.pop('school', None)
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data['name']
        if self.school and Department.objects.filter(school=self.school, name=name).exists():
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
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email Address'})
    )
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}),
        required=False,
        help_text="Enter a strong password. Leave blank to keep current password when editing."
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
        
        print(f"DEBUG Form Init - Instance PK: {self.instance.pk}")
        print(f"DEBUG Form Init - Has user: {hasattr(self.instance, 'user')}")

        # Only populate fields if editing an existing student
        if self.instance.pk and hasattr(self.instance, 'user'):
            try:
                user = self.instance.user
                print(f"DEBUG Form Init - User: {user}")
                
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
                print(f"DEBUG Form Init - Has parent: {hasattr(self.instance, 'parent')}")
                print(f"DEBUG Form Init - Parent value: {self.instance.parent if hasattr(self.instance, 'parent') else 'No attr'}")
                
                if hasattr(self.instance, 'parent') and self.instance.parent:
                    parent = self.instance.parent
                    print(f"DEBUG Form Init - Parent object: {parent}")
                    print(f"DEBUG Form Init - Father name: {parent.father_name}")
                    
                    self.fields['father_name'].initial = parent.father_name or ''
                    self.fields['mother_name'].initial = parent.mother_name or ''
                    self.fields['father_occupation'].initial = parent.father_occupation or ''
                    self.fields['mother_occupation'].initial = parent.mother_occupation or ''
                    self.fields['father_email'].initial = parent.father_email or ''
                    self.fields['mother_email'].initial = parent.mother_email or ''
                    self.fields['father_phone'].initial = parent.father_phone or ''
                    self.fields['mother_phone'].initial = parent.mother_phone or ''
                    
                    print(f"DEBUG Form Init - Set father_name initial to: {self.fields['father_name'].initial}")
                else:
                    print("DEBUG Form Init - No parent found or parent is None")

                # Make password optional for editing
                self.fields['password'].required = False
                self.fields['password'].help_text = "Leave blank to keep current password."
                
            except (AttributeError, ObjectDoesNotExist) as e:
                # Handle case where related objects don't exist
                print(f"ERROR Form Init: {e}")
                import traceback
                traceback.print_exc()
            
    def clean_email(self):
        email = self.cleaned_data.get('email')
        exclude_kwargs = {}
        if self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            exclude_kwargs['id'] = self.instance.user.id
        if CustomUser.objects.exclude(**exclude_kwargs).filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean_username(self):
        username = self.cleaned_data.get('username')
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
        elif not self.instance.pk and not password:
            raise forms.ValidationError("Password is required for new students.")
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
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.email = self.cleaned_data['email']
        user.username = self.cleaned_data['username']
        user.phone_number = self.cleaned_data.get('phone_number', '')
        user.address = self.cleaned_data['address']
        user.gender = self.cleaned_data['gender']
        user.date_of_birth = self.cleaned_data['date_of_birth']

        # Handle password
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)

        # Handle profile picture
        if 'profile_picture' in self.files:
            user.profile_picture = self.files['profile_picture']

        if commit:
            # Save user first (must exist before linking to student)
            user.save()
            
            # Update and save parent
            parent.father_name = self.cleaned_data['father_name']
            parent.mother_name = self.cleaned_data['mother_name']
            parent.father_occupation = self.cleaned_data['father_occupation']
            parent.mother_occupation = self.cleaned_data['mother_occupation']
            parent.father_email = self.cleaned_data['father_email']
            parent.mother_email = self.cleaned_data['mother_email']
            parent.father_phone = self.cleaned_data.get('father_phone', '')
            parent.mother_phone = self.cleaned_data.get('mother_phone', '')
            parent.save()

            if is_update:
                # Update existing student
                student.student_class = self.cleaned_data.get('student_class')   # type: ignore
                student.joining_date = self.cleaned_data.get('joining_date')   # type: ignore
                student.allergies = self.cleaned_data.get('allergies', '')   # type: ignore
                student.medical_conditions = self.cleaned_data.get('medical_conditions', '')   # type: ignore
                student.notes = self.cleaned_data.get('notes', '')   # type: ignore
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
                    is_active=True
                )

        return student   # type: ignore


class AddFeesForm(forms.ModelForm):
    student = forms.ModelChoiceField(
        queryset=Student.objects.none(),
        widget=forms.Select(attrs={
            'class': 'form-control select2-search',
        }),
        label="Student"
    )

    class Meta:
        model = Fees
        fields = ['student', 'fee_type', 'amount', 'due_date', 'status', 'notes']
        widgets = {
            'fee_type': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        school = kwargs.pop('school', None)
        super().__init__(*args, **kwargs)

        if school:
            self.fields['student'].queryset = Student.objects.filter( # type: ignore
                school=school, 
                is_active=True
            ).select_related('user')
        else:
            self.fields['student'].queryset = Student.objects.none() # type: ignore

    def label_from_instance(self, obj):
        return f"{obj.user.get_full_name()} ({obj.student_id})"
    
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