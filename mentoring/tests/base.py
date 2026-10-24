"""A live edition shared by the booking, session and workshop tests: development phase open today, two teams,
two mentors, and helpers to build slots, requests, bookings and past sessions."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone, translation

from accounts.models import Role, Skill
from accounts.services import set_role
from hackathons.test_helpers import make_owner
from .. import services
from ..models import MentoringSession, MentorSlot, SupportRequest
from .helpers import make_ongoing_event, make_request, make_team, make_user


class LiveBase(TestCase):
    def setUp(self):
        translation.activate('fr')
        self.addCleanup(translation.deactivate)

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.event = make_ongoing_event(cls.owner)
        cls.captain, cls.member = make_user('captain'), make_user('member')
        cls.rival_captain, cls.outsider = make_user('rival'), make_user('outsider')
        cls.mentor, cls.mentor2 = make_user('mentor'), make_user('mentor2')
        for mentor in (cls.mentor, cls.mentor2):
            set_role(actor=cls.owner, user=mentor, hackathon=cls.event, role=Role.MENTOR)
        cls.team = make_team(cls.event, cls.captain, name='Nova', members=[cls.member])
        cls.rival = make_team(cls.event, cls.rival_captain, name='Horizon')
        for participant in (cls.captain, cls.member, cls.rival_captain):
            set_role(actor=cls.owner, user=participant, hackathon=cls.event, role=Role.PARTICIPANT)
        cls.django = Skill.objects.create(name='Django', category='Backend')

    def now(self):
        return timezone.now().replace(second=0, microsecond=0)

    def slot(self, mentor=None, in_minutes=60, minutes=45):
        start = self.now() + timedelta(minutes=in_minutes)
        return MentorSlot.objects.create(hackathon=self.event, mentor=mentor or self.mentor, start=start, end=start + timedelta(minutes=minutes))

    def request(self, team=None, author=None, **overrides):
        team = team or self.team
        return make_request(team, author or team.captain.user, **overrides)

    def book(self, request=None, slot=None, actor=None):
        request = request or self.request()
        return services.book_session(actor=actor or request.team.captain.user, request=request, slot=slot or self.slot())

    def past_session(self, request=None, mentor=None):
        """A BOOKED session whose slot has already started (the services only book future slots)."""
        request = request or self.request()
        start = self.event.start_date + timedelta(minutes=5)
        slot = MentorSlot.objects.create(hackathon=self.event, mentor=mentor or self.mentor, start=start, end=start + timedelta(minutes=45))
        session = MentoringSession.objects.create(request=request, slot=slot, booked_by=request.team.captain.user)
        SupportRequest.objects.filter(pk=request.pk).update(status=SupportRequest.Status.BOOKED)
        return MentoringSession.objects.get(pk=session.pk)

    def completed_session(self, request=None):
        session = self.past_session(request)
        return services.complete_session(actor=session.slot.mentor, session=session, report='On a corrigé le serializer.', private_notes='Équipe motivée.')
