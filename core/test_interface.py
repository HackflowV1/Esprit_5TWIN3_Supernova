"""Integration checks for the shared interface, languages and form semantics."""
from html.parser import HTMLParser

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import override

from accounts.models import Role, RoleAssignment, Skill, SponsorMembership, UserSkill
from hackathons.models import Challenge, EventPhase, SponsorOrganization, Sponsorship, Track
from hackathons.services import transition
from hackathons.test_helpers import make_event, make_owner


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class InterfaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner('interface-owner')
        cls.event = make_event(cls.owner, 'interface-edition', complete=True)
        cls.event = transition(actor=cls.owner, event=cls.event, target='PUBLISHED')
        cls.organization = SponsorOrganization.objects.create(name='Interface partner')
        cls.partnership = Sponsorship.objects.create(
            organization=cls.organization, hackathon=cls.event,
            contribution_type='Mentoring', status='CONFIRMED')
        cls.skill = UserSkill.objects.create(user=cls.owner,
            skill=Skill.objects.create(name='Django', category='Backend'), level=3)

    def language(self, language):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = language

    def test_profile_has_dedicated_accessibility_navigation_and_controls(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('accounts:profile'))
        self.assertContains(response, 'data-profile-link="accessibility"')
        self.assertContains(response, 'id="accessibility" data-profile-panel')
        self.assertNotContains(response, 'a11y-preview')
        self.assertContains(response, 'data-a11y-setting="colors"')
        self.assertNotContains(response, 'a11y-text-preview')
        self.assertContains(response, 'data-a11y-reset')
        self.assertContains(response, 'accessibility-init.js')
        for route in ('profile-edit', 'skill-add', 'password'):
            self.assertContains(self.client.get(reverse('accounts:' + route)), 'data-profile-nav')

    def test_accessibility_controls_are_available_to_guests_and_admin_in_english(self):
        self.language('en')
        self.assertContains(self.client.get('/'), 'Interface colours')
        self.assertContains(self.client.get('/admin/login/'), 'id="accessibility-dialog"')
        self.assertContains(self.client.get('/admin/login/'), 'Enhanced keyboard focus')

    def test_first_visit_is_french_even_with_an_english_browser(self):
        response = self.client.get('/', HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9')
        self.assertContains(response, '<html lang="fr">')
        self.assertContains(response, 'Vos idées, en équipe.')
        self.assertEqual(response.headers['Content-Language'], 'fr')

    def test_explicit_english_choice_persists_and_counts_are_natural(self):
        response = self.client.post(reverse('set_language'), {'language': 'en', 'next': '/'})
        self.assertRedirects(response, '/')
        self.assertEqual(response.cookies[settings.LANGUAGE_COOKIE_NAME].value, 'en')
        self.assertContains(self.client.get('/'), 'Your ideas, together.')
        response = self.client.get(reverse('hackathons:list'))
        self.assertContains(response, '1 hackathon found')
        self.assertNotContains(response, 'founds')
        self.assertContains(response, 'Published')
        response = self.client.get(reverse('hackathons:list'), {'q': 'no-such-event'})
        self.assertContains(response, '0 hackathons found')

    def test_language_form_requires_csrf_and_does_not_redirect_to_another_site(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('set_language'), {'language': 'en'}).status_code, 403)
        client.get('/')
        response = client.post(reverse('set_language'), {
            'language': 'en', 'next': 'https://other.example/',
            'csrfmiddlewaretoken': client.cookies['csrftoken'].value,
        })
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('other.example', response.url)

    def test_all_user_and_organizer_screens_render_in_both_languages(self):
        self.client.force_login(self.owner)
        urls = [reverse('core:home')]
        for name in ('profile', 'profile-edit', 'password', 'password-done', 'skill-add'):
            urls.append(reverse('accounts:' + name))
        for name in ('skill-edit', 'skill-delete'):
            urls.append(reverse('accounts:' + name, kwargs={'pk': self.skill.pk}))
        for name in ('list', 'create', 'dashboard', 'compare'):
            urls.append(reverse('hackathons:' + name))
        for name in ('detail', 'edit', 'manage', 'history', 'roles', 'organization-add'):
            urls.append(reverse('hackathons:' + name, kwargs={'slug': self.event.slug}))
        for kind, model in (('track', Track), ('phase', EventPhase), ('challenge', Challenge), ('sponsorship', Sponsorship)):
            obj = (model.objects.filter(track__hackathon=self.event).first() if kind == 'challenge'
                   else model.objects.filter(hackathon=self.event).first())
            urls.append(reverse('hackathons:' + kind + '-add', kwargs={'slug': self.event.slug}))
            for action in ('edit', 'delete'):
                urls.append(reverse('hackathons:' + kind + '-' + action,
                    kwargs={'slug': self.event.slug, 'pk': obj.pk}))
        for language in ('fr', 'en'):
            self.language(language)
            for url in urls:
                with self.subTest(language=language, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, f'<html lang="{language}">')
                    self.assertContains(response, '<h1', count=1)
                    self.assertNotContains(response, 'javascript:history.back')
        # Sponsor proposal has its own contextual authorization and form.
        RoleAssignment.objects.create(user=self.owner, hackathon=self.event, role=Role.SPONSOR_REPRESENTATIVE)
        SponsorMembership.objects.create(user=self.owner, organization=self.organization)
        self.assertEqual(self.client.get(reverse('hackathons:propose', kwargs={'slug': self.event.slug})).status_code, 200)

    def test_invalid_form_associates_errors_and_labels_with_fields(self):
        self.language('en')
        response = self.client.post(reverse('accounts:signup'), {})
        self.assertContains(response, 'Check the information you entered')
        parsed = Elements(response.content.decode())
        ids = {attrs['id'] for _, attrs in parsed.elements if 'id' in attrs}
        invalid_fields = [attrs for tag, attrs in parsed.elements
                          if tag in ('input', 'select', 'textarea') and attrs.get('aria-invalid') == 'true']
        self.assertTrue(invalid_fields)
        for attrs in invalid_fields:
            self.assertIn(attrs['id'] + '_error', ids)
            self.assertIn(attrs['id'] + '_error', attrs['aria-describedby'].split())
            self.assertTrue(any(tag == 'label' and label.get('for') == attrs['id']
                                for tag, label in parsed.elements))
        self.assertContains(response, 'data-error-summary')

    def test_account_menu_has_post_logout_and_hides_technical_admin(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('accounts:profile'))
        self.assertContains(response, 'class="dropdown account-menu"')
        self.assertContains(response, 'method="post" action="' + reverse('accounts:logout') + '"')
        self.assertNotContains(response, 'href="' + reverse('admin:index') + '"')
        self.assertContains(response, 'aria-current="page"')

    def test_phase_status_code_does_not_depend_on_display_language(self):
        phase = self.event.phases.get(kind='DEVELOPMENT')
        with override('fr'):
            french_state, french_code = str(phase.state), phase.state_code
        with override('en'):
            self.assertEqual(phase.state_code, french_code)
            self.assertNotEqual(str(phase.state), french_state)

    def test_comparison_preserves_both_selected_editions(self):
        self.client.force_login(self.owner)
        other = make_event(self.owner, 'comparison-other')
        response = self.client.get(reverse('hackathons:compare'), {
            'left': str(self.event.pk), 'right': str(other.pk)})
        selected = [attrs.get('value') for tag, attrs in Elements(response.content.decode()).elements
                    if tag == 'option' and 'selected' in attrs]
        self.assertIn(str(self.event.pk), selected)
        self.assertIn(str(other.pk), selected)

    def test_manage_only_offers_draft_deletion_when_service_allows_it(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('hackathons:manage', kwargs={'slug': self.event.slug}))
        for kind, obj in (
            ('track', self.event.tracks.first()), ('phase', self.event.phases.first()),
            ('challenge', Challenge.objects.filter(track__hackathon=self.event).first()),
            ('sponsorship', self.partnership),
        ):
            url = reverse('hackathons:' + kind + '-delete', kwargs={'slug': self.event.slug, 'pk': obj.pk})
            self.assertNotContains(response, 'href="' + url + '"')
        draft = make_event(self.owner, 'deletable-draft')
        track = Track.objects.create(hackathon=draft, name='Draft track')
        response = self.client.get(reverse('hackathons:manage', kwargs={'slug': draft.slug}))
        self.assertContains(response, 'href="' + reverse('hackathons:track-delete',
            kwargs={'slug': draft.slug, 'pk': track.pk}) + '"')

    @override_settings(DEBUG=False)
    def test_error_pages_and_standalone_server_error_are_translated(self):
        self.language('en')
        self.assertContains(self.client.get('/a-missing-page/'), 'Page not found', status_code=404)
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.get('/admin/'), '/admin/login/?next=/admin/', fetch_redirect_response=False)
        other_event = make_event(make_owner('other-organizer'), 'other-edition')
        forbidden = self.client.get(reverse('hackathons:manage', kwargs={'slug': other_event.slug}))
        self.assertContains(forbidden, 'Access denied', status_code=403)
        with override('en'):
            self.assertIn('Something went wrong', render_to_string('500.html'))
