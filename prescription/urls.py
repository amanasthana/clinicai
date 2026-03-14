from django.urls import path
from . import views

app_name = 'prescription'

urlpatterns = [
    path('doctor/', views.doctor_queue_view, name='doctor_queue'),
    path('consult/<uuid:visit_id>/', views.consult_view, name='consult'),
    path('generate/', views.generate_prescription_api, name='generate'),
    path('differentials/', views.differentials_api, name='differentials'),
    path('investigations/', views.investigations_api, name='investigations'),
    path('save/<uuid:visit_id>/', views.save_prescription_api, name='save'),
    path('print/<uuid:rx_id>/', views.print_prescription_view, name='print'),
    path('api/suggest/', views.suggest_terms, name='suggest_terms'),
    path('api/pharmacy-search/', views.pharmacy_search_api, name='pharmacy_search'),
    path('favorites/', views.favorites_view, name='favorites'),
    path('favorites/add/', views.add_favorite_api, name='add_favorite'),
    path('favorites/remove/<int:pk>/', views.remove_favorite_api, name='remove_favorite'),
    path('favorites/list/', views.favorites_list_api, name='favorites_list'),
    path('share/<uuid:token>/', views.public_prescription_view, name='public_print'),
    path('api/interactions/', views.check_interactions_api, name='check_interactions'),
    path('api/scan-bill/', views.scan_bill_api, name='scan_bill'),
]
