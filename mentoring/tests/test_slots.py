from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AssignmentStatus, Role, User
from accounts.services import set_role
from hackathons.models import Hackathon
from hackathons.services import transition
from hackathons.test_helpers import make_event, make_owner
from .. import services
from .helpers import book_slot
from ..models import MentorSlot

FORMAT = '%Y-%m-%dT%H:%M'


def published_event(owner, slug='edition'):
    return transition(actor=owner, event=make_event(owner, slug, complete=True), target='PUBLISHED')


def local(value):
    return timezone.localtime(value).strftime(FORMAT)


class SlotBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.event = published_event(cls.owner)
        cls.draft = make_event(cls.owner, 'draft')
        cls.mentor = User.objects.create_user(username='mentor', email='mentor@example.test')
        cls.rival = User.objects.create_user(username='rival', email='rival@example.test')
        cls.member = User.objects.create_user(username='member', email='member@example.test')
        for user in (cls.mentor, cls.rival):
            set_role(actor=cls.owner, user=user, hackathon=cls.event, role=Role.MENTOR)
        set_role(actor=cls.owner, user=cls.mentor, hackathon=cls.draft, role=Role.MENTOR)
        set_role(actor=cls.owner, user=cls.member, hackathon=cls.event, role=Role.PARTICIPANT)

    def at(self, hours, minutes=0):
        return self.event.start_date + timedelta(hours=hours, minutes=minutes)

    def make(self, hours=1, minutes=30, mentor=None, event=None):
        return MentorSlot.objects.create(hackathon=event or self.event, mentor=mentor or self.mentor,
            start=self.at(hours), end=self.at(hours, minutes))


class SlotModelTests(SlotBase):
    def test_valid_slot(self):
        slot = self.make()
        self.assertEqual(slot.availability, 'AVAILABLE')
        self.assertEqual(slot.duration_minutes, 30)

    def test_end_must_follow_start(self):
        for end in (self.at(1), self.at(0)):
            with self.subTest(end=end), self.assertRaises(ValidationError):
                MentorSlot.objects.create(hackathon=self.event, mentor=self.mentor, start=self.at(1), end=end)

    def test_duration_is_bounded(self):
        for minutes in (10, 121, 600):
            with self.subTest(minutes=minutes), self.assertRaises(ValidationError):
                self.make(minutes=minutes)
        self.make(hours=1, minutes=15)
        self.make(hours=3, minutes=120)

    def test_slot_must_fit_inside_the_event(self):
        for start, end in ((self.event.start_date - timedelta(hours=1), self.event.start_date + timedelta(minutes=30)),
                           (self.event.end_date - timedelta(minutes=10), self.event.end_date + timedelta(minutes=20))):
            with self.subTest(start=start), self.assertRaises(ValidationError):
                MentorSlot.objects.create(hackathon=self.event, mentor=self.mentor, start=start, end=end)

    def test_mentor_role_is_required_in_that_hackathon(self):
        with self.assertRaises(ValidationError):
            self.make(mentor=self.member)
        other = published_event(self.owner, 'other')
        with self.assertRaises(ValidationError):
            self.make(event=other)

    def test_revoked_mentor_is_rejected(self):
        set_role(actor=self.owner, user=self.mentor, hackathon=self.event, role=Role.MENTOR, status=AssignmentStatus.REVOKED)
        with self.assertRaises(ValidationError):
            self.make()

    def test_a_mentor_cannot_overlap_himself(self):
        self.make(hours=1, minutes=60)
        with self.assertRaises(ValidationError):
            MentorSlot.objects.create(hackathon=self.event, mentor=self.mentor, start=self.at(1, 30), end=self.at(2, 30))
        with self.assertRaises(ValidationError):
            MentorSlot.objects.create(hackathon=self.event, mentor=self.mentor, start=self.at(0, 30), end=self.at(1, 15))
        self.assertEqual(MentorSlot.objects.count(), 1)

    def test_back_to_back_slots_are_allowed(self):
        self.make(hours=1, minutes=60)
        MentorSlot.objects.create(hackathon=self.event, mentor=self.mentor, start=self.at(2), end=self.at(2, 30))

    def test_overlap_is_checked_across_hackathons(self):
        second = published_event(self.owner, 'second')
        set_role(actor=self.owner, user=self.mentor, hackathon=second, role=Role.MENTOR)
        self.make(hours=1, minutes=60)
        with self.assertRaises(ValidationError):
            MentorSlot.objects.create(hackathon=second, mentor=self.mentor, start=self.at(1, 15), end=self.at(1, 45))

    def test_two_mentors_may_share_the_same_time(self):
        self.make(hours=1)
        self.make(hours=1, mentor=self.rival)
        self.assertEqual(MentorSlot.objects.count(), 2)

    def test_cancelled_slot_frees_the_time_and_can_always_be_saved(self):
        slot = self.make(hours=1)
        slot.withdrawn_at = timezone.now()
        slot.save()
        self.make(hours=1)
        set_role(actor=self.owner, user=self.mentor, hackathon=self.event, role=Role.MENTOR, status=AssignmentStatus.REVOKED)
        slot.save()  # cancelled slot stays saveable even after the role is revoked

    def test_archived_event_is_refused(self):
        Hackathon.objects.filter(pk=self.event.pk).update(status='ARCHIVED')
        with self.assertRaises(ValidationError):
            MentorSlot.objects.create(hackathon=Hackathon.objects.get(pk=self.event.pk), mentor=self.mentor,
                start=self.at(1), end=self.at(1, 30))

    def test_database_constraint_backs_up_validation(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            MentorSlot.objects.bulk_create([MentorSlot(hackathon=self.event, mentor=self.mentor, start=self.at(2), end=self.at(1))])


class SlotServiceTests(SlotBase):
    def test_create_slot(self):
        slot = services.create_slot(actor=self.mentor, hackathon=self.event, start=self.at(1), end=self.at(1, 30))
        self.assertEqual((slot.mentor, slot.hackathon, slot.availability), (self.mentor, self.event, 'AVAILABLE'))

    def test_only_a_mentor_of_that_hackathon_can_create(self):
        with self.assertRaises(PermissionDenied):
            services.create_slot(actor=self.member, hackathon=self.event, start=self.at(1), end=self.at(1, 30))
        with self.assertRaises(PermissionDenied):
            services.create_slot(actor=self.rival, hackathon=self.draft, start=self.at(1), end=self.at(1, 30))
        self.assertFalse(MentorSlot.objects.exists())

    def test_hackathon_must_be_published_or_ongoing(self):
        with self.assertRaises(ValidationError):
            services.create_slot(actor=self.mentor, hackathon=self.draft, start=self.at(1), end=self.at(1, 30))
        self.assertFalse(MentorSlot.objects.exists())

    def test_slot_must_start_in_the_future(self):
        with patch('mentoring.services.timezone.now', return_value=self.at(2)):
            with self.assertRaises(ValidationError):
                services.create_slot(actor=self.mentor, hackathon=self.event, start=self.at(1), end=self.at(1, 30))

    def test_update_slot(self):
        slot = self.make(hours=1)
        services.update_slot(actor=self.mentor, slot=slot, start=self.at(3), end=self.at(3, 45))
        slot.refresh_from_db()
        self.assertEqual((slot.start, slot.duration_minutes), (self.at(3), 45))

    def test_update_cannot_create_an_overlap(self):
        self.make(hours=1)
        other = self.make(hours=3)
        with self.assertRaises(ValidationError):
            services.update_slot(actor=self.mentor, slot=other, start=self.at(1, 10), end=self.at(1, 40))
        other.refresh_from_db()
        self.assertEqual(other.start, self.at(3))

    def test_booked_slot_cannot_be_changed_or_cancelled(self):
        slot = self.make()
        book_slot(self.event, slot)
        with self.assertRaises(ValidationError):
            services.update_slot(actor=self.mentor, slot=slot, start=self.at(3), end=self.at(3, 30))
        with self.assertRaises(ValidationError):
            services.cancel_slot(actor=self.mentor, slot=slot)
        slot.refresh_from_db()
        self.assertEqual(slot.availability, 'BOOKED')

    def test_started_slot_cannot_be_changed(self):
        slot = self.make(hours=1)
        with patch('mentoring.services.timezone.now', return_value=self.at(1, 10)):
            with self.assertRaises(ValidationError):
                services.update_slot(actor=self.mentor, slot=slot, start=self.at(3), end=self.at(3, 30))

    def test_nobody_touches_another_mentors_slot(self):
        slot = self.make()
        with self.assertRaises(PermissionDenied):
            services.update_slot(actor=self.rival, slot=slot, start=self.at(3), end=self.at(3, 30))
        with self.assertRaises(PermissionDenied):
            services.cancel_slot(actor=self.rival, slot=slot)
        slot.refresh_from_db()
        self.assertEqual((slot.start, slot.availability), (self.at(1), 'AVAILABLE'))

    def test_cancel_slot(self):
        slot = self.make()
        services.cancel_slot(actor=self.mentor, slot=slot)
        slot.refresh_from_db()
        self.assertEqual(slot.availability, 'WITHDRAWN')


class SlotViewTests(SlotBase):
    def setUp(self):
        self.list_url = reverse('mentoring:slot-list')
        self.add_url = reverse('mentoring:slot-add')

    def post_slot(self, start, end, hackathon=None, url=None):
        return self.client.post(url or self.add_url, {'hackathon': (hackathon or self.event).pk, 'start': local(start), 'end': local(end)})

    def test_anonymous_is_sent_to_login(self):
        slot = self.make()
        for url in (self.list_url, self.add_url, reverse('mentoring:slot-edit', args=[slot.pk]), reverse('mentoring:slot-cancel', args=[slot.pk])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('accounts:login'), response['Location'])

    def test_non_mentor_gets_403_on_every_slot_url(self):
        slot = self.make()
        self.client.force_login(self.member)
        for url in (self.list_url, self.add_url, reverse('mentoring:slot-edit', args=[slot.pk]), reverse('mentoring:slot-cancel', args=[slot.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(reverse('mentoring:slot-cancel', args=[slot.pk])).status_code, 403)
        self.assertEqual(self.post_slot(self.at(5), self.at(5, 30)).status_code, 403)
        slot.refresh_from_db()
        self.assertEqual(slot.availability, 'AVAILABLE')
        self.assertEqual(MentorSlot.objects.count(), 1)

    def test_empty_list_then_create(self):
        self.client.force_login(self.mentor)
        self.assertContains(self.client.get(self.list_url), 'Aucun créneau à venir')
        response = self.post_slot(self.at(1), self.at(1, 30))
        self.assertRedirects(response, self.list_url, fetch_redirect_response=False)
        page = self.client.get(self.list_url)
        self.assertContains(page, 'Créneau publié')
        self.assertContains(page, '<time datetime=')
        self.assertContains(page, 'aria-label="Mentorat et ateliers"')
        self.assertEqual(MentorSlot.objects.get().duration_minutes, 30)

    def test_overlap_is_reported_under_the_form(self):
        self.make(hours=1, minutes=60)
        self.client.force_login(self.mentor)
        response = self.post_slot(self.at(1, 30), self.at(2, 30))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'chevauche')
        self.assertEqual(MentorSlot.objects.count(), 1)

    def test_invalid_input_is_rejected_by_the_server(self):
        self.client.force_login(self.mentor)
        response = self.post_slot(self.at(2), self.at(1))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MentorSlot.objects.exists())
        response = self.client.post(self.add_url, {'hackathon': self.event.pk, 'start': 'pas une date', 'end': ''})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MentorSlot.objects.exists())

    def test_only_open_hackathons_where_the_user_mentors_are_offered(self):
        self.client.force_login(self.mentor)
        page = self.client.get(self.add_url)
        self.assertContains(page, self.event.title)
        self.assertNotContains(page, self.draft.title)
        response = self.post_slot(self.at(1), self.at(1, 30), hackathon=self.draft)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MentorSlot.objects.exists())

    def test_notice_when_no_hackathon_is_open(self):
        lone = User.objects.create_user(username='lone', email='lone@example.test')
        set_role(actor=self.owner, user=lone, hackathon=self.draft, role=Role.MENTOR)
        self.client.force_login(lone)
        page = self.client.get(self.list_url)
        self.assertContains(page, 'Aucun hackathon ouvert')
        self.assertNotContains(page, 'Publier un créneau')

    def test_edit_changes_times_but_not_hackathon(self):
        slot = self.make(hours=1)
        self.client.force_login(self.mentor)
        url = reverse('mentoring:slot-edit', args=[slot.pk])
        self.assertContains(self.client.get(url), local(slot.start))
        other = published_event(self.owner, 'other')
        self.post_slot(self.at(4), self.at(4, 45), hackathon=other, url=url)
        slot.refresh_from_db()
        self.assertEqual((slot.start, slot.duration_minutes, slot.hackathon), (self.at(4), 45, self.event))

    def test_another_mentor_gets_404_on_edit_and_cancel(self):
        slot = self.make()
        self.client.force_login(self.rival)
        self.assertEqual(self.client.get(reverse('mentoring:slot-edit', args=[slot.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('mentoring:slot-cancel', args=[slot.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('mentoring:slot-cancel', args=[slot.pk])).status_code, 404)
        self.assertEqual(list(self.client.get(self.list_url).context['days']), [])

    def test_cancel_needs_a_post_and_get_changes_nothing(self):
        slot = self.make()
        self.client.force_login(self.mentor)
        url = reverse('mentoring:slot-cancel', args=[slot.pk])
        self.assertContains(self.client.get(url), 'Annuler ce créneau ?')
        slot.refresh_from_db()
        self.assertEqual(slot.availability, 'AVAILABLE')
        response = self.client.post(url, follow=True)
        self.assertContains(response, 'Créneau annulé')
        slot.refresh_from_db()
        self.assertEqual(slot.availability, 'WITHDRAWN')
        self.assertContains(response, 'Passés et annulés')

    def test_booked_slot_cannot_be_cancelled_from_the_page(self):
        slot = self.make()
        book_slot(self.event, slot)
        self.client.force_login(self.mentor)
        response = self.client.post(reverse('mentoring:slot-cancel', args=[slot.pk]), follow=True)
        self.assertContains(response, 'Seul un créneau disponible')
        slot.refresh_from_db()
        self.assertEqual(slot.availability, 'BOOKED')


class SlotConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = make_owner()
        self.event = published_event(self.owner)
        self.mentor = User.objects.create_user(username='mentor', email='mentor@example.test')
        set_role(actor=self.owner, user=self.mentor, hackathon=self.event, role=Role.MENTOR)

    def test_simultaneous_overlapping_slots_are_serialized(self):
        barrier = Barrier(2)
        start = self.event.start_date + timedelta(hours=1)

        def publish(offset):
            try:
                actor = User.objects.get(pk=self.mentor.pk)
                event = Hackathon.objects.get(pk=self.event.pk)
                barrier.wait(timeout=10)
                services.create_slot(actor=actor, hackathon=event,
                    start=start + timedelta(minutes=offset), end=start + timedelta(minutes=offset + 60))
                return 'ok'
            except ValidationError:
                return 'rejected'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            result = list(executor.map(publish, [0, 30]))
        self.assertCountEqual(result, ['ok', 'rejected'])
        self.assertEqual(MentorSlot.objects.count(), 1)
