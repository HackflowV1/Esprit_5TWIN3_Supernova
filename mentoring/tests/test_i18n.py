"""Every mentoring screen, message and validation error exists in French (default) and English."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from accounts.models import Role, Skill, User
from accounts.services import set_role
from hackathons.test_helpers import make_owner
from ..models import MentorExpertise, MentorSlot, Workshop
from .test_slots import local, published_event

FRENCH_MARKERS = ('créneau', 'Créneau', 'atelier', 'Mes ', 'Ajouter', 'Modifier', 'Annuler', 'Publier', 'À venir', 'Aucun ', 'Retirer', 'Espace mentor')


class EnglishInterfaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.event = published_event(cls.owner)
        cls.mentor = User.objects.create_user(username='mentor', email='mentor@example.test')
        cls.member = User.objects.create_user(username='member', email='member@example.test')
        set_role(actor=cls.owner, user=cls.mentor, hackathon=cls.event, role=Role.MENTOR)
        set_role(actor=cls.owner, user=cls.member, hackathon=cls.event, role=Role.PARTICIPANT)
        cls.expertise = MentorExpertise.objects.create(user=cls.mentor, skill=Skill.objects.create(name='Django', category='Backend'), level=4)
        start = cls.event.start_date + timedelta(hours=1)
        cls.slot = MentorSlot.objects.create(hackathon=cls.event, mentor=cls.mentor, start=start, end=start + timedelta(minutes=30))
        cls.workshop = Workshop.objects.create(hackathon=cls.event, trainer=cls.mentor, title='API', description='REST',
            capacity=5, start=start + timedelta(hours=2), end=start + timedelta(hours=3), location='Room 1')

    def setUp(self):
        self.addCleanup(translation.deactivate)

    def english(self, user):
        self.client.force_login(user)
        self.client.post(reverse('set_language'), {'language': 'en', 'next': '/'})

    def assertEnglishPage(self, url, *expected):
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200, url)
        for text in expected:
            self.assertContains(page, text)
        html = page.content.decode()
        # Ignore the user-authored data of the fixtures (workshop title "API").
        for marker in FRENCH_MARKERS:
            self.assertNotIn(marker, html, f'{marker!r} found on {url}')
        return page

    def test_mentor_screens_are_fully_english(self):
        self.english(self.mentor)
        self.assertEnglishPage(reverse('mentoring:expertise-list'), 'My expertises', 'Add an expertise', 'Level 4 out of 5', 'You are a mentor in 1 hackathon.')
        self.assertEnglishPage(reverse('mentoring:slot-list'), 'My slots', 'Publish a slot', 'Available')
        self.assertEnglishPage(reverse('mentoring:workshop-list'), 'Workshops', 'Workshops I lead', '5 seats', 'View details')
        self.assertEnglishPage(self.workshop.get_absolute_url(), 'Practical information', 'Trainer', 'Seats', 'Room 1')

    def test_forms_and_confirmations_are_english(self):
        self.english(self.mentor)
        self.assertEnglishPage(reverse('mentoring:expertise-add'), 'Add an expertise', 'Choose a skill', '3 – Intermediate')
        self.assertEnglishPage(reverse('mentoring:slot-add'), 'Publish a slot', 'Tunis time.', 'Duration: from 15 minutes to 2 hours, during the event.')
        self.assertEnglishPage(reverse('mentoring:workshop-add'), 'Publish a workshop', 'Workshop topic', 'Number of seats', 'Provide a room, a link, or both.')
        self.assertEnglishPage(reverse('mentoring:expertise-delete', args=[self.expertise.pk]), 'Remove the expertise “Django”?')
        self.assertEnglishPage(reverse('mentoring:slot-cancel', args=[self.slot.pk]), 'Cancel this slot?', 'Keep the slot')
        self.assertEnglishPage(reverse('mentoring:workshop-cancel', args=[self.workshop.pk]), 'Cancel this workshop?', 'Yes, cancel the workshop')

    def test_participant_sees_english_workshops(self):
        self.english(self.member)
        self.assertEnglishPage(reverse('mentoring:workshop-list'), 'Workshops', '5 seats')

    def test_messages_and_validation_errors_are_english(self):
        self.english(self.mentor)
        response = self.client.post(reverse('mentoring:slot-add'), {'hackathon': self.event.pk,
            'start': local(self.slot.start + timedelta(minutes=10)), 'end': local(self.slot.end + timedelta(minutes=10))})
        self.assertContains(response, 'overlaps another one of your slots')
        response = self.client.post(reverse('mentoring:slot-cancel', args=[self.slot.pk]), follow=True)
        self.assertContains(response, 'Slot cancelled.')
        response = self.client.post(reverse('mentoring:workshop-add'), {'hackathon': self.event.pk, 'title': 'X', 'capacity': 5,
            'start': local(self.workshop.start + timedelta(days=1)), 'end': local(self.workshop.end + timedelta(days=1))})
        self.assertContains(response, 'Provide a room, an online link, or both.')

    def test_french_stays_the_default(self):
        self.client.force_login(self.mentor)
        page = self.client.get(reverse('mentoring:slot-list'))
        self.assertContains(page, 'Mes créneaux')
        self.assertContains(page, 'Publier un créneau')

    def test_workspace_navigation_is_english(self):
        self.english(self.mentor)
        page = self.client.get(reverse('mentoring:expertise-list'))
        self.assertContains(page, 'aria-label="Mentoring and workshops"')
        self.assertContains(page, 'Workshops</a>')
