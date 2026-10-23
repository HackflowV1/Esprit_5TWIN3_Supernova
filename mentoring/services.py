"""Write operations of M4. Views and admin go through these functions so rules stay in one place."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import AssignmentStatus, Role, RoleAssignment, User
from hackathons.models import Hackathon
from .models import MentorSlot

OPEN_STATUSES = (Hackathon.Status.PUBLISHED, Hackathon.Status.ONGOING)


def _lock_mentor(actor):
    # Locking the mentor row serializes all slot writes of one mentor, so overlaps cannot race.
    # Lock order is the same as accounts.services.set_role (user, then hackathon): no deadlock.
    User.objects.select_for_update(no_key=True).get(pk=actor.pk)


def _require_mentor(actor, event):
    if not RoleAssignment.objects.filter(user=actor, hackathon=event, role=Role.MENTOR,
            status=AssignmentStatus.ACTIVE).exists():
        raise PermissionDenied('Rôle mentor requis dans ce hackathon.')


def _require_open_event(event):
    if event.status not in OPEN_STATUSES:
        raise ValidationError('Les créneaux se gèrent uniquement pour un hackathon publié ou en cours.')


@transaction.atomic
def create_slot(*, actor, hackathon, start, end):
    _lock_mentor(actor)
    event = Hackathon.objects.select_for_update().get(pk=hackathon.pk)
    _require_mentor(actor, event)
    _require_open_event(event)
    if start <= timezone.now():
        raise ValidationError('Le créneau doit commencer dans le futur.')
    slot = MentorSlot(hackathon=event, mentor=actor, start=start, end=end)
    slot.save()
    return slot


def _own_available_slot(actor, slot):
    current = MentorSlot.objects.select_for_update(of=('self',)).get(pk=slot.pk)
    if current.mentor_id != actor.pk:
        raise PermissionDenied('Ce créneau ne vous appartient pas.')
    if current.status != MentorSlot.Status.AVAILABLE:
        raise ValidationError('Seul un créneau disponible peut être modifié ou annulé.')
    return current


@transaction.atomic
def update_slot(*, actor, slot, start, end):
    _lock_mentor(actor)
    current = _own_available_slot(actor, slot)
    event = Hackathon.objects.select_for_update().get(pk=current.hackathon_id)
    _require_mentor(actor, event)
    _require_open_event(event)
    if current.start <= timezone.now():
        raise ValidationError('Un créneau déjà commencé ne peut plus être modifié.')
    if start <= timezone.now():
        raise ValidationError('Le créneau doit commencer dans le futur.')
    current.hackathon = event
    current.start, current.end = start, end
    current.save()
    return current


@transaction.atomic
def cancel_slot(*, actor, slot):
    _lock_mentor(actor)
    current = _own_available_slot(actor, slot)
    current.status = MentorSlot.Status.CANCELLED
    current.save()
    return current
