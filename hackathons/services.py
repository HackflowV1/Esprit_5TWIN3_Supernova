"""M1 business operations. Consumers reuse these checks; never replicate calendar logic."""
from django.utils.translation import gettext as _
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.module_loading import import_string
from accounts.models import Role, RoleAssignment, RoleAssignmentHistory, SponsorMembership, AssignmentStatus
from accounts.permissions import require_organizer, can_create_hackathon, has_role
from .models import Hackathon, Track, Challenge, EventPhase, Sponsorship, EventHistory

PUBLIC_STATUSES = [Hackathon.Status.PUBLISHED, Hackathon.Status.ONGOING, Hackathon.Status.FINISHED, Hackathon.Status.ARCHIVED]
CONFIGURATION_FIELDS = ('title', 'slug', 'description', 'rules', 'participation_conditions', 'image', 'location', 'format',
    'start_date', 'end_date', 'registration_open', 'registration_close', 'submission_deadline', 'capacity', 'min_team_size', 'max_team_size')


def resource_snapshot(obj):
    return {field.name: str(getattr(obj, field.attname)) for field in obj._meta.concrete_fields}


def record(event, actor, action, target, **details):
    return EventHistory.objects.create(hackathon=event, actor=actor, action=action, target=str(target), details=details)


@transaction.atomic
def create_hackathon(*, actor, event):
    if not can_create_hackathon(actor):
        raise PermissionDenied(_('Autorisation technique de création requise.'))
    event.created_by = actor
    event.status = Hackathon.Status.DRAFT
    event.save()
    assignment = RoleAssignment.objects.create(user=actor, hackathon=event, role=Role.ORGANIZER, assigned_by=actor)
    RoleAssignmentHistory.objects.create(assignment=assignment, actor=actor, status=AssignmentStatus.ACTIVE)
    record(event, actor, 'Création', event)
    return event


@transaction.atomic
def save_configuration(*, actor, event):
    current = Hackathon.objects.select_for_update().get(pk=event.pk)
    require_organizer(actor, current)
    before = resource_snapshot(current)
    for name in CONFIGURATION_FIELDS:
        setattr(current, name, getattr(event, name))
    from teams.models import Registration
    from django.db.models import Count
    if current.registrations.filter(status=Registration.Status.ACCEPTED).count() > current.capacity:
        raise ValidationError(_('La capacité ne peut pas être inférieure au nombre d’inscriptions acceptées.'))
    if current.teams.filter(closed_at__isnull=True).annotate(size=Count('memberships', filter=Q(memberships__ended_at__isnull=True))).filter(size__gt=current.max_team_size).exists():
        raise ValidationError(_('La taille maximale ne peut pas être inférieure à une équipe existante.'))
    current.save()
    record(current, actor, 'Configuration', current, before=before, after=resource_snapshot(current))
    return current


def public_challenges(event):
    return Challenge.objects.filter(track__hackathon=event, track__active=True,
        track__hackathon__status__in=PUBLIC_STATUSES, status=Challenge.Status.PUBLISHED,
        approved_by__isnull=False).exclude(problem='').exclude(objectives='').exclude(deliverables='').filter(
            Q(sponsorship__isnull=True) | Q(sponsorship__status=Sponsorship.Status.CONFIRMED))


def configuration_errors(event):
    errors = []
    try:
        event.full_clean()
    except ValidationError as exc:
        errors.extend(exc.messages)
    required = {EventPhase.Kind.REGISTRATION, EventPhase.Kind.DEVELOPMENT, EventPhase.Kind.SUBMISSION, EventPhase.Kind.EVALUATION}
    missing = required - set(event.phases.values_list('kind', flat=True))
    if missing:
        errors.append(_('Phases manquantes : %(phases)s') % {'phases': ', '.join(str(EventPhase.Kind(kind).label) for kind in sorted(missing))})
    if not event.tracks.filter(active=True).exists():
        errors.append(_('Un track actif est requis.'))
    if not event.tracks.filter(active=True, challenges__status=Challenge.Status.PUBLISHED).exists():
        errors.append(_('Un challenge validé et publié est requis.'))
    return errors


@transaction.atomic
def transition(*, actor, event, target):
    event = Hackathon.objects.select_for_update().get(pk=event.pk)
    require_organizer(actor, event)
    allowed = {
        Hackathon.Status.DRAFT: [Hackathon.Status.PUBLISHED],
        Hackathon.Status.PUBLISHED: [Hackathon.Status.ONGOING, Hackathon.Status.FINISHED],
        Hackathon.Status.ONGOING: [Hackathon.Status.FINISHED],
        Hackathon.Status.FINISHED: [Hackathon.Status.ARCHIVED],
    }
    if target not in allowed.get(event.status, []):
        raise ValidationError(_('Transition de statut interdite.'))
    now = timezone.now()
    if target == Hackathon.Status.PUBLISHED:
        errors = configuration_errors(event)
        if event.end_date <= now:
            errors.append(_('Événement déjà terminé.'))
        if errors:
            raise ValidationError(errors)
    if target == Hackathon.Status.ONGOING and not event.start_date <= now < event.end_date:
        raise ValidationError(_('Le démarrage exige une date dans la période de l’événement.'))
    if target == Hackathon.Status.FINISHED and now < event.end_date:
        raise ValidationError(_('La date de fin n’est pas atteinte.'))
    previous = event.status
    if target == Hackathon.Status.ARCHIVED:
        event.archive_metrics = metrics(event)
        event.archived_at = now
    event.status = target
    event.save()
    record(event, actor, 'Statut', event, previous=previous, status=target)
    return event


def phase_is_open(event, kind, at=None):
    at = at or timezone.now()
    if event.status not in (Hackathon.Status.PUBLISHED, Hackathon.Status.ONGOING):
        return False
    if kind == EventPhase.Kind.REGISTRATION and not event.registration_open <= at < event.registration_close:
        return False
    if kind == EventPhase.Kind.SUBMISSION and at >= event.submission_deadline:
        return False
    return event.phases.filter(kind=kind, start__lte=at, end__gt=at).exists()


def require_open_phase(event, kind, at=None):
    if not phase_is_open(event, kind, at):
        raise ValidationError(_('Cette période est fermée.'))


@transaction.atomic
def save_resource(*, actor, resource, action='Modification'):
    event = Hackathon.objects.select_for_update().get(pk=resource.get_hackathon().pk)
    require_organizer(actor, event)
    before = {}
    if resource.pk:
        original = type(resource).objects.select_for_update().get(pk=resource.pk)
        if original.get_hackathon().pk != event.pk:
            raise PermissionDenied(_('Une ressource ne peut pas changer de hackathon.'))
        before = resource_snapshot(original)
        if isinstance(resource, Sponsorship) and original.organization_id != resource.organization_id:
            raise ValidationError(_('L’organisation d’un partenariat existant ne peut pas changer.'))
    # Lock the parent even when another request changes dates or archives it.
    if hasattr(resource, 'hackathon'):
        resource.hackathon = event
    if isinstance(resource, Challenge):
        resource.track = Track.objects.select_related('hackathon').get(pk=resource.track_id, hackathon=event)
        if resource.sponsorship_id:
            resource.sponsorship = Sponsorship.objects.get(pk=resource.sponsorship_id)
            if resource.sponsorship.hackathon_id != event.pk or resource.sponsorship.status != Sponsorship.Status.CONFIRMED:
                raise ValidationError(_('Un partenariat confirmé du hackathon est requis.'))
        resource.status = Challenge.Status.DRAFT
        resource.approved_by = None
        resource.approved_at = None
    if isinstance(resource, Sponsorship) and resource.status != Sponsorship.Status.CONFIRMED:
        if resource.pk and resource.challenges.filter(status__in=[Challenge.Status.APPROVED, Challenge.Status.PUBLISHED]).exists():
            raise ValidationError(_('Retirez les challenges validés avant de désactiver le partenariat.'))
    resource.save()
    record(event, actor, action, resource, model=resource._meta.label, pk=resource.pk,
        before=before, after=resource_snapshot(resource))
    return resource


@transaction.atomic
def propose_challenge(*, actor, challenge):
    event = Hackathon.objects.select_for_update().get(pk=challenge.track.hackathon_id)
    if event.status == Hackathon.Status.ARCHIVED:
        raise PermissionDenied
    if not has_role(actor, event, Role.SPONSOR_REPRESENTATIVE):
        raise PermissionDenied(_('Rôle représentant sponsor requis dans cet événement.'))
    partnership = Sponsorship.objects.filter(pk=challenge.sponsorship_id, hackathon=event).first()
    if not partnership or partnership.hackathon_id != event.pk or partnership.status != Sponsorship.Status.CONFIRMED:
        raise ValidationError(_('Un partenariat confirmé du hackathon est requis.'))
    if not SponsorMembership.objects.select_for_update().filter(user=actor, organization=partnership.organization,
            status=AssignmentStatus.ACTIVE, can_propose_challenges=True).exists():
        raise PermissionDenied(_('Mandat de représentation actif requis.'))
    challenge.sponsorship = partnership
    challenge.proposed_by = actor
    challenge.approved_by = None
    challenge.approved_at = None
    challenge.status = Challenge.Status.PROPOSED
    challenge.save()
    record(event, actor, 'Proposition sponsor', challenge, pk=challenge.pk)
    return challenge


@transaction.atomic
def review_challenge(*, actor, challenge, action):
    event = Hackathon.objects.select_for_update().get(pk=challenge.track.hackathon_id)
    require_organizer(actor, event)
    challenge = Challenge.objects.select_for_update(of=('self',)).select_related('track__hackathon', 'sponsorship').get(pk=challenge.pk)
    if action == 'approve' and challenge.status in (Challenge.Status.DRAFT, Challenge.Status.PROPOSED):
        challenge.status = Challenge.Status.APPROVED
        challenge.approved_by = actor
        challenge.approved_at = timezone.now()
    elif action == 'publish' and challenge.status == Challenge.Status.APPROVED:
        challenge.status = Challenge.Status.PUBLISHED
    elif action == 'withdraw' and challenge.status in (Challenge.Status.PROPOSED, Challenge.Status.APPROVED, Challenge.Status.PUBLISHED):
        challenge.status = Challenge.Status.WITHDRAWN
    else:
        raise ValidationError(_('Transition de challenge interdite.'))
    challenge.save()
    label = {'approve': 'validation', 'publish': 'publication', 'withdraw': 'retrait'}[action]
    record(event, actor, 'Challenge : ' + label, challenge, pk=challenge.pk)
    return challenge


def metrics(event):
    """Read-only extension contract: providers return named integer counts, or unavailable."""
    result = {
        'tracks': event.tracks.count(),
        'challenges': Challenge.objects.filter(track__hackathon=event).count(),
        'published_challenges': Challenge.objects.filter(track__hackathon=event, status=Challenge.Status.PUBLISHED).count(),
        'sponsors': event.sponsorships.filter(status=Sponsorship.Status.CONFIRMED).count(),
        'participant_roles': event.role_assignments.filter(role=Role.PARTICIPANT, status=AssignmentStatus.ACTIVE).count(),
        'modules': {},
    }
    providers = getattr(settings, 'HACKFLOW_METRIC_PROVIDERS', {})
    for module in ('M2', 'M3', 'M5'):
        item = {'available': False, 'counts': {}}
        if module in providers:
            try:
                counts = import_string(providers[module])(event)
                if not isinstance(counts, dict) or not all(isinstance(k, str) and type(v) is int and v >= 0 for k, v in counts.items()):
                    raise ValueError('Invalid metric contract')
                item = {'available': True, 'counts': counts}
            except Exception:
                item['error'] = _('Indicateurs indisponibles ; vérifier le fournisseur.')
        result['modules'][module] = item
    return result


def operational_alerts(event):
    provider = getattr(settings, 'HACKFLOW_ALERT_PROVIDER', None)
    if not provider:
        return {'available': False, 'items': []}
    try:
        items = import_string(provider)(event)
        if not isinstance(items, list) or not all(isinstance(item, dict)
                and isinstance(item.get('code'), str) and isinstance(item.get('message'), str)
                and item.get('severity') in ('info', 'warning', 'error') for item in items):
            raise ValueError('Invalid alert contract')
        return {'available': True, 'items': items}
    except Exception:
        return {'available': False, 'items': [], 'error': _('Fournisseur d’alertes indisponible.')}


def intelligence_context(*, actor, event):
    """Private read-only inputs for IA1 / IA2. No engine or decisions implemented in M1."""
    require_organizer(actor, event, mutable=False)
    return {
        'version': 1, 'hackathon_id': event.pk,
        'calendar': list(event.phases.values('kind', 'start', 'end')),
        'eligibility': {'conditions': event.participation_conditions, 'capacity': event.capacity,
            'min_team_size': event.min_team_size, 'max_team_size': event.max_team_size},
        'challenges': list(public_challenges(event).values('id', 'track_id', 'title', 'problem', 'objectives', 'deliverables', 'participation_conditions')),
        'tracks': list(event.tracks.filter(active=True).values('id', 'name', 'description')),
    }
