from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('reception.urls')),
    path('accounts/', include('accounts.urls')),
    path('rx/', include('prescription.urls')),
    path('pharmacy/', include('pharmacy.urls')),
    # Serve media files in both dev and production (letterhead images etc.)
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
