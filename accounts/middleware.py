"""
ActiveClinicMiddleware
======================
Sets request.user.staff_profile as a plain attribute (monkey-patch) so that
all existing views and templates continue to work unchanged.

For users with a single clinic membership this is transparent.
For users with multiple clinic memberships, the active clinic is determined by
request.session['active_staff_id']. If the session value is missing or invalid
the first membership is used as fallback.

Also sets request.user.all_clinic_memberships for the clinic switcher widget.
"""

from .models import StaffMember


class ActiveClinicMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_superuser:
            memberships = list(
                StaffMember.objects.filter(user=request.user)
                .select_related('clinic')
                .order_by('pk')
            )
            request.user.all_clinic_memberships = memberships

            if memberships:
                active = None
                active_id = request.session.get('active_staff_id')
                if active_id:
                    # Look for matching membership
                    for m in memberships:
                        if m.pk == active_id:
                            active = m
                            break
                if active is None:
                    active = memberships[0]
                # Monkey-patch: makes request.user.staff_profile work everywhere
                request.user.staff_profile = active
            else:
                # User has no StaffMember — leave staff_profile unset so views
                # that guard with login_required will still redirect, and
                # views that do request.user.staff_profile.clinic will raise
                # AttributeError (intentional — staff must be linked).
                request.user.all_clinic_memberships = []
        elif request.user.is_authenticated and request.user.is_superuser:
            # Superusers don't have staff memberships
            request.user.all_clinic_memberships = []

        response = self.get_response(request)
        return response
