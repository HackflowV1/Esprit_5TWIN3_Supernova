"""Workshop registration: individual, capacity-safe, conflict-aware; attendance by the trainer or an organizer."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone, translation

from accounts.models import Role, User
from accounts.services import set_role
from hackathons.models import Hackathon
from hackathons.test_helpers import make_owner
from teams.models import Registration
from .. import services
from ..models import M4History, Workshop, WorkshopRegistration
from .base import LiveBase
from .helpers import make_ongoing_event, make_team, make_user


class WorkshopBase(LiveBase):
    def workshop(self, in_minutes=60, minutes=60, capacity=3, trainer=None, title='Atelier API'):
        start = self.now() + timedelta(minutes=in_minutes)
        return services.create_workshop(actor=self.owner, hackathon=self.event, trainer=trainer or self.mentor, title=title,
            description='Construire une API.', capacity=capacity, start=start, end=start + timedelta(minutes=minutes), location='Salle A', url='')

    def started_workshop(self, capacity=5):
        """A workshop that has already started (the services only publish future ones)."""
        start = self.event.start_date + timedelta(minutes=10)
        return Workshop.objects.create(hackathon=self.event, trainer=self.mentor, title='Atelier en cours', capacity=capacity,
            start=start, end=start + timedelta(minutes=60), location='Salle B')

    def participant(self, name):
        user = make_user(name)
        Registration.objects.get_or_create(user=user, hackathon=self.event)
        set_role(actor=self.owner, user=user, hackathon=self.event, role=Role.PARTICIPANT)
        return user

    def register(self, workshop, actor=None):
        return services.register_to_workshop(actor=actor or self.captain, workshop=workshop)


class RegisterTests(WorkshopBase):
    def test_a_participant_registers_individually(self):
        workshop = self.workshop()
        row = self.register(workshop)
        self.assertEqual((row.status, row.attendance, row.registration.user), ('REGISTERED', 'UNKNOWN', self.captain))
        self.assertEqual(services.workshop_seats(workshop), (1, 2))
        self.assertFalse(WorkshopRegistration.objects.filter(registration__user=self.member).exists())  # the team is not enrolled
        entry = M4History.objects.get(action='workshop.registered', object_id=row.pk)
        self.assertEqual((entry.actor, entry.details['workshop']), (self.captain, workshop.pk))

    def test_an_accepted_hackathon_registration_is_required(self):
        workshop = self.workshop()
        from teams.models import Registration as Reg
        cancelled = make_user('quit')
        Reg.objects.create(user=cancelled, hackathon=self.event, status=Reg.Status.CANCELLED)
        for actor in (self.outsider, self.mentor, self.owner, cancelled):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                self.register(workshop, actor)
        self.assertFalse(WorkshopRegistration.objects.exists())

    def test_the_capacity_is_respected_and_a_cancellation_frees_a_seat(self):
        workshop = self.workshop(capacity=2)
        self.register(workshop, self.captain)
        self.register(workshop, self.member)
        with self.assertRaises(ValidationError) as caught:
            self.register(workshop, self.rival_captain)
        self.assertIn('complet', ' '.join(caught.exception.messages))
        services.cancel_workshop_registration(actor=self.member, workshop=workshop)
        self.register(workshop, self.rival_captain)
        self.assertEqual(services.workshop_seats(workshop), (2, 0))

    def test_no_double_registration(self):
        workshop = self.workshop()
        self.register(workshop)
        with self.assertRaises(ValidationError):
            self.register(workshop)
        self.assertEqual(WorkshopRegistration.objects.count(), 1)

    def test_registering_again_after_a_cancellation_reuses_the_same_row(self):
        workshop = self.workshop()
        first = self.register(workshop)
        WorkshopRegistration.objects.filter(pk=first.pk).update(attendance='PRESENT')
        services.cancel_workshop_registration(actor=self.captain, workshop=workshop)
        again = self.register(workshop)
        self.assertEqual((again.pk, again.status, again.attendance, again.cancelled_at), (first.pk, 'REGISTERED', 'UNKNOWN', None))
        self.assertEqual(WorkshopRegistration.objects.count(), 1)

    def test_registration_and_cancellation_close_when_the_workshop_starts(self):
        workshop = self.workshop(capacity=4)
        self.register(workshop, self.member)
        with patch('mentoring.services.timezone.now', return_value=workshop.start + timedelta(minutes=1)):
            with self.assertRaises(ValidationError):
                self.register(workshop, self.captain)
            with self.assertRaises(ValidationError):
                services.cancel_workshop_registration(actor=self.member, workshop=workshop)

    def test_a_participant_cannot_attend_two_workshops_at_once(self):
        first = self.workshop(in_minutes=60, minutes=60, trainer=self.mentor)
        overlapping = self.workshop(in_minutes=90, minutes=60, trainer=self.mentor2, title='Chevauche')
        adjacent = self.workshop(in_minutes=120, minutes=60, trainer=self.mentor, title='Juste après')
        self.register(first)
        with self.assertRaises(ValidationError) as caught:
            self.register(overlapping)
        self.assertIn('autre atelier à cette heure-là', ' '.join(caught.exception.messages))
        self.register(adjacent)

    def test_a_participant_whose_team_has_an_appointment_cannot_register_over_it(self):
        slot = self.slot(in_minutes=60)
        self.book(slot=slot)
        workshop = self.workshop(in_minutes=70, minutes=60, trainer=self.mentor2)
        for actor in (self.captain, self.member):
            with self.subTest(actor=actor.username), self.assertRaises(ValidationError):
                self.register(workshop, actor)
        self.register(workshop, self.rival_captain)  # another team is free

    def test_a_cancelled_workshop_cannot_be_joined(self):
        workshop = self.workshop()
        services.cancel_workshop(actor=self.owner, workshop=workshop)
        with self.assertRaises(ValidationError):
            self.register(workshop)

    def test_only_an_active_registration_can_be_cancelled(self):
        workshop = self.workshop()
        with self.assertRaises(ValidationError):
            services.cancel_workshop_registration(actor=self.captain, workshop=workshop)
        self.register(workshop)
        services.cancel_workshop_registration(actor=self.captain, workshop=workshop)
        row = WorkshopRegistration.objects.get()
        self.assertEqual(row.status, 'CANCELLED')
        self.assertIsNotNone(row.cancelled_at)
        self.assertTrue(M4History.objects.filter(action='workshop.unregistered').exists())

    def test_cancelling_the_workshop_releases_every_seat_and_keeps_the_rows(self):
        workshop = self.workshop()
        self.register(workshop, self.captain)
        self.register(workshop, self.member)
        services.cancel_workshop(actor=self.owner, workshop=workshop)
        self.assertEqual(set(WorkshopRegistration.objects.values_list('status', flat=True)), {'CANCELLED'})
        self.assertEqual(M4History.objects.get(action='workshop.cancelled').details['released_registrations'], 2)
        free_then = self.workshop(in_minutes=60, trainer=self.mentor2, title='Remplaçant')
        self.register(free_then)  # the participant is free again at that time


class AttendanceTests(WorkshopBase):
    def setUp(self):
        super().setUp()
        self.workshop_obj = self.started_workshop()
        self.row = WorkshopRegistration.objects.create(workshop=self.workshop_obj, registration=Registration.objects.get(user=self.captain, hackathon=self.event))

    def mark(self, actor, attendance='PRESENT', row=None):
        return services.mark_attendance(actor=actor, workshop_registration=row or self.row, attendance=attendance)

    def test_the_trainer_and_an_organizer_record_the_attendance(self):
        self.mark(self.mentor)
        self.row.refresh_from_db()
        self.assertEqual((self.row.attendance, self.row.attendance_marked_by), ('PRESENT', self.mentor))
        self.assertIsNotNone(self.row.attendance_marked_at)
        self.mark(self.owner, 'ABSENT')  # it can be corrected
        self.row.refresh_from_db()
        self.assertEqual((self.row.attendance, self.row.attendance_marked_by), ('ABSENT', self.owner))
        entry = M4History.objects.filter(action='workshop.attendance').order_by('id').last()
        self.assertEqual((entry.actor, entry.details['attendance']), (self.owner, 'ABSENT'))

    def test_nobody_else_may_record_it(self):
        for actor in (self.captain, self.member, self.mentor2, self.outsider):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                self.mark(actor)
        self.row.refresh_from_db()
        self.assertEqual(self.row.attendance, 'UNKNOWN')

    def test_it_opens_when_the_workshop_starts(self):
        future = self.workshop()
        row = self.register(future, self.member)
        with self.assertRaises(ValidationError) as caught:
            self.mark(self.mentor, row=row)
        self.assertIn('s’ouvre au début', ' '.join(caught.exception.messages))

    def test_invalid_values_and_cancelled_registrations_are_refused(self):
        with self.assertRaises(ValidationError):
            self.mark(self.mentor, 'MAYBE')
        WorkshopRegistration.objects.filter(pk=self.row.pk).update(status='CANCELLED')
        with self.assertRaises(ValidationError):
            self.mark(self.mentor)


class RegistrationConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = make_owner()
        self.event = make_ongoing_event(self.owner)
        self.mentor = make_user('mentor')
        set_role(actor=self.owner, user=self.mentor, hackathon=self.event, role=Role.MENTOR)
        self.users = [make_user('p1'), make_user('p2')]
        for index, user in enumerate(self.users):
            make_team(self.event, user, name=f'Team {index}')
        start = timezone.now().replace(second=0, microsecond=0) + timedelta(hours=1)
        self.workshop = services.create_workshop(actor=self.owner, hackathon=self.event, trainer=self.mentor, title='Dernière place',
            description='', capacity=1, start=start, end=start + timedelta(hours=1), location='Salle A', url='')

    def test_two_people_taking_the_last_seat_at_once_get_one_success(self):
        barrier = Barrier(2)

        def attempt(index):
            try:
                actor = User.objects.get(pk=self.users[index].pk)
                workshop = Workshop.objects.get(pk=self.workshop.pk)
                barrier.wait(timeout=10)
                services.register_to_workshop(actor=actor, workshop=workshop)
                return 'ok'
            except ValidationError:
                return 'full'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            result = list(executor.map(attempt, [0, 1]))
        self.assertCountEqual(result, ['ok', 'full'])
        self.assertEqual(WorkshopRegistration.objects.filter(workshop=self.workshop, status='REGISTERED').count(), 1)


class WorkshopRegistrationViewTests(WorkshopBase):
    def detail(self, workshop):
        return reverse('mentoring:workshop-detail', args=[workshop.pk])

    def test_the_list_shows_seats_and_the_registration_status(self):
        open_workshop = self.workshop(capacity=3, title='Ouvert')
        mine = self.workshop(in_minutes=180, capacity=3, title='Le mien', trainer=self.mentor2)
        full = self.workshop(in_minutes=300, capacity=1, title='Complet')
        self.register(mine, self.captain)
        self.register(full, self.member)
        self.client.force_login(self.captain)
        page = self.client.get(reverse('mentoring:workshop-list'))
        self.assertContains(page, '3 places restantes')
        self.assertContains(page, 'Vous êtes inscrit')
        self.assertContains(page, 'Complet')
        self.assertContains(page, open_workshop.get_absolute_url())

    def test_a_participant_registers_and_cancels_from_the_page(self):
        workshop = self.workshop(capacity=2)
        self.client.force_login(self.captain)
        page = self.client.get(self.detail(workshop))
        self.assertContains(page, 'M’inscrire à cet atelier')
        self.assertContains(page, '2 places restantes.')
        response = self.client.post(reverse('mentoring:workshop-register', args=[workshop.pk]), follow=True)
        self.assertContains(response, 'Inscription confirmée.')
        self.assertContains(response, 'Vous êtes inscrit')
        self.assertContains(response, 'Annuler mon inscription')
        response = self.client.post(reverse('mentoring:workshop-unregister', args=[workshop.pk]), follow=True)
        self.assertContains(response, 'Inscription annulée.')
        self.assertContains(response, 'M’inscrire à cet atelier')

    def test_a_full_workshop_says_so_and_refuses_the_post(self):
        workshop = self.workshop(capacity=1)
        self.register(workshop, self.member)
        self.client.force_login(self.captain)
        page = self.client.get(self.detail(workshop))
        self.assertContains(page, 'Toutes les places sont prises.')
        self.assertNotContains(page, 'M’inscrire à cet atelier')
        response = self.client.post(reverse('mentoring:workshop-register', args=[workshop.pk]), follow=True)
        self.assertContains(response, 'Cet atelier est complet.')
        self.assertEqual(WorkshopRegistration.objects.filter(status='REGISTERED').count(), 1)

    def test_actions_are_post_only_and_need_the_right_to_see_the_workshop(self):
        workshop = self.workshop()
        self.client.force_login(self.captain)
        for name in ('register', 'unregister'):
            self.assertEqual(self.client.get(reverse('mentoring:workshop-' + name, args=[workshop.pk])).status_code, 405)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(reverse('mentoring:workshop-register', args=[workshop.pk])).status_code, 404)

    def test_a_mentor_or_an_organizer_without_registration_is_told_why_they_cannot_join(self):
        workshop = self.workshop(trainer=self.mentor2)
        for user in (self.mentor, self.owner):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertContains(self.client.get(self.detail(workshop)), 'réservée aux participants inscrits')
        self.client.force_login(self.mentor)
        self.client.post(reverse('mentoring:workshop-register', args=[workshop.pk]), follow=True)
        self.assertFalse(WorkshopRegistration.objects.exists())

    def test_the_participants_list_is_private_to_the_trainer_and_the_organizers(self):
        workshop = self.workshop()
        self.register(workshop, self.captain)
        for user, sees in ((self.mentor, True), (self.owner, True), (self.member, False), (self.mentor2, False), (self.captain, False)):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                page = self.client.get(self.detail(workshop))
                self.assertEqual('Inscrits' in page.content.decode(), sees)
                self.assertEqual('captain' in page.content.decode().split('Inscrits', 1)[-1], sees) if sees else None

    def test_the_trainer_records_the_attendance_from_the_page(self):
        workshop = self.started_workshop()
        row = WorkshopRegistration.objects.create(workshop=workshop, registration=Registration.objects.get(user=self.captain, hackathon=self.event))
        self.client.force_login(self.mentor)
        page = self.client.get(self.detail(workshop))
        self.assertContains(page, 'name="attendance" value="PRESENT"')
        self.assertContains(page, 'aria-pressed="false"')
        response = self.client.post(reverse('mentoring:workshop-attendance', args=[workshop.pk, row.pk]), {'attendance': 'PRESENT'}, follow=True)
        self.assertContains(response, 'Présence enregistrée.')
        self.assertContains(response, 'aria-pressed="true"')
        row.refresh_from_db()
        self.assertEqual(row.attendance, 'PRESENT')
        self.client.force_login(self.captain)
        refused = self.client.post(reverse('mentoring:workshop-attendance', args=[workshop.pk, row.pk]), {'attendance': 'ABSENT'}, follow=True)
        self.assertContains(refused, 'Seuls le formateur ou un organisateur')
        row.refresh_from_db()
        self.assertEqual(row.attendance, 'PRESENT')

    def test_before_the_start_the_page_explains_that_attendance_is_not_open_yet(self):
        workshop = self.workshop()
        self.client.force_login(self.mentor)
        page = self.client.get(self.detail(workshop))
        self.assertContains(page, 'Le relevé de présence s’ouvre au début de l’atelier.')
        self.assertNotContains(page, 'name="attendance"')

    def test_the_workshop_pages_are_english_when_asked(self):
        workshop = self.workshop(capacity=2)
        self.register(workshop, self.member)
        self.client.force_login(self.captain)
        self.client.post(reverse('set_language'), {'language': 'en', 'next': '/'})
        self.addCleanup(translation.deactivate)
        french = ('Inscription', 'inscrit', 'places', 'atelier', 'Complet', 'Ateliers', 'Présence', 'Formateur', 'À venir', 'Voir les')
        for url, expected in ((reverse('mentoring:workshop-list'), '1 seat left'), (self.detail(workshop), 'Register for this workshop')):
            with self.subTest(url=url):
                page = self.client.get(url)
                self.assertContains(page, expected)
                html = page.content.decode()
                for word in french:
                    self.assertNotIn(word, html, f'{word!r} still in French on {url}')
