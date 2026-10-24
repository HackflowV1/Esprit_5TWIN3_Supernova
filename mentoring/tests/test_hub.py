"""The Mentoring home page: it explains the module whatever the role and points to what to do next."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from accounts.models import Role
from accounts.services import set_role
from hackathons.test_helpers import make_owner
from ..models import MentorSlot
from .helpers import make_ongoing_event, make_request, make_team, make_user


class HubTests(TestCase):
    def setUp(self):
        translation.activate('fr')
        self.addCleanup(translation.deactivate)
        self.url = reverse('mentoring:hub')

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.event = make_ongoing_event(cls.owner)
        cls.captain, cls.mentor, cls.outsider = make_user('captain'), make_user('mentor'), make_user('outsider')
        set_role(actor=cls.owner, user=cls.mentor, hackathon=cls.event, role=Role.MENTOR)
        cls.team = make_team(cls.event, cls.captain, name='Nova', members=[make_user('member')])

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response['Location'])

    def test_the_page_always_explains_the_three_roles(self):
        self.client.force_login(self.outsider)
        page = self.client.get(self.url)
        for text in ('Comment ça marche', 'Vous êtes dans une équipe', 'Vous êtes mentor', 'Vous voulez apprendre'):
            self.assertContains(page, text)
        self.assertNotContains(page, 'Bientôt')  # every step shown on the page exists now
        self.assertContains(page, '<h1', count=1)

    def test_a_team_member_is_told_it_is_his_case_and_can_ask_for_help(self):
        make_request(self.team, self.captain)
        self.client.force_login(self.captain)
        page = self.client.get(self.url)
        self.assertContains(page, 'C’est votre cas', count=1)  # only the team card; the mentor card is not his
        self.assertContains(page, reverse('mentoring:support-new'))
        self.assertContains(page, '1 demande en cours.')
        self.assertContains(page, 'Le rôle de mentor est attribué par l’organisateur du hackathon.')
        self.assertNotContains(page, reverse('mentoring:expertise-list'))

    def test_a_mentor_sees_his_tools_and_the_count_of_his_slots(self):
        self.client.force_login(self.mentor)
        self.assertContains(self.client.get(self.url), '0 créneaux à venir.')
        start = timezone.now().replace(second=0, microsecond=0) + timedelta(hours=1)
        MentorSlot.objects.create(hackathon=self.event, mentor=self.mentor, start=start, end=start + timedelta(minutes=30))
        page = self.client.get(self.url)
        self.assertContains(page, '1 créneau à venir.')
        self.assertContains(page, reverse('mentoring:expertise-list'))
        self.assertContains(page, reverse('mentoring:slot-list'))

    def test_an_organizer_gets_the_overview_block(self):
        self.client.force_login(self.owner)
        page = self.client.get(self.url)
        self.assertContains(page, 'Vous organisez un hackathon')
        self.assertContains(page, 'Pilotage de l’assistance')
        self.client.force_login(self.captain)
        self.assertNotContains(self.client.get(self.url), 'Vous organisez un hackathon')

    def test_a_user_with_nothing_is_invited_to_join_a_hackathon(self):
        self.client.force_login(self.outsider)
        page = self.client.get(self.url)
        self.assertContains(page, 'Pas encore dans une équipe ?')
        self.assertContains(page, reverse('hackathons:list'))
        self.assertNotContains(page, 'Ouvert à votre hackathon')

    def test_the_main_menu_has_a_single_entry_and_the_module_tabs_mark_the_current_page(self):
        self.client.force_login(self.mentor)
        page = self.client.get(self.url)
        self.assertEqual(page.content.decode().count('href="/mentoring/"'), 2)  # main menu + "Vue d'ensemble" tab
        self.assertContains(page, f'<a href="{self.url}" aria-current="page">')
        self.assertContains(page, '<li aria-current="page">Mentorat et ateliers</li>')
        self.assertNotContains(page, 'href="/" aria-current="page"')  # the site home is not "current"

    def test_the_hub_speaks_english_when_asked(self):
        self.client.force_login(self.captain)
        self.client.post(reverse('set_language'), {'language': 'en', 'next': '/'})
        self.addCleanup(translation.deactivate)
        page = self.client.get(self.url)
        for text in ('Mentoring and workshops', 'How it works', 'You are in a team', 'This is you', 'Ask for help'):
            self.assertContains(page, text)
        html = page.content.decode()
        for word in ('Comment', 'Bientôt', 'équipe', 'atelier', 'Demander'):
            self.assertNotIn(word, html)
