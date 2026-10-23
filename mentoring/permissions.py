from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from accounts.models import AssignmentStatus, Role, RoleAssignment


def is_mentor(user):
    """True when the user holds an active MENTOR role in at least one hackathon."""
    return bool(user.is_authenticated and user.is_active and RoleAssignment.objects.filter(
        user=user, role=Role.MENTOR, status=AssignmentStatus.ACTIVE).exists())


class MentorRequiredMixin(LoginRequiredMixin):
    """Anonymous users go to the login page; authenticated non-mentors get a 403."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not is_mentor(request.user):
            raise PermissionDenied('Rôle mentor requis.')
        return super().dispatch(request, *args, **kwargs)
