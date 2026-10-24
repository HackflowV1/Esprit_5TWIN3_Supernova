"""The data model of the M4 plan: constraints, derived values and rules that no service can bypass."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone, translation

from accounts.models import Role, Skill, User
from accounts.services import set_role
from hackathons.test_helpers import make_event, make_owner
from .. import services
from ..models import M4History, MentoringSession, MentorExpertise, MentorSlot, SupportRequest, Workshop, WorkshopRegistration
from .helpers import book_slot, make_request, make_team, make_user
from .test_slots import published_event
from teams.models import Registration


class PlanBase(TestCase):
    def setUp(self):
        translation.activate('fr')
        self.addCleanup(translation.deactivate)

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.event = published_event(cls.owner)
        cls.mentor = make_user('mentor')
        cls.captain = make_user('captain')
        cls.member = make_user('member')
        set_role(actor=cls.owner, user=cls.mentor, hackathon=cls.event, role=Role.MENTOR)
        cls.team = make_team(cls.event, cls.captain, members=[cls.member])

    def at(self, hours, minutes=0):
        return self.event.start_date + timedelta(hours=hours, minutes=minutes)

    def slot(self, hours=1, minutes=30, mentor=None):
        return MentorSlot.objects.create(hackathon=self.event, mentor=mentor or self.mentor, start=self.at(hours), end=self.at(hours, minutes))

    def request(self, **overrides):
        return make_request(self.team, self.captain, **overrides)

    def workshop(self, hours=1, capacity=3):
        return Workshop.objects.create(hackathon=self.event, trainer=self.mentor, title='API', capacity=capacity,
            start=self.at(hours), end=self.at(hours + 1), location='Salle A')


class ExpertiseAndCalendarTests(PlanBase):
    def test_expertise_has_an_optional_presentation(self):
        skill = Skill.objects.create(name='Django', category='Backend')
        item = MentorExpertise.objects.create(user=self.mentor, skill=skill, level=5, description='Je réponds sur DRF et les tests.')
        item.refresh_from_db()
        self.assertEqual(item.description, 'Je réponds sur DRF et les tests.')
        self.assertEqual(MentorExpertise.objects.create(user=self.mentor, skill=Skill.objects.create(name='React', category='Front')).description, '')

    def test_slot_must_be_inside_the_development_phase_not_just_the_event(self):
        deadline = self.event.submission_deadline
        with self.assertRaises(ValidationError) as caught:
            MentorSlot.objects.create(hackathon=self.event, mentor=self.mentor, start=deadline + timedelta(minutes=10),
                end=deadline + timedelta(minutes=40))
        self.assertIn('phase de développement', ' '.join(caught.exception.messages))
        MentorSlot.objects.create(hackathon=self.event, mentor=self.mentor, start=deadline - timedelta(minutes=40), end=deadline - timedelta(minutes=10))

    def test_workshop_must_be_inside_the_development_phase(self):
        deadline = self.event.submission_deadline
        with self.assertRaises(ValidationError):
            Workshop.objects.create(hackathon=self.event, trainer=self.mentor, title='Tard', capacity=5, location='A',
                start=deadline + timedelta(minutes=5), end=deadline + timedelta(minutes=65))

    def test_an_event_without_a_development_phase_has_no_slots(self):
        draft = make_event(self.owner, 'draft')
        set_role(actor=self.owner, user=self.mentor, hackathon=draft, role=Role.MENTOR)
        with self.assertRaises(ValidationError) as caught:
            MentorSlot.objects.create(hackathon=draft, mentor=self.mentor, start=draft.start_date + timedelta(hours=1),
                end=draft.start_date + timedelta(hours=2))
        self.assertIn('phase de développement', ' '.join(caught.exception.messages))


class SlotAvailabilityTests(PlanBase):
    def test_availability_is_computed_from_the_active_session(self):
        slot = self.slot()
        self.assertEqual((slot.availability, slot.is_published, slot.is_booked), ('AVAILABLE', True, False))
        session = book_slot(self.event, slot)
        slot = MentorSlot.objects.get(pk=slot.pk)
        self.assertEqual(slot.availability, 'BOOKED')
        session.status = MentoringSession.Status.CANCELLED
        session.save()
        self.assertEqual(MentorSlot.objects.get(pk=slot.pk).availability, 'AVAILABLE')

    def test_withdrawn_slot_and_queryset_helpers(self):
        free, booked, withdrawn = self.slot(1), self.slot(3), self.slot(5)
        book_slot(self.event, booked)
        withdrawn.withdrawn_at = timezone.now()
        withdrawn.save()
        self.assertEqual(MentorSlot.objects.get(pk=withdrawn.pk).availability, 'WITHDRAWN')
        self.assertEqual(list(MentorSlot.objects.available()), [free])
        self.assertCountEqual(MentorSlot.objects.published(), [free, booked])

    def test_prefetched_sessions_give_the_same_availability_without_extra_queries(self):
        slots = [self.slot(1), self.slot(3)]
        book_slot(self.event, slots[1])
        loaded = list(MentorSlot.objects.prefetch_related('sessions').order_by('start'))
        with self.assertNumQueries(0):
            self.assertEqual([s.availability for s in loaded], ['AVAILABLE', 'BOOKED'])

    def test_withdrawn_slots_do_not_block_new_ones(self):
        slot = self.slot(1, 60)
        slot.withdrawn_at = timezone.now()
        slot.save()
        self.slot(1, 60)


class MentoringSessionTests(PlanBase):
    def test_team_and_mentor_are_derived(self):
        session = book_slot(self.event, self.slot(), 'other')
        self.assertEqual((session.mentor, session.hackathon), (self.mentor, self.event))
        self.assertEqual(session.team.name, 'Team other')

    def test_one_active_session_per_slot_and_per_request_in_the_database(self):
        slot = self.slot()
        first = book_slot(self.event, slot)
        other_request = make_request(make_team(self.event, make_user('rival'), name='Rival'), make_user('rival'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            MentoringSession.objects.bulk_create([MentoringSession(request=other_request, slot=slot, booked_by=make_user('rival'))])
        second_slot = self.slot(3)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MentoringSession.objects.bulk_create([MentoringSession(request=first.request, slot=second_slot, booked_by=self.captain)])

    def test_a_cancelled_session_keeps_its_history_and_frees_the_slot_and_request(self):
        slot = self.slot()
        first = book_slot(self.event, slot)
        first.status = MentoringSession.Status.CANCELLED
        first.cancelled_at = timezone.now()
        first.save()
        again = MentoringSession.objects.create(request=first.request, slot=slot, booked_by=self.captain)
        self.assertEqual(first.request.sessions.count(), 2)
        self.assertEqual(again.status, 'BOOKED')

    def test_request_and_slot_must_belong_to_the_same_hackathon(self):
        other = published_event(self.owner, 'other')
        set_role(actor=self.owner, user=self.mentor, hackathon=other, role=Role.MENTOR)
        other_slot = MentorSlot.objects.create(hackathon=other, mentor=self.mentor, start=other.start_date + timedelta(hours=1),
            end=other.start_date + timedelta(hours=2))
        with self.assertRaises(ValidationError):
            MentoringSession.objects.create(request=self.request(), slot=other_slot, booked_by=self.captain)

    def test_a_mentor_cannot_coach_his_own_team(self):
        own_team = make_team(self.event, make_user('insider'), name='Insiders', members=[self.mentor])
        with self.assertRaises(ValidationError) as caught:
            MentoringSession.objects.create(request=make_request(own_team, own_team.captain.user), slot=self.slot(), booked_by=own_team.captain.user)
        self.assertIn('propre équipe', ' '.join(caught.exception.messages))

    def test_a_withdrawn_slot_cannot_be_booked(self):
        slot = self.slot()
        slot.withdrawn_at = timezone.now()
        slot.save()
        with self.assertRaises(ValidationError):
            MentoringSession.objects.create(request=self.request(), slot=slot, booked_by=self.captain)

    def test_feedback_is_separate_from_the_status_and_bounded(self):
        session = book_slot(self.event, self.slot())
        for rating in (0, 6):
            session.feedback_rating = rating
            with self.assertRaises(ValidationError):
                session.save()
        session.feedback_rating = 4
        session.feedback_comment = 'Très utile'
        session.save()
        self.assertEqual((session.status, session.feedback_rating), ('BOOKED', 4))
        with self.assertRaises(IntegrityError), transaction.atomic():
            MentoringSession.objects.filter(pk=session.pk).update(feedback_rating=9)


class SupportRequestModelTests(PlanBase):
    def test_defaults_and_activity(self):
        request = self.request()
        self.assertEqual((request.status, request.priority, request.is_active), ('OPEN', 'NORMAL', True))
        request.status = SupportRequest.Status.RESOLVED
        self.assertFalse(request.is_active)

    def test_team_must_belong_to_the_hackathon(self):
        other = published_event(self.owner, 'other')
        with self.assertRaises(ValidationError):
            SupportRequest.objects.create(hackathon=other, team=self.team, author=self.captain, subject='X', description='Y')

    def test_subject_cannot_be_blank(self):
        for subject in ('', '   '):
            with self.subTest(subject=repr(subject)), self.assertRaises(ValidationError):
                self.request(subject=subject)


class WorkshopRegistrationModelTests(PlanBase):
    def test_one_row_per_participant_and_workshop(self):
        workshop = self.workshop()
        registration = Registration.objects.get(user=self.captain, hackathon=self.event)
        WorkshopRegistration.objects.create(workshop=workshop, registration=registration)
        with self.assertRaises(ValidationError):
            WorkshopRegistration.objects.create(workshop=workshop, registration=registration)

    def test_registration_must_be_accepted_and_of_the_same_hackathon(self):
        workshop = self.workshop()
        other = published_event(self.owner, 'other')
        stranger = Registration.objects.create(user=make_user('stranger'), hackathon=other)
        with self.assertRaises(ValidationError):
            WorkshopRegistration.objects.create(workshop=workshop, registration=stranger)
        cancelled = Registration.objects.create(user=make_user('quit'), hackathon=self.event, status=Registration.Status.CANCELLED)
        with self.assertRaises(ValidationError):
            WorkshopRegistration.objects.create(workshop=workshop, registration=cancelled)

    def test_attendance_defaults_to_unknown(self):
        registration = Registration.objects.get(user=self.member, hackathon=self.event)
        item = WorkshopRegistration.objects.create(workshop=self.workshop(), registration=registration)
        self.assertEqual((item.status, item.attendance), ('REGISTERED', 'UNKNOWN'))


class HistoryTests(PlanBase):
    def test_slot_and_workshop_actions_are_recorded_with_their_author(self):
        slot = services.create_slot(actor=self.mentor, hackathon=self.event, start=self.at(1), end=self.at(1, 30))
        services.update_slot(actor=self.mentor, slot=slot, start=self.at(2), end=self.at(2, 30))
        services.cancel_slot(actor=self.mentor, slot=slot)
        entries = list(M4History.objects.filter(object_type='MentorSlot', object_id=slot.pk).order_by('id'))
        self.assertEqual([e.action for e in entries], ['slot.published', 'slot.updated', 'slot.withdrawn'])
        self.assertTrue(all(e.actor == self.mentor and e.hackathon == self.event for e in entries))
        self.assertIn('before', entries[1].details)
        self.assertEqual(entries[1].details['after']['start'][:10], timezone.localtime(self.at(2)).isoformat()[:10])

    def test_workshop_actions_are_recorded(self):
        workshop = services.create_workshop(actor=self.owner, trainer=self.mentor, hackathon=self.event, title='API', description='', capacity=4,
            start=self.at(1), end=self.at(2), location='Salle A', url='')
        services.update_workshop(actor=self.owner, trainer=self.mentor, workshop=workshop, title='API 2', description='', capacity=6,
            start=self.at(1), end=self.at(2), location='Salle A', url='')
        services.cancel_workshop(actor=self.owner, workshop=workshop)
        actions = list(M4History.objects.filter(object_type='Workshop', object_id=workshop.pk).order_by('id').values_list('action', flat=True))
        self.assertEqual(actions, ['workshop.published', 'workshop.updated', 'workshop.cancelled'])

    def test_a_workshop_with_registrations_keeps_its_schedule_and_enough_seats(self):
        workshop = self.workshop(capacity=3)
        for name in ('p1', 'p2'):
            WorkshopRegistration.objects.create(workshop=workshop, registration=Registration.objects.create(user=make_user(name), hackathon=self.event))
        with self.assertRaises(ValidationError):
            services.update_workshop(actor=self.owner, trainer=self.mentor, workshop=workshop, title='API', description='', capacity=1,
                start=workshop.start, end=workshop.end, location='Salle A', url='')
        with self.assertRaises(ValidationError):
            services.update_workshop(actor=self.owner, trainer=self.mentor, workshop=workshop, title='API', description='', capacity=3,
                start=self.at(4), end=self.at(5), location='Salle A', url='')
        services.update_workshop(actor=self.owner, trainer=self.mentor, workshop=workshop, title='API+', description='', capacity=2,
            start=workshop.start, end=workshop.end, location='Salle B', url='')
        workshop.refresh_from_db()
        self.assertEqual((workshop.title, workshop.capacity, workshop.location), ('API+', 2, 'Salle B'))


class ScreenTests(PlanBase):
    def test_expertise_presentation_is_saved_and_shown(self):
        from django.urls import reverse
        skill = Skill.objects.create(name='Django', category='Backend')
        self.client.force_login(self.mentor)
        response = self.client.post(reverse('mentoring:expertise-add'),
            {'skill': skill.pk, 'level': 5, 'description': 'Je réponds sur DRF et les tests.'}, follow=True)
        self.assertContains(response, 'Je réponds sur DRF et les tests.')
        self.assertContains(self.client.get(reverse('mentoring:expertise-add')), 'maxlength="500"')

    def test_booked_slot_is_shown_as_booked_without_edit_or_cancel_links(self):
        from django.urls import reverse
        slot = self.slot()
        self.client.force_login(self.mentor)
        page = self.client.get(reverse('mentoring:slot-list'))
        self.assertContains(page, reverse('mentoring:slot-cancel', args=[slot.pk]))
        book_slot(self.event, slot)
        page = self.client.get(reverse('mentoring:slot-list'))
        self.assertContains(page, 'Réservé')
        self.assertNotContains(page, reverse('mentoring:slot-cancel', args=[slot.pk]))
        self.assertNotContains(page, reverse('mentoring:slot-edit', args=[slot.pk]))
