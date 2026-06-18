from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinLengthValidator
from django.conf import settings

class User(AbstractUser):
    USER_TYPES = (
        ('instructor', 'Instructor'),
        ('student', 'Student'),
    )
    
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    email = models.EmailField(unique=True)
    user_type = models.CharField(max_length=20, choices=USER_TYPES, default='student')
    courses = models.ManyToManyField('Course', blank=True, related_name='students')
    instructor_courses = models.ManyToManyField('Course', blank=True, related_name='instructors')
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.get_user_type_display()})"
    
    @property
    def is_instructor(self):
        return self.user_type == 'instructor'
    
    @property
    def is_student(self):
        return self.user_type == 'student'

class Course(models.Model):
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class AccessCode(models.Model):
    ACCESS_TYPES = (
        ('instructor', 'Instructor Access'),
        ('student', 'Student Access'),
    )
    
    code = models.CharField(max_length=20, unique=True, validators=[MinLengthValidator(6)])
    course = models.ForeignKey(Course, on_delete=models.CASCADE, null=True, blank=True)
    access_type = models.CharField(max_length=20, choices=ACCESS_TYPES, default='student')
    is_used = models.BooleanField(default=False)
    used_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.code} -> {self.access_type}"

class Playlist(models.Model):
    title = models.CharField(max_length=100)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='playlists')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.title} ({self.course.title})"

class PlaylistAccessCode(models.Model):
    code = models.CharField(max_length=20, unique=True, validators=[MinLengthValidator(6)])
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE)
    is_used = models.BooleanField(default=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.code} -> {self.playlist.title}"

class Lesson(models.Model):
    title = models.CharField(max_length=200)
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name='lessons')
    video_url = models.URLField(blank=True, help_text="YouTube embed URL or Google Drive share link")
    notes = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def clean_youtube_url(self):
        if not self.video_url:
            return self.video_url
            
        url = self.video_url
        url = url.replace('www.', '')
        
        if 'youtu.be' in url:
            video_id = url.split('/')[-1].split('?')[0]
            return f'https://www.youtube-nocookie.com/embed/{video_id}'
        elif '/shorts/' in url:
            video_id = url.split('/shorts/')[1].split('?')[0]
            return f'https://www.youtube-nocookie.com/embed/{video_id}'
        elif 'youtube.com' in url:
            if 'embed' in url:
                return url.replace('youtube.com', 'www.youtube-nocookie.com')
            elif 'watch?v=' in url:
                video_id = url.split('watch?v=')[1].split('&')[0]
                return f'https://www.youtube-nocookie.com/embed/{video_id}'
        elif 'drive.google.com' in url:
            if 'file/d/' in url:
                file_id = url.split('file/d/')[1].split('/')[0].split('?')[0]
                return f'https://drive.google.com/uc?export=download&id={file_id}'
            elif 'open?id=' in url:
                file_id = url.split('open?id=')[1].split('&')[0]
                return f'https://drive.google.com/uc?export=download&id={file_id}'
        
        return url
    
    def save(self, *args, **kwargs):
        if self.video_url:
            self.video_url = self.clean_youtube_url()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

class CompletedLesson(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'lesson')