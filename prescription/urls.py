from django.urls import path
from . import views

app_name = 'prescription'

urlpatterns = [
    path('doctor/', views.doctor_queue_view, name='doctor_queue'),
    path('consult/<uuid:visit_id>/', views.consult_view, name='consult'),
    path('generate/', views.generate_prescription_api, name='generate'),
    path('save/<uuid:visit_id>/', views.save_prescription_api, name='save'),
    path('print/<uuid:rx_id>/', views.print_prescription_view, name='print'),
]
