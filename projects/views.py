from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Avg, Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST
from accounts.permissions import can_manage
from teams import services as teams
from teams.models import Team
from . import services
from .forms import ProjectForm, MilestoneForm, DeliverableForm, SubmitForm, ReopenForm
from .models import Project, Submission, Deliverable, Milestone


def _project(request, pk):
    project = get_object_or_404(Project.objects.select_related('team__hackathon', 'team__captain', 'challenge__track', 'official_submission'), pk=pk)
    services.require_reader(request.user, project)
    return project


def _context(request, project):
    event = project.team.hackathon
    return {'project': project, 'team': project.team, 'event': event,
        'editor': services.is_member(request.user, project), 'captain': services.can_submit(request.user, project),
        'editable': services.is_member(request.user, project) and services.editing_open(project),
        'organizer': can_manage(request.user, event)}


def _error(form, exc):
    form.add_error(None, ' '.join(exc.messages) if isinstance(exc, ValidationError) else _('Les données ont changé. Actualisez et réessayez.'))


def _form(request, form, title, project=None, **extra):
    return render(request, 'projects/form.html', {**(_context(request, project) if project else {}), 'form': form, 'title': title, **extra})


@login_required
def mine(request):
    projects = Project.objects.filter(team__memberships__registration__user=request.user,
        team__memberships__ended_at__isnull=True, team__memberships__registration__status='ACCEPTED', team__closed_at__isnull=True)
    managed = Project.objects.filter(team__hackathon__role_assignments__user=request.user,
        team__hackathon__role_assignments__role='ORGANIZER', team__hackathon__role_assignments__status='ACTIVE')
    projects = Project.objects.all() if request.user.is_superuser else (projects | managed).distinct()
    counts = projects.aggregate(total=Count('pk', distinct=True), submitted=Count('pk', filter=Q(official_submission__isnull=False), distinct=True),
        published=Count('pk', filter=Q(published=True), distinct=True))
    counts['working'] = counts['total'] - counts['submitted']
    status = request.GET.get('status', 'all')
    if status not in ('all', 'working', 'submitted', 'published'):
        status = 'all'
    if status == 'working':
        projects = projects.filter(official_submission__isnull=True)
    elif status == 'submitted':
        projects = projects.filter(official_submission__isnull=False)
    elif status == 'published':
        projects = projects.filter(published=True)
    query = request.GET.get('q', '').strip()[:200]
    if query:
        projects = projects.filter(Q(title__icontains=query) | Q(team__name__icontains=query) | Q(team__hackathon__title__icontains=query))
    projects = projects.select_related('team__hackathon', 'official_submission').annotate(
        average_progress=Avg('milestones__progress'), milestone_total=Count('milestones', distinct=True),
        milestone_done=Count('milestones', filter=Q(milestones__state=Milestone.State.DONE), distinct=True),
        version_total=Count('submissions', distinct=True)).order_by('-updated_at', 'pk')
    page = Paginator(projects, 24).get_page(request.GET.get('page'))
    for item in page:
        item.list_progress = round(item.average_progress or 0)
    available_teams = Team.objects.filter(memberships__registration__user=request.user, memberships__ended_at__isnull=True,
        memberships__registration__status='ACCEPTED', closed_at__isnull=True, project__isnull=True).select_related('hackathon')
    pagination = request.GET.copy()
    pagination.pop('page', None)
    return render(request, 'projects/mine.html', {'projects': page, 'available_teams': available_teams,
        'counts': counts, 'status_filter': status, 'search_query': query, 'pagination_query': pagination.urlencode()})


@login_required
@require_http_methods(['GET', 'POST'])
def edit(request, pk=None, team_pk=None):
    project = _project(request, pk) if pk else None
    team = project.team if project else get_object_or_404(Team.objects.select_related('hackathon'), pk=team_pk)
    probe = project or Project(team=team)
    if not services.is_member(request.user, probe):
        raise PermissionDenied
    form = ProjectForm(request.POST if request.method == 'POST' else None, instance=project, team=team)
    if request.method == 'POST' and form.is_valid():
        try:
            saved = services.save_project(actor=request.user, team=team, data=form.cleaned_data, project=project)
        except (ValidationError, IntegrityError) as exc:
            _error(form, exc)
        else:
            return redirect(saved)
    return _form(request, form, _('Modifier le projet') if project else _('Créer le projet'), project, team=team, event=team.hackathon)


@login_required
def detail(request, pk):
    project = _project(request, pk)
    milestones = list(project.milestones.all())
    for item in milestones:
        item.overdue = item.state != Milestone.State.DONE and item.due_at < timezone.now()
    return render(request, 'projects/detail.html', {**_context(request, project),
        'columns': [{'state': state, 'label': label, 'items': [item for item in milestones if item.state == state]}
            for state, label in Milestone.State.choices],
        'milestone_count': len(milestones),
        'completed_count': sum(item.state == Milestone.State.DONE for item in milestones),
        'submissions': project.submissions.all(), 'activities': project.activities.select_related('actor')[:30]})


@login_required
@require_http_methods(['GET', 'POST'])
def milestone(request, pk, milestone_pk=None):
    project = _project(request, pk)
    if not services.is_member(request.user, project):
        raise PermissionDenied
    record = get_object_or_404(Milestone, project=project, pk=milestone_pk) if milestone_pk else None
    initial = {'progress': {'TODO': 0, 'DOING': 1, 'DONE': 100}.get(request.GET.get('state'), 0)} if not record else {}
    form = MilestoneForm(request.POST if request.method == 'POST' else None, instance=record, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            services.save_milestone(actor=request.user, project=project, data=form.cleaned_data, milestone=record)
        except ValidationError as exc:
            _error(form, exc)
        else:
            return redirect(project)
    return _form(request, form, _('Modifier une étape') if record else _('Planifier une étape'), project)


@login_required
@require_POST
def milestone_delete(request, pk, milestone_pk):
    project = _project(request, pk)
    record = get_object_or_404(Milestone, project=project, pk=milestone_pk)
    try:
        services.save_milestone(actor=request.user, project=project, milestone=record, data={}, delete=True)
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    return redirect(project)


@login_required
@require_POST
def version_create(request, pk):
    project = _project(request, pk)
    try:
        submission = services.create_version(actor=request.user, project=project)
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
        return redirect(project)
    return redirect('projects:version', pk=pk, version=submission.version)


@login_required
@require_http_methods(['GET', 'POST'])
def version(request, pk, version):
    project = _project(request, pk)
    submission = get_object_or_404(Submission, project=project, version=version)
    deliverables = list(submission.deliverables.all())
    saved_kinds = {record.kind for record in deliverables}
    next_kind = next((kind for kind in Deliverable.Kind.values if kind not in saved_kinds), Deliverable.Kind.REPOSITORY)
    form = DeliverableForm(request.POST if request.method == 'POST' else None, request.FILES if request.method == 'POST' else None,
        initial={'kind': next_kind})
    if request.method == 'POST' and form.is_valid():
        try:
            services.save_deliverable(actor=request.user, submission=submission, **form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            _error(form, exc)
        else:
            messages.success(request, _('Livrable enregistré dans la version %(version)s. Cette version reste un brouillon.') % {'version': version})
            return redirect('projects:version', pk=pk, version=version)
    return render(request, 'projects/version.html', {**_context(request, project), 'submission': submission,
        'form': form, 'submit_form': SubmitForm(), 'deliverables': deliverables,
        'has_repository': any(record.kind == Deliverable.Kind.REPOSITORY for record in deliverables),
        'versions': project.submissions.annotate(deliverable_count=Count('deliverables'))})


@login_required
@require_POST
def deliverable_delete(request, pk, version, deliverable_pk):
    project = _project(request, pk)
    submission = get_object_or_404(Submission, project=project, version=version)
    record = get_object_or_404(Deliverable, submission=submission, pk=deliverable_pk)
    try:
        services.save_deliverable(actor=request.user, submission=submission, deliverable=record, kind=record.kind, delete=True)
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    return redirect('projects:version', pk=pk, version=version)


@login_required
@require_http_methods(['GET', 'POST'])
def deliverable_edit(request, pk, version, deliverable_pk):
    project = _project(request, pk)
    if not services.is_member(request.user, project):
        raise PermissionDenied
    submission = get_object_or_404(Submission, project=project, version=version)
    record = get_object_or_404(Deliverable, submission=submission, pk=deliverable_pk)
    form = DeliverableForm(request.POST if request.method == 'POST' else None,
        request.FILES if request.method == 'POST' else None,
        initial={'kind': record.kind, 'url': record.url, 'commit': record.commit})
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data.copy()
        if record.file and not data['file'] and not data['url']:
            data['file'] = record.file
        try:
            services.save_deliverable(actor=request.user, submission=submission, deliverable=record, **data)
        except (ValidationError, IntegrityError) as exc:
            _error(form, exc)
        else:
            return redirect('projects:version', pk=pk, version=version)
    return _form(request, form, _('Modifier un livrable'), project)


@login_required
@require_POST
def submit(request, pk, version):
    project = _project(request, pk)
    submission = get_object_or_404(Submission, project=project, version=version)
    form = SubmitForm(request.POST)
    if form.is_valid():
        try:
            services.submit(actor=request.user, submission=submission, **form.cleaned_data)
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(request, _('Version officielle enregistrée et figée.'))
            return redirect(project)
    return _form(request, form, _('Officialiser cette version'), project)


@login_required
@require_http_methods(['GET', 'POST'])
def reopen(request, pk):
    project = _project(request, pk)
    if not can_manage(request.user, project.team.hackathon):
        raise PermissionDenied
    form = ReopenForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            services.reopen(actor=request.user, project=project, **form.cleaned_data)
        except ValidationError as exc:
            _error(form, exc)
        else:
            return redirect(project)
    return _form(request, form, _('Réouvrir les dépôts avec dérogation'), project)


@login_required
@require_POST
def publication(request, pk, action):
    project = _project(request, pk)
    try:
        services.publication(actor=request.user, project=project, action=action)
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    return redirect(project)


def gallery(request):
    projects = services.gallery().order_by('-official_submission__submitted_at')
    public_total = projects.count()
    events = list(projects.order_by('team__hackathon__title').values_list('team__hackathon__slug', 'team__hackathon__title').distinct())
    query = request.GET.get('q', '').strip()[:200]
    event_filter = request.GET.get('event', '')[:220]
    if query:
        # Search only the approved frozen content, never private live fields.
        projects = projects.filter(Q(official_submission__snapshot__title__icontains=query) |
            Q(official_submission__snapshot__solution__icontains=query) | Q(official_submission__snapshot__stack__icontains=query) |
            Q(official_submission__snapshot__team__icontains=query))
    if event_filter:
        projects = projects.filter(team__hackathon__slug=event_filter)
    page = Paginator(projects, 24).get_page(request.GET.get('page'))
    for item in page:
        snapshot = item.official_submission.snapshot
        item.gallery_stack = [part.strip() for part in snapshot.get('stack', '').split(',') if part.strip()][:4]
    pagination = request.GET.copy()
    pagination.pop('page', None)
    return render(request, 'projects/gallery.html', {'projects': page, 'public_total': public_total,
        'event_options': events, 'event_filter': event_filter, 'search_query': query, 'pagination_query': pagination.urlencode()})


def public_detail(request, pk):
    project = get_object_or_404(services.gallery(), pk=pk)
    return render(request, 'projects/public.html', {'project': project, 'snapshot': project.official_submission.snapshot, 'deliverables': project.official_submission.deliverables.all()})


def download(request, deliverable_pk):
    record = get_object_or_404(Deliverable.objects.select_related('submission__project__team__hackathon', 'submission__project__team__captain'), pk=deliverable_pk)
    project = record.submission.project
    public = record.submission_id == project.official_submission_id and services.gallery().filter(pk=project.pk).exists()
    if not public and not services.can_read(request.user, project):
        raise PermissionDenied
    if not record.file:
        raise Http404
    try:
        response = FileResponse(record.file.open('rb'), as_attachment=True, filename=record.metadata.get('original_name', 'deliverable'))
    except FileNotFoundError:
        raise Http404 from None
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response
