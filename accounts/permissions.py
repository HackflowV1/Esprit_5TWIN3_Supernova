from django.utils.translation import gettext_lazy as _
from django.core.exceptions import PermissionDenied
from .models import Role, RoleAssignment, AssignmentStatus


def has_role(user, hackathon, *roles):
    if not user.is_authenticated or not user.is_active:
        return False
    return user.is_superuser or RoleAssignment.objects.filter(
        user=user, hackathon=hackathon, role__in=roles, status=AssignmentStatus.ACTIVE).exists()


def is_member(user, hackathon):
    return has_role(user, hackathon, *Role.values)


def can_create_hackathon(user):
    return user.is_authenticated and user.is_active and user.has_perm('accounts.create_hackathon')


def can_manage(user, hackathon):
    return has_role(user, hackathon, Role.ORGANIZER)


def require_organizer(user, hackathon, *, mutable=True):
    if not can_manage(user, hackathon):
        raise PermissionDenied(_('Rôle organisateur requis dans ce hackathon.'))
    if mutable and hackathon.status == 'ARCHIVED':
        raise PermissionDenied(_('Édition archivée : consultation uniquement.'))


class HackathonRoleMixin:
    """Consumers must provide get_hackathon(); authorization is scoped to that event."""
    required_roles = (Role.ORGANIZER,)

    def dispatch(self, request, *args, **kwargs):
        if not has_role(request.user, self.get_hackathon(), *self.required_roles):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
