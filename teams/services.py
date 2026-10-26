"""Atomic M2 transitions. Lock users (sorted), then event, as accounts.set_role does.

The event lock serializes capacity checks and every team composition change.
Read helpers below are the public integration contract for M3/M4.
"""
from datetime import timedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext as _
from accounts.models import User, Role, RoleAssignment, AssignmentStatus
from accounts.permissions import can_manage
from hackathons.models import Hackathon, EventPhase
from hackathons.services import require_open_phase, phase_is_open
from .models import Registration, Team, TeamMembership, TeamInvitation, JoinRequest, TeamSkillNeed, TeamHistory, Decision


def accepted_registration(user, event):
    if not user.is_authenticated or not user.is_active:
        return None
    return Registration.objects.filter(user=user, hackathon=event, status=Registration.Status.ACCEPTED).first()


def active_team(user, event):
    if not user.is_authenticated:
        return None
    return Team.objects.filter(hackathon=event, closed_at__isnull=True, memberships__registration__user=user,
        memberships__registration__status=Registration.Status.ACCEPTED, memberships__ended_at__isnull=True).first()


def active_members(team):
    return team.memberships.filter(ended_at__isnull=True, registration__status=Registration.Status.ACCEPTED).select_related('registration__user')


def is_captain(user, team):
    return user.is_authenticated and user.is_active and team.captain.user_id == user.pk and team.closed_at is None


def team_is_ready(team):
    return team.is_ready


def can_read(user, event):
    return bool(accepted_registration(user, event)) or can_manage(user, event)


def require_reader(user, event):
    if not can_read(user, event):
        raise PermissionDenied(_('Inscrivez-vous à cette édition pour accéder aux équipes.'))


def formation_open(event):
    return phase_is_open(event, EventPhase.Kind.TEAM_FORMATION)


def teams_with_counts(event):
    return Team.objects.filter(hackathon=event, closed_at__isnull=True).select_related('hackathon', 'captain__user').annotate(
        active_count=Count('memberships', filter=Q(memberships__ended_at__isnull=True))).prefetch_related('skill_needs__skill').order_by('name', 'pk')


def metrics(event):
    teams = teams_with_counts(event)
    return {
        'registrations': event.registrations.filter(status=Registration.Status.ACCEPTED).count(),
        'teams': teams.count(),
        'incomplete_teams': teams.filter(active_count__lt=event.min_team_size).count(),
        'participants_without_team': event.registrations.filter(status=Registration.Status.ACCEPTED).exclude(memberships__ended_at__isnull=True, memberships__isnull=False).count(),
    }


def _lock(actor, event, *others):
    ids = sorted({actor.pk, *(u.pk for u in others)})
    users = {u.pk: u for u in User.objects.select_for_update(no_key=True).filter(pk__in=ids).order_by('pk')}
    if actor.pk not in users or not users[actor.pk].is_active:
        raise PermissionDenied
    locked = Hackathon.objects.select_for_update().get(pk=event.pk)
    if locked.status == Hackathon.Status.ARCHIVED:
        raise ValidationError(_('Édition archivée : consultation uniquement.'))
    return locked, users


def _log(event, actor, action, team=None, registration=None, **details):
    TeamHistory.objects.create(hackathon=event, actor=actor, action=action, team=team, registration=registration, details=details)


def _captain(actor, team):
    if not is_captain(actor, team) and not can_manage(actor, team.hackathon):
        raise PermissionDenied(_('Seul le capitaine ou un organisateur peut gérer cette équipe.'))
    if team.closed_at:
        raise ValidationError(_('Cette équipe est fermée.'))


def _registration(user, event):
    reg = accepted_registration(user, event)
    if not reg:
        raise ValidationError(_('Une inscription acceptée est requise.'))
    if RoleAssignment.objects.filter(user=user, hackathon=event, role=Role.JURY, status=AssignmentStatus.ACTIVE).exists():
        raise ValidationError(_('Un juré ne peut pas participer au même hackathon.'))
    return reg


@transaction.atomic
def register(*, actor, event, accept_conditions):
    event, users = _lock(actor, event)
    require_open_phase(event, EventPhase.Kind.REGISTRATION)
    if not accept_conditions:
        raise ValidationError(_('Acceptez le règlement et les conditions de participation.'))
    if RoleAssignment.objects.filter(user=actor, hackathon=event, role=Role.JURY, status=AssignmentStatus.ACTIVE).exists():
        raise ValidationError(_('Un juré ne peut pas participer au même hackathon.'))
    reg = Registration.objects.filter(user=actor, hackathon=event).first()
    if reg and reg.status == Registration.Status.ACCEPTED:
        return reg
    if event.registrations.filter(status=Registration.Status.ACCEPTED).count() >= event.capacity:
        raise ValidationError(_('Ce hackathon est complet.'))
    if not reg:
        reg = Registration(user=actor, hackathon=event)
    reg.status = Registration.Status.ACCEPTED
    reg.accepted_conditions_at = timezone.now()
    reg.conditions_snapshot = event.rules + '\n\n' + event.participation_conditions
    reg.full_clean()
    reg.save()
    from accounts.services import sync_registration_role
    sync_registration_role(actor=actor, registration=reg)
    _log(event, actor, 'REGISTER', registration=reg)
    return reg


@transaction.atomic
def cancel_registration(*, actor, registration):
    event, users = _lock(actor, registration.hackathon, registration.user)
    reg = Registration.objects.get(pk=registration.pk)
    if actor.pk != reg.user_id and not can_manage(actor, event):
        raise PermissionDenied
    if reg.status != Registration.Status.ACCEPTED:
        raise ValidationError(_('Cette inscription est déjà annulée.'))
    # A registration can be withdrawn while registrations OR formation are open;
    # never after formation ended, even if registration was configured to overlap.
    phase = event.phases.filter(kind=EventPhase.Kind.TEAM_FORMATION).first()
    if phase and timezone.now() >= phase.end:
        raise ValidationError(_('La composition des équipes est figée.'))
    if not (phase_is_open(event, EventPhase.Kind.REGISTRATION) or formation_open(event)):
        raise ValidationError(_('Les annulations sont fermées.'))
    if TeamMembership.objects.filter(registration=reg, ended_at__isnull=True).exists():
        raise ValidationError(_('Quittez votre équipe avant d’annuler votre inscription.'))
    reg.status = Registration.Status.CANCELLED
    reg.save(update_fields=['status', 'updated_at'])
    from accounts.services import sync_registration_role
    sync_registration_role(actor=actor, registration=reg)
    _close_pending(reg, actor)
    _log(event, actor, 'CANCEL_REGISTRATION', registration=reg)


@transaction.atomic
def create_team(*, actor, event, name, description=''):
    event, users = _lock(actor, event)
    require_open_phase(event, EventPhase.Kind.TEAM_FORMATION)
    reg = _registration(users[actor.pk], event)
    if active_team(actor, event):
        raise ValidationError(_('Vous avez déjà une équipe dans cette édition.'))
    team = Team(hackathon=event, captain=reg, name=name.strip(), description=description.strip())
    team.full_clean()
    team.save()
    _join(team, reg, actor)
    _log(event, actor, 'CREATE_TEAM', team, reg)
    return team


@transaction.atomic
def update_team(*, actor, team, name, description, recruiting):
    event, _users = _lock(actor, team.hackathon)
    team = Team.objects.select_related('captain').get(pk=team.pk)
    _captain(actor, team)
    require_open_phase(event, EventPhase.Kind.TEAM_FORMATION)
    team.name, team.description, team.recruiting = name.strip(), description.strip(), recruiting
    team.full_clean()
    team.save()
    _log(event, actor, 'UPDATE_TEAM', team)
    return team


def _close_pending(reg, actor, exclude=None):
    for model in (TeamInvitation, JoinRequest):
        pending = model.objects.filter(registration=reg, status=Decision.PENDING)
        if exclude and isinstance(exclude, model):
            pending = pending.exclude(pk=exclude.pk)
        for record in pending:
            record.status = Decision.CANCELLED
            record.decided_by = actor
            record.decided_at = timezone.now()
            record.save(update_fields=['status', 'decided_by', 'decided_at'])
            _log(reg.hackathon, actor, 'CANCEL_RECRUITMENT', record.team, reg, kind=model.__name__, record_id=record.pk)


def _join(team, reg, actor, record=None):
    if team.closed_at or reg.hackathon_id != team.hackathon_id:
        raise ValidationError(_('Équipe indisponible pour cette inscription.'))
    _registration(reg.user, team.hackathon)
    if TeamMembership.objects.filter(registration=reg, ended_at__isnull=True).exists():
        raise ValidationError(_('Ce participant a déjà une équipe.'))
    if team.memberships.filter(ended_at__isnull=True).count() >= team.hackathon.max_team_size:
        raise ValidationError(_('Cette équipe est complète.'))
    membership = TeamMembership(registration=reg, team=team)
    membership.full_clean()
    membership.save()
    _close_pending(reg, actor, exclude=record)
    _log(team.hackathon, actor, 'JOIN_TEAM', team, reg)
    return membership


@transaction.atomic
def leave_team(*, actor, team, membership):
    event, _users = _lock(actor, team.hackathon, membership.registration.user)
    team = Team.objects.select_related('captain').get(pk=team.pk)
    member = TeamMembership.objects.select_related('registration').get(pk=membership.pk, team=team)
    if actor.pk != member.registration.user_id:
        _captain(actor, team)
    require_open_phase(event, EventPhase.Kind.TEAM_FORMATION)
    if member.ended_at:
        raise ValidationError(_('Cette personne a déjà quitté l’équipe.'))
    count = team.memberships.filter(ended_at__isnull=True).count()
    if team.captain_id == member.registration_id and count > 1:
        raise ValidationError(_('Transférez le rôle de capitaine avant ce départ.'))
    member.ended_at = timezone.now()
    member.save(update_fields=['ended_at'])
    if count == 1:
        team.closed_at, team.recruiting = timezone.now(), False
        team.save(update_fields=['closed_at', 'recruiting'])
        for model in (TeamInvitation, JoinRequest):
            for record in model.objects.filter(team=team, status=Decision.PENDING):
                record.status, record.decided_by, record.decided_at = Decision.CANCELLED, actor, timezone.now()
                record.save(update_fields=['status', 'decided_by', 'decided_at'])
                _log(event, actor, 'CANCEL_RECRUITMENT', team, record.registration, kind=model.__name__, record_id=record.pk)
    _log(event, actor, 'LEAVE_TEAM' if actor.pk == member.registration.user_id else 'REMOVE_MEMBER', team, member.registration)


@transaction.atomic
def transfer_captain(*, actor, team, membership):
    event, _users = _lock(actor, team.hackathon, membership.registration.user)
    team = Team.objects.select_related('captain').get(pk=team.pk)
    _captain(actor, team)
    require_open_phase(event, EventPhase.Kind.TEAM_FORMATION)
    member = TeamMembership.objects.select_related('registration__user').filter(pk=membership.pk, team=team, ended_at__isnull=True).first()
    if not member or not member.registration.user.is_active or member.registration.status != Registration.Status.ACCEPTED:
        raise ValidationError(_('Choisissez un membre actif de cette équipe.'))
    old = team.captain_id
    team.captain = member.registration
    team.save(update_fields=['captain'])
    _log(event, actor, 'TRANSFER_CAPTAIN', team, member.registration, previous=old)


@transaction.atomic
def recruit(*, actor, team, registration=None, message=''):
    """A captain invites a participant; a participant applies for themselves."""
    target = registration.user if registration else actor
    event, users = _lock(actor, team.hackathon, target)
    team = Team.objects.select_related('hackathon', 'captain').get(pk=team.pk)
    require_open_phase(event, EventPhase.Kind.TEAM_FORMATION)
    if team.closed_at or not team.recruiting or team.places_left == 0:
        raise ValidationError(_('Cette équipe ne recrute pas actuellement.'))
    if registration:
        _captain(actor, team)
        reg = _registration(users[target.pk], event)
        if reg.pk != registration.pk:
            raise ValidationError(_('Inscription d’une autre édition.'))
        model = TeamInvitation
        # Persist old expired invitations before permitting a fresh one.
        model.objects.filter(team=team, registration=reg, status=Decision.PENDING, expires_at__lte=timezone.now()).update(status=Decision.EXPIRED, decided_at=timezone.now())
    else:
        reg = _registration(users[actor.pk], event)
        model = JoinRequest
    if active_team(target, event):
        raise ValidationError(_('Ce participant a déjà une équipe.'))
    if model.objects.filter(team=team, registration=reg, status=Decision.PENDING).exists():
        raise ValidationError(_('Une demande est déjà en attente.'))
    kwargs = {'expires_at': min(timezone.now() + timedelta(days=7), event.phases.get(kind=EventPhase.Kind.TEAM_FORMATION).end)} if model == TeamInvitation else {}
    record = model(team=team, registration=reg, message=message.strip(), created_by=actor, **kwargs)
    record.full_clean()
    record.save()
    _log(event, actor, 'INVITE' if registration else 'APPLY', team, reg, record_id=record.pk)
    return record


@transaction.atomic
def decide(*, actor, record, decision):
    event, _users = _lock(actor, record.team.hackathon, record.registration.user)
    record = type(record).objects.select_related('team__hackathon', 'team__captain', 'registration__user').get(pk=record.pk)
    require_open_phase(event, EventPhase.Kind.TEAM_FORMATION)
    if decision not in (Decision.ACCEPTED, Decision.DECLINED, Decision.CANCELLED):
        raise ValidationError(_('Décision invalide.'))
    invitation = isinstance(record, TeamInvitation)
    if invitation:
        if decision == Decision.CANCELLED:
            _captain(actor, record.team)
        elif actor.pk != record.registration.user_id:
            raise PermissionDenied
    elif decision == Decision.CANCELLED:
        if actor.pk != record.registration.user_id:
            raise PermissionDenied
    else:
        _captain(actor, record.team)
    if record.status != Decision.PENDING:
        raise ValidationError(_('Cette demande a déjà été traitée.'))
    if invitation and record.expires_at <= timezone.now():
        raise ValidationError(_('Cette invitation a expiré.'))
    if decision == Decision.ACCEPTED:
        if not record.team.recruiting:
            raise ValidationError(_('Cette équipe a fermé son recrutement.'))
        _join(record.team, record.registration, actor, record)
    record.status, record.decided_by, record.decided_at = decision, actor, timezone.now()
    record.save(update_fields=['status', 'decided_by', 'decided_at'])
    _log(event, actor, 'DECIDE_RECRUITMENT', record.team, record.registration, kind=type(record).__name__, record_id=record.pk, decision=decision)
    return record


@transaction.atomic
def save_need(*, actor, team, skill, level, priority, need=None):
    event, _users = _lock(actor, team.hackathon)
    team = Team.objects.select_related('captain').get(pk=team.pk)
    _captain(actor, team)
    require_open_phase(event, EventPhase.Kind.TEAM_FORMATION)
    if need and need.team_id != team.pk:
        raise PermissionDenied
    need = TeamSkillNeed.objects.get(pk=need.pk, team=team) if need else TeamSkillNeed(team=team)
    need.skill, need.level, need.priority = skill, level, priority
    need.full_clean()
    need.save()
    _log(event, actor, 'SAVE_SKILL_NEED', team, skill_id=skill.pk, level=level, priority=priority)
    return need


@transaction.atomic
def delete_need(*, actor, need):
    event, _users = _lock(actor, need.team.hackathon)
    team = Team.objects.select_related('captain').get(pk=need.team_id)
    _captain(actor, team)
    require_open_phase(event, EventPhase.Kind.TEAM_FORMATION)
    _log(event, actor, 'DELETE_SKILL_NEED', team, skill_id=need.skill_id)
    need.delete()


def eligible_candidates(*, actor, team):
    """Authorized input contract for the future shared intelligence engine."""
    require_reader(actor, team.hackathon)
    return Registration.objects.filter(hackathon=team.hackathon, status=Registration.Status.ACCEPTED, user__is_active=True).exclude(
        pk__in=TeamMembership.objects.filter(ended_at__isnull=True).values('registration_id')).exclude(
        user_id__in=RoleAssignment.objects.filter(hackathon=team.hackathon, role=Role.JURY, status=AssignmentStatus.ACTIVE).values('user_id')
    ).select_related('user', 'user__profile').prefetch_related('user__user_skills__skill').distinct()


def skill_coverage(team):
    """A declared need is covered when an active member reaches its desired level.

    Keep the need for future departures; coverage is calculated, never copied.
    """
    members = list(active_members(team).prefetch_related('registration__user__user_skills'))
    needs = list(team.skill_needs.select_related('skill'))
    for need in needs:
        need.covered_by = [member.registration.user for member in members
            if any(skill.skill_id == need.skill_id and skill.level >= need.level
                for skill in member.registration.user.user_skills.all())]
    return needs


def recommendations(*, actor, team, background=True, mode='hybrid'):
    from .matching import rank
    return rank(team=team, candidates=eligible_candidates(actor=actor, team=team),
        needs=skill_coverage(team), background=background, mode=mode)


def recommendation_comparison(*, actor, team, mode='hybrid', background=True):
    """Same people, needs and skill rules; only semantic context changes.

    `rules` remains the V1 evaluation baseline. The UI uses `skills` to isolate
    the model's contribution instead of comparing two different skill formulas.
    """
    from .matching import rank
    candidates = list(eligible_candidates(actor=actor, team=team))
    needs = skill_coverage(team)
    baseline = rank(team=team, candidates=candidates, needs=needs, mode='skills')
    selected = rank(team=team, candidates=candidates, needs=needs, mode='hybrid', background=background) if mode == 'hybrid' else baseline
    return selected, baseline, [n for n in needs if not n.covered_by]
