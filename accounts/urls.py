from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('setup/', views.clinic_setup_view, name='clinic_setup'),
    path('plan/', views.plan_view, name='plan'),
    path('staff/', views.staff_list_view, name='staff_list'),
    path('staff/add/', views.add_staff_view, name='add_staff'),
    path('staff/<int:pk>/edit/', views.edit_staff_view, name='edit_staff'),
    path('staff/<int:pk>/delete/', views.delete_staff_view, name='delete_staff'),
    path('register/', views.register_view, name='register'),
    path('register/success/', views.register_success_view, name='register_success'),
    path('admin-panel/', views.admin_panel_view, name='admin_panel'),
    path('admin-panel/approve/<int:pk>/', views.approve_registration_view, name='approve_registration'),
    path('admin-panel/reject/<int:pk>/', views.reject_registration_view, name='reject_registration'),
    path('admin-panel/message/<int:pk>/read/', views.mark_contact_read_view, name='mark_contact_read'),
    path('contact/', views.contact_view, name='contact'),
    path('contact/success/', views.contact_success_view, name='contact_success'),
    path('api/preference/', views.update_preference_api, name='update_preference'),
    path('letterhead/', views.letterhead_view, name='letterhead'),
    path('admin-panel/check-user/<str:phone>/', views.check_user_view, name='check_user'),
    path('admin-panel/reset-password/<int:pk>/', views.reset_clinic_password_view, name='reset_clinic_password'),
    path('switch-clinic/', views.switch_clinic_view, name='switch_clinic'),
    path('add-clinic/', views.add_clinic_view, name='add_clinic'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('verify-otp/', views.verify_otp_view, name='verify_otp'),
    path('resend-otp/', views.resend_otp_view, name='resend_otp'),
    path('reset-password/', views.reset_password_view, name='reset_password'),
    path('change-password/', views.change_password_view, name='change_password'),
]
