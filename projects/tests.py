from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch
from io import StringIO
from django.core.management import call_command
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction, connection, close_old_connections
from django.template.loader import get_template
from django.test import TestCase, TransactionTestCase, SimpleTestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from hackathons.models import Hackathon
from hackathons.test_helpers import make_event
from teams.tests import SetupMixin
from teams import services as teams
from . import services
from .models import Project, Milestone, Submission, Deliverable
from .validators import validate_link, validate_commit, inspect_upload


class ValidationTests(SimpleTestCase):
    def test_repository_form_requires_url_and_full_commit(self):
        from .forms import DeliverableForm
        form = DeliverableForm({'kind': 'REPOSITORY', 'url': 'https://github.com/example/project', 'commit': 'be25f45'})
        self.assertFalse(form.is_valid())
        self.assertIn('commit', form.errors)
        self.assertTrue(form.fields['url'].required)
        self.assertTrue(form.fields['commit'].required)
        form = DeliverableForm({'kind': 'DEMO', 'url': 'https://example.com/demo'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.fields['commit'].required)

    def test_public_https_only(self):
        validate_link('https://github.com/example/project')
        for value in ['http://example.com', 'https://localhost', 'https://127.0.0.1/a', 'https://[::1]/', 'https://user:pass@example.com', 'https://example.com:8443/a', 'https://service.internal']:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_link(value)

    def test_commit_and_upload_validation(self):
        validate_commit('a' * 40)
        with self.assertRaises(ValidationError):
            validate_commit('main')
        metadata = inspect_upload(SimpleUploadedFile('slides.pdf', b'%PDF-1.7\nexample'))
        self.assertEqual(metadata['size'], 16)
        self.assertEqual(len(metadata['sha256']), 64)
        for name, content in [('evil.html', b'<script>'), ('fake.pdf', b'<html>'), ('empty.pdf', b'')]:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                inspect_upload(SimpleUploadedFile(name, content))
        huge = SimpleUploadedFile('huge.pdf', b'%PDF-')
        huge.size = 21 * 1024 * 1024
        with self.assertRaises(ValidationError):
            inspect_upload(huge)

    def test_templates_compile(self):
        for name in ['shell', 'form', 'mine', 'detail', 'version', 'gallery', 'public', 'deliverables', 'pagination']:
            get_template(f'projects/{name}.html')


class ProjectSetup(SetupMixin):
    def setUp(self):
        super().setUp()
        self.nova = self.team()
        reg = self.reg(self.b)
        invite = teams.recruit(actor=self.a, team=self.nova, registration=reg)
        teams.decide(actor=self.b, record=invite, decision='ACCEPTED')
        self.data = {'challenge': self.event.tracks.get().challenges.get(), 'title': 'Campus Care',
            'problem': 'Students need help', 'solution': 'Shared support', 'stack': 'Django', 'pitch': 'Help together', 'status': 'BUILDING'}
        self.at = self.event.start_date + timedelta(hours=2)
        self.time_patch = patch('projects.services.timezone.now', return_value=self.at)
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)
        self.storage = TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        self.settings_override = override_settings(PROJECT_FILES_ROOT=self.storage.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def project(self):
        return services.save_project(actor=self.a, team=self.nova, data=self.data)

    def version(self, project):
        return services.create_version(actor=self.a, project=project)

    def repo(self, submission):
        return services.save_deliverable(actor=self.a, submission=submission, kind='REPOSITORY',
            url='https://github.com/example/campus-care', commit='a' * 40)

    def official(self, project):
        version = self.version(project)
        self.repo(version)
        services.submit(actor=self.a, submission=version, confirm_requirements=True)
        version.refresh_from_db()
        project.refresh_from_db()
        return version


class ProjectFlowTests(ProjectSetup, TestCase):
    def test_live_board_moves_keep_official_snapshot_frozen(self):
        project = self.project()
        milestone = services.save_milestone(actor=self.a, project=project, data={
            'title': 'Build UI', 'due_at': self.at+timedelta(hours=1), 'progress': 25})
        official = self.official(project)
        snapshot = official.snapshot.copy()
        for state, progress in [('DONE', 100), ('DOING', 1), ('TODO', 0)]:
            moved = services.move_milestone(actor=self.b, project=project, milestone=milestone, state=state)
            self.assertEqual((moved.state, moved.progress), (state, progress))
        official.refresh_from_db()
        self.assertEqual(official.snapshot, snapshot)
        self.assertEqual(official.snapshot['progress'], 25)
        self.assertEqual(project.activities.filter(action='MOVE_MILESTONE').count(), 3)
        with self.assertRaises(ValidationError):
            services.save_project(actor=self.a, team=self.nova, project=project, data=self.data)

    def test_board_moves_reject_invalid_unauthorized_and_closed_actions(self):
        project = self.project()
        milestone = services.save_milestone(actor=self.a, project=project, data={
            'title': 'API', 'due_at': self.at+timedelta(hours=1), 'progress': 30})
        for actor in (self.c, self.owner):
            with self.assertRaises(PermissionDenied):
                services.move_milestone(actor=actor, project=project, milestone=milestone, state='DONE')
        with self.assertRaises(ValidationError):
            services.move_milestone(actor=self.a, project=project, milestone=milestone, state='INVALID')
        moved = services.move_milestone(actor=self.a, project=project, milestone=milestone, state='DOING')
        self.assertEqual(moved.progress, 30)
        self.assertFalse(project.activities.filter(action='MOVE_MILESTONE').exists())
        with patch('projects.services.timezone.now', return_value=self.event.submission_deadline):
            with self.assertRaises(ValidationError):
                services.move_milestone(actor=self.a, project=project, milestone=milestone, state='DONE')
        Hackathon.objects.filter(pk=self.event.pk).update(status='ARCHIVED')
        with self.assertRaises(ValidationError):
            services.move_milestone(actor=self.a, project=project, milestone=milestone, state='DONE')
        milestone.refresh_from_db()
        self.assertEqual(milestone.progress, 30)

    def test_discard_restore_preserves_deliverables_and_version_numbers(self):
        project = self.project()
        first = self.version(project)
        repository = self.repo(first)
        for actor in (self.b, self.c):
            with self.assertRaises(PermissionDenied):
                services.manage_draft(actor=actor, submission=first)
        services.manage_draft(actor=self.a, submission=first)
        first.refresh_from_db()
        self.assertEqual(first.status, 'DISCARDED')
        self.assertTrue(Deliverable.objects.filter(pk=repository.pk).exists())
        with self.assertRaises(ValidationError):
            services.save_deliverable(actor=self.a, submission=first, kind='DEMO', url='https://example.com')
        second = self.version(project)
        self.assertEqual(second.version, 2)
        services.manage_draft(actor=self.a, submission=first, restore=True)
        first.refresh_from_db()
        self.assertEqual(first.status, 'DRAFT')
        self.assertEqual(first.deliverables.get().commit, 'a'*40)
        self.repo(second)
        services.submit(actor=self.a, submission=second, confirm_requirements=True)
        with self.assertRaises(ValidationError):
            services.manage_draft(actor=self.a, submission=second)
        services.manage_draft(actor=self.a, submission=first)
        project.refresh_from_db()
        self.assertEqual(project.official_submission_id, second.pk)
        self.assertEqual(project.activities.filter(action='DISCARD_VERSION').count(), 2)

    def test_official_models_reject_direct_edits(self):
        project = self.project()
        version = self.official(project)
        version.snapshot = {'title': 'Tampered'}
        with self.assertRaises(ValidationError):
            version.save()
        record = version.deliverables.get()
        record.url = 'https://example.com/tampered'
        with self.assertRaises(ValidationError):
            record.save()
        with self.assertRaises(ValidationError):
            record.delete()
        with self.assertRaises(ValidationError):
            Deliverable.objects.create(submission=version, kind='DEMO', url='https://example.com')

    def test_withdrawn_challenge_cannot_be_submitted(self):
        project = self.project()
        version = self.version(project)
        self.repo(version)
        challenge = self.data['challenge']
        type(challenge).objects.filter(pk=challenge.pk).update(status='WITHDRAWN')
        with self.assertRaises(ValidationError):
            services.submit(actor=self.a, submission=version, confirm_requirements=True)

    def test_exception_expires_at_exact_limit(self):
        project = self.project()
        version = self.version(project)
        self.repo(version)
        until = self.event.submission_deadline + timedelta(hours=1)
        services.reopen(actor=self.owner, project=project, reason='Approved outage', until=until)
        with patch('projects.services.timezone.now', return_value=until):
            with self.assertRaises(ValidationError):
                services.submit(actor=self.a, submission=version, confirm_requirements=True)

    def test_creation_permissions_readiness_and_uniqueness(self):
        with self.assertRaises(PermissionDenied):
            services.save_project(actor=self.c, team=self.nova, data=self.data)
        with self.assertRaises(PermissionDenied):
            services.save_project(actor=self.owner, team=self.nova, data=self.data)
        project = self.project()
        self.assertEqual(project.team, self.nova)
        with self.assertRaises(ValidationError):
            self.project()
        other = make_event(self.owner, slug='other', complete=True)
        with self.assertRaises(ValidationError):
            services.save_project(actor=self.a, team=self.nova, project=project,
                data={**self.data, 'challenge': other.tracks.get().challenges.get()})
        with self.assertRaises(PermissionDenied):
            services.save_project(actor=self.c, team=self.nova, project=project, data=self.data)

    def test_incomplete_team_and_unpublished_challenge(self):
        self.event.min_team_size = 3
        self.event.save()
        with self.assertRaises(ValidationError):
            self.project()
        self.event.min_team_size = 2
        self.event.save()
        challenge = self.data['challenge']
        type(challenge).objects.filter(pk=challenge.pk).update(status='WITHDRAWN')
        with self.assertRaises(ValidationError):
            self.project()

    def test_milestone_kanban_progress_and_delete(self):
        project = self.project()
        data = {'title': 'Prototype', 'due_at': self.at + timedelta(hours=1), 'state': 'DONE', 'progress': 100}
        milestone = services.save_milestone(actor=self.b, project=project, data=data)
        services.save_milestone(actor=self.a, project=project, data={**data, 'title': 'MVP', 'state': 'DOING', 'progress': 20})
        self.assertEqual(project.progress, 60)
        updated = services.save_milestone(actor=self.a, project=project, milestone=milestone, data={**data, 'progress': 50})
        self.assertEqual(updated.state, 'DOING')
        with self.assertRaises(ValidationError):
            services.save_milestone(actor=self.a, project=project, data={**data, 'due_at': self.event.end_date})
        services.save_milestone(actor=self.b, project=project, milestone=milestone, data={}, delete=True)
        self.assertEqual(project.progress, 20)

    def test_official_is_frozen_and_previous_versions_retained(self):
        project = self.project()
        old = self.version(project)
        current = self.version(project)
        self.repo(current)
        with self.assertRaises(PermissionDenied):
            services.submit(actor=self.b, submission=current, confirm_requirements=True)
        services.submit(actor=self.a, submission=current, confirm_requirements=True)
        current.refresh_from_db()
        self.assertEqual(current.snapshot['title'], 'Campus Care')
        self.assertEqual(current.snapshot['deliverables'][0]['commit'], 'a'*40)
        with self.assertRaises(ValidationError):
            services.save_deliverable(actor=self.a, submission=current, kind='DEMO', url='https://example.com')
        with self.assertRaises(ValidationError):
            services.save_project(actor=self.a, team=self.nova, project=project, data={**self.data, 'title': 'New'})
        with self.assertRaises(ValidationError):
            services.create_version(actor=self.a, project=project)
        self.assertTrue(Submission.objects.filter(pk=old.pk).exists())

    def test_required_repository_commit_and_attestation(self):
        project = self.project()
        version = self.version(project)
        with self.assertRaises(ValidationError):
            services.submit(actor=self.a, submission=version, confirm_requirements=True)
        with self.assertRaises(ValidationError):
            services.save_deliverable(actor=self.a, submission=version, kind='REPOSITORY', url='https://github.com/example/repo', commit='main')
        self.repo(version)
        with self.assertRaises(ValidationError):
            services.submit(actor=self.a, submission=version, confirm_requirements=False)

    def test_deadline_exact_boundary_and_traced_exception(self):
        project = self.project()
        version = self.version(project)
        self.repo(version)
        with patch('projects.services.timezone.now', return_value=self.event.submission_deadline):
            with self.assertRaises(ValidationError):
                services.submit(actor=self.a, submission=version, confirm_requirements=True)
            with self.assertRaises(PermissionDenied):
                services.reopen(actor=self.a, project=project, reason='Late', until=self.event.end_date)
            services.reopen(actor=self.owner, project=project, reason='Network outage', until=self.event.end_date)
            services.submit(actor=self.a, submission=version, confirm_requirements=True)
        self.assertEqual(project.activities.get(action='REOPEN').details['reason'], 'Network outage')

    def test_replacement_preserves_frozen_previous_official(self):
        project = self.project()
        old = self.official(project)
        services.reopen(actor=self.owner, project=project, reason='Approved correction', until=self.event.end_date)
        services.save_project(actor=self.a, team=self.nova, project=project, data={**self.data, 'title': 'Campus Care 2'})
        current = self.official(project)
        old.refresh_from_db()
        self.assertEqual(old.snapshot['title'], 'Campus Care')
        self.assertEqual(old.status, 'OFFICIAL')
        self.assertEqual(project.official_submission_id, current.pk)
        with self.assertRaises(ValidationError):
            services.save_deliverable(actor=self.a, submission=old, kind='DEMO', url='https://example.com')

    def test_publication_consent_and_private_copilot(self):
        project = self.project()
        self.official(project)
        with self.assertRaises(ValidationError):
            services.publication(actor=self.owner, project=project, action='publish')
        with self.assertRaises(PermissionDenied):
            services.publication(actor=self.b, project=project, action='request')
        services.publication(actor=self.a, project=project, action='request')
        self.assertFalse(services.gallery().exists())
        services.publication(actor=self.owner, project=project, action='publish')
        self.assertTrue(services.gallery().exists())
        services.publication(actor=self.a, project=project, action='withdraw')
        self.assertFalse(services.gallery().exists())
        self.assertEqual(services.copilot_input(actor=self.a, project=project)['content']['stack'], 'Django')
        with self.assertRaises(PermissionDenied):
            services.copilot_input(actor=self.c, project=project)
        counts = services.metrics(self.event)
        self.assertEqual(counts['official_submissions'], 1)

    def test_archive_read_only(self):
        project = self.project()
        Hackathon.objects.filter(pk=self.event.pk).update(status='ARCHIVED')
        with self.assertRaises(ValidationError):
            services.create_version(actor=self.a, project=project)
        services.require_reader(self.a, project)

    def test_unique_version_constraint(self):
        version = self.version(self.project())
        with self.assertRaises(IntegrityError), transaction.atomic():
            Submission.objects.create(project=version.project, version=version.version, created_by=self.a)


class ScreenTests(ProjectSetup, TestCase):
    def test_move_endpoint_updates_board_and_supports_regular_forms(self):
        project = self.project()
        milestone = services.save_milestone(actor=self.a, project=project, data={
            'title': 'Work UI', 'due_at': self.at+timedelta(hours=1), 'progress': 20})
        self.client.force_login(self.a)
        url = reverse('projects:milestone-move', args=[project.pk, milestone.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.a)
        self.assertEqual(csrf_client.post(url, {'state': 'DONE'}).status_code, 403)
        response = self.client.post(url, {'state': 'DONE'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('100 %', data['board_html'])
        self.assertIn('data-move-url=', data['board_html'])
        self.assertIn('Work UI', data['board_html'])
        self.assertIn('Étape déplacée', data['activity_html'])
        self.assertEqual(self.client.post(url, {'state': 'INVALID'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 400)
        self.assertRedirects(self.client.post(url, {'state': 'TODO'}), project.get_absolute_url()+'#board')
        milestone.refresh_from_db()
        self.assertEqual(milestone.progress, 0)
        self.client.force_login(self.c)
        self.assertEqual(self.client.post(url, {'state': 'DONE'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 403)
        self.client.force_login(self.a)
        other = self.client.post(reverse('projects:milestone-move', args=[project.pk, 999999]), {'state': 'DONE'})
        self.assertEqual(other.status_code, 404)

    def test_delete_draft_requires_confirmation_and_can_be_restored(self):
        project = self.project()
        draft = self.version(project)
        official = self.official(project)
        url = reverse('projects:draft-delete', args=[project.pk, draft.version])
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(url).status_code, 200)
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'DRAFT')
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.a)
        self.assertEqual(csrf_client.post(url).status_code, 403)
        self.assertRedirects(self.client.post(url), reverse('projects:version', args=[project.pk, official.version]))
        self.assertEqual(self.client.get(reverse('projects:version', args=[project.pk, draft.version])).status_code, 404)
        response = self.client.get(reverse('projects:version', args=[project.pk, official.version]))
        self.assertEqual(list(response.context['versions'].values_list('version', flat=True)), [official.version])
        restore_url = reverse('projects:draft-restore', args=[project.pk, draft.version])
        self.assertEqual(self.client.get(restore_url).status_code, 405)
        self.assertRedirects(self.client.post(restore_url), reverse('projects:version', args=[project.pk, draft.version]))
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'DRAFT')
        self.assertEqual(self.client.get(reverse('projects:draft-delete', args=[project.pk, official.version])).status_code, 404)

    def test_workspace_filters_preserve_project_access(self):
        project = self.project()
        self.client.force_login(self.a)
        url = reverse('projects:mine')
        response = self.client.get(url, {'q': 'Campus', 'status': 'working'})
        self.assertEqual(response.context['projects'].paginator.count, 1)
        self.assertEqual(response.context['counts']['working'], 1)
        self.assertEqual(self.client.get(url, {'q': 'missing'}).context['projects'].paginator.count, 0)
        self.official(project)
        self.assertEqual(self.client.get(url, {'status': 'submitted'}).context['projects'].paginator.count, 1)
        self.assertEqual(self.client.get(url, {'status': 'working'}).context['projects'].paginator.count, 0)
        self.client.force_login(self.c)
        response = self.client.get(url, {'q': 'Campus', 'status': 'submitted'})
        self.assertEqual(response.context['projects'].paginator.count, 0)
        self.assertEqual(response.context['counts']['total'], 0)

    def test_gallery_filters_use_only_approved_snapshot_content(self):
        project = self.project()
        self.official(project)
        url = reverse('projects:gallery')
        self.assertEqual(self.client.get(url, {'q': 'Django'}).context['projects'].paginator.count, 0)
        services.publication(actor=self.a, project=project, action='request')
        services.publication(actor=self.owner, project=project, action='publish')
        Project.objects.filter(pk=project.pk).update(title='Private unpublished revision', solution='Private unpublished revision')
        response = self.client.get(url, {'q': 'Django', 'event': self.event.slug})
        self.assertEqual(response.context['projects'].paginator.count, 1)
        self.assertContains(response, 'Campus Care')
        self.assertNotContains(response, 'Private unpublished revision')
        self.assertEqual(self.client.get(url, {'q': 'Private unpublished revision'}).context['projects'].paginator.count, 0)
        self.assertEqual(self.client.get(url, {'event': 'unknown-event'}).context['projects'].paginator.count, 0)

    def test_percentage_edit_automatically_updates_milestone_state(self):
        project = self.project()
        milestone = services.save_milestone(actor=self.a, project=project, data={
            'title': 'Work UI', 'due_at': self.at + timedelta(hours=1), 'progress': 0})
        self.client.force_login(self.a)
        url = reverse('projects:milestone-edit', args=[project.pk, milestone.pk])
        self.assertNotIn('state', self.client.get(url).context['form'].fields)
        for progress, state in [(4, 'DOING'), (99, 'DOING'), (100, 'DONE'), (0, 'TODO')]:
            with self.subTest(progress=progress):
                response = self.client.post(url, {'title': 'Work UI', 'due_at': milestone.due_at.isoformat(), 'progress': progress, 'state': 'TODO'})
                self.assertRedirects(response, project.get_absolute_url())
                milestone.refresh_from_db()
                self.assertEqual((milestone.progress, milestone.state), (progress, state))
        for invalid in (-1, 101):
            response = self.client.post(url, {'title': 'Work UI', 'due_at': milestone.due_at.isoformat(), 'progress': invalid})
            self.assertEqual(response.status_code, 200)
            self.assertIn('progress', response.context['form'].errors)
            milestone.refresh_from_db()
            self.assertEqual(milestone.progress, 0)

    def test_edit_deliverable_and_prevent_cross_project_access(self):
        project = self.project()
        version = self.version(project)
        record = self.repo(version)
        self.client.force_login(self.a)
        url = reverse('projects:deliverable-edit', args=[project.pk, 1, record.pk])
        response = self.client.post(url, {'kind': 'REPOSITORY', 'url': 'https://github.com/example/new', 'commit': 'b'*40})
        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.commit, 'b'*40)
        slides = services.save_deliverable(actor=self.a, submission=version, kind='SLIDES',
            file=SimpleUploadedFile('presentation.pdf', b'%PDF-1.7\nexample'))
        edit_slides = reverse('projects:deliverable-edit', args=[project.pk, 1, slides.pk])
        self.assertEqual(self.client.post(edit_slides, {'kind': 'SLIDES'}).status_code, 302)
        slides.refresh_from_db()
        self.assertEqual(slides.metadata['original_name'], 'presentation.pdf')
        self.assertEqual(self.client.get(reverse('projects:deliverable-edit', args=[project.pk, 999, record.pk])).status_code, 404)
        self.client.force_login(self.c)
        self.assertEqual(self.client.post(url, {'kind': 'DEMO', 'url': 'https://example.com'}).status_code, 403)

    def test_full_browser_workflow_and_languages(self):
        self.client.force_login(self.a)
        response = self.client.post(reverse('projects:create', args=[self.nova.pk]), {**self.data, 'challenge': self.data['challenge'].pk})
        project = Project.objects.get()
        self.assertRedirects(response, project.get_absolute_url())
        response = self.client.post(reverse('projects:version-create', args=[project.pk]))
        submission = project.submissions.get()
        self.assertRedirects(response, reverse('projects:version', args=[project.pk, submission.version]))
        response = self.client.post(reverse('projects:version', args=[project.pk, submission.version]), {'kind': 'REPOSITORY', 'url': 'https://github.com/example/project', 'commit': 'a'*40})
        self.assertEqual(response.status_code, 302)
        for language in ('fr', 'en'):
            self.client.cookies['hackflow_language'] = language
            for name, args in [('mine', []), ('detail', [project.pk]), ('version', [project.pk, 1]), ('edit', [project.pk]), ('milestone-add', [project.pk]), ('gallery', [])]:
                self.assertEqual(self.client.get(reverse('projects:'+name, args=args)).status_code, 200, (language, name))
        self.assertEqual(self.client.post(reverse('projects:submit', args=[project.pk, 1]), {'confirm_requirements': 'on'}).status_code, 302)

    def test_private_views_cross_project_and_post_only(self):
        project = self.project()
        version = self.version(project)
        self.client.force_login(self.c)
        for name, args in [('detail', [project.pk]), ('edit', [project.pk]), ('version', [project.pk, 1])]:
            self.assertEqual(self.client.get(reverse('projects:'+name, args=args)).status_code, 403)
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(reverse('projects:submit', args=[project.pk, 1])).status_code, 405)
        self.assertEqual(self.client.get(reverse('projects:version-create', args=[project.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse('projects:version', args=[project.pk, 999])).status_code, 404)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.a)
        self.assertEqual(csrf_client.post(reverse('projects:version-create', args=[project.pk])).status_code, 403)

    def test_files_private_then_public_only_for_current_official(self):
        project = self.project()
        version = self.version(project)
        self.repo(version)
        record = services.save_deliverable(actor=self.a, submission=version, kind='SLIDES', file=SimpleUploadedFile('slides.pdf', b'%PDF-1.7\nexample'))
        url = reverse('projects:download', args=[record.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.b)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.7\nexample')
        services.submit(actor=self.a, submission=version, confirm_requirements=True)
        services.publication(actor=self.a, project=project, action='request')
        services.publication(actor=self.owner, project=project, action='publish')
        self.client.logout()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.7\nexample')
        public_url = reverse('projects:public', args=[project.pk])
        self.assertContains(self.client.get(public_url), 'Campus Care')
        self.assertNotContains(self.client.get(public_url), 'Ajouter un livrable')
        services.reopen(actor=self.owner, project=project, reason='Correction', until=self.event.end_date)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(public_url).status_code, 404)
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(reverse('projects:version', args=[project.pk, 1])).status_code, 200)


class ConcurrencyTests(ProjectSetup, TransactionTestCase):
    def test_only_one_simultaneous_official_submission_wins(self):
        project = self.project()
        versions = [self.version(project), self.version(project)]
        for version in versions:
            self.repo(version)
        barrier = Barrier(2)
        def submit(version):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                services.submit(actor=self.a, submission=version, confirm_requirements=True)
                return True
            except ValidationError:
                return False
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, versions))
        self.assertEqual(sum(outcomes), 1)
        self.assertEqual(project.submissions.filter(status='OFFICIAL').count(), 1)

    def test_simultaneous_versions_have_unique_sequence(self):
        project = self.project()
        barrier = Barrier(2)
        def create(actor):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return services.create_version(actor=actor, project=project).version
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            versions = list(pool.map(create, [self.a, self.b]))
        self.assertEqual(sorted(versions), [1, 2])


@override_settings(DEBUG=True)
class DemoTests(TestCase):
    def test_demo_repeats_without_modifying_existing_data(self):
        call_command('seed_m3_demo', stdout=StringIO())
        self.assertEqual(Project.objects.count(), 2)
        project = Project.objects.get(title='Campus Care')
        self.assertEqual(project.progress, 60)
        self.assertEqual(project.official_submission.version, 3)
        self.assertTrue(project.published)
        count = project.activities.count()
        call_command('seed_m3_demo', stdout=StringIO())
        self.assertEqual(Project.objects.count(), 2)
        self.assertEqual(project.activities.count(), count)
