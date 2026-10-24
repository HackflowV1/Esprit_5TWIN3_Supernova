from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.models import AssignmentStatus, Role, Skill, User
from accounts.services import set_role
from hackathons.test_helpers import make_event, make_owner
from ..models import MentorExpertise


class MentorExpertiseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.event = make_event(cls.owner)
        cls.mentor = User.objects.create_user(username='mentor', email='mentor@example.test')
        cls.other = User.objects.create_user(username='other', email='other@example.test')
        set_role(actor=cls.owner, user=cls.mentor, hackathon=cls.event, role=Role.MENTOR)
        cls.django = Skill.objects.create(name='Django', category='Backend')
        cls.react = Skill.objects.create(name='React', category='Frontend')

    def test_mentor_can_declare_an_expertise(self):
        item = MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=5)
        self.assertEqual(str(item), 'mentor · Django (5/5)')

    def test_level_must_stay_between_1_and_5(self):
        for level in (0, 6):
            with self.subTest(level=level), self.assertRaises(ValidationError):
                MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=level)
        self.assertFalse(MentorExpertise.objects.exists())

    def test_same_skill_cannot_be_declared_twice(self):
        MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=4)
        with self.assertRaises(ValidationError):
            MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=2)
        MentorExpertise.objects.create(user=self.mentor, skill=self.react, level=2)
        self.assertEqual(MentorExpertise.objects.filter(user=self.mentor).count(), 2)

    def test_non_mentor_is_rejected(self):
        with self.assertRaises(ValidationError):
            MentorExpertise.objects.create(user=self.other, skill=self.django, level=3)

    def test_mentor_role_in_another_hackathon_is_enough(self):
        second = make_event(self.owner, 'second')
        set_role(actor=self.owner, user=self.other, hackathon=second, role=Role.MENTOR)
        MentorExpertise.objects.create(user=self.other, skill=self.react, level=3)

    def test_revoked_mentor_is_rejected(self):
        set_role(actor=self.owner, user=self.mentor, hackathon=self.event, role=Role.MENTOR, status=AssignmentStatus.REVOKED)
        with self.assertRaises(ValidationError):
            MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=3)

    def test_database_constraints_back_up_python_validation(self):
        MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=4)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MentorExpertise.objects.bulk_create([MentorExpertise(user=self.mentor, skill=self.django, level=3)])
        with self.assertRaises(IntegrityError), transaction.atomic():
            MentorExpertise.objects.bulk_create([MentorExpertise(user=self.mentor, skill=self.react, level=9)])


class MentorSpaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.event = make_event(cls.owner)
        cls.mentor = User.objects.create_user(username='mentor', email='mentor@example.test')
        cls.rival = User.objects.create_user(username='rival', email='rival@example.test')
        cls.member = User.objects.create_user(username='member', email='member@example.test')
        for user in (cls.mentor, cls.rival):
            set_role(actor=cls.owner, user=user, hackathon=cls.event, role=Role.MENTOR)
        set_role(actor=cls.owner, user=cls.member, hackathon=cls.event, role=Role.PARTICIPANT)
        cls.django = Skill.objects.create(name='Django', category='Backend')
        cls.react = Skill.objects.create(name='React', category='Frontend')
        cls.list_url = reverse('mentoring:expertise-list')

    def test_anonymous_is_sent_to_login(self):
        for name, kwargs in (('expertise-list', {}), ('expertise-add', {}), ('expertise-edit', {'pk': 1}), ('expertise-delete', {'pk': 1})):
            with self.subTest(name=name):
                response = self.client.get(reverse('mentoring:' + name, kwargs=kwargs))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('accounts:login'), response['Location'])

    def test_non_mentor_gets_403_even_with_direct_url(self):
        self.client.force_login(self.member)
        item = MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=3)
        for url in (self.list_url, reverse('mentoring:expertise-add'),
                reverse('mentoring:expertise-edit', args=[item.pk]), reverse('mentoring:expertise-delete', args=[item.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(reverse('mentoring:expertise-delete', args=[item.pk])).status_code, 403)
        self.assertTrue(MentorExpertise.objects.filter(pk=item.pk).exists())

    def test_superuser_without_mentor_role_is_refused(self):
        boss = User.objects.create_superuser(username='boss', email='boss@example.test', password='x')
        self.client.force_login(boss)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)

    def test_mentor_sees_empty_state_then_adds_an_expertise(self):
        self.client.force_login(self.mentor)
        self.assertContains(self.client.get(self.list_url), 'Aucune expertise déclarée')
        response = self.client.post(reverse('mentoring:expertise-add'), {'skill': self.django.pk, 'level': 5}, follow=True)
        self.assertRedirects(response, self.list_url)
        self.assertContains(response, 'Expertise ajoutée')
        self.assertContains(response, 'Django')
        self.assertTrue(MentorExpertise.objects.filter(user=self.mentor, skill=self.django, level=5).exists())

    def test_declared_skill_is_not_offered_again_and_duplicate_post_is_rejected(self):
        MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=3)
        self.client.force_login(self.mentor)
        page = self.client.get(reverse('mentoring:expertise-add'))
        self.assertNotContains(page, f'value="{self.django.pk}">Django</option>')
        self.assertContains(page, f'value="{self.react.pk}">React</option>')
        response = self.client.post(reverse('mentoring:expertise-add'), {'skill': self.django.pk, 'level': 4})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(MentorExpertise.objects.filter(user=self.mentor).count(), 1)

    def test_invalid_level_is_rejected_by_the_server(self):
        self.client.force_login(self.mentor)
        response = self.client.post(reverse('mentoring:expertise-add'), {'skill': self.django.pk, 'level': 9})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MentorExpertise.objects.exists())

    def test_edit_changes_level_only(self):
        item = MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=2)
        self.client.force_login(self.mentor)
        self.client.post(reverse('mentoring:expertise-edit', args=[item.pk]), {'skill': self.react.pk, 'level': 4})
        item.refresh_from_db()
        self.assertEqual((item.skill, item.level), (self.django, 4))

    def test_a_mentor_cannot_touch_another_mentors_expertise(self):
        item = MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=2)
        self.client.force_login(self.rival)
        self.assertEqual(self.client.get(reverse('mentoring:expertise-edit', args=[item.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('mentoring:expertise-delete', args=[item.pk])).status_code, 404)
        response = self.client.get(self.list_url)
        self.assertEqual(list(response.context['expertises']), [])
        self.assertNotContains(response, 'Niveau 2/5')
        self.assertTrue(MentorExpertise.objects.filter(pk=item.pk).exists())

    def test_delete_removes_own_expertise(self):
        item = MentorExpertise.objects.create(user=self.mentor, skill=self.django, level=2)
        self.client.force_login(self.mentor)
        response = self.client.post(reverse('mentoring:expertise-delete', args=[item.pk]), follow=True)
        self.assertContains(response, 'Expertise retirée')
        self.assertFalse(MentorExpertise.objects.exists())

    def test_mentor_tabs_are_shown_only_to_mentors(self):
        self.client.force_login(self.member)
        page = self.client.get(reverse('mentoring:hub'))
        self.assertNotContains(page, reverse('mentoring:expertise-list'))
        self.assertNotContains(page, reverse('mentoring:slot-list'))
        self.client.force_login(self.mentor)
        page = self.client.get(reverse('mentoring:hub'))
        self.assertContains(page, reverse('mentoring:expertise-list'))
        self.assertContains(page, reverse('mentoring:slot-list'))
