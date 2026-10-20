from django.contrib import admin
from .models import UserNotice


@admin.register(UserNotice)
class UserNoticeAdmin(admin.ModelAdmin):
    list_display = ('user', 'key', 'created_at', 'seen_at')
    list_filter = ('key', 'seen_at')
    search_fields = ('user__username',)
