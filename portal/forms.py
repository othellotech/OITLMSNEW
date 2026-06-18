from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from .models import AccessCode

User = get_user_model()

class RegistrationForm(UserCreationForm):
    access_code = forms.CharField(max_length=20, required=True, label='Access Code')
    
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'password1', 'password2', 'access_code']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'username' in self.fields:
            self.fields.pop('username')
        
        self.fields['password1'].help_text = 'Password must be at least 8 characters.'
        self.fields['password1'].widget.attrs.update({'class': 'password-input'})
        self.fields['password2'].widget.attrs.update({'class': 'password-input'})
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError('This email is already registered. Please login or use a different email.')
        return email
    
    def clean_password1(self):
        password = self.cleaned_data.get('password1')
        
        # Basic length check for everyone
        if len(password) < 8:
            raise ValidationError('Password must be at least 8 characters long.')
        
        # Check if it's an instructor account - skip strict validation
        access_code = self.cleaned_data.get('access_code')
        is_instructor = False
        if access_code:
            try:
                ac = AccessCode.objects.get(code=access_code, is_used=False)
                if ac.access_type == 'instructor':
                    is_instructor = True
            except AccessCode.DoesNotExist:
                pass
        
        # Skip name/email validation for instructors
        if is_instructor:
            return password
        
        # Student validation - check first name, last name, email
        first_name = self.cleaned_data.get('first_name', '')
        last_name = self.cleaned_data.get('last_name', '')
        email = self.cleaned_data.get('email', '')
        
        # Check if password contains first name (only if first name exists and is long enough)
        if first_name and len(first_name) >= 3 and first_name.lower() in password.lower():
            raise ValidationError('Password cannot contain your first name.')
        
        # Check if password contains last name (only if last name exists and is long enough)
        if last_name and len(last_name) >= 3 and last_name.lower() in password.lower():
            raise ValidationError('Password cannot contain your last name.')
        
        # Check if password contains email username (only if email username is long enough)
        if email:
            email_username = email.split('@')[0].lower()
            # Only check if username is at least 3 characters and actually in password
            if len(email_username) >= 3 and email_username in password.lower():
                raise ValidationError('Password cannot contain your email username.')
        
        # Check for common weak passwords
        common_passwords = ['password', '12345678', 'qwerty123', 'admin123', 'letmein', 'welcome1']
        if password.lower() in common_passwords:
            raise ValidationError('Password is too common. Please choose a stronger password.')
        
        return password
    
    def clean_access_code(self):
        access_code = self.cleaned_data.get('access_code')
        try:
            ac = AccessCode.objects.get(code=access_code, is_used=False)
            return access_code
        except AccessCode.DoesNotExist:
            raise ValidationError('Invalid or already used access code. Please check and try again.')
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data['email']
        
        access_code_str = self.cleaned_data['access_code']
        access_code = AccessCode.objects.get(code=access_code_str)
        
        # Set user type based on access code
        if access_code.access_type == 'instructor':
            user.user_type = 'instructor'
        else:
            user.user_type = 'student'
        
        if commit:
            user.save()
        
        # For students, assign the course from access code
        if access_code.course and user.user_type == 'student':
            user.courses.add(access_code.course)
            user.save()
        
        # For instructors, assign the course to instructor_courses
        if access_code.course and user.user_type == 'instructor':
            user.instructor_courses.add(access_code.course)
            user.save()
        
        access_code.is_used = True
        access_code.used_by = user
        access_code.save()
        
        return user


class LoginForm(forms.Form):
    email = forms.EmailField(label='Email', widget=forms.EmailInput(attrs={'class': 'login-input'}))
    password = forms.CharField(label='Password', widget=forms.PasswordInput(attrs={'class': 'login-input'}))
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not User.objects.filter(email=email).exists():
            raise ValidationError('No account found with this email address.')
        return email
    
    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        password = cleaned_data.get('password')
        
        if email and password:
            try:
                user = User.objects.get(email=email)
                from django.contrib.auth import authenticate
                authenticated_user = authenticate(username=user.username, password=password)
                if not authenticated_user:
                    raise ValidationError('Invalid password. Please try again.')
            except User.DoesNotExist:
                pass
        return cleaned_data


class PlaylistUnlockForm(forms.Form):
    access_code = forms.CharField(max_length=20, required=True, label='Playlist Access Code')