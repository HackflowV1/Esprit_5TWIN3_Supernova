"""Support requests: who may open or cancel one, and who may see it (confidentiality in the query itself)."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone, translation

from accounts.models import Role, Skill, User
from accounts.services import set_role
from hackathons.test_helpers import make_event, make_owner
from teams.models import Team, TeamMembership
from .. import services
from ..models import M4History, MentoringSession, MentorSlot, SupportRequest
from .helpers import book_slot, make_ongoing_event, make_request, make_team, make_user
from .test_slots import published_event


class RequestBase(TestCase):
    def setUp(self):
        translation.activate('fr')
        self.addCleanup(translation.deactivate)

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.event = make_ongoing_event(cls.owner)
        cls.mentor = make_user('mentor')
        cls.captain, cls.member, cls.outsider = make_user('captain'), make_user('member'), make_user('outsider')
        cls.rival_captain = make_user('rival')
        set_role(actor=cls.owner, user=cls.mentor, hackathon=cls.event, role=Role.MENTOR)
        cls.team = make_team(cls.event, cls.captain, name='Nova', members=[cls.member])
        cls.rival = make_team(cls.event, cls.rival_captain, name='Horizon')
        cls.skill = Skill.objects.create(name='Django', category='Backend')

    def open(self, actor=None, team=None, **overrides):
        data = {'subject': 'API Django', 'description': 'Bloqués sur le serializer.'}
        data.update(overrides)
        return services.open_request(actor=actor or self.member, team=team or self.team, **data)

    def slot(self, hours=1):
        start = timezone.now().replace(second=0, microsecond=0) + timedelta(hours=hours)
        return MentorSlot.objects.create(hackathon=self.event, mentor=self.mentor, start=start, end=start + timedelta(minutes=30))


class OpenRequestTests(RequestBase):
    def test_any_active_member_opens_a_request_even_if_the_team_is_incomplete(self):
        self.assertFalse(self.rival.is_ready)  # one member, the minimum is two
        request = self.open(actor=self.rival_captain, team=self.rival, skill=self.skill, priority='HIGH')
        self.assertEqual((request.team, request.author, request.status, request.priority, request.skill),
            (self.rival, self.rival_captain, 'OPEN', 'HIGH', self.skill))
        request = self.open(actor=self.member)
        self.assertEqual(request.author, self.member)

    def test_the_opening_is_recorded_in_the_history(self):
        request = self.open(priority='CRITICAL')
        entry = M4History.objects.get(object_type='SupportRequest', object_id=request.pk)
        self.assertEqual((entry.action, entry.actor, entry.hackathon), ('request.opened', self.member, self.event))
        self.assertEqual((entry.details['team'], entry.details['priority']), (self.team.pk, 'CRITICAL'))

    def test_only_active_members_of_that_team_may_ask(self):
        for actor, team in ((self.outsider, self.team), (self.rival_captain, self.team), (self.member, self.rival)):
            with self.subTest(actor=actor.username, team=team.name), self.assertRaises(PermissionDenied):
                self.open(actor=actor, team=team)
        self.assertFalse(SupportRequest.objects.exists())

    def test_a_former_member_cannot_ask_any_more(self):
        TeamMembership.objects.filter(registration__user=self.member).update(ended_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.open(actor=self.member)

    def test_a_closed_team_cannot_ask(self):
        Team.objects.filter(pk=self.team.pk).update(closed_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.open(actor=self.captain)

    def test_requests_need_an_open_development_phase(self):
        upcoming = published_event(self.owner, 'upcoming')  # published, but its development phase starts in two days
        team = make_team(upcoming, make_user('early'), name='Early')
        with self.assertRaises(ValidationError):
            self.open(actor=team.captain.user, team=team)
        draft = make_event(self.owner, 'draft')
        late = make_team(draft, make_user('draftcap'), name='Draft')
        with self.assertRaises(ValidationError):
            self.open(actor=late.captain.user, team=late)
        self.assertFalse(SupportRequest.objects.exists())

    def test_a_blank_subject_is_refused(self):
        with self.assertRaises(ValidationError):
            self.open(subject='   ')
        self.assertFalse(SupportRequest.objects.exists())


class CancelRequestTests(RequestBase):
    def test_author_captain_and_organizer_may_cancel_an_open_request(self):
        for actor in (self.member, self.captain, self.owner):
            with self.subTest(actor=actor.username):
                request = self.open(actor=self.member)
                services.cancel_request(actor=actor, request=request)
                request.refresh_from_db()
                self.assertEqual(request.status, 'CANCELLED')
        last = M4History.objects.filter(action='request.cancelled').order_by('id').last()
        self.assertTrue(last.details['as_organizer'])
        self.assertFalse(M4History.objects.filter(action='request.cancelled', actor=self.member).first().details['as_organizer'])

    def test_any_member_can_cancel_but_outsiders_cannot(self):
        services.cancel_request(actor=self.member, request=self.open(actor=self.captain))
        request = self.open(actor=self.captain, subject='Autre')
        for actor in (self.outsider, self.rival_captain, self.mentor):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                services.cancel_request(actor=actor, request=request)
        request.refresh_from_db()
        self.assertEqual(request.status, 'OPEN')

    def test_only_an_open_request_can_be_cancelled(self):
        request = self.open()
        book_slot_session = MentoringSession.objects.create(request=request, slot=self.slot(), booked_by=self.captain)
        SupportRequest.objects.filter(pk=request.pk).update(status='BOOKED')
        with self.assertRaises(ValidationError) as caught:
            services.cancel_request(actor=self.captain, request=request)
        self.assertIn('Annulez d’abord le rendez-vous', ' '.join(caught.exception.messages))
        self.assertEqual(book_slot_session.status, 'BOOKED')

    def test_a_former_member_author_cannot_cancel(self):
        request = self.open(actor=self.member)
        TeamMembership.objects.filter(registration__user=self.member).update(ended_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            services.cancel_request(actor=self.member, request=request)


class VisibilityTests(RequestBase):
    def setUp(self):
        super().setUp()
        self.request = self.open(actor=self.member)
        self.other_owner = make_owner('other_owner')
        self.other_event = published_event(self.other_owner, 'elsewhere')

    def sees(self, user):
        return services.visible_requests(user).filter(pk=self.request.pk).exists()

    def test_the_team_sees_its_requests_and_another_team_does_not(self):
        self.assertTrue(self.sees(self.member) and self.sees(self.captain))
        self.assertFalse(self.sees(self.rival_captain))
        self.assertFalse(self.sees(self.outsider))
        self.assertFalse(services.can_view_request(self.rival_captain, self.request))
        self.assertTrue(services.can_view_request(self.captain, self.request))

    def test_anonymous_and_inactive_users_see_nothing(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(services.visible_requests(AnonymousUser()).count(), 0)
        User.objects.filter(pk=self.member.pk).update(is_active=False)
        self.assertEqual(services.visible_requests(User.objects.get(pk=self.member.pk)).count(), 0)

    def test_a_former_member_loses_access_but_the_request_is_kept(self):
        TeamMembership.objects.filter(registration__user=self.member).update(ended_at=timezone.now())
        self.assertFalse(self.sees(self.member))
        self.assertTrue(self.sees(self.captain))
        self.assertTrue(SupportRequest.objects.filter(pk=self.request.pk).exists())

    def test_the_organizers_of_that_event_and_the_superuser_see_it(self):
        self.assertTrue(self.sees(self.owner))
        self.assertFalse(self.sees(self.other_owner))
        boss = User.objects.create_superuser(username='boss', email='boss@example.test', password='x')
        self.assertTrue(self.sees(boss))

    def test_a_mentor_sees_only_the_requests_he_is_booked_on(self):
        self.assertFalse(self.sees(self.mentor))
        session = MentoringSession.objects.create(request=self.request, slot=self.slot(), booked_by=self.captain)
        self.assertTrue(self.sees(self.mentor))
        session.status = MentoringSession.Status.COMPLETED
        session.save()
        self.assertTrue(self.sees(self.mentor))
        session.status = MentoringSession.Status.CANCELLED
        session.save()
        self.assertFalse(self.sees(self.mentor))

    def test_another_mentor_never_sees_it(self):
        stranger = make_user('stranger_mentor')
        set_role(actor=self.owner, user=stranger, hackathon=self.event, role=Role.MENTOR)
        MentoringSession.objects.create(request=self.request, slot=self.slot(), booked_by=self.captain)
        self.assertFalse(self.sees(stranger))

    def test_results_are_not_duplicated_when_several_rules_match(self):
        MentoringSession.objects.create(request=self.request, slot=self.slot(), booked_by=self.captain)
        self.assertEqual(services.visible_requests(self.owner).filter(pk=self.request.pk).count(), 1)


class TranslationTests(RequestBase):
    def test_rules_and_labels_speak_english_when_asked(self):
        from django.utils import translation
        with translation.override('en'):
            self.assertEqual(str(SupportRequest.Status.BOOKED.label), 'Appointment booked')
            self.assertEqual(str(SupportRequest.Priority.CRITICAL.label), 'Critical')
            with self.assertRaises(PermissionDenied) as caught:
                self.open(actor=self.outsider)
            self.assertEqual(str(caught.exception), 'Only active members of the team can ask for help.')
            request = self.open()
            with self.assertRaises(PermissionDenied) as caught:
                services.cancel_request(actor=self.outsider, request=request)
            self.assertIn('Only the members of the team or an organizer', str(caught.exception))
        with translation.override('fr'):
            self.assertEqual(str(SupportRequest.Status.BOOKED.label), 'Rendez-vous réservé')
