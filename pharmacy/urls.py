from django.urls import path
from . import views

app_name = 'pharmacy'

urlpatterns = [
    path('', views.pharmacy_dashboard, name='dashboard'),
    path('add/', views.add_stock_view, name='add_stock'),
    path('item/<int:pk>/edit/', views.edit_stock_view, name='edit_stock'),
    path('item/<int:pk>/delete/', views.delete_stock_view, name='delete_stock'),
    path('item/<int:pk>/flag/', views.flag_reorder_view, name='flag_reorder'),
    path('api/search/', views.pharmacy_search_api, name='search'),
    path('api/catalog/', views.catalog_search_api, name='catalog_search'),
]
