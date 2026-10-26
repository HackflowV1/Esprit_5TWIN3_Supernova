from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from io import StringIO
from django.core.management import call_command
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import connection, close_old_connections, IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from accounts.models import User, Role, RoleAssignment, AssignmentStatus, Skill, UserSkill
from accounts.services import set_role
from hackathons.models import Hackathon, EventPhase
from hackathons.services import transition, save_configuration
from hackathons.test_helpers import make_owner, make_event
from .models import Registration, TeamMembership, TeamInvitation, JoinRequest, Decision, TeamSkillNeed
from . import services


@override_settings(DEBUG=True)
class SeedDemoTests(TestCase):
    def test_fresh_seed_repeat_and_preserve_cancellation(self):
        from .models import Team
        call_command('seed_demo', stdout=StringIO())
        event = Hackathon.objects.get(slug='ai-challenge-2026')
        self.assertEqual(event.registrations.count(), 4)
        self.assertEqual(event.teams.count(), 2)
        self.assertEqual(JoinRequest.objects.count(), 1)
        self.assertEqual(TeamInvitation.objects.count(), 1)
        mariem = User.objects.get(username='mariem')
        registration = Registration.objects.get(user=mariem, hackathon=event)
        services.cancel_registration(actor=mariem, registration=registration)
        call_command('seed_demo', stdout=StringIO())
        registration.refresh_from_db()
        self.assertEqual(registration.status, Registration.Status.CANCELLED)
        self.assertEqual(Registration.objects.count(), 4)
        self.assertEqual(Team.objects.count(), 2)
        self.assertEqual(JoinRequest.objects.count(), 1)
        self.assertEqual(TeamInvitation.objects.count(), 1)


class SetupMixin:
    def setUp(self):
        self.owner = make_owner()
        self.event = make_event(self.owner, complete=True)
        EventPhase.objects.create(hackathon=self.event, kind='TEAM_FORMATION', start=self.event.registration_open, end=self.event.start_date)
        transition(actor=self.owner, event=self.event, target='PUBLISHED')
        self.event.refresh_from_db()
        self.a = User.objects.create_user('alice', password='Test-only#2026')
        self.b = User.objects.create_user('bob', password='Test-only#2026')
        self.c = User.objects.create_user('carol', password='Test-only#2026')

    def reg(self, user):
        return services.register(actor=user, event=self.event, accept_conditions=True)

    def team(self):
        self.reg(self.a)
        return services.create_team(actor=self.a, event=self.event, name='Nova', description='Build useful things')


class RegistrationTests(SetupMixin, TestCase):
    def test_register_cancel_reactivate_and_roles(self):
        set_role(actor=self.owner, user=self.a, hackathon=self.event, role=Role.MENTOR)
        reg = self.reg(self.a)
        self.assertEqual(self.reg(self.a).pk, reg.pk)
        self.assertTrue(RoleAssignment.objects.filter(user=self.a, role=Role.PARTICIPANT, status='ACTIVE').exists())
        services.cancel_registration(actor=self.a, registration=reg)
        self.assertTrue(RoleAssignment.objects.filter(user=self.a, role=Role.MENTOR, status='ACTIVE').exists())
        self.assertEqual(self.reg(self.a).pk, reg.pk)
        self.assertEqual(reg.history.count(), 3)

    def test_jury_conditions_closed_and_inactive(self):
        with self.assertRaises(ValidationError):
            services.register(actor=self.a, event=self.event, accept_conditions=False)
        set_role(actor=self.owner, user=self.a, hackathon=self.event, role=Role.JURY)
        with self.assertRaises(ValidationError):
            self.reg(self.a)
        self.event.phases.filter(kind='REGISTRATION').update(end=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(ValidationError):
            self.reg(self.b)
        self.b.is_active = False
        self.b.save()
        with self.assertRaises(PermissionDenied):
            self.reg(self.b)

    def test_manual_role_is_not_registration_and_cannot_revoke_registered_role(self):
        set_role(actor=self.owner, user=self.a, hackathon=self.event, role=Role.PARTICIPANT)
        self.assertIsNone(services.accepted_registration(self.a, self.event))
        self.assertFalse(services.can_read(self.a, self.event))
        self.reg(self.a)
        with self.assertRaises(ValidationError):
            set_role(actor=self.owner, user=self.a, hackathon=self.event, role=Role.PARTICIPANT, status='REVOKED')
        with self.assertRaises(ValidationError):
            set_role(actor=self.owner, user=self.a, hackathon=self.event, role=Role.JURY)

    def test_only_self_or_organizer_can_cancel(self):
        reg = self.reg(self.a)
        with self.assertRaises(PermissionDenied):
            services.cancel_registration(actor=self.b, registration=reg)


class TeamFlowTests(SetupMixin, TestCase):
    def test_application_to_ready_team_and_pending_cleanup(self):
        team = self.team()
        self.assertFalse(team.is_ready)
        self.assertEqual(services.active_members(team).count(), 1)
        reg = self.reg(self.b)
        request = services.recruit(actor=self.b, team=team, message='I can help')
        invite = services.recruit(actor=self.a, team=team, registration=reg)
        services.decide(actor=self.a, record=request, decision='ACCEPTED')
        invite.refresh_from_db()
        self.assertEqual(invite.status, Decision.CANCELLED)
        self.assertTrue(team.is_ready)
        self.assertEqual(services.active_team(self.b, self.event), team)
        with self.assertRaises(ValidationError):
            services.decide(actor=self.a, record=request, decision='ACCEPTED')

    def test_invitation_acceptance_is_only_for_invitee(self):
        team = self.team()
        invite = services.recruit(actor=self.a, team=team, registration=self.reg(self.b))
        with self.assertRaises(PermissionDenied):
            services.decide(actor=self.c, record=invite, decision='ACCEPTED')
        services.decide(actor=self.b, record=invite, decision='ACCEPTED')
        self.assertEqual(team.member_count, 2)

    def test_single_team_and_captain_transfer_leave(self):
        team = self.team()
        reg = self.reg(self.b)
        invite = services.recruit(actor=self.a, team=team, registration=reg)
        services.decide(actor=self.b, record=invite, decision='ACCEPTED')
        captain = services.active_members(team).get(registration__user=self.a)
        with self.assertRaises(ValidationError):
            services.leave_team(actor=self.a, team=team, membership=captain)
        with self.assertRaises(ValidationError):
            services.create_team(actor=self.b, event=self.event, name='Other')
        member = services.active_members(team).get(registration=reg)
        services.transfer_captain(actor=self.a, team=team, membership=member)
        services.leave_team(actor=self.a, team=team, membership=captain)
        team.refresh_from_db()
        self.assertEqual(team.captain_id, reg.pk)
        self.assertEqual(team.member_count, 1)
        services.leave_team(actor=self.b, team=team, membership=member)
        team.refresh_from_db()
        self.assertIsNotNone(team.closed_at)

    def test_cancellation_requires_leaving_first(self):
        team = self.team()
        reg = Registration.objects.get(user=self.a)
        with self.assertRaises(ValidationError):
            services.cancel_registration(actor=self.a, registration=reg)

    def test_full_expired_duplicate_and_wrong_team_requests(self):
        team = self.team()
        reg = self.reg(self.b)
        invite = services.recruit(actor=self.a, team=team, registration=reg)
        with self.assertRaises(ValidationError):
            services.recruit(actor=self.a, team=team, registration=reg)
        TeamInvitation.objects.filter(pk=invite.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(ValidationError):
            services.decide(actor=self.b, record=invite, decision='ACCEPTED')
        renewed = services.recruit(actor=self.a, team=team, registration=reg)
        self.assertNotEqual(invite.pk, renewed.pk)
        self.event.max_team_size = 2
        self.event.save()
        services.decide(actor=self.b, record=renewed, decision='ACCEPTED')
        self.reg(self.c)
        with self.assertRaises(ValidationError):
            services.recruit(actor=self.c, team=team)

    def test_other_member_cannot_manage(self):
        team = self.team()
        self.reg(self.b)
        with self.assertRaises(PermissionDenied):
            services.update_team(actor=self.b, team=team, name='Hijack', description='', recruiting=True)

    def test_frozen_and_archived_event(self):
        team = self.team()
        reg = self.reg(self.b)
        invite = services.recruit(actor=self.a, team=team, registration=reg)
        self.event.phases.filter(kind='TEAM_FORMATION').update(end=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(ValidationError):
            services.decide(actor=self.b, record=invite, decision='ACCEPTED')
        with self.assertRaises(ValidationError):
            services.cancel_registration(actor=self.b, registration=reg)
        Hackathon.objects.filter(pk=self.event.pk).update(status='ARCHIVED')
        self.assertTrue(services.can_read(self.a, self.event))
        with self.assertRaises(ValidationError):
            services.update_team(actor=self.a, team=team, name='Changed', description='', recruiting=True)

    def test_m1_cannot_shrink_occupied_capacity(self):
        team = self.team()
        self.reg(self.b)
        self.reg(self.c)
        self.event.capacity = 2
        self.event.max_team_size = 2
        with self.assertRaises(ValidationError):
            save_configuration(actor=self.owner, event=self.event)

    def test_matching_is_scoped_and_explainable(self):
        team = self.team()
        reg = self.reg(self.b)
        self.reg(self.c)
        skill = Skill.objects.create(name='Figma', category='Design')
        UserSkill.objects.create(user=self.b, skill=skill, level=4)
        services.save_need(actor=self.a, team=team, skill=skill, level=3, priority=3)
        other = make_event(self.owner, slug='other')
        set_role(actor=self.owner, user=self.b, hackathon=other, role=Role.JURY)
        matches = services.recommendations(actor=self.a, team=team)
        self.assertEqual(matches[0]['registration'], reg)
        self.assertTrue(matches[0]['matches'][0]['meets'])
        self.assertEqual(len(matches), 2)
        stranger = User.objects.create_user('stranger')
        with self.assertRaises(PermissionDenied):
            services.recommendations(actor=stranger, team=team)
        self.assertEqual(services.metrics(self.event), {'registrations': 3, 'teams': 1, 'incomplete_teams': 1, 'participants_without_team': 2})
        invitation = services.recruit(actor=self.a, team=team, registration=reg)
        services.decide(actor=self.b, record=invitation, decision='ACCEPTED')
        self.assertEqual(services.skill_coverage(team)[0].covered_by, [self.b])
        self.assertEqual(services.recommendations(actor=self.a, team=team)[0]['score'], 0)

    def test_membership_database_constraint_and_cross_event_validation(self):
        team = self.team()
        reg = Registration.objects.get(user=self.a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeamMembership.objects.create(team=team, registration=reg)
        other = make_event(self.owner, slug='other')
        wrong = Registration.objects.create(user=self.b, hackathon=other)
        with self.assertRaises(ValidationError):
            TeamMembership(team=team, registration=wrong).full_clean()


class ScreenTests(SetupMixin, TestCase):
    def test_navigation_and_full_form_flow(self):
        self.client.force_login(self.a)
        response = self.client.get(reverse('hackathons:detail', args=[self.event.slug]))
        self.assertContains(response, reverse('teams:register', args=[self.event.slug]))
        response = self.client.post(reverse('teams:register', args=[self.event.slug]), {'accept_conditions': 'on'})
        self.assertRedirects(response, reverse('teams:list', args=[self.event.slug]))
        response = self.client.post(reverse('teams:create', args=[self.event.slug]), {'name': 'Nova', 'description': 'A meaningful project'})
        team = services.active_team(self.a, self.event)
        self.assertRedirects(response, team.get_absolute_url())
        skill = Skill.objects.create(name='UX', category='Design')
        response = self.client.post(reverse('teams:need-add', args=[self.event.slug, team.pk]), {'skill': skill.pk, 'level': 3, 'priority': 2})
        self.assertRedirects(response, team.get_absolute_url())
        self.assertEqual(team.skill_needs.count(), 1)
        for name, args in [('mine', []), ('list', [self.event.slug]), ('detail', [self.event.slug, team.pk]), ('inbox', [self.event.slug]), ('candidates', [self.event.slug, team.pk]), ('invite', [self.event.slug, team.pk]), ('edit', [self.event.slug, team.pk])]:
            for lang in ('fr', 'en'):
                self.client.cookies['hackflow_language'] = lang
                self.assertEqual(self.client.get(reverse('teams:'+name, args=args)).status_code, 200, (name, lang))

    def test_privacy_cross_event_and_post_only_decisions(self):
        team = self.team()
        self.client.force_login(self.b)
        self.assertTemplateUsed(self.client.get(team.get_absolute_url()), 'teams/preview.html')
        self.reg(self.b)
        response = self.client.get(team.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.a.email) if self.a.email else None
        self.assertEqual(self.client.get(reverse('teams:manage', args=[self.event.slug])).status_code, 403)
        other = make_event(self.owner, slug='other')
        self.assertEqual(self.client.get(reverse('teams:detail', args=[other.slug, team.pk])).status_code, 404)
        request = services.recruit(actor=self.b, team=team)
        self.assertEqual(self.client.get(reverse('teams:decide', args=[self.event.slug, 'application', request.pk, 'ACCEPTED'])).status_code, 405)

    def test_organizer_management_and_registration_error(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('teams:manage', args=[self.event.slug])).status_code, 200)
        self.client.force_login(self.b)
        response = self.client.post(reverse('teams:register', args=[self.event.slug]), {})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(Registration.objects.filter(user=self.b).exists())

    def test_skill_need_update_delete_and_english(self):
        team = self.team()
        self.client.force_login(self.a)
        skill = Skill.objects.create(name='React', category='Frontend')
        need = services.save_need(actor=self.a, team=team, skill=skill, level=2, priority=1)
        self.client.post(reverse('teams:need-edit', args=[self.event.slug, team.pk, need.pk]), {'skill': skill.pk, 'level': 4, 'priority': 3})
        need.refresh_from_db()
        self.assertEqual(need.level, 4)
        self.client.cookies['hackflow_language'] = 'en'
        self.assertContains(self.client.get(reverse('teams:list', args=[self.event.slug])), 'Find your team')
        self.client.post(reverse('teams:need-delete', args=[self.event.slug, team.pk, need.pk]))
        self.assertFalse(TeamSkillNeed.objects.filter(pk=need.pk).exists())

    def test_archive_counts_use_recorded_snapshot(self):
        self.client.force_login(self.owner)
        Hackathon.objects.filter(pk=self.event.pk).update(status='ARCHIVED', archive_metrics={'modules': {'M2': {'available': True, 'counts': {'registrations': 7, 'teams': 2, 'incomplete_teams': 1, 'participants_without_team': 1}}}})
        response = self.client.get(reverse('teams:manage', args=[self.event.slug]))
        self.assertEqual(response.context['counts']['registrations'], 7)


class ConcurrencyTests(SetupMixin, TransactionTestCase):
    def race(self, tasks):
        barrier = Barrier(len(tasks))
        def run(task):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                task()
                return True
            except ValidationError:
                return False
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            return list(pool.map(run, tasks))

    def test_last_registration_place(self):
        self.event.capacity = self.event.max_team_size = 2
        self.event.save()
        self.reg(self.a)
        results = self.race([lambda: self.reg(self.b), lambda: self.reg(self.c)])
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.event.registrations.filter(status='ACCEPTED').count(), 2)

    def test_last_team_place(self):
        team = self.team()
        self.event.max_team_size = 2
        self.event.save()
        b, c = self.reg(self.b), self.reg(self.c)
        i1 = services.recruit(actor=self.a, team=team, registration=b)
        i2 = services.recruit(actor=self.a, team=team, registration=c)
        results = self.race([lambda: services.decide(actor=self.b, record=i1, decision='ACCEPTED'), lambda: services.decide(actor=self.c, record=i2, decision='ACCEPTED')])
        self.assertEqual(sum(results), 1)
        self.assertEqual(team.member_count, 2)

    def test_two_teams_same_participant(self):
        team1 = self.team()
        self.reg(self.b)
        team2 = services.create_team(actor=self.b, event=self.event, name='Horizon')
        reg = self.reg(self.c)
        i1 = services.recruit(actor=self.a, team=team1, registration=reg)
        i2 = services.recruit(actor=self.b, team=team2, registration=reg)
        results = self.race([lambda: services.decide(actor=self.c, record=i1, decision='ACCEPTED'), lambda: services.decide(actor=self.c, record=i2, decision='ACCEPTED')])
        self.assertEqual(sum(results), 1)
        self.assertEqual(reg.memberships.filter(ended_at__isnull=True).count(), 1)
