"""The mentoring app is wired into the shared layout (settings, urls, menu, breadcrumbs, design system)."""
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, Skill, User
from accounts.services import set_role
from hackathons.test_helpers import make_owner
from ..models import MentorExpertise
from .helpers import make_user
from .test_slots import published_event


class WiringTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.event = published_event(cls.owner)
        cls.mentor = User.objects.create_user(username='mentor', email='mentor@example.test')
        cls.member = User.objects.create_user(username='member', email='member@example.test')
        set_role(actor=cls.owner, user=cls.mentor, hackathon=cls.event, role=Role.MENTOR)
        set_role(actor=cls.owner, user=cls.member, hackathon=cls.event, role=Role.PARTICIPANT)
        cls.item = MentorExpertise.objects.create(user=cls.mentor, skill=Skill.objects.create(name='Django', category='Backend'), level=4)

    def test_mentor_screens_use_the_shared_layout_and_the_mentoring_stylesheet(self):
        self.client.force_login(self.mentor)
        for name, args in (('expertise-list', []), ('slot-list', []), ('workshop-list', []), ('expertise-add', []),
                           ('slot-add', []), ('expertise-edit', [self.item.pk]), ('expertise-delete', [self.item.pk])):
            with self.subTest(name=name):
                page = self.client.get(reverse('mentoring:' + name, args=args))
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, 'class="breadcrumbs"')
                self.assertContains(page, 'class="skip-link"')
                self.assertContains(page, '<h1', count=1)

    def test_mentor_gets_the_workspace_navigation_with_the_current_page_marked(self):
        self.client.force_login(self.mentor)
        page = self.client.get(reverse('mentoring:slot-list'))
        self.assertContains(page, 'css/mentoring.css')
        self.assertContains(page, 'class="m4-nav" aria-label="Mentorat et ateliers"')
        self.assertContains(page, f'<a href="{reverse("mentoring:slot-list")}" aria-current="page">')
        self.assertContains(self.client.get(reverse('core:home')), f'href="{reverse("mentoring:hub")}"')

    def test_participant_sees_workshops_but_no_mentor_workspace(self):
        self.client.force_login(self.member)
        page = self.client.get(reverse('mentoring:workshop-list'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'class="m4-nav"')
        self.assertNotContains(page, reverse('mentoring:expertise-list'))
        self.assertNotContains(page, reverse('mentoring:slot-list'))

    def test_breadcrumbs_name_the_parent_and_the_current_page(self):
        self.client.force_login(self.mentor)
        page = self.client.get(reverse('mentoring:slot-add'))
        self.assertContains(page, f'<a href="{reverse("mentoring:slot-list")}">Mes créneaux</a>')
        self.assertContains(page, '<li aria-current="page">Publier un créneau</li>')

    def test_cancel_button_of_shared_forms_returns_to_the_mentoring_list(self):
        self.client.force_login(self.mentor)
        for name, target in (('expertise-add', 'expertise-list'), ('slot-add', 'slot-list')):
            with self.subTest(name=name):
                page = self.client.get(reverse('mentoring:' + name))
                self.assertContains(page, f'href="{reverse("mentoring:" + target)}"')
                self.assertContains(page, 'Annuler</a>')

    def test_the_organizer_workshop_form_uses_the_layout_and_cancels_back_to_the_list(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse('mentoring:workshop-add'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'class="breadcrumbs"')
        self.assertContains(page, '<h1', count=1)
        self.assertContains(page, f'href="{reverse("mentoring:workshop-list")}"')
        self.client.force_login(make_user('outsider'))
        self.assertEqual(self.client.get(reverse('mentoring:workshop-add')).status_code, 403)
