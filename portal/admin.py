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

from django.contrib import admin
from .models import Notification, UserNotification

class NotificationAdmin(admin.ModelAdmin):
    list_display = ['title', 'notification_type', 'is_active', 'show_on_login', 'show_on_dashboard', 'created_at']
    list_filter = ['notification_type', 'is_active', 'show_on_login']
    search_fields = ['title', 'message']
    fieldsets = (
        ('Notification Details', {
            'fields': ('title', 'message', 'notification_type')
        }),
        ('Display Options', {
            'fields': ('show_on_login', 'show_on_dashboard', 'is_dismissible', 'is_active')
        }),
        ('Timing', {
            'fields': ('expires_at',)
        }),
    )

class UserNotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'notification', 'is_read', 'is_dismissed', 'seen_at']
    list_filter = ['is_read', 'is_dismissed']

admin.site.register(Notification, NotificationAdmin)
admin.site.register(UserNotification, UserNotificationAdmin)