"""seed_m4_demo: a demo edition that is open today, with complete teams, built through the real services."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import translation

from accounts.models import Role, RoleAssignment, User
from hackathons.models import Hackathon
from teams import services as team_services
from teams.models import Team
from .. import services
from ..models import MentorExpertise, MentorSlot, SupportRequest


def run(*args, **options):
    out = StringIO()
    call_command(*args, stdout=out, **options)
    return out.getvalue()


@override_settings(DEBUG=True)
class SeedM4Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        translation.activate('fr')
        User.objects.create_user(username='asma02', email='asma@example.test')
        run('seed_demo', user='asma02')  # accounts, skills and the two historical editions (+ seed_m2_demo)
        run('seed_m4_demo', user='asma02')
        cls.event = Hackathon.objects.get(slug='mentoring-lab-2026')

    def tearDown(self):
        translation.deactivate()

    def snapshot(self):
        return (Team.objects.count(), SupportRequest.objects.count(), MentorSlot.objects.count(),
                MentorExpertise.objects.count(), RoleAssignment.objects.count())

    def test_the_edition_is_ongoing_and_its_development_phase_is_open_today(self):
        from hackathons.models import EventPhase
        from hackathons.services import phase_is_open
        self.assertEqual(self.event.status, 'ONGOING')
        self.assertTrue(phase_is_open(self.event, EventPhase.Kind.DEVELOPMENT))

    def test_both_teams_are_complete_with_two_active_members(self):
        for name, captain in (('Nova Live', 'ahmed'), ('Horizon Live', 'sami')):
            team = Team.objects.get(hackathon=self.event, name=name)
            self.assertTrue(team.is_ready, name)
            self.assertEqual(team_services.active_members(team).count(), 2)
            self.assertEqual(team.captain.user.username, captain)

    def test_mentors_have_expertises_slots_and_the_mentor_role(self):
        for username in ('mentor.django', 'mentor.front', 'mentor.data'):
            user = User.objects.get(username=username)
            self.assertTrue(MentorExpertise.objects.filter(user=user).exists(), username)
            self.assertTrue(MentorSlot.objects.published().filter(mentor=user, hackathon=self.event).exists(), username)
            self.assertTrue(RoleAssignment.objects.filter(user=user, hackathon=self.event, role=Role.MENTOR, status='ACTIVE').exists())
        self.assertEqual(MentorSlot.objects.published().filter(hackathon=self.event).count(), 7)  # 6 to come + 1 already held

    def test_requests_follow_the_confidentiality_rules(self):
        ahmed, sami = User.objects.get(username='ahmed'), User.objects.get(username='sami')
        self.assertEqual({r.subject for r in services.visible_requests(ahmed).filter(hackathon=self.event)},
            {'Erreur 500 sur notre API Django', 'Mise en page responsive'})
        self.assertEqual(services.visible_requests(sami).filter(hackathon=self.event).count(), 2)
        # A mentor only sees the requests he is booked on: mentor.django has one appointment, mentor.data none.
        self.assertEqual([r.subject for r in services.visible_requests(User.objects.get(username='mentor.django')).filter(hackathon=self.event)],
            ['Erreur 500 sur notre API Django'])
        self.assertFalse(services.visible_requests(User.objects.get(username='mentor.data')).filter(hackathon=self.event).exists())

    def test_the_organizer_overview_has_real_critical_and_recurring_data(self):
        insights = services.support_insights(self.event)
        self.assertEqual(insights['active_count'], 4)
        self.assertEqual([r.subject for r in insights['critical']], ['Déploiement bloqué'])
        self.assertEqual([(row['skill__name'], row['teams']) for row in insights['recurring']], [('Django', 2)])

    def test_the_given_user_becomes_organizer_and_mentor_of_the_edition(self):
        asma = User.objects.get(username='asma02')
        roles = set(RoleAssignment.objects.filter(user=asma, hackathon=self.event, status='ACTIVE').values_list('role', flat=True))
        self.assertEqual(roles, {Role.ORGANIZER, Role.MENTOR})

    def test_running_it_again_creates_nothing_new(self):
        before = self.snapshot()
        run('seed_m4_demo', user='asma02')
        run('seed_demo', user='asma02')
        run('seed_m4_demo', user='asma02')
        self.assertEqual(self.snapshot(), before)

    def test_it_refuses_to_run_without_the_demo_accounts_or_outside_development(self):
        User.objects.filter(username='ines').update(username='gone')
        with self.assertRaises(CommandError):
            run('seed_m4_demo')
        User.objects.filter(username='gone').update(username='ines')
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            run('seed_m4_demo')
        with self.assertRaises(CommandError):
            run('seed_m4_demo', user='nobody')

    def test_the_demo_has_a_booked_appointment_and_a_finished_session_waiting_for_feedback(self):
        from ..models import MentoringSession
        booked = MentoringSession.objects.get(request__subject='Erreur 500 sur notre API Django')
        self.assertEqual((booked.status, booked.slot.mentor.username, booked.request.status), ('BOOKED', 'mentor.django', 'BOOKED'))
        done = MentoringSession.objects.get(request__subject='Mise en page responsive')
        self.assertEqual((done.status, done.slot.mentor.username, done.request.status), ('COMPLETED', 'mentor.front', 'IN_PROGRESS'))
        self.assertIn('points de rupture', done.report)
        ahmed = User.objects.get(username='ahmed')
        self.assertTrue(services.can_give_feedback(ahmed, done))
        self.assertTrue(services.can_cancel_session(ahmed, booked))

    def test_the_demo_has_an_open_workshop_and_a_full_one_with_real_registrations(self):
        from ..models import Workshop, WorkshopRegistration
        open_workshop = Workshop.objects.get(hackathon=self.event, title='Atelier API Django')
        full = Workshop.objects.get(hackathon=self.event, title='Atelier UI/UX en 1 heure')
        self.assertEqual((open_workshop.trainer.username, services.workshop_seats(open_workshop)), ('mentor.django', (2, 2)))
        self.assertEqual((full.trainer.username, services.workshop_seats(full)), ('mentor.front', (2, 0)))
        self.assertEqual(WorkshopRegistration.objects.filter(status='REGISTERED').count(), 4)
        sami = User.objects.get(username='sami')
        from django.core.exceptions import ValidationError
        outsider_team_member = User.objects.get(username='mariem')
        with self.assertRaises(ValidationError):
            services.register_to_workshop(actor=outsider_team_member, workshop=full)  # full: nobody else gets in
        self.assertEqual(services.workshop_seats(full), (2, 0))
        self.assertTrue(sami)
