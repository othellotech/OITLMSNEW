from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinLengthValidator
from django.conf import settings
from django.utils import timezone


class User(AbstractUser):
    USER_TYPES = (
        ('instructor', 'Instructor'),
        ('student', 'Student'),
        ('manager', 'Manager'),
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

    @property
    def is_manager(self):
        return self.user_type == 'manager'


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


class PlaylistUnlock(models.Model):
    """
    Single source of truth: does this user have this playlist unlocked.

    Populated automatically whenever a PlaylistAccessCode or
    MultiPlaylistAccessCode is redeemed, and backfilled once from
    pre-existing redeemed codes via a data migration. All "is this
    unlocked" checks in views should query this table rather than
    the access-code tables directly.
    """
    UNLOCK_SOURCES = (
        ('single_code', 'Single Playlist Code'),
        ('multi_code', 'Multi Playlist Code'),
        ('manual', 'Manually Granted'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='playlist_unlocks')
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name='unlocks')
    source = models.CharField(max_length=20, choices=UNLOCK_SOURCES, default='manual')
    unlocked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'playlist')

    def __str__(self):
        return f"{self.user} -> {self.playlist} ({self.source})"


class PlaylistAccessCode(models.Model):
    """Legacy single-playlist code. Still fully supported."""
    code = models.CharField(max_length=20, unique=True, validators=[MinLengthValidator(6)])
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE)
    is_used = models.BooleanField(default=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.code} -> {self.playlist.title}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_used and self.user_id:
            PlaylistUnlock.objects.get_or_create(
                user_id=self.user_id, playlist_id=self.playlist_id,
                defaults={'source': 'single_code'}
            )


class MultiPlaylistAccessCode(models.Model):
    """
    One code that unlocks one or more playlists (any mix, any courses)
    for whoever redeems it. Create/manage these from Django admin --
    use the playlists multi-select to choose exactly which playlist(s)
    a code grants (works fine with just one playlist selected too).
    """
    code = models.CharField(max_length=20, unique=True, validators=[MinLengthValidator(6)])
    playlists = models.ManyToManyField(Playlist, related_name='multi_access_codes')
    is_used = models.BooleanField(default=False)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='multi_access_codes_used'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        names = ", ".join(p.title for p in self.playlists.all()[:3])
        extra = self.playlists.count() - 3
        if extra > 0:
            names += f" (+{extra} more)"
        return f"{self.code} -> {names or 'no playlists selected'}"

    def redeem(self, user):
        """Marks the code used and unlocks every attached playlist for user.
        Returns the list of Playlist objects that were unlocked."""
        playlists = list(self.playlists.all())
        for playlist in playlists:
            PlaylistUnlock.objects.get_or_create(
                user=user, playlist=playlist, defaults={'source': 'multi_code'}
            )
        self.is_used = True
        self.used_by = user
        self.used_at = timezone.now()
        self.save()
        return playlists


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


# Add to your models.py

class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('system', 'System Alert'),
        ('payment', 'Payment Alert'),
        ('suspension', 'Suspension Warning'),
        ('general', 'General Announcement'),
    )

    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='general')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    show_on_login = models.BooleanField(default=False)  # Show when user logs in
    show_on_dashboard = models.BooleanField(default=True)  # Show on dashboard
    is_dismissible = models.BooleanField(default=True)  # User can dismiss

    def __str__(self):
        return f"{self.title} - {self.notification_type}"

    def is_expired(self):
        if self.expires_at:
            from django.utils import timezone
            return timezone.now() > self.expires_at
        return False

    @classmethod
    def get_active_notifications(cls, notification_type=None):
        from django.utils import timezone
        queryset = cls.objects.filter(
            is_active=True
        ).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
        )
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)
        return queryset


class UserNotification(models.Model):
    """
    This row is what makes a notification visible to a specific student.
    Creating a Notification in Django Admin has NO effect by itself -- it
    doesn't email anyone and doesn't appear on any dashboard. Only once an
    admin/instructor creates a UserNotification row here (assigning that
    notification to a specific student) does the student get emailed and see
    it appear on their dashboard. This same row also tracks read/dismissed
    state as the student interacts with it afterward.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE)
    is_read = models.BooleanField(default=False)
    is_dismissed = models.BooleanField(default=False)
    seen_at = models.DateTimeField(auto_now_add=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('user', 'notification')

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            self._email_student()

    def _email_student(self):
        """Best-effort email to this one student, the moment the notification
        is assigned to them. Never raises -- a mail hiccup shouldn't block
        the admin action that assigns it."""
        if not self.user.email:
            return
        from django.core.mail import send_mail
        from django.conf import settings as dj_settings
        try:
            send_mail(
                subject=f'[Othello Institute of Technology] {self.notification.title}',
                message=self.notification.message,
                from_email=dj_settings.DEFAULT_FROM_EMAIL,
                recipient_list=[self.user.email],
                fail_silently=True,
            )
        except Exception:
            pass


# ==============================================
# TASKS & SUBMISSIONS (auto-graded, instructor-approval-gated)
# ==============================================

class Task(models.Model):
    """A small auto-gradable task attached to a lesson."""
    TASK_TYPES = (
        ('text', 'Text (exact match)'),
        ('mcq', 'Multiple Choice'),
        ('true_false', 'True / False'),
    )

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='tasks')
    task_type = models.CharField(max_length=20, choices=TASK_TYPES, default='text')
    prompt = models.TextField(help_text="The question/instruction shown to the student.")
    correct_answer = models.CharField(
        max_length=500, blank=True,
        help_text="Used for 'Text' type (exact match, case-insensitive) and 'True/False' "
                   "type (enter True or False). Not used for Multiple Choice -- add options below instead."
    )
    max_score = models.PositiveIntegerField(default=10)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"Task for {self.lesson.title}"

    def grade(self, answer):
        """Auto-grader dispatched by task_type. Full marks on a correct answer, else 0."""
        if answer is None:
            return 0
        answer = str(answer).strip()

        if self.task_type == 'mcq':
            try:
                option = self.options.get(id=int(answer))
            except (TaskOption.DoesNotExist, ValueError, TypeError):
                return 0
            return self.max_score if option.is_correct else 0

        # 'text' and 'true_false' both use a simple case-insensitive exact match
        return self.max_score if answer.lower() == self.correct_answer.strip().lower() else 0


class TaskOption(models.Model):
    """One selectable option for a Multiple Choice Task."""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='options')
    text = models.CharField(max_length=300)
    is_correct = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.text


class Submission(models.Model):
    """
    A student's answer to a Task. Score is computed immediately (auto_score),
    but is only ever shown to the student once an instructor approves it.
    Instructors can override the score, and can approve or reject -- a
    rejected submission stays visible to the student as outstanding, and
    an approved one can still be revisited/edited later if needed.
    """
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='submissions')
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='submissions')
    answer = models.CharField(max_length=500)
    auto_score = models.PositiveIntegerField(default=0)
    instructor_score = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Leave blank to use the auto-computed score. Set this to override it before approving."
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    instructor_note = models.TextField(blank=True, help_text="Optional note shown to the student, e.g. why it was rejected.")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='reviewed_submissions'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'task')
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.student} -> {self.task} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.pk:
            self.auto_score = self.task.grade(self.answer)
        super().save(*args, **kwargs)

    @property
    def is_approved(self):
        return self.status == 'approved'

    @property
    def final_score(self):
        return self.instructor_score if self.instructor_score is not None else self.auto_score

    def approve(self, by_user, score=None):
        if score is not None:
            self.instructor_score = score
        self.status = 'approved'
        self.approved_by = by_user
        self.approved_at = timezone.now()
        self.save()

    def reject(self, by_user, note=''):
        self.status = 'rejected'
        self.approved_by = by_user
        self.approved_at = timezone.now()
        if note:
            self.instructor_note = note
        self.save()


class AssignedTask(models.Model):
    """
    A custom, link-based task an instructor assigns directly to one student
    (separate from the auto-graded lesson Tasks above). The student reads
    the instructions/resource link and submits their own link back; the
    instructor reviews and approves or rejects it. Optionally gated behind
    full completion of a specific playlist.
    """
    STATUS_CHOICES = (
        ('not_submitted', 'Not Submitted'),
        ('submitted', 'Submitted - Awaiting Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected - Needs Resubmission'),
    )

    instructor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assigned_tasks_given')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assigned_tasks')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='assigned_tasks')
    title = models.CharField(max_length=200)
    instructions = models.TextField()
    resource_link = models.URLField(
        blank=True,
        help_text="Optional reference link for the student to read first, e.g. a Google Drive PDF."
    )
    required_playlist = models.ForeignKey(
        Playlist, on_delete=models.SET_NULL, null=True, blank=True, related_name='gated_assigned_tasks',
        help_text="If set, this task only appears on the student's dashboard once the student has "
                   "completed at least 'Required lesson count' lessons in this playlist. Leave blank "
                   "for no prerequisite."
    )
    required_lesson_count = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="How many lessons in the required playlist must be completed before this task "
                   "becomes visible. Only used if a required playlist is set above."
    )
    submission_link = models.URLField(blank=True, help_text="The student's submitted link.")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_submitted')
    score = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Score out of 100, set by the instructor when approving. Optional."
    )
    instructor_note = models.TextField(blank=True, help_text="Optional note shown to the student, e.g. why it was rejected.")
    assigned_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='reviewed_assigned_tasks'
    )

    class Meta:
        ordering = ['-assigned_at']

    def __str__(self):
        return f"{self.title} -> {self.student}"

    @property
    def is_unlocked(self):
        if not self.required_playlist_id:
            return True
        completed = CompletedLesson.objects.filter(
            user=self.student, lesson__playlist=self.required_playlist
        ).count()
        # Falls back to "every lesson in the playlist" only if this task was
        # created before required_lesson_count existed (keeps old data working).
        required = self.required_lesson_count
        if required is None:
            required = self.required_playlist.lessons.count()
        return completed >= required

    def submit(self, link):
        self.submission_link = link
        self.status = 'submitted'
        self.submitted_at = timezone.now()
        self.save()

    def approve(self, by_user, score=None):
        self.status = 'approved'
        self.reviewed_by = by_user
        self.reviewed_at = timezone.now()
        if score is not None:
            self.score = score
        self.save()

    def reject(self, by_user, note=''):
        self.status = 'rejected'
        self.reviewed_by = by_user
        self.reviewed_at = timezone.now()
        if note:
            self.instructor_note = note
        self.save()


# ==============================================
# STUDENT PULSE SURVEY (monthly rating, admin-configurable frequency)
# ==============================================

class SurveyQuestion(models.Model):
    """One of the fixed questions shown in the periodic student survey."""
    text = models.CharField(max_length=300)
    is_instructor_related = models.BooleanField(
        default=False,
        help_text="Tick for the question that rates the instructor's performance. "
                   "Only this question's ratings are shown on instructor dashboards."
    )
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.text


class CourseSurveyConfig(models.Model):
    """Per-course control over how often the pulse survey is shown to its students."""
    course = models.OneToOneField(Course, on_delete=models.CASCADE, related_name='survey_config')
    interval_days = models.PositiveIntegerField(
        default=30,
        help_text="Days between one survey prompt and the next (e.g. 30 for monthly)."
    )
    max_occurrences = models.PositiveIntegerField(
        default=4,
        help_text="Total number of times the survey should ever be shown to a student on this course "
                   "(e.g. 2 for a short course, 4 or 5 for a longer one)."
    )

    def __str__(self):
        return f"{self.course.title}: every {self.interval_days}d, x{self.max_occurrences}"


class SurveyPrompt(models.Model):
    """
    One row per scheduled survey occurrence for a given student on a given course.
    Created lazily (get_or_create) as each occurrence becomes due. While
    completed_at is null and due_at <= now, this prompt BLOCKS the student's
    dashboard until answered -- it persists across logout/login.
    """
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='survey_prompts')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='survey_prompts')
    occurrence_number = models.PositiveIntegerField()
    due_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('student', 'course', 'occurrence_number')
        ordering = ['due_at']

    def __str__(self):
        return f"{self.student} / {self.course} #{self.occurrence_number}"

    @property
    def is_pending(self):
        return self.completed_at is None and self.due_at <= timezone.now()


class SurveyResponse(models.Model):
    """A single 1-10 answer to one question, tied to the course/instructor it's about."""
    prompt = models.ForeignKey(SurveyPrompt, on_delete=models.CASCADE, related_name='responses')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='survey_responses')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='survey_responses')
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_ratings',
        null=True, blank=True,
        help_text="Derived automatically from the course's instructor at save time."
    )
    question = models.ForeignKey(SurveyQuestion, on_delete=models.CASCADE, related_name='responses')
    rating = models.PositiveIntegerField(help_text="1-10")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('prompt', 'question')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student} rated '{self.question}' = {self.rating}"

    @property
    def color(self):
        if self.rating <= 3:
            return 'red'
        elif self.rating <= 6:
            return 'yellow'
        return 'green'

    def save(self, *args, **kwargs):
        if self.instructor_id is None:
            first_instructor = self.course.instructors.first()
            if first_instructor:
                self.instructor_id = first_instructor.id
        super().save(*args, **kwargs)