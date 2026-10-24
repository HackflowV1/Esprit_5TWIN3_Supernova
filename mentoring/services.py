from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, When
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import AssignmentStatus, Role, RoleAssignment, User
from accounts.permissions import can_manage
from hackathons.models import EventPhase, Hackathon
from hackathons.services import phase_is_open
from teams import services as team_services
from teams.models import Registration, Team
from .models import M4History, MentoringSession, MentorSlot, SupportRequest, Workshop, WorkshopRegistration

OPEN_STATUSES = (Hackathon.Status.PUBLISHED, Hackathon.Status.ONGOING)
SLOTS_CLOSED = _('Les créneaux se gèrent uniquement pour un hackathon publié ou en cours.')
WORKSHOPS_CLOSED = _('Les ateliers se gèrent uniquement pour un hackathon publié ou en cours.')
SUPPORT_CLOSED = _('Les demandes d’aide sont possibles pendant la phase de développement d’un hackathon publié ou en cours.')
ARCHIVED = _('Édition archivée : modification interdite.')


# ------------------------------------------------------------------ helpers
def mentor_open_hackathons(user):
    """Hackathons in which the user is an active mentor and that are open (published or ongoing)."""
    return Hackathon.objects.filter(
        role_assignments__user=user, role_assignments__role=Role.MENTOR,
        role_assignments__status=AssignmentStatus.ACTIVE, status__in=OPEN_STATUSES).distinct()


def organized_hackathons(user):
    if not (user.is_authenticated and user.is_active):
        return Hackathon.objects.none()
    if user.is_superuser:
        return Hackathon.objects.all()
    return Hackathon.objects.filter(role_assignments__user=user, role_assignments__role=Role.ORGANIZER,
        role_assignments__status=AssignmentStatus.ACTIVE).distinct()


def organizer_open_hackathons(user):
    return organized_hackathons(user).filter(status__in=OPEN_STATUSES)


def publishable_hackathons(user):
    """Open editions in which the user may publish a workshop: as organizer, or as a mentor for himself."""
    return Hackathon.objects.filter(Q(pk__in=organizer_open_hackathons(user).values('pk'))
        | Q(pk__in=mentor_open_hackathons(user).values('pk'))).distinct()


def trainer_choices(user):
    """Who can lead the workshop the user publishes: an organizer picks any mentor of his open editions,
    a mentor can only pick himself."""
    active_mentor = Q(role_assignments__role=Role.MENTOR, role_assignments__status=AssignmentStatus.ACTIVE)
    own = Q(pk=user.pk, role_assignments__hackathon__in=mentor_open_hackathons(user)) & active_mentor
    organized = Q(role_assignments__hackathon__in=organizer_open_hackathons(user)) & active_mentor
    return User.objects.filter(is_active=True).filter(own | organized).distinct().order_by('first_name', 'username')


def manageable_workshops(user):
    """The workshops the user may edit or cancel: those of the editions he organizes, and his own."""
    return Workshop.objects.filter(Q(hackathon__in=organized_hackathons(user)) | Q(trainer=user)).distinct()


def visible_workshops(user):
    """Workshops of the hackathons in which the user holds an active role (any role)."""
    queryset = Workshop.objects.select_related('hackathon', 'trainer')
    if not (user.is_authenticated and user.is_active):
        return queryset.none()
    if user.is_superuser:
        return queryset
    return queryset.filter(hackathon__role_assignments__user=user,
        hackathon__role_assignments__status=AssignmentStatus.ACTIVE).distinct()


def record(*, event, actor, action, obj, **details):
    """Append one line to the M4 history. Details must be JSON-friendly (str, int, bool, None)."""
    return M4History.objects.create(hackathon=event, actor=actor, action=action,
        object_type=type(obj).__name__, object_id=obj.pk, details=details)


def _iso(value):
    return timezone.localtime(value).isoformat(timespec='minutes')


def _lock_users(*ids):
    list(User.objects.select_for_update(no_key=True).filter(pk__in=sorted(set(ids))).order_by('pk'))


def _lock_actor(actor):
    _lock_users(actor.pk)


def _require_mentor(actor, event):
    if not RoleAssignment.objects.filter(user=actor, hackathon=event, role=Role.MENTOR,
            status=AssignmentStatus.ACTIVE).exists():
        raise PermissionDenied(_('Rôle mentor requis dans ce hackathon.'))


def _require_open_event(event, message):
    if event.status not in OPEN_STATUSES:
        raise ValidationError(message)


def _is_active_member(user, team):
    return team.closed_at is None and team_services.active_members(team).filter(registration__user=user).exists()


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
def _lock_workshop(workshop):
    return Workshop.objects.select_for_update(of=('self',)).get(pk=workshop.pk)


def _ensure_open(current):
    if current.status != Workshop.Status.PUBLISHED:
        raise ValidationError(_('Cet atelier est déjà annulé.'))
    if current.start <= timezone.now():
        raise ValidationError(_('Un atelier déjà commencé ne peut plus être modifié ni annulé.'))


def _active_registrations(workshop):
    return workshop.registrations.filter(status=WorkshopRegistration.Status.REGISTERED)


@transaction.atomic
def create_workshop(*, actor, hackathon, trainer, title, description, capacity, start, end, location, url):
    """A mentor publishes his own workshop; an organizer may publish one for any mentor of the edition."""
    _lock_users(actor.pk, trainer.pk)
    event = Hackathon.objects.select_for_update().get(pk=hackathon.pk)
    as_organizer = can_manage(actor, event)
    if not (as_organizer or actor.pk == trainer.pk):
        raise PermissionDenied(_('Seul un organisateur, ou le formateur lui-même, peut publier cet atelier.'))
    if event.status == Hackathon.Status.ARCHIVED:
        raise ValidationError(ARCHIVED)
    _require_open_event(event, WORKSHOPS_CLOSED)
    if start <= timezone.now():
        raise ValidationError(_('L’atelier doit commencer dans le futur.'))
    workshop = Workshop(hackathon=event, trainer=trainer, title=title.strip(), description=description,
        capacity=capacity, start=start, end=end, location=location.strip(), url=url)
    workshop.save()
    record(event=event, actor=actor, action='workshop.published', obj=workshop, title=workshop.title, capacity=capacity,
        trainer=trainer.pk, as_organizer=as_organizer and actor.pk != trainer.pk)
    return workshop


@transaction.atomic
def update_workshop(*, actor, workshop, trainer, title, description, capacity, start, end, location, url):
    """The trainer edits his own workshop; an organizer edits any and may hand it to another mentor."""
    _lock_users(actor.pk, trainer.pk, workshop.trainer_id)
    event = Hackathon.objects.select_for_update().get(pk=workshop.hackathon_id)
    current = _lock_workshop(workshop)
    as_organizer = can_manage(actor, event)
    if not (as_organizer or current.trainer_id == actor.pk):
        raise PermissionDenied(_('Seuls un organisateur ou le formateur peuvent modifier cet atelier.'))
    if not as_organizer and trainer.pk != actor.pk:
        raise PermissionDenied(_('Seul un organisateur peut confier l’atelier à un autre mentor.'))
    if event.status == Hackathon.Status.ARCHIVED:
        raise ValidationError(ARCHIVED)
    _ensure_open(current)
    _require_open_event(event, WORKSHOPS_CLOSED)
    if start <= timezone.now():
        raise ValidationError(_('L’atelier doit commencer dans le futur.'))
    registered = _active_registrations(current).count()
    if capacity < registered:
        raise ValidationError(_('La capacité ne peut pas être inférieure au nombre d’inscrits (%(count)s).') % {'count': registered})
    if registered and (start != current.start or end != current.end):
        raise ValidationError(_('Un atelier qui a des inscrits ne peut pas changer d’horaire : annulez-le et publiez-en un nouveau.'))
    before = {'title': current.title, 'capacity': current.capacity, 'trainer': current.trainer_id,
        'start': _iso(current.start), 'end': _iso(current.end)}
    current.hackathon, current.trainer = event, trainer
    current.title, current.description, current.capacity = title.strip(), description, capacity
    current.start, current.end, current.location, current.url = start, end, location.strip(), url
    current.save()
    record(event=event, actor=actor, action='workshop.updated', obj=current, before=before,
        after={'title': current.title, 'capacity': capacity, 'trainer': trainer.pk, 'start': _iso(start), 'end': _iso(end)},
        as_organizer=as_organizer and current.trainer_id != actor.pk)
    return current


@transaction.atomic
def cancel_workshop(*, actor, workshop):
    """The trainer or an organizer cancels; every seat is released (the registration rows are kept)."""
    _lock_users(actor.pk, workshop.trainer_id)
    event = Hackathon.objects.select_for_update().get(pk=workshop.hackathon_id)
    current = _lock_workshop(workshop)
    as_organizer = can_manage(actor, event)
    if not (as_organizer or current.trainer_id == actor.pk):
        raise PermissionDenied(_('Seuls un organisateur ou le formateur peuvent annuler cet atelier.'))
    if event.status == Hackathon.Status.ARCHIVED:
        raise ValidationError(ARCHIVED)
    _ensure_open(current)
    released = _active_registrations(current).update(status=WorkshopRegistration.Status.CANCELLED, cancelled_at=timezone.now())
    current.status = Workshop.Status.CANCELLED
    current.save()
    record(event=event, actor=actor, action='workshop.cancelled', obj=current, released_registrations=released,
        as_organizer=as_organizer and current.trainer_id != actor.pk)
    return current


@transaction.atomic
def register_to_workshop(*, actor, workshop):
    """Individual registration of an accepted participant. The seat count is re-checked under the workshop lock."""
    _lock_actor(actor)
    event = Hackathon.objects.select_for_update().get(pk=workshop.hackathon_id)
    current = Workshop.objects.select_for_update(of=('self',)).get(pk=workshop.pk)
    registration = team_services.accepted_registration(actor, event)
    if registration is None:
        raise PermissionDenied(_('Une inscription acceptée au hackathon est requise pour s’inscrire à un atelier.'))
    _require_open_event(event, WORKSHOPS_CLOSED)
    if current.status != Workshop.Status.PUBLISHED:
        raise ValidationError(_('Cet atelier est annulé.'))
    if current.start <= timezone.now():
        raise ValidationError(_('Les inscriptions sont closes : l’atelier a commencé.'))
    row = WorkshopRegistration.objects.select_for_update().filter(workshop=current, registration=registration).first()
    if row and row.status == WorkshopRegistration.Status.REGISTERED:
        raise ValidationError(_('Vous êtes déjà inscrit à cet atelier.'))
    if _active_registrations(current).count() >= current.capacity:
        raise ValidationError(_('Cet atelier est complet.'))
    if WorkshopRegistration.objects.filter(registration__user=actor, status=WorkshopRegistration.Status.REGISTERED,
            workshop__status=Workshop.Status.PUBLISHED, workshop__start__lt=current.end,
            workshop__end__gt=current.start).exclude(workshop=current).exists():
        raise ValidationError(_('Vous êtes déjà inscrit à un autre atelier à cette heure-là.'))
    if MentoringSession.objects.filter(status=MentoringSession.Status.BOOKED, request__team__closed_at__isnull=True,
            request__team__memberships__ended_at__isnull=True, request__team__memberships__registration__user=actor,
            slot__start__lt=current.end, slot__end__gt=current.start).exists():
        raise ValidationError(_('Votre équipe a un rendez-vous de mentorat à cette heure-là.'))
    if row:
        row.status, row.attendance, row.cancelled_at = WorkshopRegistration.Status.REGISTERED, WorkshopRegistration.Attendance.UNKNOWN, None
        row.attendance_marked_by, row.attendance_marked_at = None, None
    else:
        row = WorkshopRegistration(workshop=current, registration=registration)
    row.save()
    record(event=event, actor=actor, action='workshop.registered', obj=row, workshop=current.pk)
    return row


@transaction.atomic
def cancel_workshop_registration(*, actor, workshop):
    _lock_actor(actor)
    event = Hackathon.objects.select_for_update().get(pk=workshop.hackathon_id)
    current = Workshop.objects.select_for_update(of=('self',)).get(pk=workshop.pk)
    row = WorkshopRegistration.objects.select_for_update().filter(workshop=current, registration__user=actor,
        status=WorkshopRegistration.Status.REGISTERED).first()
    if row is None:
        raise ValidationError(_('Vous n’êtes pas inscrit à cet atelier.'))
    if current.start <= timezone.now():
        raise ValidationError(_('Une inscription ne peut plus être annulée une fois l’atelier commencé.'))
    row.status, row.cancelled_at = WorkshopRegistration.Status.CANCELLED, timezone.now()
    row.save()
    record(event=event, actor=actor, action='workshop.unregistered', obj=row, workshop=current.pk)
    return row


@transaction.atomic
def mark_attendance(*, actor, workshop_registration, attendance):
    """Only the trainer or an organizer, once the workshop has started."""
    row_ref = WorkshopRegistration.objects.select_related('workshop').get(pk=workshop_registration.pk)
    _lock_actor(actor)
    event = Hackathon.objects.select_for_update().get(pk=row_ref.workshop.hackathon_id)
    row = WorkshopRegistration.objects.select_for_update(of=('self',)).select_related('workshop', 'registration__user').get(pk=row_ref.pk)
    if not (row.workshop.trainer_id == actor.pk or can_manage(actor, event)):
        raise PermissionDenied(_('Seuls le formateur ou un organisateur peuvent relever la présence.'))
    if attendance not in WorkshopRegistration.Attendance.values:
        raise ValidationError(_('Présence invalide.'))
    if event.status == Hackathon.Status.ARCHIVED:
        raise ValidationError(ARCHIVED)
    if row.status != WorkshopRegistration.Status.REGISTERED or row.workshop.status != Workshop.Status.PUBLISHED:
        raise ValidationError(_('Seule une inscription active peut recevoir une présence.'))
    if row.workshop.start > timezone.now():
        raise ValidationError(_('Le relevé de présence s’ouvre au début de l’atelier.'))
    row.attendance, row.attendance_marked_by, row.attendance_marked_at = attendance, actor, timezone.now()
    row.save()
    record(event=event, actor=actor, action='workshop.attendance', obj=row, workshop=row.workshop_id,
        participant=row.registration.user_id, attendance=attendance)
    return row


def workshop_seats(workshop):
    """(registered, free) from the live count."""
    registered = _active_registrations(workshop).count()
    return registered, max(workshop.capacity - registered, 0)


# ----------------------------------------------------------- support requests
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
        raise ValidationError(ARCHIVED)
    if current.status != SupportRequest.Status.OPEN:
        raise ValidationError(_('Seule une demande ouverte peut être annulée. Annulez d’abord le rendez-vous.'))
    current.status = SupportRequest.Status.CANCELLED
    current.save()
    record(event=event, actor=actor, action='request.cancelled', obj=current, as_organizer=as_organizer and not
        team_services.is_captain(actor, current.team) and current.author_id != actor.pk)
    return current


def can_cancel_request(user, request):
    if request.status != SupportRequest.Status.OPEN or request.hackathon.status == Hackathon.Status.ARCHIVED:
        return False
    return bool(team_services.is_captain(user, request.team)
        or (request.author_id == user.pk and _is_active_member(user, request.team)) or can_manage(user, request.hackathon))


# --------------------------------------------------------- booking a mentor
def can_book(user, request):
    """The captain books for the team; an organizer may step in (and is traced)."""
    if request.status != SupportRequest.Status.OPEN or request.hackathon.status not in OPEN_STATUSES:
        return False
    if not phase_is_open(request.hackathon, EventPhase.Kind.DEVELOPMENT):
        return False
    return bool(team_services.is_captain(user, request.team) or can_manage(user, request.hackathon))


def bookable_slots(request, skill=None):
    """The real free slots a team can book: published, future, not booked, offered by an active mentor of the
    edition who is not in the team, without conflict with the team's other appointments or the mentor's workshops.
    The optional skill only filters by what mentors declared: it never ranks them."""
    members = team_services.active_members(request.team).values('registration__user')
    mentor_ok = RoleAssignment.objects.filter(user=OuterRef('mentor'), hackathon=OuterRef('hackathon'), role=Role.MENTOR,
        status=AssignmentStatus.ACTIVE)
    team_busy = MentoringSession.objects.filter(request__team=request.team, status=MentoringSession.Status.BOOKED,
        slot__start__lt=OuterRef('end'), slot__end__gt=OuterRef('start'))
    teaching = Workshop.objects.filter(trainer=OuterRef('mentor'), status=Workshop.Status.PUBLISHED,
        start__lt=OuterRef('end'), end__gt=OuterRef('start'))
    slots = (MentorSlot.objects.available().filter(hackathon_id=request.hackathon_id, start__gt=timezone.now())
        .filter(Exists(mentor_ok)).exclude(mentor__in=members).exclude(Exists(team_busy)).exclude(Exists(teaching))
        .select_related('mentor').prefetch_related('mentor__mentor_expertises__skill').order_by('start', 'mentor__username'))
    if skill is not None:
        slots = slots.filter(mentor__mentor_expertises__skill=skill).distinct()
    return slots


@transaction.atomic
def book_session(*, actor, request, slot):
    """Book a free slot for a request. Everything is re-checked under the locks of the people, the edition,
    the request and the slot; the unique indexes catch whatever could still slip through."""
    mentor_id = MentorSlot.objects.values_list('mentor_id', flat=True).get(pk=slot.pk)
    _lock_users(actor.pk, mentor_id)
    event = Hackathon.objects.select_for_update().get(pk=request.hackathon_id)
    current = SupportRequest.objects.select_for_update(of=('self',)).select_related('team__captain').get(pk=request.pk)
    slot = MentorSlot.objects.select_for_update(of=('self',)).select_related('mentor').get(pk=slot.pk)
    as_organizer = can_manage(actor, event)
    captain = team_services.is_captain(actor, current.team)
    if not (captain or as_organizer):
        raise PermissionDenied(_('Seul le capitaine de l’équipe (ou un organisateur) peut réserver un mentor.'))
    if event.status == Hackathon.Status.ARCHIVED:
        raise ValidationError(ARCHIVED)
    if event.status not in OPEN_STATUSES or not phase_is_open(event, EventPhase.Kind.DEVELOPMENT):
        raise ValidationError(SUPPORT_CLOSED)
    if current.status != SupportRequest.Status.OPEN or current.team.closed_at is not None:
        raise ValidationError(_('Cette demande n’attend pas de rendez-vous.'))
    if slot.hackathon_id != event.pk:
        raise ValidationError(_('Ce créneau appartient à un autre hackathon.'))
    if slot.withdrawn_at is not None:
        raise ValidationError(_('Ce créneau n’est plus proposé.'))
    if slot.start <= timezone.now():
        raise ValidationError(_('Ce créneau est déjà commencé ou passé.'))
    if slot.sessions.filter(status=MentoringSession.Status.BOOKED).exists():
        raise ValidationError(_('Ce créneau vient d’être réservé par une autre équipe.'))
    if not RoleAssignment.objects.filter(user=slot.mentor, hackathon=event, role=Role.MENTOR, status=AssignmentStatus.ACTIVE).exists():
        raise ValidationError(_('Ce mentor n’est plus actif dans ce hackathon.'))
    session = MentoringSession(request=current, slot=slot, booked_by=actor)
    try:
        with transaction.atomic():
            session.save()
    except IntegrityError:
        raise ValidationError(_('Ce créneau vient d’être réservé par une autre équipe.')) from None
    current.status = SupportRequest.Status.BOOKED
    current.save()
    record(event=event, actor=actor, action='session.booked', obj=session, request=current.pk, slot=slot.pk,
        mentor=slot.mentor_id, start=_iso(slot.start), as_organizer=as_organizer and not captain)
    return session


@transaction.atomic
def cancel_session(*, actor, session):
    """Before the start, the captain, the mentor or an organizer may cancel. The slot is free again and the
    request goes back to OPEN; the cancelled session stays in the history."""
    ref = MentoringSession.objects.select_related('slot').get(pk=session.pk)
    _lock_users(actor.pk, ref.slot.mentor_id)
    event = Hackathon.objects.select_for_update().get(pk=ref.slot.hackathon_id)
    current = MentoringSession.objects.select_for_update(of=('self',)).select_related('request__team__captain', 'slot').get(pk=ref.pk)
    team_request = SupportRequest.objects.select_for_update(of=('self',)).get(pk=current.request_id)
    as_organizer = can_manage(actor, event)
    captain = team_services.is_captain(actor, current.request.team)
    mentor = current.slot.mentor_id == actor.pk
    if not (captain or mentor or as_organizer):
        raise PermissionDenied(_('Seuls le capitaine, le mentor ou un organisateur peuvent annuler ce rendez-vous.'))
    if event.status == Hackathon.Status.ARCHIVED:
        raise ValidationError(ARCHIVED)
    if current.status != MentoringSession.Status.BOOKED:
        raise ValidationError(_('Seul un rendez-vous réservé peut être annulé.'))
    if current.slot.start <= timezone.now():
        raise ValidationError(_('Un rendez-vous commencé ne peut plus être annulé.'))
    current.status, current.cancelled_at, current.cancelled_by = MentoringSession.Status.CANCELLED, timezone.now(), actor
    current.save()
    if team_request.status == SupportRequest.Status.BOOKED:
        team_request.status = SupportRequest.Status.OPEN
        team_request.save()
    record(event=event, actor=actor, action='session.cancelled', obj=current, request=team_request.pk,
        by='team' if captain else 'mentor' if mentor else 'organizer')
    return current


# ------------------------------------------ the session: report, feedback, result
@transaction.atomic
def complete_session(*, actor, session, report, private_notes=''):
    """The mentor of the session writes the report and finishes it, once it has started."""
    ref = MentoringSession.objects.select_related('slot').get(pk=session.pk)
    _lock_users(actor.pk)
    event = Hackathon.objects.select_for_update().get(pk=ref.slot.hackathon_id)
    current = MentoringSession.objects.select_for_update(of=('self',)).select_related('slot', 'request').get(pk=ref.pk)
    team_request = SupportRequest.objects.select_for_update(of=('self',)).get(pk=current.request_id)
    if current.slot.mentor_id != actor.pk:
        raise PermissionDenied(_('Seul le mentor de la séance peut la terminer.'))
    if event.status == Hackathon.Status.ARCHIVED:
        raise ValidationError(ARCHIVED)
    if current.status != MentoringSession.Status.BOOKED:
        raise ValidationError(_('Seule une séance réservée peut être terminée.'))
    if current.slot.start > timezone.now():
        raise ValidationError(_('La séance n’a pas encore commencé.'))
    if not (report or '').strip():
        raise ValidationError(_('Le compte rendu est obligatoire pour terminer la séance.'))
    current.status, current.completed_at = MentoringSession.Status.COMPLETED, timezone.now()
    current.report, current.private_notes = report.strip(), (private_notes or '').strip()
    current.save()
    team_request.status = SupportRequest.Status.IN_PROGRESS
    team_request.save()
    record(event=event, actor=actor, action='session.completed', obj=current, request=team_request.pk)
    return current


@transaction.atomic
def update_report(*, actor, session, report, private_notes=''):
    """The mentor may correct the report until the team has said whether the problem is solved."""
    ref = MentoringSession.objects.select_related('slot').get(pk=session.pk)
    _lock_users(actor.pk)
    event = Hackathon.objects.select_for_update().get(pk=ref.slot.hackathon_id)
    current = MentoringSession.objects.select_for_update(of=('self',)).select_related('slot', 'request').get(pk=ref.pk)
    if current.slot.mentor_id != actor.pk:
        raise PermissionDenied(_('Seul le mentor de la séance peut modifier son compte rendu.'))
    if current.status != MentoringSession.Status.COMPLETED or current.request.status != SupportRequest.Status.IN_PROGRESS:
        raise ValidationError(_('Le compte rendu ne peut plus être modifié.'))
    if not (report or '').strip():
        raise ValidationError(_('Le compte rendu est obligatoire pour terminer la séance.'))
    current.report, current.private_notes = report.strip(), (private_notes or '').strip()
    current.save()
    record(event=event, actor=actor, action='session.report_updated', obj=current, request=current.request_id)
    return current


@transaction.atomic
def give_feedback(*, actor, session, rating, comment, resolved):
    """An active member of the team rates the session and says whether the problem is solved. A finished
    session does not mean a solved problem: if it is not, the request is open again for a new appointment."""
    ref = MentoringSession.objects.select_related('slot', 'request').get(pk=session.pk)
    _lock_users(actor.pk)
    event = Hackathon.objects.select_for_update().get(pk=ref.slot.hackathon_id)
    current = MentoringSession.objects.select_for_update(of=('self',)).select_related('slot', 'request__team').get(pk=ref.pk)
    team_request = SupportRequest.objects.select_for_update(of=('self',)).select_related('team').get(pk=current.request_id)
    if not _is_active_member(actor, team_request.team):
        raise PermissionDenied(_('Seuls les membres actifs de l’équipe peuvent donner leur retour.'))
    if event.status == Hackathon.Status.ARCHIVED:
        raise ValidationError(ARCHIVED)
    if current.status != MentoringSession.Status.COMPLETED or team_request.status != SupportRequest.Status.IN_PROGRESS:
        raise ValidationError(_('Le retour se donne après la fin de la séance.'))
    if current.feedback_at is not None:
        raise ValidationError(_('Votre équipe a déjà donné son retour sur cette séance.'))
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        rating = 0
    if not 1 <= rating <= 5:
        raise ValidationError(_('Donnez une note entre 1 et 5.'))
    now = timezone.now()
    current.feedback_rating, current.feedback_comment, current.feedback_at = rating, (comment or '').strip(), now
    current.save()
    team_request.status = SupportRequest.Status.RESOLVED if resolved else SupportRequest.Status.OPEN
    team_request.resolved_at = now if resolved else None
    team_request.save()
    record(event=event, actor=actor, action='session.feedback', obj=current, request=team_request.pk, rating=rating, resolved=bool(resolved))
    record(event=event, actor=actor, action='request.resolved' if resolved else 'request.reopened', obj=team_request, session=current.pk)
    return current


def can_complete_session(user, session):
    return (session.status == MentoringSession.Status.BOOKED and session.slot.mentor_id == user.pk
        and session.slot.start <= timezone.now() and session.slot.hackathon.status != Hackathon.Status.ARCHIVED)


def can_cancel_session(user, session):
    if session.status != MentoringSession.Status.BOOKED or session.slot.start <= timezone.now():
        return False
    if session.slot.hackathon.status == Hackathon.Status.ARCHIVED:
        return False
    return bool(team_services.is_captain(user, session.request.team) or session.slot.mentor_id == user.pk
        or can_manage(user, session.slot.hackathon))


def can_give_feedback(user, session):
    return bool(session.status == MentoringSession.Status.COMPLETED and session.feedback_at is None
        and session.request.status == SupportRequest.Status.IN_PROGRESS and _is_active_member(user, session.request.team))


# ---------------------------------------------------- reading: who sees what
def visible_requests(user):
    """Confidentiality rule, enforced in the query: a request is private to
    - the active members of its (still open) team,
    - the mentor of one of its booked or completed sessions,
    - the organizers of its hackathon (and the technical superuser).
    A former member loses access; the requests of the team are kept.
    """
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


def visible_sessions(user):
    """Appointments of the user's team(s), of the mentor himself, and of the editions the user organizes."""
    queryset = MentoringSession.objects.select_related('request__team', 'request__hackathon', 'slot__mentor', 'slot__hackathon')
    if not (user.is_authenticated and user.is_active):
        return queryset.none()
    if user.is_superuser:
        return queryset
    member = Q(request__team__closed_at__isnull=True, request__team__memberships__ended_at__isnull=True,
        request__team__memberships__registration__user=user,
        request__team__memberships__registration__status=Registration.Status.ACCEPTED)
    mentor = Q(slot__mentor=user)
    organizer = Q(request__hackathon__role_assignments__user=user, request__hackathon__role_assignments__role=Role.ORGANIZER,
        request__hackathon__role_assignments__status=AssignmentStatus.ACTIVE)
    return queryset.filter(member | mentor | organizer).distinct()


PRIORITY_RANK = Case(When(priority='CRITICAL', then=0), When(priority='HIGH', then=1), When(priority='NORMAL', then=2),
    default=3, output_field=IntegerField())


def requestable_teams(user):
    """Teams in which the user may open a help request right now (active member, development phase open)."""
    if not (user.is_authenticated and user.is_active):
        return []
    teams = Team.objects.filter(closed_at__isnull=True, memberships__ended_at__isnull=True,
        memberships__registration__user=user, memberships__registration__status=Registration.Status.ACCEPTED,
        hackathon__status__in=OPEN_STATUSES).select_related('hackathon').distinct().order_by('hackathon__title', 'name')
    return [team for team in teams if phase_is_open(team.hackathon, EventPhase.Kind.DEVELOPMENT)]


def team_requests(user):
    """The requests of the teams the user is an active member of."""
    return visible_requests(user).filter(team__closed_at__isnull=True, team__memberships__ended_at__isnull=True,
        team__memberships__registration__user=user,
        team__memberships__registration__status=Registration.Status.ACCEPTED).distinct()


def coached_requests(user):
    """The requests the user follows as a mentor (booked or completed session on one of his slots)."""
    return visible_requests(user).filter(sessions__slot__mentor=user, sessions__status__in=['BOOKED', 'COMPLETED']).distinct()


def support_insights(event):
    """Real figures for the organizers of an edition: what is blocked, and what keeps coming back."""
    requests = SupportRequest.objects.filter(hackathon=event)
    active = requests.filter(status__in=SupportRequest.ACTIVE_STATUSES)
    recurring = (requests.filter(skill__isnull=False).values('skill__name')
        .annotate(teams=Count('team', distinct=True), total=Count('id')).filter(teams__gte=2)
        .order_by('-teams', '-total', 'skill__name'))
    return {
        'event': event,
        'active_count': active.count(),
        'critical': list(active.filter(priority=SupportRequest.Priority.CRITICAL).select_related('team').order_by('created_at')[:10]),
        'recurring': list(recurring),
        'requests': requests.select_related('team', 'skill').annotate(rank=PRIORITY_RANK).order_by('rank', '-created_at'),
    }
