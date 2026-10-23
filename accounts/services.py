from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.db import transaction
from .models import User, RoleAssignment, RoleAssignmentHistory, AssignmentStatus, Role
from .permissions import require_organizer
from hackathons.models import Hackathon


@transaction.atomic
def set_role(*, actor, user, hackathon, role, status=AssignmentStatus.ACTIVE):
    # Serialize assignments for one person: cross-role conflicts cannot race.
    User.objects.select_for_update(no_key=True).get(pk=user.pk)
    event = Hackathon.objects.select_for_update().get(pk=hackathon.pk)
    require_organizer(actor, event)
    assignment = RoleAssignment.objects.filter(user=user, hackathon=event, role=role).first()
    previous = assignment.status if assignment else ''
    if assignment and role == Role.ORGANIZER and status == AssignmentStatus.REVOKED:
        if not event.role_assignments.filter(role=Role.ORGANIZER, status=AssignmentStatus.ACTIVE).exclude(pk=assignment.pk).exists():
            raise ValidationError(_('Le dernier organisateur actif ne peut pas être retiré.'))
    if assignment is None:
        assignment = RoleAssignment(user=user, hackathon=event, role=role, assigned_by=actor)
    assignment.status = status
    assignment.full_clean()
    assignment.save()
    if previous != status:
        RoleAssignmentHistory.objects.create(assignment=assignment, actor=actor, previous_status=previous, status=status)
        from hackathons.services import record
        record(event, actor, 'Affectation de rôle', user.username, role=role, previous_status=previous, status=status)
    return assignment
