from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('notices/<slug:key>/dismiss/', views.dismiss_notice, name='dismiss_notice'),
]
