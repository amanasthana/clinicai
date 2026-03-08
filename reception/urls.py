from django.urls import path
from . import views, api

app_name = 'reception'

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('patient/new/', views.new_patient_view, name='new_patient'),
    path('patient/<uuid:pk>/', views.patient_detail_view, name='patient_detail'),
    path('patient/<uuid:pk>/edit/', views.patient_edit_view, name='patient_edit'),
    path('visit/<uuid:pk>/', views.visit_detail_view, name='visit_detail'),
    # JSON APIs
    path('api/patient/search/', api.patient_search_api, name='patient_search'),
    path('api/queue/', api.queue_api, name='queue'),
    path('api/visit/<uuid:pk>/status/', api.visit_status_api, name='visit_status'),
]
