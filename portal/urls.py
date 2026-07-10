from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.registration_view, name='registration'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('suspended/', views.suspended_view, name='suspended'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    
    # Course URLs
    path('course/<int:course_id>/playlists/', views.course_playlists_view, name='course_playlists'),
    
    path('unlock/<int:playlist_id>/', views.unlock_playlist_view, name='unlock_playlist'),
    path('playlist/<int:playlist_id>/', views.playlist_lessons_view, name='playlist_lessons'),
    path('playlist/<int:playlist_id>/lesson/<int:lesson_id>/', views.lesson_detail_view, name='lesson_detail'),
    path('playlist/<int:playlist_id>/lesson/<int:lesson_id>/task/<int:task_id>/', views.task_detail_view, name='task_detail'),

    # Instructor dashboard
    path('instructor-dashboard/', views.instructor_dashboard, name='instructor_dashboard'),
    path('instructor/students/', views.instructor_students_view, name='instructor_students'),
    path('admin-student/<int:student_id>/', views.admin_student_detail, name='admin_student_detail'),
    path('instructor/approvals/', views.instructor_approvals_view, name='instructor_approvals'),
    path('instructor/approve/<int:submission_id>/', views.approve_submission_view, name='approve_submission'),
    path('instructor/reject/<int:submission_id>/', views.reject_submission_view, name='reject_submission'),
    path('instructor/approve-all/', views.approve_all_submissions_view, name='approve_all_submissions'),
    path('instructor/reject-all/', views.reject_all_submissions_view, name='reject_all_submissions'),
    path('instructor/assign-task/', views.instructor_assign_task_view, name='instructor_assign_task'),
    path('instructor/assigned-tasks/', views.instructor_assigned_tasks_list_view, name='instructor_assigned_tasks_list'),
    path('instructor/assigned-tasks/<int:assigned_task_id>/edit/', views.instructor_edit_assigned_task_view, name='instructor_edit_assigned_task'),
    path('instructor/assigned-tasks/<int:assigned_task_id>/delete/', views.instructor_delete_assigned_task_view, name='instructor_delete_assigned_task'),
    path('instructor/assigned-task/<int:assigned_task_id>/approve/', views.approve_assigned_task_view, name='approve_assigned_task'),
    path('instructor/assigned-task/<int:assigned_task_id>/reject/', views.reject_assigned_task_view, name='reject_assigned_task'),
    path('instructor/outline/', views.instructor_course_outline_view, name='instructor_course_outline'),
    path('instructor/survey/', views.instructor_survey_view, name='instructor_survey'),

    # Manager dashboard
    path('manager-dashboard/', views.manager_dashboard_view, name='manager_dashboard'),
    path('manager/survey/', views.manager_survey_view, name='manager_survey'),

    # Student grades, survey & assigned tasks
    path('grades/', views.student_grades_view, name='student_grades'),
    path('survey/submit/<int:prompt_id>/', views.submit_survey_view, name='submit_survey'),
    path('my-tasks/', views.student_tasks_view, name='student_tasks'),
    path('my-tasks/<int:assigned_task_id>/', views.assigned_task_detail_view, name='assigned_task_detail'),
    
    # AJAX endpoints
    path('check-email/', views.check_email_exists, name='check_email'),
    path('check-access-code/', views.check_access_code_valid, name='check_access_code'),
    
    # Notification URLs
    path('notifications/mark-read/<int:notification_id>/', views.notification_mark_read, name='notification_mark_read'),
    path('notifications/dismiss/<int:notification_id>/', views.notification_dismiss, name='notification_dismiss'),
    path('notifications/api/', views.get_notifications_api, name='get_notifications_api'),
    
    # Password reset
    path('password-reset/', 
         auth_views.PasswordResetView.as_view(template_name='portal/password_reset.html'), 
         name='password_reset'),
    path('password-reset/done/', 
         auth_views.PasswordResetDoneView.as_view(template_name='portal/password_reset_done.html'), 
         name='password_reset_done'),
    path('reset/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(template_name='portal/password_reset_confirm.html'), 
         name='password_reset_confirm'),
    path('reset/done/', 
         auth_views.PasswordResetCompleteView.as_view(template_name='portal/password_reset_complete.html'), 
         name='password_reset_complete'),
]