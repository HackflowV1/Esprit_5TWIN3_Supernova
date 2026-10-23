from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from accounts.models import AssignmentStatus, Role, Skill, User
from accounts.services import set_role
from hackathons.test_helpers import make_event, make_owner
from .models import MentorExpertise


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
