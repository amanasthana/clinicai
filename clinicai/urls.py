from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('reception.urls')),
    path('accounts/', include('accounts.urls')),
    path('rx/', include('prescription.urls')),
    path('pharmacy/', include('pharmacy.urls')),
]
