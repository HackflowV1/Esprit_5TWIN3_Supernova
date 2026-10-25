"""The session: report by the mentor, feedback and resolution by the team, and the whole help flow end to end."""
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone, translation

from teams.models import TeamMembership
from .. import services
from ..models import M4History, MentoringSession, SupportRequest
from .base import LiveBase


class CompleteSessionTests(LiveBase):
    def test_the_mentor_finishes_a_started_session_with_a_report(self):
        session = self.past_session()
        services.complete_session(actor=self.mentor, session=session, report='  On a corrigé le serializer.  ', private_notes='RAS')
        session.refresh_from_db()
        session.request.refresh_from_db()
        self.assertEqual((session.status, session.report, session.private_notes), ('COMPLETED', 'On a corrigé le serializer.', 'RAS'))
        self.assertIsNotNone(session.completed_at)
        self.assertEqual(session.request.status, 'IN_PROGRESS')  # finished, but not yet declared solved
        entry = M4History.objects.get(action='session.completed', object_id=session.pk)
        self.assertEqual((entry.actor, entry.details['request']), (self.mentor, session.request_id))

    def test_it_cannot_be_finished_before_it_starts(self):
        session = self.book()
        with self.assertRaises(ValidationError) as caught:
            services.complete_session(actor=self.mentor, session=session, report='Trop tôt')
        self.assertIn('pas encore commencé', ' '.join(caught.exception.messages))
        session.refresh_from_db()
        self.assertEqual(session.status, 'BOOKED')

    def test_only_the_mentor_of_the_session_may_finish_it(self):
        session = self.past_session()
        for actor in (self.captain, self.member, self.owner, self.mentor2, self.outsider):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                services.complete_session(actor=actor, session=session, report='Pas moi')

    def test_the_report_is_required(self):
        session = self.past_session()
        for report in ('', '   '):
            with self.subTest(report=repr(report)), self.assertRaises(ValidationError):
                services.complete_session(actor=self.mentor, session=session, report=report)
        session.refresh_from_db()
        self.assertEqual(session.status, 'BOOKED')

    def test_only_a_booked_session_can_be_finished(self):
        session = self.completed_session()
        with self.assertRaises(ValidationError):
            services.complete_session(actor=self.mentor, session=session, report='Encore')


class UpdateReportTests(LiveBase):
    def test_the_mentor_may_correct_the_report_until_the_team_answers(self):
        session = self.completed_session()
        services.update_report(actor=self.mentor, session=session, report='Version corrigée', private_notes='')
        session.refresh_from_db()
        self.assertEqual((session.report, session.private_notes), ('Version corrigée', ''))
        self.assertTrue(M4History.objects.filter(action='session.report_updated', object_id=session.pk).exists())
        services.give_feedback(actor=self.captain, session=session, rating=4, comment='', resolved=True)
        with self.assertRaises(ValidationError):
            services.update_report(actor=self.mentor, session=session, report='Trop tard')

    def test_nobody_else_edits_the_report(self):
        session = self.completed_session()
        for actor in (self.captain, self.owner, self.mentor2):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                services.update_report(actor=actor, session=session, report='Piraté')


class FeedbackTests(LiveBase):
    def feedback(self, session, actor=None, rating=5, comment='Très utile', resolved=True):
        return services.give_feedback(actor=actor or self.member, session=session, rating=rating, comment=comment, resolved=resolved)

    def test_a_member_confirms_the_resolution(self):
        session = self.completed_session()
        self.feedback(session)
        session.refresh_from_db()
        request = session.request
        request.refresh_from_db()
        self.assertEqual((session.feedback_rating, session.feedback_comment, request.status), (5, 'Très utile', 'RESOLVED'))
        self.assertIsNotNone(request.resolved_at)
        actions = list(M4History.objects.filter(actor=self.member).order_by('id').values_list('action', flat=True))
        self.assertEqual(actions, ['session.feedback', 'request.resolved'])

    def test_an_unsolved_problem_reopens_the_request_for_a_new_appointment(self):
        session = self.completed_session()
        self.feedback(session, resolved=False)
        request = SupportRequest.objects.get(pk=session.request_id)
        self.assertEqual((request.status, request.resolved_at), ('OPEN', None))
        again = self.book(request=request, slot=self.slot(in_minutes=120))
        self.assertEqual(again.status, 'BOOKED')
        self.assertEqual(request.sessions.count(), 2)  # the first session is kept
        self.assertEqual(M4History.objects.filter(action='request.reopened').count(), 1)

    def test_only_active_members_of_the_team_may_answer(self):
        session = self.completed_session()
        for actor in (self.outsider, self.rival_captain, self.mentor, self.owner):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                self.feedback(session, actor=actor)
        TeamMembership.objects.filter(registration__user=self.member).update(ended_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.feedback(session)

    def test_the_team_answers_only_once_and_only_after_the_session(self):
        booked = self.book()
        with self.assertRaises(ValidationError):
            self.feedback(booked)
        session = self.completed_session(self.request(subject='Autre'))
        self.feedback(session)
        with self.assertRaises(ValidationError):
            self.feedback(session)

    def test_the_rating_must_be_between_1_and_5(self):
        session = self.completed_session()
        for rating in (0, 6, 'x', None):
            with self.subTest(rating=rating), self.assertRaises(ValidationError):
                self.feedback(session, rating=rating)
        session.refresh_from_db()
        self.assertIsNone(session.feedback_at)


class EndToEndFlowTests(LiveBase):
    def test_from_the_blockage_to_the_confirmed_resolution(self):
        request = services.open_request(actor=self.member, team=self.team, subject='API Django', description='Le serializer plante.',
            skill=self.django, priority='HIGH')
        slot = self.slot(in_minutes=60)
        session = services.book_session(actor=self.captain, request=request, slot=slot)
        request.refresh_from_db()
        self.assertEqual(request.status, 'BOOKED')
        with patch('django.utils.timezone.now', return_value=slot.start + timedelta(minutes=50)):
            services.complete_session(actor=self.mentor, session=session, report='Voir la doc DRF.')
            request.refresh_from_db()
            self.assertEqual(request.status, 'IN_PROGRESS')
            services.give_feedback(actor=self.captain, session=session, rating=5, comment='', resolved=True)
        request.refresh_from_db()
        self.assertEqual(request.status, 'RESOLVED')
        self.assertEqual(list(M4History.objects.filter(hackathon=self.event).order_by('id').values_list('action', flat=True)),
            ['request.opened', 'session.booked', 'session.completed', 'session.feedback', 'request.resolved'])


class SessionViewTests(LiveBase):
    def url(self, session):
        return reverse('mentoring:session-detail', args=[session.pk])

    def test_who_can_open_an_appointment(self):
        session = self.book()
        for user in (self.captain, self.member, self.mentor, self.owner):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertEqual(self.client.get(self.url(session)).status_code, 200)
        for user in (self.rival_captain, self.outsider, self.mentor2):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertEqual(self.client.get(self.url(session)).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url(session)).status_code, 302)

    def test_before_the_start_the_mentor_waits_and_the_team_prepares(self):
        session = self.book()
        self.client.force_login(self.mentor)
        page = self.client.get(self.url(session))
        self.assertContains(page, 'Le rendez-vous n’a pas encore commencé.')
        self.assertNotContains(page, 'name="report"')
        self.client.force_login(self.captain)
        page = self.client.get(self.url(session))
        self.assertContains(page, 'préparez vos questions')
        self.assertContains(page, reverse('mentoring:session-cancel', args=[session.pk]))
        self.assertContains(page, '<h1', count=1)

    def test_the_mentor_finishes_the_session_from_the_page(self):
        session = self.past_session()
        self.client.force_login(self.mentor)
        self.assertContains(self.client.get(self.url(session)), 'name="report"')
        response = self.client.post(self.url(session), {'action': 'complete', 'report': '  ', 'private_notes': ''})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-error-summary')
        session.refresh_from_db()
        self.assertEqual(session.status, 'BOOKED')
        response = self.client.post(self.url(session), {'action': 'complete', 'report': 'Pistes DRF', 'private_notes': 'Notes'}, follow=True)
        self.assertContains(response, 'Séance terminée.')
        self.assertContains(response, 'Pistes DRF')
        session.refresh_from_db()
        self.assertEqual(session.status, 'COMPLETED')

    def test_the_team_reads_the_report_but_not_the_private_notes(self):
        session = self.completed_session()
        self.client.force_login(self.member)
        page = self.client.get(self.url(session))
        self.assertContains(page, 'On a corrigé le serializer.')
        self.assertNotContains(page, 'Équipe motivée.')
        for user in (self.mentor, self.owner):
            self.client.force_login(user)
            self.assertContains(self.client.get(self.url(session)), 'Équipe motivée.')

    def test_the_team_gives_its_feedback_and_the_request_is_solved(self):
        session = self.completed_session()
        self.client.force_login(self.member)
        page = self.client.get(self.url(session))
        self.assertContains(page, 'Le problème est-il résolu ?')
        self.assertContains(page, '<fieldset', count=2)
        bad = self.client.post(self.url(session), {'action': 'feedback', 'comment': 'x'})
        self.assertEqual(bad.status_code, 200)
        self.assertContains(bad, 'data-error-summary')
        response = self.client.post(self.url(session), {'action': 'feedback', 'rating': '5', 'comment': 'Merci', 'resolved': '1'}, follow=True)
        self.assertContains(response, 'Merci pour votre retour.')
        self.assertContains(response, 'Retour de l’équipe')
        self.assertContains(self.client.get(session.request.get_absolute_url()), 'Problème résolu')
        self.assertNotContains(self.client.get(self.url(session)), 'name="rating"')

    def test_an_unsolved_problem_gives_the_booking_back(self):
        session = self.completed_session()
        self.client.force_login(self.captain)
        self.client.post(self.url(session), {'action': 'feedback', 'rating': '3', 'comment': '', 'resolved': '0'})
        page = self.client.get(session.request.get_absolute_url())
        self.assertContains(page, reverse('mentoring:support-book', args=[session.request_id]))
        self.assertEqual(SupportRequest.objects.get(pk=session.request_id).status, 'OPEN')

    def test_the_captain_cancels_an_appointment_after_a_confirmation(self):
        session = self.book()
        self.client.force_login(self.captain)
        url = reverse('mentoring:session-cancel', args=[session.pk])
        self.assertContains(self.client.get(url), 'Annuler ce rendez-vous ?')
        session.refresh_from_db()
        self.assertEqual(session.status, 'BOOKED')
        response = self.client.post(url, follow=True)
        self.assertContains(response, 'Rendez-vous annulé.')
        session.refresh_from_db()
        self.assertEqual(session.status, 'CANCELLED')
        self.assertEqual(SupportRequest.objects.get(pk=session.request_id).status, 'OPEN')

    def test_who_cannot_cancel_is_told_so_and_nothing_changes(self):
        started = self.past_session(self.request(subject='Autre'))
        self.client.force_login(self.captain)
        self.assertContains(self.client.get(reverse('mentoring:session-cancel', args=[started.pk]), follow=True), 'ne peut pas être annulé')


class AppointmentsViewTests(LiveBase):
    def setUp(self):
        super().setUp()
        self.url = reverse('mentoring:appointments')

    def test_the_team_and_the_mentor_see_the_upcoming_appointment(self):
        session = self.book(request=self.request(subject='API Django'))
        for user in (self.captain, self.member, self.mentor, self.owner):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                page = self.client.get(self.url)
                self.assertContains(page, 'API Django')
                self.assertContains(page, session.get_absolute_url())
                self.assertContains(page, '<time datetime=')
        for user in (self.rival_captain, self.outsider, self.mentor2):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertNotContains(self.client.get(self.url), 'API Django')

    def test_cancelled_and_finished_appointments_move_to_the_past_list(self):
        done = self.completed_session(self.request(subject='Terminé'))
        cancelled = self.book(request=self.request(subject='Annulé'))
        services.cancel_session(actor=self.captain, session=cancelled)
        self.client.force_login(self.captain)
        page = self.client.get(self.url)
        self.assertContains(page, 'Passés et annulés')
        self.assertContains(page, 'Terminé')
        self.assertContains(page, 'Aucun rendez-vous à venir')
        self.assertEqual([s.pk for s in page.context['upcoming']], [])
        self.assertEqual({s.pk for s in page.context['past']}, {done.pk, cancelled.pk})

    def test_someone_without_appointments_gets_a_useful_empty_page(self):
        self.client.force_login(self.outsider)
        page = self.client.get(self.url)
        self.assertContains(page, 'Aucun rendez-vous à venir')
        self.assertContains(page, reverse('mentoring:support-list'))


class EnglishFlowTests(LiveBase):
    def test_booking_session_and_appointment_pages_are_english(self):
        session = self.completed_session()
        request = self.request(subject='Open one')
        self.slot()
        self.client.force_login(self.captain)
        self.client.post(reverse('set_language'), {'language': 'en', 'next': '/'})
        self.addCleanup(translation.deactivate)
        french = ('Réserver', 'Rendez-vous', 'créneau', 'Compte rendu', 'Prochaine', 'Aucun', 'Équipe', 'Description du blocage')
        for url, expected in ((reverse('mentoring:support-book', args=[request.pk]), 'Available slots'),
                              (session.get_absolute_url(), 'Is the problem solved?'),
                              (reverse('mentoring:appointments'), 'My appointments')):
            with self.subTest(url=url):
                page = self.client.get(url)
                self.assertContains(page, expected)
                html = page.content.decode()
                for word in french:
                    self.assertNotIn(word, html, f'{word!r} still in French on {url}')
