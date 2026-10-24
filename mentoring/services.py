from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import AssignmentStatus, Role, RoleAssignment, User
from accounts.permissions import can_manage
from hackathons.models import EventPhase, Hackathon
from hackathons.services import phase_is_open
from teams import services as team_services
from teams.models import Registration, Team
from .models import M4History, MentorSlot, SupportRequest, Workshop, WorkshopRegistration

OPEN_STATUSES = (Hackathon.Status.PUBLISHED, Hackathon.Status.ONGOING)
SLOTS_CLOSED = _('Les créneaux se gèrent uniquement pour un hackathon publié ou en cours.')
WORKSHOPS_CLOSED = _('Les ateliers se gèrent uniquement pour un hackathon publié ou en cours.')
SUPPORT_CLOSED = _('Les demandes d’aide sont possibles pendant la phase de développement d’un hackathon publié ou en cours.')


# ------------------------------------------------------------------ helpers
def mentor_open_hackathons(user):
    return Hackathon.objects.filter(
        role_assignments__user=user, role_assignments__role=Role.MENTOR,
        role_assignments__status=AssignmentStatus.ACTIVE, status__in=OPEN_STATUSES).distinct()


def visible_workshops(user):
    queryset = Workshop.objects.select_related('hackathon', 'trainer')
    if not (user.is_authenticated and user.is_active):
        return queryset.none()
    if user.is_superuser:
        return queryset
    return queryset.filter(hackathon__role_assignments__user=user,
        hackathon__role_assignments__status=AssignmentStatus.ACTIVE).distinct()


def record(*, event, actor, action, obj, **details):
    return M4History.objects.create(hackathon=event, actor=actor, action=action,
        object_type=type(obj).__name__, object_id=obj.pk, details=details)


def _iso(value):
    return timezone.localtime(value).isoformat(timespec='minutes')


def _lock_actor(actor):
    User.objects.select_for_update(no_key=True).get(pk=actor.pk)


def _require_mentor(actor, event):
    if not RoleAssignment.objects.filter(user=actor, hackathon=event, role=Role.MENTOR,
            status=AssignmentStatus.ACTIVE).exists():
        raise PermissionDenied(_('Rôle mentor requis dans ce hackathon.'))


def _require_open_event(event, message):
    if event.status not in OPEN_STATUSES:
        raise ValidationError(message)


# ------------------------------------------------------------------ slots
@transaction.atomic
def create_slot(*, actor, hackathon, start, end):
    _lock_actor(actor)
    event = Hackathon.objects.select_for_update().get(pk=hackathon.pk)
    _require_mentor(actor, event)
    _require_open_event(event, SLOTS_CLOSED)
    if start <= timezone.now():
        raise ValidationError(_('Le créneau doit commencer dans le futur.'))
    slot = MentorSlot(hackathon=event, mentor=actor, start=start, end=end)
    slot.save()
    record(event=event, actor=actor, action='slot.published', obj=slot, start=_iso(start), end=_iso(end))
    return slot


def _own_available_slot(actor, slot):
    current = MentorSlot.objects.select_for_update(of=('self',)).get(pk=slot.pk)
    if current.mentor_id != actor.pk:
        raise PermissionDenied(_('Ce créneau ne vous appartient pas.'))
    if current.availability != 'AVAILABLE':
        raise ValidationError(_('Seul un créneau disponible peut être modifié ou annulé.'))
    return current


@transaction.atomic
def update_slot(*, actor, slot, start, end):
    _lock_actor(actor)
    current = _own_available_slot(actor, slot)
    event = Hackathon.objects.select_for_update().get(pk=current.hackathon_id)
    _require_mentor(actor, event)
    _require_open_event(event, SLOTS_CLOSED)
    if current.start <= timezone.now():
        raise ValidationError(_('Un créneau déjà commencé ne peut plus être modifié.'))
    if start <= timezone.now():
        raise ValidationError(_('Le créneau doit commencer dans le futur.'))
    before = {'start': _iso(current.start), 'end': _iso(current.end)}
    current.hackathon = event
    current.start, current.end = start, end
    current.save()
    record(event=event, actor=actor, action='slot.updated', obj=current, before=before, after={'start': _iso(start), 'end': _iso(end)})
    return current


@transaction.atomic
def cancel_slot(*, actor, slot):
    """Withdraw a free slot. A booked slot cannot be withdrawn: the booking must be cancelled first."""
    _lock_actor(actor)
    current = _own_available_slot(actor, slot)
    current.withdrawn_at = timezone.now()
    current.save()
    record(event=current.hackathon, actor=actor, action='slot.withdrawn', obj=current)
    return current


# -------------------------------------------------------------- workshops
@transaction.atomic
def create_workshop(*, actor, hackathon, title, description, capacity, start, end, location, url):
    _lock_actor(actor)
    event = Hackathon.objects.select_for_update().get(pk=hackathon.pk)
    _require_mentor(actor, event)
    _require_open_event(event, WORKSHOPS_CLOSED)
    if start <= timezone.now():
        raise ValidationError(_('L’atelier doit commencer dans le futur.'))
    workshop = Workshop(hackathon=event, trainer=actor, title=title.strip(), description=description,
        capacity=capacity, start=start, end=end, location=location.strip(), url=url)
    workshop.save()
    record(event=event, actor=actor, action='workshop.published', obj=workshop, title=workshop.title, capacity=capacity)
    return workshop


def _own_open_workshop(actor, workshop):
    current = Workshop.objects.select_for_update(of=('self',)).get(pk=workshop.pk)
    if current.trainer_id != actor.pk:
        raise PermissionDenied(_('Cet atelier ne vous appartient pas.'))
    if current.status != Workshop.Status.PUBLISHED:
        raise ValidationError(_('Cet atelier est déjà annulé.'))
    if current.start <= timezone.now():
        raise ValidationError(_('Un atelier déjà commencé ne peut plus être modifié ni annulé.'))
    return current


@transaction.atomic
def update_workshop(*, actor, workshop, title, description, capacity, start, end, location, url):
    _lock_actor(actor)
    current = _own_open_workshop(actor, workshop)
    event = Hackathon.objects.select_for_update().get(pk=current.hackathon_id)
    _require_mentor(actor, event)
    _require_open_event(event, WORKSHOPS_CLOSED)
    if start <= timezone.now():
        raise ValidationError(_('L’atelier doit commencer dans le futur.'))
    registered = current.registrations.filter(status=WorkshopRegistration.Status.REGISTERED).count()
    if capacity < registered:
        raise ValidationError(_('La capacité ne peut pas être inférieure au nombre d’inscrits (%(count)s).') % {'count': registered})
    if registered and (start != current.start or end != current.end):
        raise ValidationError(_('Un atelier qui a des inscrits ne peut pas changer d’horaire : annulez-le et publiez-en un nouveau.'))
    before = {'title': current.title, 'capacity': current.capacity, 'start': _iso(current.start), 'end': _iso(current.end)}
    current.hackathon = event
    current.title, current.description, current.capacity = title.strip(), description, capacity
    current.start, current.end, current.location, current.url = start, end, location.strip(), url
    current.save()
    record(event=event, actor=actor, action='workshop.updated', obj=current, before=before,
        after={'title': current.title, 'capacity': capacity, 'start': _iso(start), 'end': _iso(end)})
    return current


@transaction.atomic
def cancel_workshop(*, actor, workshop):
    _lock_actor(actor)
    current = _own_open_workshop(actor, workshop)
    current.status = Workshop.Status.CANCELLED
    current.save()
    record(event=current.hackathon, actor=actor, action='workshop.cancelled', obj=current)
    return current


# ----------------------------------------------------------- support requests
def _is_active_member(user, team):
    return team.closed_at is None and team_services.active_members(team).filter(registration__user=user).exists()


@transaction.atomic
def open_request(*, actor, team, subject, description, skill=None, priority=SupportRequest.Priority.NORMAL):
    """Any active member of the team may ask for help, even if the team is not complete yet."""
    _lock_actor(actor)
    event = Hackathon.objects.select_for_update().get(pk=team.hackathon_id)
    team = Team.objects.select_related('captain').get(pk=team.pk)
    if not _is_active_member(actor, team):
        raise PermissionDenied(_('Seuls les membres actifs de l’équipe peuvent demander de l’aide.'))
    if not phase_is_open(event, EventPhase.Kind.DEVELOPMENT):
        raise ValidationError(SUPPORT_CLOSED)
    request = SupportRequest(hackathon=event, team=team, author=actor, subject=(subject or '').strip(),
        description=(description or '').strip(), skill=skill, priority=priority)
    request.save()
    record(event=event, actor=actor, action='request.opened', obj=request, team=team.pk, priority=priority,
        skill=skill.pk if skill else None)
    return request


@transaction.atomic
def cancel_request(*, actor, request):
    """An OPEN request may be cancelled by its author (still a member), the captain, or an organizer."""
    _lock_actor(actor)
    event = Hackathon.objects.select_for_update().get(pk=request.hackathon_id)
    current = SupportRequest.objects.select_for_update(of=('self',)).select_related('team__captain').get(pk=request.pk)
    as_organizer = can_manage(actor, event)
    allowed = (team_services.is_captain(actor, current.team)
        or (current.author_id == actor.pk and _is_active_member(actor, current.team)) or as_organizer)
    if not allowed:
        raise PermissionDenied(_('Seuls l’auteur, le capitaine ou un organisateur peuvent annuler cette demande.'))
    if event.status == Hackathon.Status.ARCHIVED:
        raise ValidationError(_('Édition archivée : modification interdite.'))
    if current.status != SupportRequest.Status.OPEN:
        raise ValidationError(_('Seule une demande ouverte peut être annulée. Annulez d’abord le rendez-vous.'))
    current.status = SupportRequest.Status.CANCELLED
    current.save()
    record(event=event, actor=actor, action='request.cancelled', obj=current, as_organizer=as_organizer and not
        team_services.is_captain(actor, current.team) and current.author_id != actor.pk)
    return current


def visible_requests(user):
    queryset = SupportRequest.objects.select_related('team', 'hackathon', 'skill', 'author')
    if not (user.is_authenticated and user.is_active):
        return queryset.none()
    if user.is_superuser:
        return queryset
    member = Q(team__closed_at__isnull=True, team__memberships__ended_at__isnull=True,
        team__memberships__registration__user=user, team__memberships__registration__status=Registration.Status.ACCEPTED)
    mentor = Q(sessions__slot__mentor=user, sessions__status__in=['BOOKED', 'COMPLETED'])
    organizer = Q(hackathon__role_assignments__user=user, hackathon__role_assignments__role=Role.ORGANIZER,
        hackathon__role_assignments__status=AssignmentStatus.ACTIVE)
    return queryset.filter(member | mentor | organizer).distinct()


def can_view_request(user, request):
    return visible_requests(user).filter(pk=request.pk).exists()
