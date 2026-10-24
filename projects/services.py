"""M3 operations serialize with M2: actor, event, then project. No external AI calls."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext as _
from accounts.models import User
from accounts.permissions import can_manage
from hackathons.models import Hackathon, Challenge, EventPhase
from hackathons.services import phase_is_open
from teams import services as teams
from teams.models import Team
from .models import Project, Milestone, Submission, Deliverable, ProjectActivity
from .validators import validate_link, validate_commit, inspect_upload


def is_member(actor, project):
    return bool(actor.is_authenticated and actor.is_active and project.team.closed_at is None and
        teams.active_members(project.team).filter(registration__user=actor).exists())


def can_read(actor, project):
    return is_member(actor, project) or can_manage(actor, project.team.hackathon)


def require_reader(actor, project):
    if not can_read(actor, project):
        raise PermissionDenied


def can_submit(actor, project):
    return is_member(actor, project) and teams.is_captain(actor, project.team)


def editing_open(project):
    if project.official_submission_id or project.team.hackathon.status not in ('PUBLISHED', 'ONGOING'):
        return False
    try:
        _window(project.team.hackathon, project)
    except ValidationError:
        return False
    return True


def can_manage_drafts(actor, project):
    if not can_submit(actor, project) or project.team.hackathon.status not in ('PUBLISHED', 'ONGOING'):
        return False
    try:
        _window(project.team.hackathon, project)
    except ValidationError:
        return False
    return True


def gallery():
    return Project.objects.filter(published=True, public_requested=True, official_submission__status='OFFICIAL',
        team__hackathon__status__in=['PUBLISHED', 'ONGOING', 'FINISHED', 'ARCHIVED']).select_related('official_submission', 'team__hackathon')


def _lock(actor, team, project=None):
    if project is not None and project.team_id != team.pk:
        raise PermissionDenied
    user = User.objects.select_for_update(no_key=True).filter(pk=actor.pk, is_active=True).first()
    if not user:
        raise PermissionDenied
    event = Hackathon.objects.select_for_update().get(pk=team.hackathon_id)
    if event.status not in (Hackathon.Status.PUBLISHED, Hackathon.Status.ONGOING):
        raise ValidationError(_('Cette édition est en consultation uniquement.'))
    team = Team.objects.select_related('hackathon', 'captain').get(pk=team.pk)
    project = Project.objects.select_for_update(of=('self',)).select_related('challenge__track', 'official_submission').get(pk=project.pk, team=team) if project else None
    if project:
        project.team = team
    return user, event, team, project


def _editor(actor, project):
    if not is_member(actor, project):
        raise PermissionDenied


def _window(event, project=None):
    now = timezone.now()
    if project and project.exception_until and now < project.exception_until:
        return
    if not (phase_is_open(event, EventPhase.Kind.DEVELOPMENT, now) or phase_is_open(event, EventPhase.Kind.SUBMISSION, now)) or now >= event.submission_deadline:
        raise ValidationError(_('Le développement et les dépôts sont fermés.'))


def _draft(actor, project, submission):
    _editor(actor, project)
    _window(project.team.hackathon, project)
    if project.official_submission_id:
        raise ValidationError(_('Une réouverture par l’organisateur est requise.'))
    submission = Submission.objects.get(pk=submission.pk, project=project)
    if submission.status != Submission.Status.DRAFT:
        raise ValidationError(_('Cette version est figée. Créez une nouvelle version.'))
    return submission


def _log(project, actor, action, **details):
    ProjectActivity.objects.create(project=project, actor=actor, action=action, details=details)


@transaction.atomic
def save_project(*, actor, team, data, project=None):
    actor, event, team, existing = _lock(actor, team, project)
    project = existing or Project(team=team)
    _editor(actor, project)
    _window(event, project)
    if project.official_submission_id:
        raise ValidationError(_('La fiche officielle est figée. Demandez une réouverture.'))
    if not teams.team_is_ready(team):
        raise ValidationError(_('Une équipe valide est requise.'))
    allowed = {'challenge', 'title', 'problem', 'solution', 'stack', 'pitch', 'status'}
    for key in allowed:
        if key in data:
            setattr(project, key, data[key])
    if not Challenge.objects.filter(pk=project.challenge_id, track__hackathon=event, track__active=True, status='PUBLISHED').exists():
        raise ValidationError(_('Choisissez un challenge publié de cette édition.'))
    project.full_clean()
    project.save()
    _log(project, actor, 'UPDATE_PROJECT' if existing else 'CREATE_PROJECT')
    return project


@transaction.atomic
def save_milestone(*, actor, project, data, milestone=None, delete=False):
    actor, event, team, project = _lock(actor, project.team, project)
    _editor(actor, project)
    _window(event, project)
    if project.official_submission_id:
        raise ValidationError(_('La progression officielle est figée.'))
    milestone = Milestone.objects.get(pk=milestone.pk, project=project) if milestone else Milestone(project=project)
    if delete:
        _log(project, actor, 'DELETE_MILESTONE', title=milestone.title)
        milestone.delete()
        return
    for key in ('title', 'due_at', 'progress'):
        setattr(milestone, key, data[key])
    limit = max(event.submission_deadline, project.exception_until or event.submission_deadline)
    if not event.start_date <= milestone.due_at <= limit:
        raise ValidationError(_('L’échéance doit être comprise entre le début et la limite de dépôt.'))
    milestone.full_clean()
    milestone.save()
    _log(project, actor, 'SAVE_MILESTONE', milestone=milestone.pk, state=milestone.state, progress=milestone.progress)
    return milestone


def project_snapshot(project):
    return {**{key: getattr(project, key) for key in ('title', 'problem', 'solution', 'stack', 'pitch', 'status')},
        'team': project.team.name, 'challenge_id': project.challenge_id, 'challenge': project.challenge.title,
        'requirements': project.challenge.deliverables, 'progress': project.progress}


@transaction.atomic
def create_version(*, actor, project):
    actor, event, team, project = _lock(actor, project.team, project)
    _editor(actor, project)
    _window(event, project)
    if project.official_submission_id:
        raise ValidationError(_('Une réouverture est requise avant une nouvelle version.'))
    version = (project.submissions.aggregate(value=Max('version'))['value'] or 0) + 1
    submission = Submission.objects.create(project=project, version=version, created_by=actor, snapshot=project_snapshot(project))
    _log(project, actor, 'CREATE_VERSION', version=version)
    return submission


@transaction.atomic
def manage_draft(*, actor, submission, restore=False):
    actor, event, team, project = _lock(actor, submission.project.team, submission.project)
    if not can_submit(actor, project):
        raise PermissionDenied
    _window(event, project)
    submission = Submission.objects.get(pk=submission.pk, project=project)
    expected = Submission.Status.DISCARDED if restore else Submission.Status.DRAFT
    if submission.status != expected or submission.pk == project.official_submission_id:
        raise ValidationError(_('Seuls les brouillons peuvent être supprimés ou restaurés.'))
    submission.status = Submission.Status.DRAFT if restore else Submission.Status.DISCARDED
    submission.save(update_fields=['status'])
    _log(project, actor, 'RESTORE_VERSION' if restore else 'DISCARD_VERSION', version=submission.version)
    return submission


@transaction.atomic
def save_deliverable(*, actor, submission, kind, url='', file=None, commit='', deliverable=None, delete=False):
    actor, event, team, project = _lock(actor, submission.project.team, submission.project)
    submission = _draft(actor, project, submission)
    record = Deliverable.objects.get(pk=deliverable.pk, submission=submission) if deliverable else Deliverable(submission=submission)
    if delete:
        _log(project, actor, 'DELETE_DELIVERABLE', version=submission.version, kind=record.kind)
        record.delete()  # Stored blobs are retained; storage cleanup is a separate operation.
        return
    if url:
        validate_link(url)
    if kind == Deliverable.Kind.REPOSITORY:
        validate_commit(commit)
    metadata = inspect_upload(file) if file else {}
    if file and record.file and getattr(file, '_committed', False) and file.name == record.file.name:
        metadata['original_name'] = record.metadata.get('original_name', metadata['original_name'])
    record.kind, record.url, record.file, record.commit, record.metadata = kind, url, file or '', commit.lower(), metadata
    record.full_clean()
    record.save()
    _log(project, actor, 'SAVE_DELIVERABLE', version=submission.version, kind=kind)
    return record


@transaction.atomic
def submit(*, actor, submission, confirm_requirements):
    actor, event, team, project = _lock(actor, submission.project.team, submission.project)
    submission = _draft(actor, project, submission)
    if not can_submit(actor, project):
        raise PermissionDenied(_('Seul le capitaine actif peut officialiser le dépôt.'))
    now = timezone.now()
    if not (project.exception_until and now < project.exception_until) and not phase_is_open(event, EventPhase.Kind.SUBMISSION, now):
        raise ValidationError(_('La période de soumission est fermée.'))
    if not teams.team_is_ready(team):
        raise ValidationError(_('L’équipe doit être valide au moment du dépôt.'))
    if not Challenge.objects.filter(pk=project.challenge_id, track__hackathon=event, track__active=True, status='PUBLISHED').exists():
        raise ValidationError(_('Choisissez un challenge publié de cette édition.'))
    records = list(submission.deliverables.all())
    if not confirm_requirements or not any(r.kind == 'REPOSITORY' for r in records):
        raise ValidationError(_('Ajoutez le dépôt avec son commit et confirmez les exigences du challenge.'))
    for record in records:
        record.full_clean()
        if record.url:
            validate_link(record.url)
        if record.kind == 'REPOSITORY':
            validate_commit(record.commit)
    submission.snapshot = project_snapshot(project)
    submission.snapshot['deliverables'] = [{'id': r.pk, 'kind': r.kind, 'url': r.url, 'commit': r.commit, 'file': r.file.name, 'metadata': r.metadata} for r in records]
    submission.requirements_confirmed = True
    submission.status, submission.submitted_at = Submission.Status.OFFICIAL, now
    submission.save()
    project.official_submission = submission
    project.exception_until = None
    project.published = False
    project.full_clean()
    project.save()
    _log(project, actor, 'SUBMIT', version=submission.version)
    return submission


@transaction.atomic
def reopen(*, actor, project, reason, until):
    actor, event, team, project = _lock(actor, project.team, project)
    if not can_manage(actor, event):
        raise PermissionDenied
    if not reason.strip() or not timezone.now() < until <= event.end_date:
        raise ValidationError(_('Une justification et une limite future avant la fin sont requises.'))
    previous = project.official_submission_id
    project.official_submission = None
    project.exception_until = until
    project.published = project.public_requested = False
    project.save()
    _log(project, actor, 'REOPEN', reason=reason.strip(), until=until.isoformat(), previous_submission=previous)


@transaction.atomic
def publication(*, actor, project, action):
    # Publication remains possible after the event, but archives stay immutable.
    if not User.objects.select_for_update(no_key=True).filter(pk=actor.pk, is_active=True).exists():
        raise PermissionDenied
    event = Hackathon.objects.select_for_update().get(pk=project.team.hackathon_id)
    project = Project.objects.select_for_update(of=('self',)).select_related('team__hackathon', 'team__captain').get(pk=project.pk)
    if event.status in ('DRAFT', 'ARCHIVED'):
        raise ValidationError(_('Cette édition est en consultation uniquement.'))
    if action in ('request', 'withdraw'):
        if not can_submit(actor, project):
            raise PermissionDenied
        if action == 'request' and not project.official_submission_id:
            raise ValidationError(_('Une soumission officielle est requise.'))
        project.public_requested = action == 'request'
        if action == 'withdraw':
            project.published = False
    elif action in ('publish', 'unpublish'):
        if not can_manage(actor, event):
            raise PermissionDenied
        project.published = action == 'publish'
    else:
        raise ValidationError(_('Action inconnue.'))
    project.full_clean()
    project.save()
    _log(project, actor, 'PUBLICATION', action_taken=action)


def official_submission(*, actor, project):
    """M5 contract: caller must enforce JuryAssignment before calling as organizer.

    Unassigned jurors get no blanket access. M5 can consume the FK internally
    after its own assignment/conflict authorization; public views use snapshots.
    """
    current = Project.objects.select_related('team__hackathon', 'official_submission').get(pk=project.pk)
    require_reader(actor, current)
    return current.official_submission


def copilot_input(*, actor, project):
    require_reader(actor, project)
    return {'schema_version': 1, 'project_id': project.pk, 'content': project_snapshot(project)}


def metrics(event):
    projects = Project.objects.filter(team__hackathon=event)
    total = projects.count()
    official = projects.filter(official_submission__isnull=False).count()
    return {'projects': total, 'official_submissions': official, 'missing_submissions': total - official, 'published_projects': projects.filter(published=True).count()}
