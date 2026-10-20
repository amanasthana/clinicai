from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import UserNotice


@login_required
@require_POST
def dismiss_notice(request, key):
    """Mark a one-time notice as seen for the current user."""
    UserNotice.objects.filter(
        user=request.user, key=key, seen_at__isnull=True,
    ).update(seen_at=timezone.now())
    return JsonResponse({'ok': True})
