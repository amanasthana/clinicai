from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('notices/<slug:key>/dismiss/', views.dismiss_notice, name='dismiss_notice'),
    path('announcements/', views.announcements_view, name='announcements'),
    path('announcements/preview/', views.announcement_preview_view, name='announcement_preview'),
    path('gift/<int:clinic_pk>/', views.gift_email_view, name='gift_email'),
    path('gift/<int:clinic_pk>/preview/', views.gift_email_preview_view, name='gift_email_preview'),
]
