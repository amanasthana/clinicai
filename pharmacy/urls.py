from django.urls import path
from . import views

app_name = 'pharmacy'

urlpatterns = [
    path('', views.pharmacy_dashboard, name='dashboard'),
    path('add/', views.add_stock_view, name='add_stock'),
    path('item/<int:pk>/add-batch/', views.add_batch_view, name='add_batch'),
    path('item/<int:pk>/edit/', views.edit_item_view, name='edit_item'),
    path('item/<int:pk>/flag/', views.flag_reorder_view, name='flag_reorder'),
    path('item/<int:pk>/delete/', views.delete_item_view, name='delete_item'),
    path('batch/<int:pk>/edit/', views.edit_batch_view, name='edit_batch'),
    path('batch/<int:pk>/delete/', views.delete_batch_view, name='delete_batch'),
    path('api/search/', views.pharmacy_search_api, name='search'),
    path('api/catalog/', views.catalog_search_api, name='catalog_search'),
    path('dispense/<uuid:visit_id>/', views.dispense_view, name='dispense'),
    path('dispense/<uuid:visit_id>/confirm/', views.confirm_dispense_api, name='confirm_dispense'),
    path('bill/<int:bill_id>/', views.bill_view, name='bill'),
    path('api/alternatives/<int:item_id>/', views.alternatives_api, name='alternatives'),
    path('api/item-detail/', views.item_detail_api, name='item_detail'),
    path('walk-in/', views.walk_in_view, name='walk_in'),
    path('bill/<int:bill_id>/edit/', views.edit_bill_view, name='edit_bill'),
    path('scan/', views.add_stock_scan_view, name='scan'),
    path('settings/', views.pharmacy_settings_view, name='settings'),
    path('return/', views.medicine_return_view, name='return'),
    path('return/<int:bill_id>/', views.medicine_return_view, name='return_bill'),
    path('return/<int:bill_id>/process/', views.process_return_view, name='process_return'),
    path('bills/', views.bill_list_view, name='bill_list'),
    path('analytics/', views.pharmacy_analytics_view, name='analytics'),
    path('ledger/', views.ledger_view, name='ledger'),
    path('import/', views.import_medicines_view, name='import_medicines'),
    path('inventory-report/', views.inventory_report_view, name='inventory_report'),
]
