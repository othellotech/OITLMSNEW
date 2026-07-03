from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction
from django.contrib.auth import get_user_model
from .models import (
    AccessCode, Course, Playlist, PlaylistAccessCode, MultiPlaylistAccessCode,
    PlaylistUnlock, Lesson, CompletedLesson, Notification, UserNotification
)
from .forms import RegistrationForm, PlaylistUnlockForm, LoginForm
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db import models

User = get_user_model()


def is_instructor(user):
    return user.is_authenticated and user.user_type == 'instructor'


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
    user = request.user
    instructor_courses = user.instructor_courses.all()

    if not instructor_courses.exists():
        messages.warning(request, 'You are not assigned to any courses yet.')
        context = {
            'instructor_courses': [],
            'students': [],
            'total_students': 0,
        }
        return render(request, 'portal/instructor_dashboard.html', context)

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

        # --- NEW: per-course breakdown of unlocked playlists ---
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
        # --- END NEW ---

        student_progress.append({
            'student': student,
            'courses': student_courses,
            'completed': completed_lessons,
            'total': total_lessons,
            'progress': int((completed_lessons / total_lessons) * 100) if total_lessons > 0 else 0,
            'unlocked_playlists': unlocked_playlists,
            'total_playlists': total_playlists,
            'playlist_breakdown': playlist_breakdown,  # NEW
        })

    student_progress.sort(key=lambda x: x['progress'], reverse=True)

    context = {
        'instructor_courses': instructor_courses,
        'students': student_progress,
        'total_students': len(student_progress),
        'user': user,
    }

    return render(request, 'portal/instructor_dashboard.html', context)


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

    context = {
        'student': student,
        'lessons_by_playlist': lessons_by_playlist,
        'total_completed': completed_lessons.count(),
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
            if not is_completed:
                CompletedLesson.objects.create(user=request.user, lesson=lesson)
                messages.success(request, f'✓ "{lesson.title}" completed!')
                return redirect('lesson_detail', playlist_id=playlist.id, lesson_id=lesson.id)

        elif 'undo_complete' in request.POST:
            if is_completed:
                CompletedLesson.objects.filter(user=request.user, lesson=lesson).delete()
                messages.info(request, f'"{lesson.title}" marked as incomplete.')
                return redirect('lesson_detail', playlist_id=playlist.id, lesson_id=lesson.id)

    context = {
        'playlist': playlist,
        'lesson': lesson,
        'is_completed': is_completed,
        'prev_lesson': prev_lesson,
        'next_lesson': next_lesson,
        'total_lessons': len(lessons),
        'current_number': current_index + 1,
    }
    return render(request, 'portal/lesson_detail.html', context)


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
    """Get all notifications for a user"""
    from django.db import models

    # Get active notifications
    active_notifications = Notification.objects.filter(
        is_active=True
    ).filter(
        models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
    )

    # Get user's notification status
    user_notifications = UserNotification.objects.filter(user=user)
    user_notification_ids = user_notifications.values_list('notification_id', flat=True)

    # Get dismissed notifications
    dismissed_ids = user_notifications.filter(is_dismissed=True).values_list('notification_id', flat=True)

    # Prepare notification data
    notifications_data = []
    for notification in active_notifications:
        is_dismissed = notification.id in dismissed_ids
        is_read = False
        if notification.id in user_notification_ids:
            user_notif = user_notifications.get(notification_id=notification.id)
            is_read = user_notif.is_read

        # Skip dismissed notifications (unless they're on login)
        if is_dismissed and not notification.show_on_login:
            continue

        # Convert datetime to string safely
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
            'is_read': is_read,
            'is_dismissed': is_dismissed,
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