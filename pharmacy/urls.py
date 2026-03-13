from django.urls import path
from . import views

app_name = 'pharmacy'

urlpatterns = [
    path('', views.pharmacy_dashboard, name='dashboard'),
    path('add/', views.add_stock_view, name='add_stock'),
    path('item/<int:pk>/add-batch/', views.add_batch_view, name='add_batch'),
    path('item/<int:pk>/flag/', views.flag_reorder_view, name='flag_reorder'),
    path('item/<int:pk>/delete/', views.delete_item_view, name='delete_item'),
    path('batch/<int:pk>/edit/', views.edit_batch_view, name='edit_batch'),
    path('batch/<int:pk>/delete/', views.delete_batch_view, name='delete_batch'),
    path('api/search/', views.pharmacy_search_api, name='search'),
    path('api/catalog/', views.catalog_search_api, name='catalog_search'),
]
