from datetime import timedelta
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.test import TestCase, TransactionTestCase, override_settings, Client
from django.db import connection, connections, IntegrityError, transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, Role, RoleAssignment, SponsorMembership
from accounts.services import set_role
from .models import Hackathon, Track, Challenge, EventPhase, SponsorOrganization, Sponsorship
from . import services
from .test_helpers import make_owner, make_event, event_payload


def sample_metrics(event):
    return {'registrations': 17, 'incomplete_teams': 2}


def broken_metrics(event):
    raise RuntimeError('provider failure')


def sample_alerts(event):
    return [{'code': 'IA_REVIEW', 'message': 'Vérification humaine demandée', 'severity': 'warning'}]


class M1Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.outsider = User.objects.create_user(username='outsider')
        cls.event = make_event(cls.owner, complete=True)
        cls.other = make_event(make_owner('owner2'), 'other')

    def url(self, name, **kwargs):
        return reverse('hackathons:' + name, kwargs={'slug': self.event.slug, **kwargs})

    def test_postgresql_test_database_is_isolated(self):
        self.assertEqual(connection.vendor, 'postgresql')
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_database()')
            self.assertEqual(cursor.fetchone()[0], 'test_hackflow_db')

    def test_create_assigns_organizer_atomically(self):
        self.client.force_login(self.owner)
        data = event_payload(self.event)
        data.update(slug='created', title='Nouvelle édition', status='PUBLISHED', created_by=self.outsider.pk)
        response = self.client.post(reverse('hackathons:create'), data)
        event = Hackathon.objects.get(slug='created')
        self.assertRedirects(response, event.get_absolute_url())
        self.assertEqual(event.status, 'DRAFT')
        self.assertEqual(event.created_by, self.owner)
        self.assertTrue(event.role_assignments.filter(user=self.owner, role='ORGANIZER', status='ACTIVE').exists())
        self.assertEqual(event.history.count(), 1)

    def test_creation_requires_dedicated_permission(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(reverse('hackathons:create'), event_payload(self.event)).status_code, 403)

    def test_invalid_event_dates_and_capacity(self):
        for changes in [dict(start_date=self.event.end_date), dict(registration_close=self.event.registration_open),
                dict(submission_deadline=self.event.end_date+timedelta(hours=1)), dict(min_team_size=8), dict(capacity=0)]:
            event = Hackathon.objects.get(pk=self.event.pk)
            for key, value in changes.items():
                setattr(event, key, value)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                event.full_clean()

    def test_database_rejects_invalid_dates_without_model_validation(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Hackathon.objects.filter(pk=self.event.pk).update(end_date=self.event.start_date)

    def test_edit_event_and_record_history(self):
        self.client.force_login(self.owner)
        data = event_payload(self.event)
        data['title'] = 'Titre modifié'
        self.assertEqual(self.client.post(self.url('edit'), data).status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.title, 'Titre modifié')
        entry = self.event.history.first()
        self.assertEqual(entry.details['after']['title'], 'Titre modifié')

    def test_event_edit_cannot_invalidate_existing_phases(self):
        self.client.force_login(self.owner)
        data = event_payload(self.event)
        data['start_date'] = self.event.start_date+timedelta(hours=4)
        self.assertEqual(self.client.post(self.url('edit'), data).status_code, 200)
        self.event.refresh_from_db()
        self.assertNotEqual(self.event.start_date, data['start_date'])

    def test_publication_and_public_search(self):
        self.assertEqual(self.client.get(self.event.get_absolute_url()).status_code, 404)
        services.transition(actor=self.owner, event=self.event, target='PUBLISHED')
        self.assertContains(self.client.get(self.event.get_absolute_url()), 'Défi public')
        self.assertContains(self.client.get(reverse('hackathons:list')+'?q=edition&format=ONSITE&status=PUBLISHED'), self.event.title)
        self.assertNotContains(self.client.get(reverse('hackathons:list')+'?q=missing'), self.event.title)

    def test_incomplete_publication_blocked(self):
        event = make_event(self.owner, 'incomplete')
        with self.assertRaises(ValidationError):
            services.transition(actor=self.owner, event=event, target='PUBLISHED')
        event.refresh_from_db()
        self.assertEqual(event.status, 'DRAFT')

    def test_lifecycle_date_guards_and_archive_snapshot(self):
        event = services.transition(actor=self.owner, event=self.event, target='PUBLISHED')
        with self.assertRaises(ValidationError):
            services.transition(actor=self.owner, event=event, target='ONGOING')
        with patch('hackathons.services.timezone.now', return_value=event.start_date+timedelta(hours=1)):
            event = services.transition(actor=self.owner, event=event, target='ONGOING')
        with self.assertRaises(ValidationError):
            services.transition(actor=self.owner, event=event, target='FINISHED')
        with patch('hackathons.services.timezone.now', return_value=event.end_date+timedelta(hours=1)):
            event = services.transition(actor=self.owner, event=event, target='FINISHED')
            event = services.transition(actor=self.owner, event=event, target='ARCHIVED')
        self.assertEqual(event.archive_metrics['tracks'], 1)
        self.assertEqual(event.archive_metrics['published_challenges'], 1)
        self.assertIsNotNone(event.archived_at)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url('manage')).status_code, 200)
        self.assertEqual(self.client.get(self.url('edit')).status_code, 403)
        with patch('hackathons.services.metrics', side_effect=AssertionError('Archive must use frozen metrics')):
            self.assertEqual(self.client.get(reverse('hackathons:dashboard')).status_code, 200)
            response = self.client.get(reverse('hackathons:compare'), {'left': event.pk, 'right': event.pk})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['rows'][0]['metrics'], event.archive_metrics)
        with self.assertRaises(PermissionDenied):
            services.save_resource(actor=self.owner, resource=Track(hackathon=event, name='late'))
        with self.assertRaises(ValidationError):
            event.save()

    def test_get_cannot_mutate_lifecycle_or_review(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url('status', target='PUBLISHED')).status_code, 405)
        challenge = Challenge.objects.get(track__hackathon=self.event)
        self.assertEqual(self.client.get(self.url('challenge-action', pk=challenge.pk, action='withdraw')).status_code, 405)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(self.url('status', target='PUBLISHED')).status_code, 403)

    def test_cross_event_access_and_resource_ids(self):
        self.client.force_login(self.outsider)
        for name in ('edit', 'manage', 'roles', 'track-add', 'phase-add', 'challenge-add', 'sponsorship-add', 'organization-add'):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(self.url(name)).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('hackathons:manage', args=[self.other.slug])).status_code, 403)
        track = Track.objects.create(hackathon=self.other, name='Autre track')
        self.assertEqual(self.client.get(self.url('track-edit', pk=track.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url('track-delete', pk=track.pk)).status_code, 404)

    def test_resource_forms_and_delete(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(self.url('track-add'), {'name': 'Data', 'active': True}).status_code, 302)
        track = self.event.tracks.get(name='Data')
        self.assertEqual(self.client.get(self.url('track-delete', pk=track.pk)).status_code, 200)
        self.assertEqual(self.client.post(self.url('track-edit', pk=track.pk), {'name': 'Data science', 'active': True}).status_code, 302)
        self.assertEqual(self.client.post(self.url('track-delete', pk=track.pk)).status_code, 302)
        self.assertFalse(Track.objects.filter(pk=track.pk).exists())

    def test_protected_track_delete_does_not_lose_history(self):
        self.client.force_login(self.owner)
        track = self.event.tracks.get()
        response = self.client.post(self.url('track-delete', pk=track.pk), follow=True)
        self.assertContains(response, 'suppression impossible')
        self.assertTrue(Track.objects.filter(pk=track.pk).exists())

    def test_challenge_form_rejects_cross_event_track(self):
        self.client.force_login(self.owner)
        track = Track.objects.create(hackathon=self.other, name='Autre')
        response = self.client.post(self.url('challenge-add'), {'track': track.pk, 'title': 'Hidden', 'problem': 'a', 'objectives': 'b', 'deliverables': 'c'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Challenge.objects.filter(title='Hidden').exists())

    def test_challenge_edits_reset_approval_and_visibility(self):
        self.client.force_login(self.owner)
        challenge = Challenge.objects.get(track__hackathon=self.event)
        response = self.client.post(self.url('challenge-edit', pk=challenge.pk), {'track': challenge.track_id,
            'title': challenge.title, 'problem': 'Nouveau problème', 'objectives': challenge.objectives, 'deliverables': challenge.deliverables})
        self.assertEqual(response.status_code, 302)
        challenge.refresh_from_db()
        self.assertEqual(challenge.status, 'DRAFT')
        self.assertIsNone(challenge.approved_by)
        self.assertFalse(services.public_challenges(self.event).exists())

    def test_incomplete_challenge_cannot_publish(self):
        challenge = Challenge.objects.get(track__hackathon=self.event)
        challenge.deliverables = '   '
        with self.assertRaises(ValidationError):
            challenge.save()

    def test_phase_overlap_boundary_and_derived_state(self):
        phase = self.event.phases.get(kind='DEVELOPMENT')
        phase.end = self.event.end_date
        with self.assertRaises(ValidationError):
            services.save_resource(actor=self.owner, resource=phase)
        phase.refresh_from_db()
        with patch('hackathons.models.timezone.now', return_value=phase.start):
            self.assertEqual(phase.state, 'En cours')
        with patch('hackathons.models.timezone.now', return_value=phase.end):
            self.assertEqual(phase.state, 'Terminée')

    def test_phase_outside_event_and_registration_drift_rejected(self):
        phase = self.event.phases.get(kind='REGISTRATION')
        phase.end += timedelta(hours=1)
        with self.assertRaises(ValidationError):
            phase.save()
        phase = self.event.phases.get(kind='DEVELOPMENT')
        phase.start = self.event.registration_open
        with self.assertRaises(ValidationError):
            phase.save()

    def test_late_registration_and_submission_denied_at_exact_boundary(self):
        event = services.transition(actor=self.owner, event=self.event, target='PUBLISHED')
        self.assertTrue(services.phase_is_open(event, 'REGISTRATION', event.registration_open))
        for at in (event.registration_close, event.registration_close+timedelta(seconds=1)):
            with self.assertRaises(ValidationError):
                services.require_open_phase(event, 'REGISTRATION', at)
        self.assertTrue(services.phase_is_open(event, 'SUBMISSION', event.submission_deadline-timedelta(seconds=1)))
        self.assertFalse(services.phase_is_open(event, 'SUBMISSION', event.submission_deadline))
        self.assertFalse(services.phase_is_open(self.event, 'REGISTRATION', self.event.registration_open))

    def test_sponsor_proposal_needs_context_role_and_membership_and_review(self):
        org = SponsorOrganization.objects.create(name='Acme', contact_email='contact@example.test')
        partnership = services.save_resource(actor=self.owner, resource=Sponsorship(hackathon=self.event, organization=org,
            contribution_type='Financement', estimated_value=1000, status='CONFIRMED'))
        self.assertIsNotNone(partnership.confirmed_at)
        set_role(actor=self.owner, user=self.outsider, hackathon=self.event, role=Role.SPONSOR_REPRESENTATIVE)
        challenge = Challenge(track=self.event.tracks.get(), title='Proposition sponsor', problem='Problème', objectives='Objectifs', deliverables='Démo', sponsorship=partnership)
        with self.assertRaises(PermissionDenied):
            services.propose_challenge(actor=self.outsider, challenge=challenge)
        SponsorMembership.objects.create(user=self.outsider, organization=org)
        challenge = services.propose_challenge(actor=self.outsider, challenge=challenge)
        event = services.transition(actor=self.owner, event=self.event, target='PUBLISHED')
        self.assertNotContains(self.client.get(event.get_absolute_url()), 'Proposition sponsor')
        with self.assertRaises(PermissionDenied):
            services.review_challenge(actor=self.outsider, challenge=challenge, action='publish')
        with self.assertRaises(ValidationError):
            services.review_challenge(actor=self.owner, challenge=challenge, action='publish')
        services.review_challenge(actor=self.owner, challenge=challenge, action='approve')
        services.review_challenge(actor=self.owner, challenge=challenge, action='publish')
        self.assertContains(self.client.get(event.get_absolute_url()), 'Proposition sponsor')
        partnership.status = 'CANCELLED'
        with self.assertRaises(ValidationError):
            services.save_resource(actor=self.owner, resource=partnership)
        services.review_challenge(actor=self.owner, challenge=challenge, action='withdraw')
        services.save_resource(actor=self.owner, resource=partnership)
        self.assertNotContains(self.client.get(event.get_absolute_url()), 'Proposition sponsor')

    def test_sponsor_proposal_view_ignores_injected_approval(self):
        org = SponsorOrganization.objects.create(name='Sponsor')
        partnership = Sponsorship.objects.create(hackathon=self.event, organization=org, contribution_type='Support', status='CONFIRMED')
        set_role(actor=self.owner, user=self.outsider, hackathon=self.event, role=Role.SPONSOR_REPRESENTATIVE)
        SponsorMembership.objects.create(user=self.outsider, organization=org)
        self.client.force_login(self.outsider)
        response = self.client.post(self.url('propose'), {'track': self.event.tracks.get().pk, 'sponsorship': partnership.pk,
            'title': 'Proposition', 'problem': 'P', 'objectives': 'O', 'deliverables': 'D', 'status': 'PUBLISHED', 'approved_by': self.outsider.pk})
        self.assertEqual(response.status_code, 302)
        challenge = Challenge.objects.get(title='Proposition')
        self.assertEqual(challenge.status, 'PROPOSED')
        self.assertIsNone(challenge.approved_by)

    def test_stale_partnership_does_not_allow_a_sponsor_proposal(self):
        org = SponsorOrganization.objects.create(name='Stale sponsor')
        partnership = Sponsorship.objects.create(hackathon=self.event, organization=org, contribution_type='Support', status='CONFIRMED')
        set_role(actor=self.owner, user=self.outsider, hackathon=self.event, role=Role.SPONSOR_REPRESENTATIVE)
        SponsorMembership.objects.create(user=self.outsider, organization=org)
        challenge = Challenge(track=self.event.tracks.get(), title='Stale', problem='P', objectives='O', deliverables='D', sponsorship=partnership)
        current = Sponsorship.objects.get(pk=partnership.pk)
        current.status = 'CANCELLED'
        services.save_resource(actor=self.owner, resource=current)
        with self.assertRaises(ValidationError):
            services.propose_challenge(actor=self.outsider, challenge=challenge)
        self.assertFalse(Challenge.objects.filter(title='Stale').exists())

    def test_partnership_organization_cannot_be_reassigned(self):
        first = SponsorOrganization.objects.create(name='First')
        second = SponsorOrganization.objects.create(name='Second')
        partnership = Sponsorship.objects.create(hackathon=self.event, organization=first, contribution_type='Support')
        partnership.organization = second
        with self.assertRaises(ValidationError):
            services.save_resource(actor=self.owner, resource=partnership)
        partnership.refresh_from_db()
        self.assertEqual(partnership.organization_id, first.pk)

    def test_partnership_scope_and_value(self):
        org = SponsorOrganization.objects.create(name='Org')
        partnership = Sponsorship.objects.create(hackathon=self.other, organization=org, contribution_type='Support', status='CONFIRMED')
        challenge = Challenge.objects.get(track__hackathon=self.event)
        challenge.sponsorship = partnership
        with self.assertRaises(ValidationError):
            challenge.save()
        partnership.estimated_value = -1
        with self.assertRaises(ValidationError):
            partnership.save()

    def test_organization_and_partnership_forms(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(self.url('organization-add'), {'name': 'Test org', 'website': 'https://example.test'}).status_code, 302)
        org = SponsorOrganization.objects.get(name='Test org')
        self.assertEqual(self.client.post(self.url('sponsorship-add'), {'organization': org.pk, 'contribution_type': 'Matériel',
            'currency': 'TND', 'estimated_value': '20.50', 'status': 'CONFIRMED'}).status_code, 302)
        self.assertTrue(self.event.sponsorships.filter(organization=org, confirmed_at__isnull=False).exists())

    def test_dashboard_no_fake_counters_and_private_comparison(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('hackathons:dashboard'))
        self.assertContains(response, 'Control Tower')
        self.assertContains(response, 'Module non connecté')
        self.assertNotContains(response, self.other.title)
        response = self.client.get(reverse('hackathons:compare'), {'left': self.event.pk, 'right': self.event.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse('hackathons:compare'), {'left': self.other.pk}).status_code, 404)

    @override_settings(HACKFLOW_METRIC_PROVIDERS={'M2': 'hackathons.tests.sample_metrics', 'M3': 'hackathons.tests.broken_metrics'})
    def test_connected_metrics_are_real_provider_values_and_fail_closed(self):
        data = services.metrics(self.event)
        self.assertEqual(data['modules']['M2']['counts']['registrations'], 17)
        self.assertFalse(data['modules']['M3']['available'])
        self.client.force_login(self.owner)
        response = self.client.get(reverse('hackathons:dashboard'))
        self.assertContains(response, 'registrations : 17')
        self.assertContains(response, 'Indicateurs indisponibles')

    def test_intelligence_contract_is_read_only_and_authorized(self):
        with self.assertRaises(PermissionDenied):
            services.intelligence_context(actor=self.outsider, event=self.event)
        context = services.intelligence_context(actor=self.owner, event=self.event)
        self.assertEqual(context['version'], 1)
        self.assertEqual(context['eligibility']['capacity'], 100)
        self.assertEqual(len(context['calendar']), 4)
        self.assertEqual(len(context['tracks']), 1)
        self.assertNotIn('contact_email', str(context))

    def test_all_configuration_pages_render(self):
        self.client.force_login(self.owner)
        for name in ('manage', 'edit', 'roles', 'track-add', 'challenge-add', 'phase-add', 'sponsorship-add', 'organization-add'):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(self.url(name)).status_code, 200)

    @override_settings(HACKFLOW_ALERT_PROVIDER='hackathons.tests.sample_alerts')
    def test_transversal_alert_provider(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('hackathons:dashboard')), 'Vérification humaine demandée')
        with override_settings(HACKFLOW_ALERT_PROVIDER='hackathons.tests.broken_metrics'):
            self.assertFalse(services.operational_alerts(self.event)['available'])

    def test_history_is_paginated_and_private(self):
        self.client.force_login(self.owner)
        for i in range(51):
            services.record(self.event, self.owner, 'Test', str(i))
        response = self.client.get(self.url('history'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['page_obj'].has_next())
        self.assertEqual(self.client.get(self.url('history')+'?page=2').status_code, 200)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url('history')).status_code, 403)

    def test_resource_service_cannot_move_between_events(self):
        track = self.event.tracks.get()
        track.hackathon = self.other
        other_owner = self.other.created_by
        with self.assertRaises(PermissionDenied):
            services.save_resource(actor=other_owner, resource=track)
        track.refresh_from_db()
        self.assertEqual(track.hackathon_id, self.event.pk)

    def test_late_published_edition_can_be_finished(self):
        event = services.transition(actor=self.owner, event=self.event, target='PUBLISHED')
        with patch('hackathons.services.timezone.now', return_value=event.end_date+timedelta(hours=1)):
            event = services.transition(actor=self.owner, event=event, target='FINISHED')
        self.assertEqual(event.status, 'FINISHED')

    def test_superuser_admin_pages_and_sensitive_forms(self):
        admin = User.objects.create_superuser(username='technical', email='technical@example.test')
        self.client.force_login(admin)
        for model in ('user', 'roleassignment', 'sponsormembership', 'roleassignmenthistory', 'skill'):
            self.assertEqual(self.client.get(f'/admin/accounts/{model}/').status_code, 200)
        for model in ('hackathon', 'track', 'challenge', 'eventphase', 'sponsororganization', 'sponsorship', 'eventhistory'):
            self.assertEqual(self.client.get(f'/admin/hackathons/{model}/').status_code, 200)
        for app, model in [('hackathons','hackathon'), ('hackathons','challenge'), ('accounts','user'), ('accounts','roleassignment')]:
            self.assertEqual(self.client.get(f'/admin/{app}/{model}/add/').status_code, 200)
        self.assertEqual(self.client.get(f'/admin/hackathons/hackathon/{self.event.pk}/change/').status_code, 200)

    def test_full_required_integration_flow(self):
        self.client.post(reverse('accounts:signup'), {'username': 'integration', 'email': 'integration@example.test',
            'password1': 'FictionalTest!9427', 'password2': 'FictionalTest!9427'})
        user = User.objects.get(username='integration')
        user.user_permissions.add(Permission.objects.get(codename='create_hackathon'))
        data = event_payload(self.event)
        data.update(slug='integration', title='Integration')
        self.assertEqual(self.client.post(reverse('hackathons:create'), data).status_code, 302)
        event = Hackathon.objects.get(slug='integration')
        self.assertTrue(event.role_assignments.filter(user=user, role='ORGANIZER').exists())
        base = {'slug': event.slug}
        self.assertEqual(self.client.post(reverse('hackathons:track-add', kwargs=base), {'name': 'Data', 'active': True}).status_code, 302)
        track = event.tracks.get()
        self.client.post(reverse('hackathons:challenge-add', kwargs=base), {'track': track.pk, 'title': 'Défi intégration', 'problem': 'P', 'objectives': 'O', 'deliverables': 'D'})
        challenge = Challenge.objects.get(track=track)
        for action in ('approve', 'publish'):
            self.assertEqual(self.client.post(reverse('hackathons:challenge-action', kwargs={**base, 'pk': challenge.pk, 'action': action})).status_code, 302)
        for phase in self.event.phases.all():
            self.assertEqual(self.client.post(reverse('hackathons:phase-add', kwargs=base), {'kind': phase.kind, 'start': phase.start, 'end': phase.end}).status_code, 302)
        self.client.post(reverse('hackathons:organization-add', kwargs=base), {'name': 'Sponsor intégration'})
        organization = SponsorOrganization.objects.get(name='Sponsor intégration')
        self.assertEqual(self.client.post(reverse('hackathons:sponsorship-add', kwargs=base), {'organization': organization.pk, 'contribution_type': 'Soutien', 'currency': 'TND', 'status': 'CONFIRMED'}).status_code, 302)
        self.client.post(reverse('hackathons:status', kwargs={**base, 'target': 'PUBLISHED'}))
        event.refresh_from_db()
        self.assertEqual(event.status, 'PUBLISHED')
        self.client.logout()
        self.assertContains(self.client.get(event.get_absolute_url()), 'Défi intégration')
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(reverse('hackathons:edit', kwargs=base), data).status_code, 403)


class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = make_owner()
        self.user = User.objects.create_user(username='concurrent')
        self.event = make_event(self.owner)

    def test_incompatible_role_assignments_are_serialized(self):
        barrier = Barrier(2)
        def assign(role):
            try:
                actor = User.objects.get(pk=self.owner.pk)
                user = User.objects.get(pk=self.user.pk)
                event = Hackathon.objects.get(pk=self.event.pk)
                barrier.wait(timeout=10)
                set_role(actor=actor, user=user, hackathon=event, role=role)
                return 'ok'
            except ValidationError:
                return 'rejected'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = list(executor.map(assign, [Role.PARTICIPANT, Role.JURY]))
        self.assertCountEqual(result, ['ok', 'rejected'])
        self.assertEqual(RoleAssignment.objects.filter(user=self.user, status='ACTIVE').count(), 1)

    def test_conflicting_phase_updates_are_serialized(self):
        barrier = Barrier(2)
        def configure(kind):
            try:
                actor = User.objects.get(pk=self.owner.pk)
                event = Hackathon.objects.get(pk=self.event.pk)
                phase = EventPhase(hackathon=event, kind=kind, start=event.submission_deadline, end=event.end_date)
                barrier.wait(timeout=10)
                services.save_resource(actor=actor, resource=phase)
                return 'ok'
            except ValidationError:
                return 'rejected'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = list(executor.map(configure, ['DEVELOPMENT', 'EVALUATION']))
        self.assertCountEqual(result, ['ok', 'rejected'])
        self.assertEqual(self.event.phases.count(), 1)
