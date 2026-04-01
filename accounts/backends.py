from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User


class EmailOrUsernameBackend(ModelBackend):
    """
    Login with:
    1. Plain phone (clinic admin) — stored as plain username
    2. Just the staff username e.g. "prakash" — system finds clinic__prakash automatically
    3. Full namespaced "clinic_mobile__username" — direct lookup
    4. Email address
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        user = None

        # 1. Exact match (clinic admin phone, old-style plain username, or full namespaced)
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            pass

        # 2. Email match
        if user is None:
            try:
                user = User.objects.get(email__iexact=username)
            except User.DoesNotExist:
                pass

        # 3. Staff pattern: username typed is just "prakash", stored as "9876543210__prakash"
        #    Find all users whose namespaced username ends with __{typed}
        if user is None and username and '__' not in username:
            candidates = list(
                User.objects.filter(username__endswith=f'__{username}')
            )
            if len(candidates) == 1:
                user = candidates[0]
            # If multiple clinics have same username, fall through (error shown in view)

        if user is None:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
