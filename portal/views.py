from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction
from django.contrib.auth import get_user_model
from .models import (
    AccessCode, Course, Playlist, PlaylistAccessCode, MultiPlaylistAccessCode,
    PlaylistUnlock, Lesson, CompletedLesson, Notification, UserNotification,
    Task, TaskOption, Submission, AssignedTask,
    SurveyQuestion, CourseSurveyConfig, SurveyPrompt, SurveyResponse,
)
from .forms import RegistrationForm, PlaylistUnlockForm, LoginForm
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from datetime import timedelta
from django.db import models
from django.db.models import Q
import math

User = get_user_model()

SURVEY_DISPLAY_DELAY_SECONDS = 600  # show the pulse survey ~10 minutes into the session, not instantly


def is_instructor(user):
    return user.is_authenticated and user.user_type == 'instructor'


def is_manager(user):
    return user.is_authenticated and user.user_type == 'manager'


# ==============================================
# GAUGE HELPER (used by KPI/gauge visuals on dashboards)
# ==============================================

def gauge_dash(value, max_value, radius=50):
    """Returns (circumference, dash_offset) for an SVG ring gauge, so templates
    can just drop these straight into stroke-dasharray / stroke-dashoffset."""
    circumference = 2 * math.pi * radius
    if not max_value:
        ratio = 0
    else:
        ratio = max(0, min(1, (value or 0) / max_value))
    offset = circumference * (1 - ratio)
    return round(circumference, 2), round(offset, 2)


def rating_color(value):
    if value is None:
        return '#bbbbbb'
    if value <= 3:
        return '#f44336'
    elif value <= 6:
        return '#f9a825'
    return '#4caf50'


def instructor_rating_responses(instructor):
    """All instructor-performance ratings for courses this instructor teaches.
    Matches purely by course + the is_instructor_related question flag --
    NOT by the stored `instructor` field on SurveyResponse. That field is
    only a snapshot taken from `course.instructors.first()` at the moment
    the student rated, which silently breaks the moment a course has more
    than one instructor (whoever isn't "first" would never see any rating).
    Matching by course directly avoids that class of bug entirely."""
    instructor_courses = instructor.instructor_courses.all()
    return SurveyResponse.objects.filter(
        question__is_instructor_related=True, course__in=instructor_courses
    )


def send_task_email(to_email, subject, message):
    """Best-effort email -- never raises, so a mail-server hiccup never
    breaks the request/response cycle it's attached to."""
    if not to_email:
        return
    from django.core.mail import send_mail
    from django.conf import settings as dj_settings
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=dj_settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=True,
        )
    except Exception:
        pass


# ==============================================
# PULSE SURVEY HELPERS
# ==============================================

def get_blocking_survey_prompt(student):
    """
    Returns the first SurveyPrompt that is currently due and unanswered for this
    student, creating it lazily if this is the first time it has become due.
    Returns None if nothing is currently due (survey exhausted, not due yet,
    or course has no CourseSurveyConfig).
    """
    if not student.is_authenticated or student.user_type != 'student':
        return None

    now = timezone.now()
    for course in student.courses.all():
        config = getattr(course, 'survey_config', None)
        if not config:
            continue

        completed_count = SurveyPrompt.objects.filter(
            student=student, course=course, completed_at__isnull=False
        ).count()
        if completed_count >= config.max_occurrences:
            continue

        occurrence_number = completed_count + 1
        due_at = student.date_joined + timedelta(days=config.interval_days * occurrence_number)
        if due_at > now:
            continue

        prompt, _ = SurveyPrompt.objects.get_or_create(
            student=student, course=course, occurrence_number=occurrence_number,
            defaults={'due_at': due_at}
        )
        if prompt.completed_at is None:
            return prompt
    return None


def get_outstanding_assigned_tasks(student):
    """Assigned tasks that are unlocked (prerequisite playlist met, if any) and
    still need student action (never submitted, or rejected and awaiting resubmit)."""
    candidates = AssignedTask.objects.filter(student=student).exclude(status='approved').select_related('required_playlist')
    return [t for t in candidates if t.is_unlocked and t.status in ('not_submitted', 'rejected')]


def get_visible_assigned_tasks(student):
    """All assigned tasks currently visible to the student (prerequisite met)."""
    candidates = AssignedTask.objects.filter(student=student).select_related(
        'required_playlist', 'course', 'instructor'
    ).order_by('-assigned_at')
    return [t for t in candidates if t.is_unlocked]


def registration_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
                    messages.success(request, f'✅ Account created successfully! Welcome {user.first_name}! Please login to continue.')
                    return redirect('login')
            except Exception as e:
                messages.error(request, f'Registration failed: {str(e)}')
                return render(request, 'portal/registration.html', {'form': form})
    else:
        form = RegistrationForm()

    return render(request, 'portal/registration.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        try:
            user = User.objects.get(email=email)

            if not user.is_active:
                request.session['suspended_email'] = email
                return redirect('suspended')

            user_auth = authenticate(request, username=user.username, password=password)
            if user_auth is not None:
                login(request, user_auth)
                messages.success(request, f'Welcome back, {user_auth.first_name}!')

                # Mark the moment this session started, so the pulse survey
                # (if one is due) waits a few minutes before appearing instead
                # of popping up the instant the student logs in.
                request.session['login_time'] = timezone.now().timestamp()

                # Clear any old session data
                if 'login_notifications' in request.session:
                    del request.session['login_notifications']

                # Check for notifications to show on login
                notifications = get_user_notifications(user)
                login_notifications = [n for n in notifications if n.get('show_on_login', False)]
                if login_notifications:
                    # Make sure all dates are strings
                    for notification in login_notifications:
                        if 'created_at' in notification and notification['created_at']:
                            if hasattr(notification['created_at'], 'isoformat'):
                                notification['created_at'] = notification['created_at'].isoformat()
                    request.session['login_notifications'] = login_notifications

                return redirect('dashboard')
            else:
                messages.error(request, 'Invalid email or password.')
        except User.DoesNotExist:
            messages.error(request, 'Invalid email or password.')

        return redirect('login')

    return render(request, 'portal/login.html')


def suspended_view(request):
    return render(request, 'portal/suspended.html')


def logout_view(request):
    logout(request)
    request.session.flush()
    return redirect('registration')


@login_required
def dashboard_view(request):
    user = request.user

    if user.user_type == 'instructor':
        return redirect('instructor_dashboard')

    if user.user_type == 'manager':
        return redirect('manager_dashboard')

    raw_pending_survey_prompt = get_blocking_survey_prompt(user)
    pending_survey_questions = SurveyQuestion.objects.filter(is_active=True) if raw_pending_survey_prompt else []
    survey_scale = range(1, 11)

    # Don't show the survey the instant a student logs in -- wait a
    # reasonable delay into the session first. If it's due but the delay
    # hasn't elapsed yet, we still tell the template how many seconds are
    # left so it can auto-reveal itself once the wait is over.
    login_time = request.session.get('login_time')
    elapsed = (timezone.now().timestamp() - login_time) if login_time else SURVEY_DISPLAY_DELAY_SECONDS
    seconds_remaining = max(0, int(SURVEY_DISPLAY_DELAY_SECONDS - elapsed))
    pending_survey_prompt = raw_pending_survey_prompt if seconds_remaining == 0 else None

    my_tasks_count = len(get_outstanding_assigned_tasks(user))
    rejected_lesson_tasks_count = Submission.objects.filter(student=user, status='rejected').count()

    student_courses = user.courses.all()

    if not student_courses.exists():
        messages.warning(request, 'You are not enrolled in any courses yet. Please contact your administrator.')
        context = {
            'user': user,
            'courses_data': [],
            'overall_progress': 0,
            'total_courses': 0,
            'total_completed': 0,
            'total_lessons': 0,
            'no_courses': True,
            'has_single_course': False,
            'notifications': [],
            'login_notifications': [],
            'has_unread_notifications': False,
            'pending_survey_prompt': pending_survey_prompt,
            'pending_survey_questions': pending_survey_questions,
            'survey_scale': survey_scale,
            'survey_seconds_remaining': seconds_remaining if raw_pending_survey_prompt else None,
            'my_tasks_count': my_tasks_count,
            'rejected_lesson_tasks_count': rejected_lesson_tasks_count,
        }
        return render(request, 'portal/student_dashboard.html', context)

    has_single_course = student_courses.count() == 1

    courses_data = []
    total_completed = 0
    total_lessons = 0

    for course in student_courses:
        course_lessons = Lesson.objects.filter(playlist__course=course).select_related('playlist')
        course_total = course_lessons.count()

        completed = CompletedLesson.objects.filter(
            user=user,
            lesson__in=course_lessons
        ).count()

        # Set of this user's completed lesson IDs in this course (used below to build the outline)
        completed_lesson_ids = set(
            CompletedLesson.objects.filter(user=user, lesson__in=course_lessons).values_list('lesson_id', flat=True)
        )

        total_completed += completed
        total_lessons += course_total

        playlists = Playlist.objects.filter(course=course)
        unlocked_playlist_ids = list(
            PlaylistUnlock.objects.filter(user=user, playlist__in=playlists).values_list('playlist_id', flat=True)
        )

        # --- NEW: build the expandable outline (playlist -> lessons) for this course ---
        outline = []
        for playlist in playlists:
            playlist_lessons = playlist.lessons.all()
            is_unlocked = playlist.id in unlocked_playlist_ids
            lessons_data = [
                {
                    'lesson': lesson,
                    'is_completed': lesson.id in completed_lesson_ids,
                }
                for lesson in playlist_lessons
            ]
            outline.append({
                'playlist': playlist,
                'lessons': lessons_data,
                'is_unlocked': is_unlocked,
                'lesson_count': len(lessons_data),
                'completed_count': sum(1 for l in lessons_data if l['is_completed']),
            })
        # --- END NEW ---

        courses_data.append({
            'course': course,
            'playlists': playlists,
            'unlocked_playlists': unlocked_playlist_ids,
            'completed': completed,
            'total': course_total,
            'progress': int((completed / course_total) * 100) if course_total > 0 else 0,
            'outline': outline,  # NEW — used only by the new course outline section
        })

    overall_progress = int((total_completed / total_lessons) * 100) if total_lessons > 0 else 0

    notifications = get_user_notifications(user)
    login_notifications = request.session.pop('login_notifications', [])

    context = {
        'user': user,
        'courses_data': courses_data,
        'overall_progress': overall_progress,
        'total_courses': student_courses.count(),
        'total_completed': total_completed,
        'total_lessons': total_lessons,
        'no_courses': False,
        'has_single_course': has_single_course,
        'single_course': courses_data[0] if has_single_course else None,
        'notifications': notifications,
        'login_notifications': login_notifications,
        'has_unread_notifications': any(not n['is_read'] for n in notifications if not n['is_dismissed']),
        'pending_survey_prompt': pending_survey_prompt,
        'pending_survey_questions': pending_survey_questions,
        'survey_scale': survey_scale,
        'survey_seconds_remaining': seconds_remaining if raw_pending_survey_prompt else None,
        'my_tasks_count': my_tasks_count,
        'rejected_lesson_tasks_count': rejected_lesson_tasks_count,
    }

    return render(request, 'portal/student_dashboard.html', context)


@login_required
def course_playlists_view(request, course_id):
    course = get_object_or_404(Course, id=course_id, students=request.user)

    playlists = Playlist.objects.filter(course=course)
    unlocked_playlist_ids = list(
        PlaylistUnlock.objects.filter(user=request.user, playlist__in=playlists).values_list('playlist_id', flat=True)
    )

    course_lessons = Lesson.objects.filter(playlist__course=course)
    total = course_lessons.count()
    completed = CompletedLesson.objects.filter(
        user=request.user,
        lesson__in=course_lessons
    ).count()
    progress = int((completed / total) * 100) if total > 0 else 0

    context = {
        'course': course,
        'playlists': playlists,
        'unlocked_playlists': unlocked_playlist_ids,
        'completed': completed,
        'total': total,
        'progress': progress,
        'user': request.user,
    }

    return render(request, 'portal/course_playlists.html', context)


@login_required
@user_passes_test(is_instructor)
def instructor_dashboard(request):
    """'My Courses' -- landing page for instructors: their course cards
    (equal-width, fills the row) plus their aggregate performance rating."""
    user = request.user
    instructor_courses = user.instructor_courses.all()

    pending_approvals_count = Submission.objects.filter(
        status='pending', task__lesson__playlist__course__in=instructor_courses
    ).count()
    pending_assigned_tasks_count = AssignedTask.objects.filter(
        instructor=user, status='submitted'
    ).count()

    total_students = User.objects.filter(user_type='student', courses__in=instructor_courses).distinct().count()

    # Aggregate instructor-performance rating across ALL of this instructor's courses
    instructor_responses = instructor_rating_responses(user)
    total_ratings = instructor_responses.count()
    overall_rating = round(sum(r.rating for r in instructor_responses) / total_ratings, 1) if total_ratings else None
    gauge_circumference, gauge_offset = gauge_dash(overall_rating or 0, 10)

    if not instructor_courses.exists():
        messages.warning(request, 'You are not assigned to any courses yet.')

    context = {
        'instructor_courses': instructor_courses,
        'total_students': total_students,
        'user': user,
        'pending_approvals_count': pending_approvals_count,
        'pending_assigned_tasks_count': pending_assigned_tasks_count,
        'overall_rating': overall_rating,
        'gauge_circumference': gauge_circumference,
        'gauge_offset': gauge_offset,
        'gauge_color': rating_color(overall_rating),
    }

    return render(request, 'portal/instructor_dashboard.html', context)


@login_required
@user_passes_test(is_instructor)
def instructor_students_view(request):
    """'My Students' -- the student progress table (moved out of the old
    combined dashboard so course cards and student progress are separate tabs)."""
    user = request.user
    instructor_courses = user.instructor_courses.all()

    if not instructor_courses.exists():
        messages.warning(request, 'You are not assigned to any courses yet.')
        context = {'students': [], 'total_students': 0}
        return render(request, 'portal/instructor_students.html', context)

    students = User.objects.filter(
        user_type='student',
        courses__in=instructor_courses
    ).distinct()

    student_progress = []
    for student in students:
        student_courses = student.courses.filter(id__in=instructor_courses)
        course_lessons = Lesson.objects.filter(playlist__course__in=student_courses)
        total_lessons = course_lessons.count()
        completed_lessons = CompletedLesson.objects.filter(
            user=student,
            lesson__in=course_lessons
        ).count()

        course_playlists = Playlist.objects.filter(course__in=student_courses)
        total_playlists = course_playlists.count()
        unlocked_playlists = PlaylistUnlock.objects.filter(
            user=student, playlist__in=course_playlists
        ).count()

        playlist_breakdown = []
        for course in student_courses:
            course_playlist_qs = Playlist.objects.filter(course=course)
            course_total_playlists = course_playlist_qs.count()
            course_unlocked = PlaylistUnlock.objects.filter(
                user=student, playlist__in=course_playlist_qs
            ).count()
            playlist_breakdown.append({
                'course': course,
                'unlocked': course_unlocked,
                'total': course_total_playlists,
            })

        student_progress.append({
            'student': student,
            'courses': student_courses,
            'completed': completed_lessons,
            'total': total_lessons,
            'progress': int((completed_lessons / total_lessons) * 100) if total_lessons > 0 else 0,
            'unlocked_playlists': unlocked_playlists,
            'total_playlists': total_playlists,
            'playlist_breakdown': playlist_breakdown,
        })

    student_progress.sort(key=lambda x: x['progress'], reverse=True)

    pending_approvals_count = Submission.objects.filter(
        status='pending', task__lesson__playlist__course__in=instructor_courses
    ).count()

    pending_assigned_tasks_count = AssignedTask.objects.filter(
        instructor=request.user, status='submitted'
    ).count()

    context = {
        'students': student_progress,
        'total_students': len(student_progress),
        'pending_approvals_count': pending_approvals_count,
        'pending_assigned_tasks_count': pending_assigned_tasks_count,
    }

    return render(request, 'portal/instructor_students.html', context)


@login_required
def admin_student_detail(request, student_id):
    student = get_object_or_404(User, id=student_id, user_type='student')

    if request.user.user_type == 'instructor':
        if not student.courses.filter(id__in=request.user.instructor_courses.all()).exists():
            messages.error(request, "You don't have permission to view this student.")
            return redirect('instructor_dashboard')
    else:
        messages.error(request, "You don't have permission to access this page.")
        return redirect('dashboard')

    instructor_courses = request.user.instructor_courses.all()
    completed_lessons = CompletedLesson.objects.filter(
        user=student,
        lesson__playlist__course__in=instructor_courses
    ).select_related('lesson', 'lesson__playlist')

    lessons_by_playlist = {}
    for completed in completed_lessons:
        lesson = completed.lesson
        playlist = lesson.playlist
        if playlist.id not in lessons_by_playlist:
            lessons_by_playlist[playlist.id] = {
                'playlist': playlist,
                'lessons': []
            }
        lessons_by_playlist[playlist.id]['lessons'].append(lesson)

    # All of this student's work in the instructor's courses -- scores visible
    # and revisitable/editable right here, not just in the separate approvals queue.
    submissions = Submission.objects.filter(
        student=student, task__lesson__playlist__course__in=instructor_courses
    ).select_related('task', 'task__lesson', 'task__lesson__playlist').order_by('-submitted_at')

    assigned_tasks = AssignedTask.objects.filter(
        student=student, course__in=instructor_courses
    ).order_by('-assigned_at')

    context = {
        'student': student,
        'lessons_by_playlist': lessons_by_playlist,
        'total_completed': completed_lessons.count(),
        'submissions': submissions,
        'assigned_tasks': assigned_tasks,
    }

    return render(request, 'portal/admin_student_detail.html', context)


@login_required
def unlock_playlist_view(request, playlist_id):
    playlist = get_object_or_404(Playlist, id=playlist_id, course__in=request.user.courses.all())

    if PlaylistUnlock.objects.filter(user=request.user, playlist=playlist).exists():
        messages.info(request, f'Playlist "{playlist.title}" is already unlocked!')
        return redirect('playlist_lessons', playlist_id=playlist.id)

    if request.method == 'POST':
        code = request.POST.get('access_code', '').strip().upper()

        # Try legacy single-playlist code first
        try:
            pac = PlaylistAccessCode.objects.get(code=code, playlist=playlist, is_used=False)
            pac.is_used = True
            pac.user = request.user
            pac.save()
            messages.success(request, f'Successfully unlocked "{playlist.title}"!')
            return redirect('playlist_lessons', playlist_id=playlist.id)
        except PlaylistAccessCode.DoesNotExist:
            pass

        # Fall back to a multi-playlist code that includes this playlist
        try:
            mpac = MultiPlaylistAccessCode.objects.get(code=code, is_used=False, playlists=playlist)
            unlocked = mpac.redeem(request.user)
            if len(unlocked) > 1:
                titles = ", ".join(p.title for p in unlocked)
                messages.success(request, f'Code accepted! Unlocked {len(unlocked)} playlists: {titles}')
            else:
                messages.success(request, f'Successfully unlocked "{playlist.title}"!')
            return redirect('playlist_lessons', playlist_id=playlist.id)
        except MultiPlaylistAccessCode.DoesNotExist:
            messages.error(request, f'Invalid access code for "{playlist.title}".')
    else:
        form = PlaylistUnlockForm()

    return render(request, 'portal/unlock_playlist.html', {'playlist': playlist})


@login_required
def playlist_lessons_view(request, playlist_id):
    playlist = get_object_or_404(Playlist, id=playlist_id, course__in=request.user.courses.all())

    if not PlaylistUnlock.objects.filter(user=request.user, playlist=playlist).exists():
        messages.warning(request, f'You need to unlock "{playlist.title}" first.')
        return redirect('unlock_playlist', playlist_id=playlist.id)

    lessons = playlist.lessons.all()
    completed_ids = CompletedLesson.objects.filter(user=request.user, lesson__in=lessons).values_list('lesson_id', flat=True)

    context = {
        'playlist': playlist,
        'lessons': lessons,
        'completed_ids': completed_ids,
    }
    return render(request, 'portal/playlist_lessons.html', context)


@login_required
def lesson_detail_view(request, playlist_id, lesson_id):
    playlist = get_object_or_404(Playlist, id=playlist_id, course__in=request.user.courses.all())

    if not PlaylistUnlock.objects.filter(user=request.user, playlist=playlist).exists():
        messages.warning(request, f'You need to unlock "{playlist.title}" first.')
        return redirect('unlock_playlist', playlist_id=playlist.id)

    lesson = get_object_or_404(Lesson, id=lesson_id, playlist=playlist)
    is_completed = CompletedLesson.objects.filter(user=request.user, lesson=lesson).exists()

    tasks = list(lesson.tasks.all())
    submissions_by_task = {
        s.task_id: s for s in Submission.objects.filter(student=request.user, task__in=tasks)
    }

    lessons = list(playlist.lessons.all())
    current_index = next((i for i, l in enumerate(lessons) if l.id == lesson.id), -1)
    prev_lesson = lessons[current_index - 1] if current_index > 0 else None
    next_lesson = lessons[current_index + 1] if current_index + 1 < len(lessons) else None

    if prev_lesson:
        prev_completed = CompletedLesson.objects.filter(user=request.user, lesson=prev_lesson).exists()
        if not prev_completed and not is_completed:
            messages.warning(request, f'Please complete "{prev_lesson.title}" first.')
            return redirect('lesson_detail', playlist_id=playlist.id, lesson_id=prev_lesson.id)

    if request.method == 'POST':
        if 'mark_complete' in request.POST:
            unsubmitted_tasks = [t for t in tasks if t.id not in submissions_by_task or submissions_by_task[t.id].status == 'rejected']
            outstanding_assigned = get_outstanding_assigned_tasks(request.user)

            if unsubmitted_tasks:
                messages.warning(request, f'Please complete the task on this lesson before marking it done.')
                return redirect('lesson_detail', playlist_id=playlist.id, lesson_id=lesson.id)
            if outstanding_assigned:
                messages.warning(request, 'You have an outstanding assigned task waiting -- please submit it before continuing.')
                return redirect('student_tasks')

            if not is_completed:
                CompletedLesson.objects.create(user=request.user, lesson=lesson)
                messages.success(request, f'✓ "{lesson.title}" completed!')
                return redirect('lesson_detail', playlist_id=playlist.id, lesson_id=lesson.id)

        elif 'undo_complete' in request.POST:
            if is_completed:
                CompletedLesson.objects.filter(user=request.user, lesson=lesson).delete()
                messages.info(request, f'"{lesson.title}" marked as incomplete.')
                return redirect('lesson_detail', playlist_id=playlist.id, lesson_id=lesson.id)

    # Tasks are attempted on their own page now (task_detail_view) --
    # here we just show each task's status and a link to attempt/review it.
    tasks_data = [
        {'task': t, 'submission': submissions_by_task.get(t.id)}
        for t in tasks
    ]

    unsubmitted_tasks = [t for t in tasks if t.id not in submissions_by_task or submissions_by_task[t.id].status == 'rejected']
    outstanding_assigned = get_outstanding_assigned_tasks(request.user)
    can_proceed = not unsubmitted_tasks and not outstanding_assigned

    context = {
        'playlist': playlist,
        'lesson': lesson,
        'is_completed': is_completed,
        'prev_lesson': prev_lesson,
        'next_lesson': next_lesson,
        'total_lessons': len(lessons),
        'current_number': current_index + 1,
        'tasks_data': tasks_data,
        'can_proceed': can_proceed,
        'has_unsubmitted_lesson_tasks': bool(unsubmitted_tasks),
        'has_outstanding_assigned_tasks': bool(outstanding_assigned),
    }
    return render(request, 'portal/lesson_detail.html', context)


@login_required
def task_detail_view(request, playlist_id, lesson_id, task_id):
    """Standalone attempt page for a lesson task -- text, MCQ, or true/false.
    A rejected submission can be edited and resubmitted here."""
    playlist = get_object_or_404(Playlist, id=playlist_id, course__in=request.user.courses.all())
    if not PlaylistUnlock.objects.filter(user=request.user, playlist=playlist).exists():
        messages.warning(request, f'You need to unlock "{playlist.title}" first.')
        return redirect('unlock_playlist', playlist_id=playlist.id)

    lesson = get_object_or_404(Lesson, id=lesson_id, playlist=playlist)
    task = get_object_or_404(Task, id=task_id, lesson=lesson)
    submission = Submission.objects.filter(student=request.user, task=task).first()
    can_submit = submission is None or submission.status == 'rejected'

    if request.method == 'POST' and can_submit:
        if task.task_type == 'mcq':
            answer = request.POST.get('option_id', '').strip()
        else:
            answer = request.POST.get('answer', '').strip()

        if not answer:
            messages.error(request, 'Please provide an answer before submitting.')
        elif submission is None:
            submission = Submission.objects.create(student=request.user, task=task, answer=answer)
            messages.success(request, 'Task submitted! Your instructor will review and approve it before the score appears in Grades.')
            return redirect('lesson_detail', playlist_id=playlist.id, lesson_id=lesson.id)
        else:
            # Resubmission after rejection
            submission.answer = answer
            submission.auto_score = task.grade(answer)
            submission.status = 'pending'
            submission.instructor_note = ''
            submission.save()
            messages.success(request, 'Resubmitted! Awaiting instructor review.')
            return redirect('lesson_detail', playlist_id=playlist.id, lesson_id=lesson.id)

    context = {
        'playlist': playlist,
        'lesson': lesson,
        'task': task,
        'submission': submission,
        'can_submit': can_submit,
        'options': task.options.all() if task.task_type == 'mcq' else None,
    }
    return render(request, 'portal/task_detail.html', context)


@login_required
def submit_survey_view(request, prompt_id):
    """Handles the blocking monthly pulse survey. Student must rate every
    active question 1-10 before the prompt is marked complete and released."""
    prompt = get_object_or_404(SurveyPrompt, id=prompt_id, student=request.user)

    if prompt.completed_at is not None:
        return redirect('dashboard')

    if request.method == 'POST':
        questions = list(SurveyQuestion.objects.filter(is_active=True))
        answers = {}
        for question in questions:
            raw = request.POST.get(f'question_{question.id}')
            try:
                rating = int(raw)
            except (TypeError, ValueError):
                rating = None
            if rating is None or rating < 1 or rating > 10:
                messages.error(request, 'Please rate every question from 1 to 10 before continuing.')
                return redirect('dashboard')
            answers[question] = rating

        with transaction.atomic():
            for question, rating in answers.items():
                SurveyResponse.objects.update_or_create(
                    prompt=prompt, question=question,
                    defaults={
                        'student': request.user,
                        'course': prompt.course,
                        'rating': rating,
                    }
                )
            prompt.completed_at = timezone.now()
            prompt.save(update_fields=['completed_at'])

        messages.success(request, 'Thanks for your feedback!')
        return redirect('dashboard')

    return redirect('dashboard')


@login_required
def student_grades_view(request):
    """Student-facing Grades tab: only shows submissions the instructor has approved,
    plus an overall CGPA-style percentage across ALL approved work -- lesson
    tasks AND instructor-assigned tasks, combined cumulatively."""
    user = request.user
    submissions = Submission.objects.filter(
        student=user, status='approved'
    ).select_related('task', 'task__lesson', 'task__lesson__playlist', 'task__lesson__playlist__course')

    pending_count = Submission.objects.filter(student=user, status='pending').count()
    rejected_submissions = Submission.objects.filter(student=user, status='rejected').select_related(
        'task', 'task__lesson', 'task__lesson__playlist'
    )
    rejected_count = rejected_submissions.count()
    first_rejected = rejected_submissions.first()

    scored_assigned_tasks = AssignedTask.objects.filter(
        student=user, status='approved', score__isnull=False
    ).select_related('course')

    total_scored = sum(s.final_score for s in submissions) + sum(t.score for t in scored_assigned_tasks)
    total_possible = sum(s.task.max_score for s in submissions) + (100 * scored_assigned_tasks.count())
    cgpa_percent = round((total_scored / total_possible) * 100, 1) if total_possible else None

    circumference, offset = gauge_dash(cgpa_percent or 0, 100)

    context = {
        'submissions': submissions,
        'scored_assigned_tasks': scored_assigned_tasks,
        'pending_count': pending_count,
        'rejected_count': rejected_count,
        'first_rejected': first_rejected,
        'cgpa_percent': cgpa_percent,
        'gauge_circumference': circumference,
        'gauge_offset': offset,
    }
    return render(request, 'portal/student_grades.html', context)


@login_required
@user_passes_test(is_instructor)
def instructor_approvals_view(request):
    """'My Tasks' -- auto-graded lesson-task submissions AND instructor-assigned
    link tasks awaiting review. Once graded (approved OR rejected), an item
    leaves this page entirely -- it can only be revisited afterward from
    that student's 'View Details' page."""
    instructor_courses = request.user.instructor_courses.all()

    pending_submissions = Submission.objects.filter(
        status='pending', task__lesson__playlist__course__in=instructor_courses
    ).select_related('student', 'task', 'task__lesson', 'task__lesson__playlist').order_by('-submitted_at')

    pending_assigned = AssignedTask.objects.filter(
        instructor=request.user, status='submitted'
    ).select_related('student', 'course').order_by('-submitted_at')

    pending_count = pending_submissions.count()
    pending_assigned_count = pending_assigned.count()

    context = {
        'pending_submissions': pending_submissions,
        'pending_assigned': pending_assigned,
        'pending_count': pending_count,
        'pending_approvals_count': pending_count,
        'pending_assigned_tasks_count': pending_assigned_count,
    }
    return render(request, 'portal/instructor_approvals.html', context)


@login_required
@user_passes_test(is_instructor)
def approve_submission_view(request, submission_id):
    """Approve (or re-approve) a submission. An optional 'score' field lets the
    instructor override the auto-computed score before/while approving."""
    instructor_courses = request.user.instructor_courses.all()
    submission = get_object_or_404(
        Submission, id=submission_id, task__lesson__playlist__course__in=instructor_courses
    )
    if request.method == 'POST':
        raw_score = request.POST.get('score', '').strip()
        score = int(raw_score) if raw_score.isdigit() else None
        submission.approve(request.user, score=score)
        messages.success(request, f"Approved {submission.student.get_full_name()}'s submission.")
    return redirect('instructor_approvals')


@login_required
@user_passes_test(is_instructor)
def reject_submission_view(request, submission_id):
    """Reject a submission -- it becomes outstanding for the student to resubmit."""
    instructor_courses = request.user.instructor_courses.all()
    submission = get_object_or_404(
        Submission, id=submission_id, task__lesson__playlist__course__in=instructor_courses
    )
    if request.method == 'POST':
        submission.reject(request.user, note=request.POST.get('note', ''))
        messages.info(request, f"Rejected {submission.student.get_full_name()}'s submission -- they can resubmit.")

        task_url = request.build_absolute_uri(
            reverse('task_detail', args=[submission.task.lesson.playlist.id, submission.task.lesson.id, submission.task.id])
        )
        send_task_email(
            submission.student.email,
            subject='[OIT] A task submission needs your attention',
            message=(
                f"Hi {submission.student.first_name},\n\n"
                f"Your instructor reviewed your submission for \"{submission.task.prompt}\" "
                f"and asked you to resubmit it.\n\n"
                f"{'Note: ' + submission.instructor_note if submission.instructor_note else ''}\n\n"
                f"Please resubmit here: {task_url}\n\n"
                f"- Othello Institute of Technology"
            ),
        )
    return redirect('instructor_approvals')


@login_required
@user_passes_test(is_instructor)
def approve_all_submissions_view(request):
    instructor_courses = request.user.instructor_courses.all()
    if request.method == 'POST':
        pending = Submission.objects.filter(
            status='pending', task__lesson__playlist__course__in=instructor_courses
        )
        count = pending.count()
        now = timezone.now()
        pending.update(status='approved', approved_by=request.user, approved_at=now)
        messages.success(request, f'Approved {count} submission(s).')
    return redirect('instructor_approvals')


@login_required
@user_passes_test(is_instructor)
def reject_all_submissions_view(request):
    instructor_courses = request.user.instructor_courses.all()
    if request.method == 'POST':
        pending = Submission.objects.filter(
            status='pending', task__lesson__playlist__course__in=instructor_courses
        )
        count = pending.count()
        now = timezone.now()
        pending.update(status='rejected', approved_by=request.user, approved_at=now)
        messages.info(request, f'Rejected {count} submission(s). Students can resubmit.')
    return redirect('instructor_approvals')


@login_required
@user_passes_test(is_instructor)
def approve_assigned_task_view(request, assigned_task_id):
    assigned_task = get_object_or_404(AssignedTask, id=assigned_task_id, instructor=request.user)
    if request.method == 'POST':
        raw_score = request.POST.get('score', '').strip()
        score = None
        if raw_score.isdigit():
            score = max(1, min(100, int(raw_score)))
        assigned_task.approve(request.user, score=score)
        messages.success(request, f"Approved {assigned_task.student.get_full_name()}'s assigned task.")
    return redirect('instructor_approvals')


@login_required
@user_passes_test(is_instructor)
def reject_assigned_task_view(request, assigned_task_id):
    assigned_task = get_object_or_404(AssignedTask, id=assigned_task_id, instructor=request.user)
    if request.method == 'POST':
        assigned_task.reject(request.user, note=request.POST.get('note', ''))
        messages.info(request, f"Rejected {assigned_task.student.get_full_name()}'s assigned task -- they can resubmit.")

        task_url = request.build_absolute_uri(reverse('assigned_task_detail', args=[assigned_task.id]))
        send_task_email(
            assigned_task.student.email,
            subject='[OIT] Your assigned task needs your attention',
            message=(
                f"Hi {assigned_task.student.first_name},\n\n"
                f"Your instructor reviewed your submission for \"{assigned_task.title}\" "
                f"and asked you to resubmit it.\n\n"
                f"{'Note: ' + assigned_task.instructor_note if assigned_task.instructor_note else ''}\n\n"
                f"Please resubmit here: {task_url}\n\n"
                f"- Othello Institute of Technology"
            ),
        )
    return redirect('instructor_approvals')


@login_required
@user_passes_test(is_instructor)
def instructor_course_outline_view(request):
    """Instructor's own outline view: every playlist/lesson for their courses,
    laid out vertically and grouped by playlist -- no locks, and the lesson
    video can be played right there (same player students get)."""
    instructor_courses = request.user.instructor_courses.all()
    courses_outline = []
    for course in instructor_courses:
        playlists = Playlist.objects.filter(course=course).prefetch_related('lessons')
        courses_outline.append({
            'course': course,
            'playlists': playlists,
        })

    pending_approvals_count = Submission.objects.filter(
        status='pending', task__lesson__playlist__course__in=instructor_courses
    ).count()
    pending_assigned_tasks_count = AssignedTask.objects.filter(
        instructor=request.user, status='submitted'
    ).count()
    context = {
        'courses_outline': courses_outline,
        'pending_approvals_count': pending_approvals_count,
        'pending_assigned_tasks_count': pending_assigned_tasks_count,
    }
    return render(request, 'portal/instructor_course_outline.html', context)


@login_required
@user_passes_test(is_instructor)
def instructor_survey_view(request):
    """Instructor sees ONLY the ratings tied to their own courses, and only the
    instructor-performance question -- never other instructors' ratings, no
    response counts, no student identity -- just the overall rating and a
    breakdown per course."""
    responses = instructor_rating_responses(request.user).select_related('course')

    total = responses.count()
    average = round(sum(r.rating for r in responses) / total, 1) if total else None
    gauge_circumference, gauge_offset = gauge_dash(average or 0, 10)

    per_course = []
    for course in request.user.instructor_courses.all():
        course_responses = responses.filter(course=course)
        c_total = course_responses.count()
        c_avg = round(sum(r.rating for r in course_responses) / c_total, 1) if c_total else None
        per_course.append({'course': course, 'average': c_avg, 'color': rating_color(c_avg)})

    instructor_courses = request.user.instructor_courses.all()
    pending_approvals_count = Submission.objects.filter(
        status='pending', task__lesson__playlist__course__in=instructor_courses
    ).count()
    pending_assigned_tasks_count = AssignedTask.objects.filter(
        instructor=request.user, status='submitted'
    ).count()

    context = {
        'average': average,
        'gauge_circumference': gauge_circumference,
        'gauge_offset': gauge_offset,
        'gauge_color': rating_color(average),
        'per_course': per_course,
        'pending_approvals_count': pending_approvals_count,
        'pending_assigned_tasks_count': pending_assigned_tasks_count,
    }
    return render(request, 'portal/instructor_survey.html', context)


@login_required
@user_passes_test(is_manager)
def manager_dashboard_view(request):
    """Manager: assigned to all courses. Sees student progress and unlocked
    playlists like an instructor, but NOT course outline/lessons. Includes
    equally-sized KPI cards (incl. an aggregate rating gauge) under the
    welcome card."""
    all_courses = Course.objects.all()
    students = User.objects.filter(user_type='student').distinct()

    student_progress = []
    for student in students:
        student_courses = student.courses.all()
        if not student_courses.exists():
            continue
        course_lessons = Lesson.objects.filter(playlist__course__in=student_courses)
        total_lessons = course_lessons.count()
        completed_lessons = CompletedLesson.objects.filter(user=student, lesson__in=course_lessons).count()

        course_playlists = Playlist.objects.filter(course__in=student_courses)
        total_playlists = course_playlists.count()
        unlocked_playlists = PlaylistUnlock.objects.filter(user=student, playlist__in=course_playlists).count()

        student_progress.append({
            'student': student,
            'courses': student_courses,
            'completed': completed_lessons,
            'total': total_lessons,
            'progress': int((completed_lessons / total_lessons) * 100) if total_lessons > 0 else 0,
            'unlocked_playlists': unlocked_playlists,
            'total_playlists': total_playlists,
        })

    student_progress.sort(key=lambda x: x['progress'], reverse=True)

    # Platform-wide aggregate rating (all questions, all courses) for the KPI gauge
    all_responses = SurveyResponse.objects.all()
    total_ratings = all_responses.count()
    overall_rating = round(sum(r.rating for r in all_responses) / total_ratings, 1) if total_ratings else None
    gauge_circumference, gauge_offset = gauge_dash(overall_rating or 0, 10)

    context = {
        'all_courses': all_courses,
        'students': student_progress,
        'total_students': len(student_progress),
        'overall_rating': overall_rating,
        'gauge_circumference': gauge_circumference,
        'gauge_offset': gauge_offset,
        'gauge_color': rating_color(overall_rating),
        'total_ratings': total_ratings,
    }
    return render(request, 'portal/manager_dashboard.html', context)


@login_required
@user_passes_test(is_manager)
def manager_survey_view(request):
    """Manager sees ALL survey data across every course/instructor: raw
    per-response rows (with student name+email) plus an aggregate rollup."""
    responses = SurveyResponse.objects.select_related(
        'student', 'course', 'instructor', 'question'
    ).order_by('-created_at')

    aggregates = {}
    for question in SurveyQuestion.objects.filter(is_active=True):
        q_responses = responses.filter(question=question)
        total = q_responses.count()
        avg = (sum(r.rating for r in q_responses) / total) if total else None
        aggregates[question.text] = {
            'total': total,
            'average': round(avg, 1) if avg is not None else None,
        }

    context = {
        'responses': responses,
        'aggregates': aggregates,
    }
    return render(request, 'portal/manager_survey.html', context)


@login_required
def student_tasks_view(request):
    """'My Tasks' -- instructor-assigned link-based tasks visible to this
    student (prerequisite playlist, if any, already completed)."""
    if request.user.user_type != 'student':
        return redirect('dashboard')

    visible_tasks = get_visible_assigned_tasks(request.user)

    context = {'assigned_tasks': visible_tasks}
    return render(request, 'portal/student_tasks.html', context)


@login_required
def assigned_task_detail_view(request, assigned_task_id):
    """Student reads instructions/resource link and submits (or updates,
    pre-approval) their own submission link."""
    assigned_task = get_object_or_404(AssignedTask, id=assigned_task_id, student=request.user)

    if not assigned_task.is_unlocked:
        messages.warning(request, 'This task is not available to you yet.')
        return redirect('student_tasks')

    can_edit = assigned_task.status != 'approved'

    if request.method == 'POST' and can_edit:
        link = request.POST.get('submission_link', '').strip()
        if not link:
            messages.error(request, 'Please provide a link before submitting.')
        else:
            assigned_task.submit(link)
            messages.success(request, 'Submitted! Your instructor will review it.')
            return redirect('student_tasks')

    context = {
        'assigned_task': assigned_task,
        'can_edit': can_edit,
    }
    return render(request, 'portal/assigned_task_detail.html', context)


@login_required
@user_passes_test(is_instructor)
def instructor_assign_task_view(request):
    """Instructor assigns a custom, link-based task directly to one OR
    several of their own students at once, optionally gated behind a
    minimum number of completed lessons in a chosen playlist."""
    instructor_courses = request.user.instructor_courses.all()
    students = User.objects.filter(user_type='student', courses__in=instructor_courses).distinct()
    playlists = Playlist.objects.filter(course__in=instructor_courses)

    if request.method == 'POST':
        student_ids = request.POST.getlist('student_ids')
        course_id = request.POST.get('course_id')
        title = request.POST.get('title', '').strip()
        instructions = request.POST.get('instructions', '').strip()
        resource_link = request.POST.get('resource_link', '').strip()
        required_playlist_id = request.POST.get('required_playlist_id') or None
        raw_required_count = request.POST.get('required_lesson_count', '').strip()
        required_lesson_count = int(raw_required_count) if raw_required_count.isdigit() else None

        course = get_object_or_404(Course, id=course_id, id__in=instructor_courses.values_list('id', flat=True))
        selected_students = User.objects.filter(
            id__in=student_ids, user_type='student', courses__in=instructor_courses
        ).distinct()

        if not title or not instructions:
            messages.error(request, 'Please provide at least a title and instructions.')
        elif not selected_students.exists():
            messages.error(request, 'Please select at least one student.')
        else:
            for student in selected_students:
                assigned_task = AssignedTask.objects.create(
                    instructor=request.user,
                    student=student,
                    course=course,
                    title=title,
                    instructions=instructions,
                    resource_link=resource_link,
                    required_playlist_id=required_playlist_id,
                    required_lesson_count=required_lesson_count if required_playlist_id else None,
                )
                task_url = request.build_absolute_uri(reverse('assigned_task_detail', args=[assigned_task.id]))
                send_task_email(
                    student.email,
                    subject=f'[OIT] New task assigned: {title}',
                    message=(
                        f"Hi {student.first_name},\n\n"
                        f"Your instructor has assigned you a new task: \"{title}\".\n\n"
                        f"{instructions}\n\n"
                        f"View and submit it here: {task_url}\n\n"
                        f"- Othello Institute of Technology"
                    ),
                )
            messages.success(request, f'Task assigned to {selected_students.count()} student(s).')
            return redirect('instructor_approvals')

    context = {
        'students': students,
        'courses': instructor_courses,
        'playlists': playlists,
    }
    return render(request, 'portal/instructor_assign_task.html', context)


@require_http_methods(["GET"])
def check_email_exists(request):
    email = request.GET.get('email', '')
    exists = User.objects.filter(email=email).exists()
    return JsonResponse({'exists': exists})


@require_http_methods(["GET"])
def check_access_code_valid(request):
    code = request.GET.get('code', '')
    try:
        access_code = AccessCode.objects.get(code=code, is_used=False)
        return JsonResponse({
            'valid': True,
            'course': access_code.course.title if access_code.course else None,
            'access_type': access_code.access_type
        })
    except AccessCode.DoesNotExist:
        return JsonResponse({'valid': False})


# ==============================================
# NOTIFICATION FUNCTIONS
# ==============================================

def get_user_notifications(user):
    """Get notifications for a user -- ONLY ones that have actually been
    assigned to them via a UserNotification row. Creating a Notification in
    Django Admin does not, by itself, make it visible to anyone; an
    admin/instructor must assign it to specific student(s) first."""
    from django.db import models

    user_notifications = UserNotification.objects.filter(user=user).select_related('notification')

    notifications_data = []
    for user_notif in user_notifications:
        notification = user_notif.notification

        if not notification.is_active:
            continue
        if notification.expires_at and notification.expires_at <= timezone.now():
            continue

        # Skip dismissed notifications (unless they're on login)
        if user_notif.is_dismissed and not notification.show_on_login:
            continue

        created_at_str = None
        if notification.created_at:
            if hasattr(notification.created_at, 'isoformat'):
                created_at_str = notification.created_at.isoformat()
            else:
                created_at_str = str(notification.created_at)

        notifications_data.append({
            'id': notification.id,
            'title': notification.title,
            'message': notification.message,
            'notification_type': notification.notification_type,
            'created_at': created_at_str,
            'is_read': user_notif.is_read,
            'is_dismissed': user_notif.is_dismissed,
            'show_on_login': notification.show_on_login,
            'is_dismissible': notification.is_dismissible,
        })

    return notifications_data


@login_required
def notification_mark_read(request, notification_id):
    if request.method == 'POST':
        try:
            notification = get_object_or_404(Notification, id=notification_id)
            user_notif, created = UserNotification.objects.get_or_create(
                user=request.user,
                notification=notification
            )
            user_notif.is_read = True
            user_notif.save()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False})


@login_required
def notification_dismiss(request, notification_id):
    if request.method == 'POST':
        try:
            notification = get_object_or_404(Notification, id=notification_id)
            user_notif, created = UserNotification.objects.get_or_create(
                user=request.user,
                notification=notification
            )
            user_notif.is_dismissed = True
            user_notif.dismissed_at = timezone.now()
            user_notif.save()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False})


@login_required
def get_notifications_api(request):
    notifications = get_user_notifications(request.user)
    return JsonResponse({
        'notifications': notifications,
        'has_unread': any(not n['is_read'] for n in notifications if not n['is_dismissed'])
    })