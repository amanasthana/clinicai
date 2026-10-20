from .models import UserNotice


def pending_notices(request):
    """Expose `show_rebrand_notice` to every template for logged-in users who
    have not dismissed the MedlynAI rebrand notice yet."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    return {
        'show_rebrand_notice': UserNotice.objects.filter(
            user=user, key=UserNotice.REBRAND_MEDLYNAI, seen_at__isnull=True,
        ).exists(),
    }
