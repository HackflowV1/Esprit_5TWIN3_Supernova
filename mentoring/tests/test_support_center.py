"""The Support Center screens: list, request form, follow-up page and cancellation."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from accounts.models import Role, Skill
from accounts.services import set_role
from hackathons.test_helpers import make_owner
from ..models import MentoringSession, MentorSlot, SupportRequest
from .helpers import make_ongoing_event, make_request, make_team, make_user


class CenterBase(TestCase):
    def setUp(self):
        translation.activate('fr')
        self.addCleanup(translation.deactivate)

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.event = make_ongoing_event(cls.owner)
        cls.captain, cls.member, cls.outsider = make_user('captain'), make_user('member'), make_user('outsider')
        cls.rival_captain, cls.mentor = make_user('rival'), make_user('mentor')
        set_role(actor=cls.owner, user=cls.mentor, hackathon=cls.event, role=Role.MENTOR)
        cls.team = make_team(cls.event, cls.captain, name='Nova', members=[cls.member])
        cls.rival = make_team(cls.event, cls.rival_captain, name='Horizon')
        cls.django = Skill.objects.create(name='Django', category='Backend')
        cls.list_url = reverse('mentoring:support-list')
        cls.new_url = reverse('mentoring:support-new')

    def mine(self, **overrides):
        return make_request(self.team, self.member, **overrides)

    def theirs(self, **overrides):
        return make_request(self.rival, self.rival_captain, **{'subject': 'Problème Horizon', **overrides})

    def book(self, request):
        start = timezone.now().replace(second=0, microsecond=0) + timedelta(hours=1)
        slot = MentorSlot.objects.create(hackathon=self.event, mentor=self.mentor, start=start, end=start + timedelta(minutes=30))
        return MentoringSession.objects.create(request=request, slot=slot, booked_by=self.captain)

    def url(self, name, request):
        return reverse('mentoring:' + name, args=[request.pk])


class AccessTests(CenterBase):
    def test_anonymous_is_sent_to_login(self):
        request = self.mine()
        for url in (self.list_url, self.new_url, self.url('support-detail', request), self.url('support-cancel', request)):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('accounts:login'), response['Location'])


class ListTests(CenterBase):
    def test_a_team_member_sees_the_requests_of_his_team_only(self):
        self.mine(subject='API Django')
        self.theirs()
        self.client.force_login(self.member)
        page = self.client.get(self.list_url)
        self.assertContains(page, 'API Django')
        self.assertNotContains(page, 'Problème Horizon')
        self.assertContains(page, 'Demander de l’aide')
        self.assertContains(page, '<time datetime=')

    def test_empty_state_invites_the_team_to_ask(self):
        self.client.force_login(self.member)
        page = self.client.get(self.list_url)
        self.assertContains(page, 'Aucune demande pour l’instant')
        self.assertContains(page, self.new_url)

    def test_priority_is_written_in_words_and_most_urgent_comes_first(self):
        self.mine(subject='Question simple', priority='LOW')
        self.mine(subject='Tout est bloqué', priority='CRITICAL')
        self.client.force_login(self.member)
        page = self.client.get(self.list_url)
        self.assertContains(page, 'Priorité :')
        self.assertContains(page, 'Critique')
        html = page.content.decode()
        self.assertLess(html.index('Tout est bloqué'), html.index('Question simple'))

    def test_a_user_without_team_is_told_what_to_do(self):
        self.client.force_login(self.outsider)
        page = self.client.get(self.list_url)
        self.assertContains(page, 'L’assistance, c’est pour les équipes')
        self.assertNotContains(page, self.new_url)

    def test_a_mentor_sees_only_the_requests_he_coaches(self):
        request = self.mine(subject='API Django')
        self.client.force_login(self.mentor)
        page = self.client.get(self.list_url)
        self.assertContains(page, 'Aucune demande à accompagner')
        self.assertNotContains(page, 'API Django')
        self.book(request)
        page = self.client.get(self.list_url)
        self.assertContains(page, 'Les demandes que j’accompagne')
        self.assertContains(page, 'API Django')
        self.assertNotContains(page, self.new_url)

    def test_the_organizer_gets_critical_and_recurring_blocks_from_real_data(self):
        self.mine(subject='Tout est bloqué', priority='CRITICAL', skill=self.django)
        self.theirs(skill=self.django)
        self.client.force_login(self.owner)
        page = self.client.get(self.list_url)
        self.assertContains(page, 'Pilotage de l’assistance')
        self.assertContains(page, 'Blocages critiques')
        self.assertContains(page, 'Ce qui revient souvent')
        self.assertContains(page, '2 équipes · 2 demandes')
        self.assertContains(page, 'Problème Horizon')

    def test_one_team_asking_twice_is_not_recurring(self):
        self.mine(skill=self.django)
        self.mine(subject='Autre', skill=self.django)
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(self.list_url), 'Ce qui revient souvent')

    def test_another_organizer_does_not_see_this_edition(self):
        self.mine(subject='API Django')
        other = make_owner('other_owner')
        self.client.force_login(other)
        self.assertNotContains(self.client.get(self.list_url), 'API Django')


class FormTests(CenterBase):
    payload = {'subject': 'Erreur 500 sur /api', 'description': 'Le serializer plante.', 'priority': 'HIGH'}

    def test_the_form_offers_the_user_teams_and_preselects_the_requested_one(self):
        self.client.force_login(self.member)
        page = self.client.get(self.new_url)
        self.assertContains(page, 'Nova — Hackathon live')
        self.assertContains(page, 'Décrivez le blocage')
        self.assertContains(page, 'Je ne sais pas / autre')
        self.assertContains(self.client.get(f'{self.new_url}?team={self.team.pk}'), f'value="{self.team.pk}" selected')

    def test_a_member_opens_a_request(self):
        self.client.force_login(self.member)
        response = self.client.post(self.new_url, {**self.payload, 'team': self.team.pk, 'skill': self.django.pk})
        request = SupportRequest.objects.get()
        self.assertRedirects(response, request.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((request.team, request.author, request.skill, request.priority, request.status),
            (self.team, self.member, self.django, 'HIGH', 'OPEN'))
        page = self.client.get(request.get_absolute_url())
        self.assertContains(page, 'Votre demande d’aide est ouverte.')
        self.assertContains(page, 'Demande ouverte')

    def test_errors_are_summarized_and_nothing_is_saved(self):
        self.client.force_login(self.member)
        response = self.client.post(self.new_url, {'team': self.team.pk, 'subject': '  ', 'description': '', 'priority': 'NORMAL'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-error-summary')
        self.assertFalse(SupportRequest.objects.exists())

    def test_another_team_cannot_be_chosen(self):
        self.client.force_login(self.member)
        response = self.client.post(self.new_url, {**self.payload, 'team': self.rival.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SupportRequest.objects.exists())

    def test_a_user_without_team_gets_an_explanation_and_cannot_post(self):
        self.client.force_login(self.outsider)
        self.assertContains(self.client.get(self.new_url), 'Vous ne pouvez pas demander d’aide pour le moment')
        self.client.post(self.new_url, {**self.payload, 'team': self.team.pk})
        self.assertFalse(SupportRequest.objects.exists())

    def test_the_form_is_closed_outside_the_development_phase(self):
        from django.utils import timezone as tz
        from unittest.mock import patch
        self.client.force_login(self.member)
        with patch('hackathons.services.timezone.now', return_value=tz.now() + timedelta(days=2, hours=1)):
            self.assertContains(self.client.get(self.new_url), 'Vous ne pouvez pas demander d’aide pour le moment')


class DetailTests(CenterBase):
    def test_the_team_follows_its_request(self):
        request = self.mine(subject='API Django', description='Bloqués sur le serializer.')
        self.client.force_login(self.captain)
        page = self.client.get(self.url('support-detail', request))
        for text in ('API Django', 'Bloqués sur le serializer.', 'Prochaine étape', 'Choisir un mentor et un créneau.',
                     'Aucun rendez-vous pour l’instant.', 'Nova', 'Annuler la demande'):
            self.assertContains(page, text)
        self.assertContains(page, '<h1', count=1)

    def test_other_teams_outsiders_and_unrelated_mentors_get_a_404(self):
        request = self.mine()
        for user in (self.rival_captain, self.outsider, self.mentor):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url('support-detail', request)).status_code, 404)
                self.assertEqual(self.client.get(self.url('support-cancel', request)).status_code, 404)

    def test_a_former_member_loses_the_access(self):
        from teams.models import TeamMembership
        request = self.mine()
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url('support-detail', request)).status_code, 200)
        TeamMembership.objects.filter(registration__user=self.member).update(ended_at=timezone.now())
        self.assertEqual(self.client.get(self.url('support-detail', request)).status_code, 404)

    def test_organizer_and_coaching_mentor_can_read_but_the_mentor_cannot_cancel(self):
        request = self.mine()
        self.book(request)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url('support-detail', request)).status_code, 200)
        self.client.force_login(self.mentor)
        page = self.client.get(self.url('support-detail', request))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Rendez-vous')
        self.assertNotContains(page, self.url('support-cancel', request))

    def test_the_status_changes_the_next_step_text(self):
        request = self.mine()
        self.client.force_login(self.captain)
        for status, text in (('BOOKED', 'préparez vos questions'), ('IN_PROGRESS', 'dites-nous si le problème est résolu'),
                             ('RESOLVED', 'Problème résolu'), ('CANCELLED', 'Cette demande a été annulée.')):
            SupportRequest.objects.filter(pk=request.pk).update(status=status)
            self.assertContains(self.client.get(self.url('support-detail', request)), text)

    def test_the_m2_team_page_links_to_the_request_form_for_members_only(self):
        link = f'{self.new_url}?team={self.team.pk}'
        self.client.force_login(self.member)
        self.assertContains(self.client.get(self.team.get_absolute_url()), link)
        self.client.force_login(self.rival_captain)
        self.assertNotContains(self.client.get(self.team.get_absolute_url()), link)


class CancelTests(CenterBase):
    def test_get_asks_for_confirmation_and_changes_nothing(self):
        request = self.mine()
        self.client.force_login(self.captain)
        self.assertContains(self.client.get(self.url('support-cancel', request)), 'Annuler cette demande ?')
        request.refresh_from_db()
        self.assertEqual(request.status, 'OPEN')

    def test_the_author_cancels_with_a_post(self):
        request = self.mine()
        self.client.force_login(self.member)
        response = self.client.post(self.url('support-cancel', request), follow=True)
        self.assertContains(response, 'Demande annulée.')
        request.refresh_from_db()
        self.assertEqual(request.status, 'CANCELLED')
        self.assertContains(response, 'Cette demande a été annulée.')
        self.assertNotContains(response, 'Annuler la demande')

    def test_any_member_cancels_a_request_of_the_team(self):
        request = make_request(self.team, self.captain)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url('support-cancel', request)).status_code, 200)
        self.client.post(self.url('support-cancel', request))
        request.refresh_from_db()
        self.assertEqual(request.status, 'CANCELLED')

    def test_a_booked_request_must_have_its_appointment_cancelled_first(self):
        request = self.mine()
        self.book(request)
        SupportRequest.objects.filter(pk=request.pk).update(status='BOOKED')
        self.client.force_login(self.captain)
        response = self.client.post(self.url('support-cancel', request), follow=True)
        self.assertContains(response, 'Annulez d’abord le rendez-vous')
        request.refresh_from_db()
        self.assertEqual(request.status, 'BOOKED')

    def test_the_organizer_can_cancel_for_a_team(self):
        request = self.mine()
        self.client.force_login(self.owner)
        self.client.post(self.url('support-cancel', request))
        request.refresh_from_db()
        self.assertEqual(request.status, 'CANCELLED')


class NavigationAndLanguageTests(CenterBase):
    def test_the_main_menu_has_one_mentoring_entry_for_signed_in_users_only(self):
        hub = reverse('mentoring:hub')
        self.assertNotContains(self.client.get(reverse('core:home')), f'href="{hub}"')
        self.client.force_login(self.member)
        page = self.client.get(reverse('core:home'))
        self.assertContains(page, f'href="{hub}"')
        self.assertNotContains(page, f'href="{self.list_url}"')  # assistance, workshops... live inside the module tabs

    def test_breadcrumbs_and_titles(self):
        request = self.mine(subject='API Django')
        self.client.force_login(self.member)
        page = self.client.get(self.url('support-detail', request))
        self.assertContains(page, f'<a href="{self.list_url}">Assistance</a>')
        self.assertContains(page, '<li aria-current="page">API Django</li>')
        self.assertContains(self.client.get(self.new_url), '<li aria-current="page">Demander de l’aide</li>')

    def test_every_support_screen_is_english_when_asked(self):
        request = self.mine(subject='API Django')
        self.client.force_login(self.member)
        self.client.post(reverse('set_language'), {'language': 'en', 'next': '/'})
        self.addCleanup(translation.deactivate)
        french = ('Demander', 'Annuler', 'demande', 'Prochaine', 'Rendez-vous', 'Aucun', 'Équipe', 'équipe', 'Historique', 'Décrivez', 'Priorité')
        for url, expected in ((self.list_url, 'Support Center'), (self.new_url, 'Describe the blockage'),
                              (self.url('support-detail', request), 'Next step'), (self.url('support-cancel', request), 'Cancel this request?')):
            with self.subTest(url=url):
                page = self.client.get(url)
                self.assertContains(page, expected)
                html = page.content.decode()
                for word in french:
                    self.assertNotIn(word, html, f'{word!r} still in French on {url}')
