from django.contrib import admin

# Register your models here.

from .models import Course, AccessCode, Playlist, PlaylistAccessCode, Lesson, CompletedLesson, User

admin.site.register(User)
admin.site.register(Course)
admin.site.register(AccessCode)
admin.site.register(Playlist)
admin.site.register(PlaylistAccessCode)
admin.site.register(Lesson)
admin.site.register(CompletedLesson)