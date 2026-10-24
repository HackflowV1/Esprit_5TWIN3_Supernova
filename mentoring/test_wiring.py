"""The mentoring app is wired into the shared layout (settings, urls, menu, breadcrumbs, design system)."""
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, Skill, User
from accounts.services import set_role
from hackathons.test_helpers import make_owner
from .models import MentorExpertise
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
                           ('slot-add', []), ('workshop-add', []), ('expertise-edit', [self.item.pk]), ('expertise-delete', [self.item.pk])):
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
        self.assertContains(page, 'class="m4-nav" aria-label="Espace mentor"')
        self.assertContains(page, f'<a href="{reverse("mentoring:slot-list")}" aria-current="page">')
        main_nav = self.client.get(reverse('core:home'))
        self.assertContains(main_nav, 'Espace mentor')
        self.assertContains(main_nav, '>Ateliers</a>')

    def test_participant_sees_workshops_but_no_mentor_workspace(self):
        self.client.force_login(self.member)
        page = self.client.get(reverse('mentoring:workshop-list'))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'class="m4-nav"')
        self.assertNotContains(page, reverse('mentoring:expertise-list'))

    def test_breadcrumbs_name_the_parent_and_the_current_page(self):
        self.client.force_login(self.mentor)
        page = self.client.get(reverse('mentoring:slot-add'))
        self.assertContains(page, f'<a href="{reverse("mentoring:slot-list")}">Mes créneaux</a>')
        self.assertContains(page, '<li aria-current="page">Publier un créneau</li>')

    def test_cancel_button_of_shared_forms_returns_to_the_mentoring_list(self):
        self.client.force_login(self.mentor)
        for name, target in (('expertise-add', 'expertise-list'), ('slot-add', 'slot-list'), ('workshop-add', 'workshop-list')):
            with self.subTest(name=name):
                page = self.client.get(reverse('mentoring:' + name))
                self.assertContains(page, f'href="{reverse("mentoring:" + target)}"')
                self.assertContains(page, 'Annuler</a>')
