from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.registration_view, name='registration'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('suspended/', views.suspended_view, name='suspended'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    
    # New: View playlists for a specific course
    path('course/<int:course_id>/playlists/', views.course_playlists_view, name='course_playlists'),
    
    path('unlock/<int:playlist_id>/', views.unlock_playlist_view, name='unlock_playlist'),
    path('playlist/<int:playlist_id>/', views.playlist_lessons_view, name='playlist_lessons'),
    path('playlist/<int:playlist_id>/lesson/<int:lesson_id>/', views.lesson_detail_view, name='lesson_detail'),
    
    # Instructor dashboard
    path('instructor-dashboard/', views.instructor_dashboard, name='instructor_dashboard'),
    path('admin-student/<int:student_id>/', views.admin_student_detail, name='admin_student_detail'),
    
    # AJAX endpoints
    path('check-email/', views.check_email_exists, name='check_email'),
    path('check-access-code/', views.check_access_code_valid, name='check_access_code'),
    
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