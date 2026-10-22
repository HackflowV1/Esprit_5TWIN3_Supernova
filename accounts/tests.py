from django.test import TestCase
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError, transaction
from django.urls import reverse
from .models import User, Profile, Skill, UserSkill, Role, RoleAssignment, AssignmentStatus, SponsorMembership
from .permissions import has_role, can_manage, is_member
from .services import set_role
from hackathons.test_helpers import make_owner, make_event


class AccountsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.user = User.objects.create_user(username='member', email='member@example.test')
        cls.event = make_event(cls.owner)
        cls.other = make_event(cls.owner, 'other')
        cls.skill = Skill.objects.create(name='Django', category='Backend')

    def test_signup_hashes_password_and_creates_profile_without_privileges(self):
        response = self.client.post(reverse('accounts:signup'), {
            'username': 'new', 'email': 'New@example.test', 'password1': 'FictionalTest!9427', 'password2': 'FictionalTest!9427',
            'is_staff': True, 'is_superuser': True, 'role': 'ORGANIZER'})
        self.assertRedirects(response, reverse('accounts:profile'))
        user = User.objects.get(username='new')
        self.assertTrue(user.check_password('FictionalTest!9427'))
        self.assertEqual(user.email, 'new@example.test')
        self.assertTrue(Profile.objects.filter(user=user).exists())
        self.assertFalse(user.is_staff or user.is_superuser or user.role_assignments.exists())
        self.assertFalse(user.has_perm('accounts.create_hackathon'))

    def test_signup_rejects_duplicate_email_case_insensitive(self):
        response = self.client.post(reverse('accounts:signup'), {'username': 'new', 'email': 'MEMBER@example.test',
            'password1': 'FictionalTest!9427', 'password2': 'FictionalTest!9427'})
        self.assertContains(response, 'déjà utilisé')
        self.assertFalse(User.objects.filter(username='new').exists())

    def test_email_database_uniqueness(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username='duplicate', email='MEMBER@example.test')

    def test_login_logout_post_only(self):
        self.user.set_password('FictionalTest!9427')
        self.user.save()
        response = self.client.post(reverse('accounts:login'), {'username': 'member', 'password': 'FictionalTest!9427'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(reverse('accounts:profile')).status_code, 200)
        self.assertEqual(self.client.get(reverse('accounts:logout')).status_code, 405)
        self.assertEqual(self.client.post(reverse('accounts:logout')).status_code, 302)
        self.assertEqual(self.client.get(reverse('accounts:profile')).status_code, 302)

    def test_login_rejects_wrong_password_and_external_next(self):
        response = self.client.post(reverse('accounts:login'), {'username': 'member', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.user.set_password('FictionalTest!9427')
        self.user.save()
        response = self.client.post(reverse('accounts:login')+'?next=https://example.com/', {'username': 'member', 'password': 'FictionalTest!9427'})
        self.assertEqual(response.url, reverse('accounts:profile'))

    def test_profile_is_owner_scoped_and_filters_sensitive_fields(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('accounts:profile-edit'), {'first_name': 'Mariem', 'email': 'edited@example.test',
            'university': 'ESPRIT', 'biography': 'Dev', 'user': self.owner.pk, 'is_superuser': True})
        self.assertRedirects(response, reverse('accounts:profile'))
        self.user.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Mariem')
        self.assertEqual(self.user.profile.university, 'ESPRIT')
        self.assertFalse(self.user.is_superuser)
        self.assertEqual(self.owner.email, 'owner@example.test')

    def test_profile_rejects_another_users_email(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('accounts:profile-edit'), {'email': self.owner.email})
        self.assertContains(response, 'déjà utilisé')

    def test_password_change(self):
        self.user.set_password('FictionalTest!9427')
        self.user.save()
        self.client.force_login(self.user)
        response = self.client.post(reverse('accounts:password'), {'old_password': 'FictionalTest!9427',
            'new_password1': 'AnotherFiction!8142', 'new_password2': 'AnotherFiction!8142'})
        self.assertRedirects(response, reverse('accounts:password-done'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('AnotherFiction!8142'))
        self.assertEqual(self.client.get(reverse('accounts:profile')).status_code, 200)

    def test_skill_crud_uniqueness_and_range(self):
        self.client.force_login(self.user)
        url = reverse('accounts:skill-add')
        self.assertEqual(self.client.post(url, {'skill': self.skill.pk, 'level': 4}).status_code, 302)
        item = self.user.user_skills.get()
        self.assertEqual(self.client.post(url, {'skill': self.skill.pk, 'level': 4}).status_code, 200)
        self.assertEqual(self.user.user_skills.count(), 1)
        self.assertEqual(self.client.post(reverse('accounts:skill-edit', args=[item.pk]), {'skill': self.skill.pk, 'level': 6}).status_code, 200)
        self.assertEqual(self.client.post(reverse('accounts:skill-edit', args=[item.pk]), {'skill': self.skill.pk, 'level': 5}).status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.level, 5)
        self.assertEqual(self.client.post(reverse('accounts:skill-delete', args=[item.pk])).status_code, 302)
        self.assertFalse(self.user.user_skills.exists())

    def test_cannot_edit_others_skill(self):
        item = UserSkill.objects.create(user=self.owner, skill=self.skill)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse('accounts:skill-delete', args=[item.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('accounts:skill-edit', args=[item.pk])).status_code, 404)

    def test_contextual_roles_and_history(self):
        assignment = set_role(actor=self.owner, user=self.user, hackathon=self.event, role=Role.PARTICIPANT)
        set_role(actor=self.owner, user=self.user, hackathon=self.event, role=Role.MENTOR)
        set_role(actor=self.owner, user=self.user, hackathon=self.other, role=Role.JURY)
        self.assertTrue(has_role(self.user, self.event, Role.PARTICIPANT, Role.JURY))
        self.assertTrue(has_role(self.user, self.other, Role.JURY))
        self.assertFalse(has_role(self.user, self.event, Role.JURY))
        self.assertFalse(can_manage(self.user, self.event))
        set_role(actor=self.owner, user=self.user, hackathon=self.event, role=Role.PARTICIPANT, status=AssignmentStatus.REVOKED)
        self.assertFalse(has_role(self.user, self.event, Role.PARTICIPANT))
        self.assertEqual(assignment.history.count(), 2)
        set_role(actor=self.owner, user=self.user, hackathon=self.event, role=Role.PARTICIPANT)
        self.assertEqual(assignment.history.count(), 3)
        self.assertEqual(RoleAssignment.objects.filter(user=self.user, hackathon=self.event, role=Role.PARTICIPANT).count(), 1)

    def test_conflicting_roles_same_event_rejected(self):
        set_role(actor=self.owner, user=self.user, hackathon=self.event, role=Role.PARTICIPANT)
        with self.assertRaises(ValidationError):
            set_role(actor=self.owner, user=self.user, hackathon=self.event, role=Role.JURY)

    def test_unassigned_user_cannot_assign_roles(self):
        with self.assertRaises(PermissionDenied):
            set_role(actor=self.user, user=self.user, hackathon=self.event, role=Role.ORGANIZER)
        self.assertFalse(is_member(self.user, self.event))

    def test_last_organizer_cannot_be_revoked(self):
        with self.assertRaises(ValidationError):
            set_role(actor=self.owner, user=self.owner, hackathon=self.event, role=Role.ORGANIZER, status='REVOKED')

    def test_inactive_user_never_authorized(self):
        self.owner.is_active = False
        self.owner.save()
        self.assertFalse(can_manage(self.owner, self.event))

    def test_technical_admin_is_separate_from_organizer(self):
        self.owner.is_staff = True
        self.owner.save()
        self.owner.user_permissions.add(Permission.objects.get(codename='change_user'))
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/admin/accounts/user/').status_code, 403)
        self.owner.user_permissions.add(Permission.objects.get(codename='change_group'))
        self.assertEqual(self.client.get('/admin/auth/group/').status_code, 403)

    def test_avatar_validated_and_size_limited(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.validators import validate_image_size
        self.client.force_login(self.user)
        response = self.client.post(reverse('accounts:profile-edit'), {'email': self.user.email,
            'avatar': SimpleUploadedFile('fake.png', b'not an image', content_type='image/png')})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors.get('avatar'))
        with self.assertRaises(ValidationError):
            validate_image_size(SimpleUploadedFile('large.png', b'x'*(5*1024*1024+1)))
