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
    if role == Role.PARTICIPANT and status == AssignmentStatus.REVOKED:
        from teams.models import Registration
        if Registration.objects.filter(user=user, hackathon=event, status=Registration.Status.ACCEPTED).exists():
            raise ValidationError(_('Annulez d’abord l’inscription depuis la gestion des participants.'))
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


@transaction.atomic
def sync_registration_role(*, actor, registration):
    """M2-only lifecycle: accepted registration grants participation, cancellation revokes it.

    Does not weaken the general organizer-only role assignment operation.
    """
    from teams.models import Registration
    User.objects.select_for_update(no_key=True).get(pk=registration.user_id)
    event = Hackathon.objects.select_for_update().get(pk=registration.hackathon_id)
    if actor.pk != registration.user_id:
        require_organizer(actor, event)
    if event.status == Hackathon.Status.ARCHIVED:
        raise ValidationError(_('Édition archivée : consultation uniquement.'))
    registration = Registration.objects.get(pk=registration.pk)
    status = AssignmentStatus.ACTIVE if registration.status == Registration.Status.ACCEPTED else AssignmentStatus.REVOKED
    assignment = RoleAssignment.objects.filter(user_id=registration.user_id, hackathon=event, role=Role.PARTICIPANT).first()
    previous = assignment.status if assignment else ''
    if assignment is None:
        assignment = RoleAssignment(user_id=registration.user_id, hackathon=event, role=Role.PARTICIPANT, assigned_by=actor)
    assignment.status = status
    assignment.full_clean()
    assignment.save()
    if previous != status:
        RoleAssignmentHistory.objects.create(assignment=assignment, actor=actor, previous_status=previous, status=status)
    return assignment
