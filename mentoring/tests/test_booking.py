"""Booking a mentor: which slots a team may see, the rules checked at booking time, cancellation, and concurrency."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AssignmentStatus, Role, User
from accounts.services import set_role
from hackathons.models import Hackathon
from hackathons.test_helpers import make_owner
from teams.models import Team
from .. import services
from ..models import M4History, MentoringSession, MentorExpertise, MentorSlot, SupportRequest, Workshop
from .base import LiveBase
from .helpers import make_ongoing_event, make_request, make_team, make_user


class BookableSlotsTests(LiveBase):
    def test_only_real_free_slots_are_offered_in_chronological_order(self):
        later, free = self.slot(in_minutes=240), self.slot(in_minutes=60)
        taken, withdrawn = self.slot(in_minutes=120), self.slot(in_minutes=180)
        withdrawn.withdrawn_at = timezone.now()
        withdrawn.save()
        self.book(request=self.request(team=self.rival), slot=taken)
        past = self.past_session().slot
        self.assertEqual(list(services.bookable_slots(self.request())), [free, later])
        self.assertNotIn(past, services.bookable_slots(self.request()))

    def test_a_mentor_who_is_in_the_team_is_never_offered(self):
        insiders = make_team(self.event, make_user('insider'), name='Insiders', members=[self.mentor2])
        own, other = self.slot(self.mentor2), self.slot(self.mentor, in_minutes=200)
        self.assertEqual(list(services.bookable_slots(make_request(insiders, insiders.captain.user))), [other])
        self.assertIn(own, services.bookable_slots(self.request()))

    def test_a_mentor_without_an_active_role_is_not_offered(self):
        slot = self.slot(self.mentor2)
        self.assertIn(slot, services.bookable_slots(self.request()))
        set_role(actor=self.owner, user=self.mentor2, hackathon=self.event, role=Role.MENTOR, status=AssignmentStatus.REVOKED)
        self.assertNotIn(slot, services.bookable_slots(self.request()))

    def test_a_mentor_who_teaches_at_that_time_is_not_offered(self):
        slot = self.slot(self.mentor2, in_minutes=100)
        Workshop.objects.create(hackathon=self.event, trainer=self.mentor2, title='Atelier', capacity=5, location='A',
            start=slot.start + timedelta(minutes=10), end=slot.start + timedelta(minutes=70))
        self.assertNotIn(slot, services.bookable_slots(self.request()))

    def test_slots_that_overlap_the_team_own_appointment_are_not_offered(self):
        first = self.slot(self.mentor, in_minutes=60, minutes=45)
        overlapping = self.slot(self.mentor2, in_minutes=90, minutes=45)
        adjacent = self.slot(self.mentor, in_minutes=105, minutes=45)  # starts exactly when the first one ends
        self.book(slot=first)
        offered = list(services.bookable_slots(self.request(subject='Autre')))
        self.assertNotIn(overlapping, offered)
        self.assertIn(adjacent, offered)

    def test_the_skill_only_filters_it_does_not_rank(self):
        with_skill, without = self.slot(self.mentor, in_minutes=200), self.slot(self.mentor2, in_minutes=60)
        MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=3)
        request = self.request()
        self.assertEqual(list(services.bookable_slots(request)), [without, with_skill])  # chronological, not by skill
        self.assertEqual(list(services.bookable_slots(request, self.django)), [with_skill])


class BookSessionTests(LiveBase):
    def test_the_captain_books_a_slot(self):
        request, slot = self.request(), self.slot()
        session = services.book_session(actor=self.captain, request=request, slot=slot)
        request.refresh_from_db()
        self.assertEqual((session.status, request.status, session.booked_by), ('BOOKED', 'BOOKED', self.captain))
        self.assertEqual(MentorSlot.objects.get(pk=slot.pk).availability, 'BOOKED')
        entry = M4History.objects.get(action='session.booked', object_id=session.pk)
        self.assertEqual((entry.actor, entry.details['mentor'], entry.details['as_organizer']), (self.captain, self.mentor.pk, False))

    def test_only_the_captain_or_an_organizer_may_book(self):
        request, slot = self.request(), self.slot()
        for actor in (self.member, self.outsider, self.rival_captain, self.mentor):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                services.book_session(actor=actor, request=request, slot=slot)
        self.assertFalse(MentoringSession.objects.exists())

    def test_an_organizer_may_step_in_and_is_traced(self):
        session = services.book_session(actor=self.owner, request=self.request(), slot=self.slot())
        self.assertTrue(M4History.objects.get(action='session.booked', object_id=session.pk).details['as_organizer'])

    def test_the_request_must_be_waiting_for_an_appointment(self):
        slot = self.slot()
        for status in ('BOOKED', 'IN_PROGRESS', 'RESOLVED', 'CANCELLED'):
            request = self.request(subject=status)
            SupportRequest.objects.filter(pk=request.pk).update(status=status)
            with self.subTest(status=status), self.assertRaises(ValidationError):
                services.book_session(actor=self.captain, request=request, slot=slot)

    def test_a_slot_already_booked_by_another_team_is_refused(self):
        slot = self.slot()
        services.book_session(actor=self.rival_captain, request=self.request(team=self.rival), slot=slot)
        with self.assertRaises(ValidationError) as caught:
            services.book_session(actor=self.captain, request=self.request(), slot=slot)
        self.assertIn('vient d’être réservé', ' '.join(caught.exception.messages))
        self.assertEqual(MentoringSession.objects.filter(slot=slot, status='BOOKED').count(), 1)

    def test_withdrawn_past_and_foreign_slots_are_refused(self):
        request = self.request()
        withdrawn = self.slot()
        withdrawn.withdrawn_at = timezone.now()
        withdrawn.save()
        past = self.past_session(self.request(team=self.rival)).slot
        other_event = make_ongoing_event(self.owner, 'other')
        set_role(actor=self.owner, user=self.mentor, hackathon=other_event, role=Role.MENTOR)
        start = self.now() + timedelta(minutes=30)
        foreign = MentorSlot.objects.create(hackathon=other_event, mentor=self.mentor, start=start, end=start + timedelta(minutes=30))
        for slot in (withdrawn, past, foreign):
            with self.subTest(slot=slot.pk), self.assertRaises(ValidationError):
                services.book_session(actor=self.captain, request=request, slot=slot)

    def test_a_mentor_who_lost_the_role_cannot_be_booked(self):
        slot = self.slot(self.mentor2)
        set_role(actor=self.owner, user=self.mentor2, hackathon=self.event, role=Role.MENTOR, status=AssignmentStatus.REVOKED)
        with self.assertRaises(ValidationError):
            services.book_session(actor=self.captain, request=self.request(), slot=slot)

    def test_a_team_cannot_have_two_appointments_at_the_same_time(self):
        self.book(slot=self.slot(self.mentor, in_minutes=60))
        with self.assertRaises(ValidationError) as caught:
            self.book(request=self.request(subject='Autre'), slot=self.slot(self.mentor2, in_minutes=75))
        self.assertIn('Votre équipe a déjà un rendez-vous', ' '.join(caught.exception.messages))

    def test_a_mentor_cannot_be_booked_while_teaching(self):
        slot = self.slot(self.mentor, in_minutes=100)
        Workshop.objects.create(hackathon=self.event, trainer=self.mentor, title='Atelier', capacity=5, location='A',
            start=slot.start + timedelta(minutes=10), end=slot.start + timedelta(minutes=70))
        with self.assertRaises(ValidationError):
            services.book_session(actor=self.captain, request=self.request(), slot=slot)

    def test_nothing_can_be_booked_once_the_development_phase_is_over(self):
        request, slot = self.request(), self.slot()
        with patch('hackathons.services.timezone.now', return_value=self.event.submission_deadline + timedelta(hours=1)):
            with self.assertRaises(ValidationError):
                services.book_session(actor=self.captain, request=request, slot=slot)

    def test_a_workshop_cannot_be_published_over_a_booked_appointment(self):
        slot = self.slot(self.mentor, in_minutes=100)
        self.book(slot=slot)
        with self.assertRaises(ValidationError):
            services.create_workshop(actor=self.owner, hackathon=self.event, trainer=self.mentor, title='Atelier', description='',
                capacity=5, start=slot.start, end=slot.start + timedelta(minutes=60), location='A', url='')


class CancelSessionTests(LiveBase):
    def test_captain_mentor_and_organizer_may_cancel_before_the_start(self):
        for actor, who in (('captain', 'team'), ('mentor', 'mentor'), ('owner', 'organizer')):
            with self.subTest(actor=actor):
                request, slot = self.request(subject=actor), self.slot(in_minutes=60 + 60 * ['captain', 'mentor', 'owner'].index(actor))
                session = self.book(request=request, slot=slot)
                services.cancel_session(actor=getattr(self, actor), session=session)
                session.refresh_from_db()
                request.refresh_from_db()
                self.assertEqual((session.status, request.status, session.cancelled_by), ('CANCELLED', 'OPEN', getattr(self, actor)))
                self.assertEqual(MentorSlot.objects.get(pk=slot.pk).availability, 'AVAILABLE')
                self.assertEqual(M4History.objects.filter(action='session.cancelled', object_id=session.pk).get().details['by'], who)

    def test_a_simple_member_or_a_stranger_cannot_cancel(self):
        session = self.book()
        for actor in (self.member, self.outsider, self.rival_captain, self.mentor2):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                services.cancel_session(actor=actor, session=session)
        session.refresh_from_db()
        self.assertEqual(session.status, 'BOOKED')

    def test_a_started_or_cancelled_appointment_cannot_be_cancelled(self):
        started = self.past_session()
        with self.assertRaises(ValidationError):
            services.cancel_session(actor=self.captain, session=started)
        session = self.book(request=self.request(subject='Autre'))
        services.cancel_session(actor=self.captain, session=session)
        with self.assertRaises(ValidationError):
            services.cancel_session(actor=self.captain, session=session)

    def test_after_a_cancellation_the_team_can_book_again_and_the_history_keeps_both(self):
        request, slot = self.request(), self.slot()
        first = self.book(request=request, slot=slot)
        services.cancel_session(actor=self.captain, session=first)
        second = services.book_session(actor=self.captain, request=request, slot=slot)
        self.assertEqual([s.status for s in request.sessions.order_by('id')], ['CANCELLED', 'BOOKED'])
        self.assertNotEqual(first.pk, second.pk)


class BookingConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = make_owner()
        self.event = make_ongoing_event(self.owner)
        self.mentor = make_user('mentor')
        set_role(actor=self.owner, user=self.mentor, hackathon=self.event, role=Role.MENTOR)
        self.captains = [make_user('cap1'), make_user('cap2')]
        self.requests = [make_request(make_team(self.event, user, name=f'Team {i}'), user) for i, user in enumerate(self.captains)]
        start = timezone.now().replace(second=0, microsecond=0) + timedelta(hours=1)
        self.slot = MentorSlot.objects.create(hackathon=self.event, mentor=self.mentor, start=start, end=start + timedelta(minutes=45))

    def test_two_teams_booking_the_same_slot_at_once_get_one_success(self):
        barrier = Barrier(2)

        def attempt(index):
            try:
                actor = User.objects.get(pk=self.captains[index].pk)
                request = SupportRequest.objects.get(pk=self.requests[index].pk)
                slot = MentorSlot.objects.get(pk=self.slot.pk)
                barrier.wait(timeout=10)
                services.book_session(actor=actor, request=request, slot=slot)
                return 'ok'
            except ValidationError:
                return 'refused'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            result = list(executor.map(attempt, [0, 1]))
        self.assertCountEqual(result, ['ok', 'refused'])
        self.assertEqual(MentoringSession.objects.filter(slot=self.slot, status='BOOKED').count(), 1)
        self.assertEqual(SupportRequest.objects.filter(status='BOOKED').count(), 1)
        self.assertEqual(SupportRequest.objects.filter(status='OPEN').count(), 1)


class BookingViewTests(LiveBase):
    def book_url(self, request):
        return reverse('mentoring:support-book', args=[request.pk])

    def slot_url(self, request, slot):
        return reverse('mentoring:support-book-slot', args=[request.pk, slot.pk])

    def test_anonymous_is_sent_to_login(self):
        request = self.request()
        for url in (self.book_url(request), reverse('mentoring:appointments')):
            self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.post(self.slot_url(request, self.slot())).status_code, 302)

    def test_the_captain_sees_the_free_slots_with_the_mentor_expertise(self):
        MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=5)
        request, slot = self.request(), self.slot()
        self.client.force_login(self.captain)
        page = self.client.get(self.book_url(request))
        for text in ('Réserver un mentor', 'Créneaux disponibles', 'mentor', 'Django · 5/5', 'Réserver'):
            self.assertContains(page, text)
        self.assertContains(page, self.slot_url(request, slot))
        self.assertContains(page, '<time datetime=')
        self.assertContains(page, '<h1', count=1)

    def test_a_simple_member_can_look_but_not_book(self):
        request, slot = self.request(), self.slot()
        self.client.force_login(self.member)
        page = self.client.get(self.book_url(request))
        self.assertContains(page, 'Vous ne pouvez pas réserver pour le moment.')
        self.assertNotContains(page, self.slot_url(request, slot))
        self.assertEqual(self.client.post(self.slot_url(request, slot), follow=True).redirect_chain[-1][0], self.book_url(request))
        self.assertFalse(MentoringSession.objects.exists())

    def test_booking_redirects_to_the_appointment(self):
        request, slot = self.request(), self.slot()
        self.client.force_login(self.captain)
        response = self.client.post(self.slot_url(request, slot), follow=True)
        session = MentoringSession.objects.get()
        self.assertEqual(response.redirect_chain[-1][0], session.get_absolute_url())
        self.assertContains(response, 'Rendez-vous réservé.')
        self.assertContains(self.client.get(request.get_absolute_url()), 'Un rendez-vous est réservé')

    def test_a_slot_taken_in_the_meantime_shows_a_clear_message(self):
        request, slot = self.request(), self.slot()
        self.book(request=self.request(team=self.rival), slot=slot)
        self.client.force_login(self.captain)
        response = self.client.post(self.slot_url(request, slot), follow=True)
        self.assertContains(response, 'vient d’être réservé par une autre équipe')
        self.assertEqual(response.redirect_chain[-1][0], self.book_url(request))

    def test_booking_needs_a_post_and_a_slot_of_the_same_edition(self):
        request, slot = self.request(), self.slot()
        self.client.force_login(self.captain)
        self.assertEqual(self.client.get(self.slot_url(request, slot)).status_code, 405)
        other_event = make_ongoing_event(self.owner, 'other')
        set_role(actor=self.owner, user=self.mentor, hackathon=other_event, role=Role.MENTOR)
        start = self.now() + timedelta(minutes=30)
        foreign = MentorSlot.objects.create(hackathon=other_event, mentor=self.mentor, start=start, end=start + timedelta(minutes=30))
        self.assertEqual(self.client.post(self.slot_url(request, foreign)).status_code, 404)

    def test_another_team_or_a_stranger_gets_a_404(self):
        request, slot = self.request(), self.slot()
        for user in (self.rival_captain, self.outsider, self.mentor):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertEqual(self.client.get(self.book_url(request)).status_code, 404)
                self.assertEqual(self.client.post(self.slot_url(request, slot)).status_code, 404)

    def test_the_skill_filter_and_the_empty_states(self):
        request = self.request()
        self.client.force_login(self.captain)
        self.assertContains(self.client.get(self.book_url(request)), 'Aucun créneau disponible pour l’instant')
        self.slot(self.mentor2)
        self.slot(self.mentor, in_minutes=200)
        MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=4)
        both = self.client.get(self.book_url(request))
        self.assertContains(both, 'mentor2')
        filtered = self.client.get(self.book_url(request), {'skill': self.django.pk})
        self.assertNotContains(filtered, 'mentor2')
        self.assertContains(filtered, 'Réinitialiser')
        MentorExpertise.objects.all().delete()
        self.assertContains(self.client.get(self.book_url(request), {'skill': self.django.pk}), 'Aucun mentor disponible n’a déclaré cette compétence')

    def test_the_request_page_offers_the_booking_to_the_captain_only(self):
        request = self.request()
        self.client.force_login(self.captain)
        self.assertContains(self.client.get(request.get_absolute_url()), self.book_url(request))
        self.client.force_login(self.member)
        page = self.client.get(request.get_absolute_url())
        self.assertNotContains(page, self.book_url(request))
        self.assertContains(page, 'Le capitaine de l’équipe réserve le mentor.')
