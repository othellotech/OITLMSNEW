from django.contrib import admin
from django.utils import timezone

from .models import (
    Course, AccessCode, Playlist, PlaylistAccessCode, Lesson, CompletedLesson, User,
    MultiPlaylistAccessCode, PlaylistUnlock,
    Task, TaskOption, Submission, AssignedTask,
    SurveyQuestion, CourseSurveyConfig, SurveyPrompt, SurveyResponse,
)

admin.site.register(User)
admin.site.register(AccessCode)
admin.site.register(Playlist)
admin.site.register(CompletedLesson)


class CourseSurveyConfigInline(admin.StackedInline):
    """Lets you set how many times (and how often) the pulse survey shows up
    for students on this course, right from the Course admin page."""
    model = CourseSurveyConfig
    extra = 0
    max_num = 1


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('title', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('title',)
    inlines = [CourseSurveyConfigInline]


class TaskInline(admin.TabularInline):
    """Quick-add simple (Text or True/False) tasks from a lesson's admin page.
    For Multiple Choice tasks with answer options, use the standalone Tasks
    admin page instead (so you can add the option rows)."""
    model = Task
    extra = 0
    fields = ('task_type', 'prompt', 'correct_answer', 'max_score', 'order')


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('title', 'playlist', 'order')
    list_filter = ('playlist__course',)
    search_fields = ('title',)
    inlines = [TaskInline]


class TaskOptionInline(admin.TabularInline):
    """Add the selectable answers for a Multiple Choice task, and tick the correct one."""
    model = TaskOption
    extra = 2


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('prompt', 'lesson', 'task_type', 'max_score', 'order')
    list_filter = ('task_type', 'lesson__playlist__course')
    search_fields = ('prompt', 'lesson__title')
    inlines = [TaskOptionInline]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ('student', 'task', 'auto_score', 'instructor_score', 'status', 'approved_by', 'submitted_at')
    list_filter = ('status', 'task__lesson__playlist__course')
    search_fields = ('student__email', 'student__first_name', 'student__last_name', 'task__lesson__title')
    readonly_fields = ('auto_score', 'submitted_at', 'approved_at')
    actions = ['approve_selected', 'reject_selected']

    def approve_selected(self, request, queryset):
        count = 0
        for submission in queryset:
            submission.approve(request.user)
            count += 1
        self.message_user(request, f'Approved {count} submission(s).')
    approve_selected.short_description = 'Approve selected submissions'

    def reject_selected(self, request, queryset):
        count = 0
        for submission in queryset:
            submission.reject(request.user)
            count += 1
        self.message_user(request, f'Rejected {count} submission(s).')
    reject_selected.short_description = 'Reject selected submissions'


@admin.register(AssignedTask)
class AssignedTaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'student', 'instructor', 'course', 'required_playlist', 'status', 'assigned_at')
    list_filter = ('status', 'course')
    search_fields = ('title', 'student__email', 'student__first_name', 'student__last_name')
    readonly_fields = ('assigned_at', 'submitted_at', 'reviewed_at')
    actions = ['approve_selected', 'reject_selected']

    def approve_selected(self, request, queryset):
        count = 0
        for at in queryset:
            at.approve(request.user)
            count += 1
        self.message_user(request, f'Approved {count} assigned task(s).')
    approve_selected.short_description = 'Approve selected assigned tasks'

    def reject_selected(self, request, queryset):
        count = 0
        for at in queryset:
            at.reject(request.user)
            count += 1
        self.message_user(request, f'Rejected {count} assigned task(s).')
    reject_selected.short_description = 'Reject selected assigned tasks'


@admin.register(SurveyQuestion)
class SurveyQuestionAdmin(admin.ModelAdmin):
    list_display = ('text', 'is_instructor_related', 'order', 'is_active')
    list_filter = ('is_instructor_related', 'is_active')


@admin.register(SurveyPrompt)
class SurveyPromptAdmin(admin.ModelAdmin):
    """Read-oriented: shows scheduling/completion status per student/course."""
    list_display = ('student', 'course', 'occurrence_number', 'due_at', 'completed_at')
    list_filter = ('course', 'completed_at')
    search_fields = ('student__email', 'student__first_name', 'student__last_name')
    readonly_fields = ('student', 'course', 'occurrence_number', 'due_at')


@admin.register(SurveyResponse)
class SurveyResponseAdmin(admin.ModelAdmin):
    list_display = ('student', 'course', 'instructor', 'question', 'rating', 'created_at')
    list_filter = ('course', 'instructor', 'question')
    search_fields = ('student__email', 'student__first_name', 'student__last_name')
    readonly_fields = ('student', 'course', 'instructor', 'question', 'rating', 'prompt', 'created_at')


@admin.register(PlaylistAccessCode)
class PlaylistAccessCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'playlist', 'is_used', 'user')
    list_filter = ('is_used',)
    search_fields = ('code', 'user__email', 'user__username', 'playlist__title')

    def save_model(self, request, obj, form, change):
        was_used = False
        if change and obj.pk:
            try:
                was_used = PlaylistAccessCode.objects.get(pk=obj.pk).is_used
            except PlaylistAccessCode.DoesNotExist:
                was_used = False

        # obj.save() runs here — its existing override still auto-unlocks
        # if is_used is ticked and a user is set, so ticking still works exactly as before.
        super().save_model(request, obj, form, change)

        # NEW: if it was used and just got unticked, relock the playlist for that user.
        # "used_by"/user field is intentionally left untouched (kept as a record).
        if was_used and not obj.is_used and obj.user_id:
            PlaylistUnlock.objects.filter(user_id=obj.user_id, playlist_id=obj.playlist_id).delete()


@admin.register(MultiPlaylistAccessCode)
class MultiPlaylistAccessCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'playlist_list', 'is_used', 'used_by', 'created_at', 'used_at')
    list_filter = ('is_used',)
    search_fields = ('code', 'used_by__email', 'used_by__username', 'used_by__first_name', 'used_by__last_name')
    filter_horizontal = ('playlists',)  # multi-select box: pick one or several playlists for this code
    readonly_fields = ('used_at', 'created_at')  # 'used_by' editable so it can be manually assigned

    def playlist_list(self, obj):
        return ", ".join(p.title for p in obj.playlists.all())
    playlist_list.short_description = 'Playlists'

    def save_model(self, request, obj, form, change):
        # Capture the OLD is_used value before it's overwritten, so save_related
        # (which runs after the M2M playlists are actually committed) can tell
        # whether this save just unticked a previously-used code.
        request._multicode_was_used = False
        if change and obj.pk:
            try:
                request._multicode_was_used = MultiPlaylistAccessCode.objects.get(pk=obj.pk).is_used
            except MultiPlaylistAccessCode.DoesNotExist:
                pass
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        # Runs AFTER the playlists (M2M) selection is committed to the DB.
        super().save_related(request, form, formsets, change)
        obj = form.instance
        was_used = getattr(request, '_multicode_was_used', False)

        if obj.is_used and obj.used_by_id:
            needs_save = False
            if not obj.used_at:
                obj.used_at = timezone.now()
                needs_save = True

            for playlist in obj.playlists.all():
                PlaylistUnlock.objects.get_or_create(
                    user=obj.used_by,
                    playlist=playlist,
                    defaults={'source': 'multi_code'}
                )

            if needs_save:
                obj.save(update_fields=['used_at'])

        elif was_used and not obj.is_used and obj.used_by_id:
            # NEW: code was used, now unticked -> relock all its playlists for that user.
            # "used_by" is intentionally left untouched (kept as a record).
            PlaylistUnlock.objects.filter(
                user_id=obj.used_by_id, playlist__in=obj.playlists.all()
            ).delete()


@admin.register(PlaylistUnlock)
class PlaylistUnlockAdmin(admin.ModelAdmin):
    list_display = ('user', 'playlist', 'source', 'unlocked_at')
    list_filter = ('source',)
    search_fields = ('user__email', 'user__username', 'playlist__title')
    readonly_fields = ('unlocked_at',)


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