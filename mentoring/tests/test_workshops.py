from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import AssignmentStatus, Role, User
from accounts.services import set_role
from hackathons.models import Hackathon
from hackathons.test_helpers import make_event, make_owner
from .. import services
from ..models import Workshop
from .test_slots import local, published_event


class WorkshopBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.event = published_event(cls.owner)
        cls.draft = make_event(cls.owner, 'draft')
        cls.trainer = User.objects.create_user(username='trainer', email='trainer@example.test')
        cls.rival = User.objects.create_user(username='rival', email='rival@example.test')
        cls.member = User.objects.create_user(username='member', email='member@example.test')
        cls.outsider = User.objects.create_user(username='outsider', email='outsider@example.test')
        for user in (cls.trainer, cls.rival):
            set_role(actor=cls.owner, user=user, hackathon=cls.event, role=Role.MENTOR)
        set_role(actor=cls.owner, user=cls.trainer, hackathon=cls.draft, role=Role.MENTOR)
        set_role(actor=cls.owner, user=cls.member, hackathon=cls.event, role=Role.PARTICIPANT)

    def at(self, hours, minutes=0):
        return self.event.start_date + timedelta(hours=hours, minutes=minutes)

    def data(self, **overrides):
        data = {'title': 'Atelier API Django', 'description': 'Construire une API REST.', 'capacity': 20,
            'start': self.at(1), 'end': self.at(2), 'location': 'Salle A', 'url': ''}
        data.update(overrides)
        return data

    def make(self, trainer=None, event=None, **overrides):
        return Workshop.objects.create(hackathon=event or self.event, trainer=trainer or self.trainer, **self.data(**overrides))


class WorkshopModelTests(WorkshopBase):
    def test_valid_workshop(self):
        workshop = self.make()
        self.assertEqual((workshop.status, workshop.duration_minutes, str(workshop)), ('PUBLISHED', 60, 'Atelier API Django'))

    def test_end_must_follow_start(self):
        with self.assertRaises(ValidationError):
            self.make(start=self.at(2), end=self.at(1))

    def test_duration_is_bounded(self):
        for end in (self.at(1, 10), self.at(1) + timedelta(minutes=241)):
            with self.subTest(end=end), self.assertRaises(ValidationError):
                self.make(end=end)
        self.make(start=self.at(1), end=self.at(1, 15))
        self.make(start=self.at(3), end=self.at(7))

    def test_capacity_must_be_between_1_and_the_maximum(self):
        for capacity in (0, Workshop.MAX_CAPACITY + 1):
            with self.subTest(capacity=capacity), self.assertRaises(ValidationError):
                self.make(capacity=capacity)

    def test_a_room_or_a_link_is_required(self):
        with self.assertRaises(ValidationError):
            self.make(location='  ', url='')
        self.make(location='', url='https://meet.example.test/atelier')

    def test_workshop_must_fit_inside_the_event(self):
        with self.assertRaises(ValidationError):
            self.make(start=self.event.start_date - timedelta(hours=1), end=self.event.start_date + timedelta(minutes=30))
        with self.assertRaises(ValidationError):
            self.make(start=self.event.end_date - timedelta(minutes=10), end=self.event.end_date + timedelta(minutes=50))

    def test_trainer_must_be_a_mentor_of_that_hackathon(self):
        with self.assertRaises(ValidationError):
            self.make(trainer=self.member)
        other = published_event(self.owner, 'other')
        with self.assertRaises(ValidationError):
            self.make(event=other)

    def test_revoked_mentor_cannot_be_trainer(self):
        set_role(actor=self.owner, user=self.trainer, hackathon=self.event, role=Role.MENTOR, status=AssignmentStatus.REVOKED)
        with self.assertRaises(ValidationError):
            self.make()

    def test_trainer_cannot_teach_two_workshops_at_once(self):
        self.make(start=self.at(1), end=self.at(2))
        with self.assertRaises(ValidationError):
            self.make(start=self.at(1, 30), end=self.at(2, 30))
        self.make(start=self.at(2), end=self.at(3))  # back to back is fine
        self.make(trainer=self.rival, start=self.at(1), end=self.at(2))  # another trainer, same hour
        self.assertEqual(Workshop.objects.count(), 3)

    def test_cancelled_workshop_frees_the_time_and_stays_saveable(self):
        workshop = self.make()
        workshop.status = Workshop.Status.CANCELLED
        workshop.save()
        self.make()
        set_role(actor=self.owner, user=self.trainer, hackathon=self.event, role=Role.MENTOR, status=AssignmentStatus.REVOKED)
        workshop.save()

    def test_archived_event_is_refused(self):
        Hackathon.objects.filter(pk=self.event.pk).update(status='ARCHIVED')
        with self.assertRaises(ValidationError):
            self.make(event=Hackathon.objects.get(pk=self.event.pk))

    def test_database_constraints_back_up_validation(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Workshop.objects.bulk_create([Workshop(hackathon=self.event, trainer=self.trainer, title='x', capacity=5,
                location='A', start=self.at(2), end=self.at(1))])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Workshop.objects.bulk_create([Workshop(hackathon=self.event, trainer=self.trainer, title='x', capacity=0,
                location='A', start=self.at(1), end=self.at(2))])


class WorkshopServiceTests(WorkshopBase):
    def create(self, actor=None, event=None, **overrides):
        return services.create_workshop(actor=actor or self.trainer, hackathon=event or self.event, **self.data(**overrides))

    def test_create_workshop(self):
        workshop = self.create(title='  Atelier React  ')
        self.assertEqual((workshop.title, workshop.trainer, workshop.status), ('Atelier React', self.trainer, 'PUBLISHED'))

    def test_only_a_mentor_of_that_hackathon_can_create(self):
        with self.assertRaises(PermissionDenied):
            self.create(actor=self.member)
        with self.assertRaises(PermissionDenied):
            self.create(actor=self.rival, event=self.draft)
        self.assertFalse(Workshop.objects.exists())

    def test_hackathon_must_be_published_or_ongoing(self):
        with self.assertRaises(ValidationError):
            self.create(event=self.draft)
        self.assertFalse(Workshop.objects.exists())

    def test_workshop_must_start_in_the_future(self):
        with patch('mentoring.services.timezone.now', return_value=self.at(2)):
            with self.assertRaises(ValidationError):
                self.create()

    def test_update_workshop(self):
        workshop = self.make()
        services.update_workshop(actor=self.trainer, workshop=workshop, **self.data(title='Nouveau thème', capacity=8,
            start=self.at(3), end=self.at(4)))
        workshop.refresh_from_db()
        self.assertEqual((workshop.title, workshop.capacity, workshop.start), ('Nouveau thème', 8, self.at(3)))

    def test_update_cannot_create_an_overlap(self):
        self.make(start=self.at(1), end=self.at(2))
        other = self.make(start=self.at(4), end=self.at(5))
        with self.assertRaises(ValidationError):
            services.update_workshop(actor=self.trainer, workshop=other, **self.data(start=self.at(1, 30), end=self.at(2, 30)))
        other.refresh_from_db()
        self.assertEqual(other.start, self.at(4))

    def test_started_workshop_cannot_be_changed_or_cancelled(self):
        workshop = self.make()
        with patch('mentoring.services.timezone.now', return_value=self.at(1, 10)):
            with self.assertRaises(ValidationError):
                services.update_workshop(actor=self.trainer, workshop=workshop, **self.data(start=self.at(3), end=self.at(4)))
            with self.assertRaises(ValidationError):
                services.cancel_workshop(actor=self.trainer, workshop=workshop)

    def test_nobody_touches_another_trainers_workshop(self):
        workshop = self.make()
        with self.assertRaises(PermissionDenied):
            services.update_workshop(actor=self.rival, workshop=workshop, **self.data(title='Piraté'))
        with self.assertRaises(PermissionDenied):
            services.cancel_workshop(actor=self.rival, workshop=workshop)
        workshop.refresh_from_db()
        self.assertEqual((workshop.title, workshop.status), ('Atelier API Django', 'PUBLISHED'))

    def test_cancel_workshop_once(self):
        workshop = self.make()
        services.cancel_workshop(actor=self.trainer, workshop=workshop)
        workshop.refresh_from_db()
        self.assertEqual(workshop.status, 'CANCELLED')
        with self.assertRaises(ValidationError):
            services.cancel_workshop(actor=self.trainer, workshop=workshop)

    def test_visibility_follows_roles(self):
        workshop = self.make()
        self.assertIn(workshop, services.visible_workshops(self.member))
        self.assertIn(workshop, services.visible_workshops(self.trainer))
        self.assertNotIn(workshop, services.visible_workshops(self.outsider))
        self.assertEqual(services.visible_workshops(AnonymousUser()).count(), 0)
        boss = User.objects.create_superuser(username='boss', email='boss@example.test', password='x')
        self.assertIn(workshop, services.visible_workshops(boss))


class WorkshopViewTests(WorkshopBase):
    def setUp(self):
        self.list_url = reverse('mentoring:workshop-list')
        self.add_url = reverse('mentoring:workshop-add')

    def post(self, url=None, **overrides):
        data = self.data(hackathon=self.event.pk, **overrides)
        data['start'], data['end'] = local(data['start']), local(data['end'])
        return self.client.post(url or self.add_url, data)

    def test_anonymous_is_sent_to_login(self):
        workshop = self.make()
        urls = [self.list_url, self.add_url] + [reverse('mentoring:workshop-' + name, args=[workshop.pk]) for name in ('detail', 'edit', 'cancel')]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('accounts:login'), response['Location'])

    def test_members_see_published_workshops_and_outsiders_do_not(self):
        workshop = self.make()
        self.client.force_login(self.member)
        page = self.client.get(self.list_url)
        self.assertContains(page, 'Atelier API Django')
        self.assertContains(page, '<time datetime=')
        self.assertNotContains(page, 'Les ateliers que j’anime')
        self.assertEqual(self.client.get(workshop.get_absolute_url()).status_code, 200)
        self.client.force_login(self.outsider)
        self.assertNotContains(self.client.get(self.list_url), 'Atelier API Django')
        self.assertEqual(self.client.get(workshop.get_absolute_url()).status_code, 404)

    def test_detail_shows_practical_information_and_cancellation(self):
        workshop = self.make(url='https://meet.example.test/api')
        self.client.force_login(self.member)
        page = self.client.get(workshop.get_absolute_url())
        for text in ('Salle A', 'Rejoindre l’atelier', 'Construire une API REST.', '20'):
            self.assertContains(page, text)
        self.assertNotContains(page, 'Annuler l’atelier')
        services.cancel_workshop(actor=self.trainer, workshop=workshop)
        self.assertContains(self.client.get(workshop.get_absolute_url()), 'Cet atelier a été annulé')
        self.assertNotContains(self.client.get(self.list_url), 'Atelier API Django')

    def test_non_mentor_gets_403_on_management_urls(self):
        workshop = self.make()
        self.client.force_login(self.member)
        for name in ('edit', 'cancel'):
            self.assertEqual(self.client.get(reverse('mentoring:workshop-' + name, args=[workshop.pk])).status_code, 403)
        self.assertEqual(self.client.get(self.add_url).status_code, 403)
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.client.post(reverse('mentoring:workshop-cancel', args=[workshop.pk])).status_code, 403)
        self.assertEqual(Workshop.objects.count(), 1)

    def test_trainer_creates_a_workshop(self):
        self.client.force_login(self.trainer)
        self.assertContains(self.client.get(self.list_url), 'Les ateliers que j’anime')
        response = self.post(title='Atelier React', capacity=12)
        workshop = Workshop.objects.get()
        self.assertRedirects(response, workshop.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((workshop.title, workshop.capacity, workshop.trainer), ('Atelier React', 12, self.trainer))
        self.assertContains(self.client.get(workshop.get_absolute_url()), 'Atelier publié')

    def test_form_errors_are_reported_and_nothing_is_saved(self):
        self.client.force_login(self.trainer)
        response = self.post(location='', url='')
        self.assertContains(response, 'Indiquez une salle')
        self.make(start=self.at(1), end=self.at(2))
        response = self.post(start=self.at(1, 30), end=self.at(2, 30))
        self.assertContains(response, 'déjà un autre atelier')
        response = self.post(capacity=0)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Workshop.objects.count(), 1)

    def test_only_open_hackathons_of_the_mentor_are_offered(self):
        self.client.force_login(self.trainer)
        page = self.client.get(self.add_url)
        self.assertContains(page, self.event.title)
        self.assertNotContains(page, self.draft.title)
        data = self.data(hackathon=self.draft.pk)
        data['start'], data['end'] = local(data['start']), local(data['end'])
        self.assertEqual(self.client.post(self.add_url, data).status_code, 200)
        self.assertFalse(Workshop.objects.exists())

    def test_trainer_edits_but_cannot_move_it_to_another_hackathon(self):
        workshop = self.make()
        self.client.force_login(self.trainer)
        url = reverse('mentoring:workshop-edit', args=[workshop.pk])
        self.assertContains(self.client.get(url), 'Atelier API Django')
        other = published_event(self.owner, 'other')
        set_role(actor=self.owner, user=self.trainer, hackathon=other, role=Role.MENTOR)
        data = self.data(hackathon=other.pk, title='Thème modifié', start=self.at(3), end=self.at(4))
        data['start'], data['end'] = local(data['start']), local(data['end'])
        self.client.post(url, data)
        workshop.refresh_from_db()
        self.assertEqual((workshop.title, workshop.hackathon, workshop.start), ('Thème modifié', self.event, self.at(3)))

    def test_another_mentor_gets_404_on_edit_and_cancel(self):
        workshop = self.make()
        self.client.force_login(self.rival)
        for name in ('edit', 'cancel'):
            self.assertEqual(self.client.get(reverse('mentoring:workshop-' + name, args=[workshop.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('mentoring:workshop-cancel', args=[workshop.pk])).status_code, 404)
        self.assertEqual(list(self.client.get(self.list_url).context['mine']), [])
        workshop.refresh_from_db()
        self.assertEqual(workshop.status, 'PUBLISHED')

    def test_cancel_needs_a_post(self):
        workshop = self.make()
        self.client.force_login(self.trainer)
        url = reverse('mentoring:workshop-cancel', args=[workshop.pk])
        self.assertContains(self.client.get(url), 'Annuler cet atelier ?')
        workshop.refresh_from_db()
        self.assertEqual(workshop.status, 'PUBLISHED')
        self.assertContains(self.client.post(url, follow=True), 'Atelier annulé')
        workshop.refresh_from_db()
        self.assertEqual(workshop.status, 'CANCELLED')

    def test_cancelled_workshop_cannot_be_edited(self):
        workshop = self.make()
        services.cancel_workshop(actor=self.trainer, workshop=workshop)
        self.client.force_login(self.trainer)
        response = self.post(url=reverse('mentoring:workshop-edit', args=[workshop.pk]), title='Trop tard')
        self.assertContains(response, 'déjà annulé')
        workshop.refresh_from_db()
        self.assertEqual(workshop.title, 'Atelier API Django')

    def test_navigation_links(self):
        self.assertNotContains(self.client.get(reverse('core:home')), '>Ateliers</a>')
        self.client.force_login(self.member)
        self.assertContains(self.client.get(reverse('core:home')), '>Ateliers</a>')
        self.client.force_login(self.trainer)
        page = self.client.get(self.list_url)
        self.assertContains(page, 'aria-label="Espace mentor"')
        self.assertContains(page, '>Ateliers</a>')


class WorkshopConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = make_owner()
        self.event = published_event(self.owner)
        self.trainer = User.objects.create_user(username='trainer', email='trainer@example.test')
        set_role(actor=self.owner, user=self.trainer, hackathon=self.event, role=Role.MENTOR)

    def test_simultaneous_overlapping_workshops_are_serialized(self):
        barrier = Barrier(2)
        start = self.event.start_date + timedelta(hours=1)

        def publish(offset):
            try:
                actor = User.objects.get(pk=self.trainer.pk)
                event = Hackathon.objects.get(pk=self.event.pk)
                barrier.wait(timeout=10)
                services.create_workshop(actor=actor, hackathon=event, title=f'Atelier {offset}', description='',
                    capacity=10, start=start + timedelta(minutes=offset), end=start + timedelta(minutes=offset + 60),
                    location='Salle A', url='')
                return 'ok'
            except ValidationError:
                return 'rejected'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            result = list(executor.map(publish, [0, 30]))
        self.assertCountEqual(result, ['ok', 'rejected'])
        self.assertEqual(Workshop.objects.count(), 1)
