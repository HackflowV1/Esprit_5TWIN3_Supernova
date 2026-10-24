"""The "Mentorat" entry: no overview page, it opens the page of the user's own role, and the tabs show only that role."""
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from accounts.models import Role
from accounts.services import set_role
from hackathons.test_helpers import make_owner
from .helpers import make_ongoing_event, make_request, make_team, make_user


class EntryTests(TestCase):
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

    def test_each_role_lands_on_its_own_page(self):
        for user, target in ((self.captain, 'mentoring:support-list'), (self.mentor, 'mentoring:appointments'),
                             (self.owner, 'mentoring:support-list'), (self.outsider, 'mentoring:workshop-list')):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertRedirects(self.client.get(self.url), reverse(target))

    def test_there_is_no_overview_tab(self):
        self.client.force_login(self.mentor)
        page = self.client.get(reverse('mentoring:appointments'))
        self.assertNotContains(page, 'Vue d’ensemble')

    def test_tabs_show_only_what_the_role_can_use(self):
        support, appointments = reverse('mentoring:support-list'), reverse('mentoring:appointments')
        expertise, slots = reverse('mentoring:expertise-list'), reverse('mentoring:slot-list')
        cases = ((self.outsider, (), (support, appointments, expertise, slots)),
                 (self.captain, (support, appointments), (expertise, slots)),
                 (self.mentor, (appointments, expertise, slots), (support,)))
        for user, shown, hidden in cases:
            with self.subTest(user=user.username):
                self.client.force_login(user)
                page = self.client.get(reverse('mentoring:workshop-list'))
                for url in shown:
                    self.assertContains(page, f'href="{url}"')
                for url in hidden:
                    self.assertNotContains(page, f'href="{url}"')

    def test_the_current_tab_is_marked(self):
        self.client.force_login(self.captain)
        page = self.client.get(reverse('mentoring:support-list'))
        self.assertContains(page, f'<a href="{reverse("mentoring:support-list")}" aria-current="page">')

    def test_the_main_menu_has_a_single_entry(self):
        self.client.force_login(self.mentor)
        page = self.client.get(reverse('mentoring:appointments'))
        self.assertEqual(page.content.decode().count('href="/mentoring/"'), 1)  # the main menu only, no tab points to it

    def test_the_request_page_shows_the_four_steps_and_the_current_one(self):
        request = make_request(self.team, self.captain)
        self.client.force_login(self.captain)
        page = self.client.get(request.get_absolute_url())
        self.assertContains(page, 'class="m4-flow"')
        self.assertContains(page, 'aria-current="step"', count=1)
        self.assertContains(page, 'Demande ouverte')
        self.assertContains(page, 'étape en cours')  # the state is written, not only coloured

    def test_the_flow_speaks_english_when_asked(self):
        request = make_request(self.team, self.captain)
        self.client.force_login(self.captain)
        self.client.post(reverse('set_language'), {'language': 'en', 'next': '/'})
        self.addCleanup(translation.deactivate)
        page = self.client.get(request.get_absolute_url())
        for text in ('Request progress', 'Request opened', 'Appointment booked', 'current step'):
            self.assertContains(page, text)
        self.assertNotContains(page, 'Progression de la demande')

    def test_cancel_button_of_shared_forms_returns_to_the_mentoring_list(self):
        self.client.force_login(self.mentor)
        for name, target in (('expertise-add', 'expertise-list'), ('slot-add', 'slot-list')):
            with self.subTest(name=name):
                page = self.client.get(reverse('mentoring:' + name))
                self.assertContains(page, f'href="{reverse("mentoring:" + target)}"')
                self.assertContains(page, 'Annuler</a>')


class PaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.event = make_ongoing_event(cls.owner)
        cls.captain = make_user('captain')
        cls.team = make_team(cls.event, cls.captain, name='Nova')
        for number in range(11):
            make_request(cls.team, cls.captain, subject=f'Blocage {number:02d}')

    def setUp(self):
        translation.activate('fr')
        self.addCleanup(translation.deactivate)
        self.client.force_login(self.captain)
        self.url = reverse('mentoring:support-list')

    def test_a_long_list_is_cut_into_pages_with_a_pager(self):
        first = self.client.get(self.url)
        self.assertContains(first, 'Page 1 sur 2')
        self.assertContains(first, '?page_mine=2')
        self.assertNotContains(first, '?page_mine=0')
        second = self.client.get(self.url, {'page_mine': 2})
        self.assertContains(second, 'Page 2 sur 2')
        self.assertContains(second, 'Précédent')
        self.assertEqual(len(second.context['my_requests']), 3)

    def test_a_short_list_has_no_pager_and_a_bad_page_falls_back(self):
        self.assertEqual(self.client.get(self.url, {'page_mine': 'abc'}).status_code, 200)
        self.assertEqual(self.client.get(self.url, {'page_mine': 99}).context['my_requests'].number, 2)
        self.assertNotContains(self.client.get(reverse('mentoring:appointments')), 'Page 1 sur')
