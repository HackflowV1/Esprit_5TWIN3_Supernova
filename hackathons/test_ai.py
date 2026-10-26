"""M1 drafting: Gemini is mocked; no automatic business writes are permitted."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from accounts.models import AssignmentStatus, Role, RoleAssignment, User
from . import ai
from .models import Challenge, EventHistory, Hackathon, Track
from .test_helpers import make_event, make_owner
from .views import SUGGESTIONS_PER_HOUR


SUGGESTION = {'title': 'Un campus accessible', 'problem': 'Les trajets sont difficiles.',
              'objectives': 'Identifier trois obstacles et proposer un trajet.',
              'deliverables': 'Un prototype et une démonstration.'}


@override_settings(GOOGLE_API_KEY='test-only-key', GEMINI_MODELS=['gemini-3.5-flash'])
class SuggestionServiceTests(SimpleTestCase):
    def ask(self, **kwargs):
        return ai.suggest_challenge(
            event=SimpleNamespace(title='Campus', description='Un événement étudiant'),
            track=SimpleNamespace(name='Mobilité', description='Trajets accessibles'),
            idea='Aider les étudiants', **kwargs)

    @patch('hackathons.ai.genai.Client')
    def test_structured_request_timeout_and_minimal_context(self, client):
        generate = client.return_value.__enter__.return_value.models.generate_content
        generate.return_value.text = json.dumps(SUGGESTION)
        self.assertEqual(self.ask(audience='Débutants', duration='24 heures', language='en'), SUGGESTION)
        self.assertEqual(client.call_args.kwargs['http_options'].timeout, 20000)
        call = generate.call_args.kwargs
        self.assertEqual(call['model'], 'gemini-3.5-flash')
        self.assertEqual(call['config'].response_mime_type, 'application/json')
        self.assertEqual(call['config'].thinking_config.thinking_level.value, 'MINIMAL')
        self.assertIn('English', call['contents'])
        self.assertIn('Débutants', call['contents'])
        self.assertIn('24 heures', call['contents'])
        self.assertIn('untrusted data', call['contents'])
        self.assertNotIn('test-only-key', call['contents'])
        self.assertNotIn('email', call['contents'])

    @patch('hackathons.ai.genai.Client')
    @override_settings(GEMINI_MODELS=['gemini-2.5-flash'])
    def test_gemini_25_configuration_and_french(self, client):
        generate = client.return_value.__enter__.return_value.models.generate_content
        generate.return_value.text = json.dumps(SUGGESTION)
        self.ask()
        self.assertEqual(generate.call_args.kwargs['config'].thinking_config.thinking_budget, 0)
        self.assertIn('French', generate.call_args.kwargs['contents'])

    def test_strict_output_validation(self):
        invalid = [None, [], 'text', {}, {**SUGGESTION, 'status': 'PUBLISHED'},
                   {**SUGGESTION, 'title': 'x' * 201}, {**SUGGESTION, 'problem': 'x' * 4001}]
        for name in ai.FIELDS:
            for value in (None, [], {}, 12, True, '', '  ', 'bad\x00text'):
                invalid.append({**SUGGESTION, name: value})
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ai.SuggestionUnavailable):
                ai.clean_suggestion(payload)
        self.assertEqual(ai.clean_suggestion({k: '  ' + v + '  ' for k, v in SUGGESTION.items()}), SUGGESTION)

    @patch('hackathons.ai.genai.Client')
    def test_invalid_json_and_empty_or_excessive_response(self, client):
        generate = client.return_value.__enter__.return_value.models.generate_content
        for text in ('not json', '', None, 'null', '[]', '{}', 'x' * 60001,
                     json.dumps({**SUGGESTION, 'permissions': ['organizer']})):
            generate.return_value.text = text
            with self.subTest(text=str(text)[:30]), self.assertRaises(ai.SuggestionUnavailable):
                self.ask()

    @patch('hackathons.ai.genai.Client')
    def test_api_failures_never_expose_credentials(self, client):
        generate = client.return_value.__enter__.return_value.models.generate_content
        for error in (TimeoutError('private content'), RuntimeError('API_KEY_INVALID test-only-key'),
                      RuntimeError('429 quota private content'), RuntimeError('503 private content')):
            generate.side_effect = error
            with self.subTest(error=type(error).__name__), self.assertRaises(ai.SuggestionUnavailable) as raised:
                self.ask()
            self.assertNotIn('test-only-key', str(raised.exception))
            self.assertNotIn('private content', str(raised.exception))

    @patch('hackathons.ai.genai.Client')
    @override_settings(GOOGLE_API_KEY='')
    def test_missing_key_does_not_call_google(self, client):
        with self.assertRaises(ai.SuggestionUnavailable):
            self.ask()
        client.assert_not_called()


@override_settings(GOOGLE_API_KEY='test-only-key', GEMINI_MODELS=['gemini-3.5-flash'])
class SuggestionViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner('m1-ai-owner')
        cls.event = make_event(cls.owner, 'm1-ai-event')
        cls.track = Track.objects.create(hackathon=cls.event, name='Mobilité')
        cls.other_owner = make_owner('m1-ai-other')
        cls.other = make_event(cls.other_owner, 'm1-ai-other')
        cls.other_track = Track.objects.create(hackathon=cls.other, name='Autre')
        cls.outsider = User.objects.create_user(username='m1-ai-outsider', email='outside@example.test')

    def setUp(self):
        cache.clear()
        self.client.force_login(self.owner)
        self.url = reverse('hackathons:challenge-suggest', args=[self.event.slug])
        self.add_url = reverse('hackathons:challenge-add', args=[self.event.slug])

    def ask(self, **kwargs):
        return self.client.post(self.url, {'track': self.track.pk, 'idea': 'Rendre le campus accessible', **kwargs})

    @patch('hackathons.ai.genai.Client')
    def test_success_never_saves_any_business_object(self, client):
        generate = client.return_value.__enter__.return_value.models.generate_content
        generate.return_value.text = json.dumps(SUGGESTION)
        before = (Challenge.objects.count(), EventHistory.objects.count(), list(Hackathon.objects.values()))
        response = self.ask(audience='Débutants', duration='24 heures', status='PUBLISHED', approved_by=self.owner.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), SUGGESTION)
        self.assertEqual(before, (Challenge.objects.count(), EventHistory.objects.count(), list(Hackathon.objects.values())))

    @patch('hackathons.ai.suggest_challenge', return_value=SUGGESTION)
    def test_explicit_ordinary_save_creates_only_a_draft(self, suggest):
        self.ask()
        self.assertFalse(Challenge.objects.exists())
        response = self.client.post(self.add_url, {**SUGGESTION, 'track': self.track.pk,
            'title': 'Titre corrigé', 'idea': 'Idée', 'status': 'PUBLISHED', 'approved_by': self.owner.pk})
        self.assertEqual(response.status_code, 302)
        challenge = Challenge.objects.get()
        self.assertEqual(challenge.title, 'Titre corrigé')
        self.assertEqual(challenge.status, Challenge.Status.DRAFT)
        self.assertIsNone(challenge.approved_by_id)
        self.assertIsNone(challenge.approved_at)
        self.assertEqual(challenge.proposed_by, self.owner)
        self.assertEqual(suggest.call_count, 1)

    @patch('hackathons.ai.suggest_challenge')
    def test_anonymous_outsider_staff_and_sponsor_are_denied(self, suggest):
        self.client.logout()
        self.assertEqual(self.ask().status_code, 302)
        self.client.force_login(self.outsider)
        self.assertEqual(self.ask().status_code, 403)
        User.objects.filter(pk=self.outsider.pk).update(is_staff=True)
        self.assertEqual(self.ask().status_code, 403)
        RoleAssignment.objects.create(user=self.outsider, hackathon=self.event,
                                      role=Role.SPONSOR_REPRESENTATIVE, assigned_by=self.owner)
        self.assertEqual(self.ask().status_code, 403)
        self.client.force_login(self.other_owner)
        self.assertEqual(self.ask().status_code, 403)
        suggest.assert_not_called()

    @patch('hackathons.ai.suggest_challenge')
    def test_inactive_or_revoked_organizer_and_archive_are_denied(self, suggest):
        self.owner.is_active = False
        self.owner.save()
        self.assertIn(self.ask().status_code, (302, 403))
        self.owner.is_active = True
        self.owner.save()
        self.client.force_login(self.owner)
        assignment = RoleAssignment.objects.get(user=self.owner, hackathon=self.event)
        assignment.status = AssignmentStatus.REVOKED
        assignment.save()
        self.assertEqual(self.ask().status_code, 403)
        assignment.status = AssignmentStatus.ACTIVE
        assignment.save()
        Hackathon.objects.filter(pk=self.event.pk).update(status='ARCHIVED')
        self.assertEqual(self.ask().status_code, 403)
        suggest.assert_not_called()

    @patch('hackathons.ai.suggest_challenge', return_value=SUGGESTION)
    def test_active_superuser_can_ask(self, suggest):
        self.outsider.is_staff = self.outsider.is_superuser = True
        self.outsider.save()
        self.client.force_login(self.outsider)
        self.assertEqual(self.ask().status_code, 200)

    @patch('hackathons.ai.suggest_challenge')
    def test_track_scope_and_input_limits(self, suggest):
        inactive = Track.objects.create(hackathon=self.event, name='Fermé', active=False)
        for payload in ({'track': self.other_track.pk}, {'track': inactive.pk}, {'track': ''},
                        {'track': 'abc'}, {'track': 999999}, {'idea': ''}, {'idea': ' '},
                        {'idea': 'x' * 1001}, {'audience': 'x' * 151}, {'duration': 'x' * 101}):
            with self.subTest(payload=payload):
                self.assertEqual(self.ask(**payload).status_code, 400)
        suggest.assert_not_called()

    @patch('hackathons.ai.suggest_challenge')
    def test_post_and_csrf_are_required(self, suggest):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(self.url, {'track': self.track.pk, 'idea': 'Idée'}).status_code, 403)
        suggest.assert_not_called()

    @patch('hackathons.ai.suggest_challenge', return_value=SUGGESTION)
    def test_limit_is_per_user_across_events(self, suggest):
        for _ in range(SUGGESTIONS_PER_HOUR):
            self.assertEqual(self.ask().status_code, 200)
        response = self.ask()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Retry-After'], '3600')
        another = make_event(self.owner, 'm1-ai-second')
        track = Track.objects.create(hackathon=another, name='Deuxième')
        response = self.client.post(reverse('hackathons:challenge-suggest', args=[another.slug]),
                                    {'track': track.pk, 'idea': 'Autre idée'})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(suggest.call_count, SUGGESTIONS_PER_HOUR)
        self.client.force_login(self.other_owner)
        response = self.client.post(reverse('hackathons:challenge-suggest', args=[self.other.slug]),
                                    {'track': self.other_track.pk, 'idea': 'Autre idée'})
        self.assertEqual(response.status_code, 200)

    @patch('hackathons.ai.suggest_challenge', side_effect=ai.SuggestionUnavailable('Indisponible'))
    def test_failures_count_towards_the_limit_without_saving(self, suggest):
        for _ in range(SUGGESTIONS_PER_HOUR):
            self.assertEqual(self.ask().status_code, 503)
        self.assertEqual(self.ask().status_code, 429)
        self.assertFalse(Challenge.objects.exists())

    @patch('hackathons.ai.genai.Client')
    def test_bad_gemini_json_returns_safe_503(self, client):
        client.return_value.__enter__.return_value.models.generate_content.return_value.text = 'bad json'
        response = self.ask()
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, 'test-only-key', status_code=503)
        self.assertFalse(Challenge.objects.exists())

    @patch('hackathons.ai.suggest_challenge')
    @override_settings(GOOGLE_API_KEY='')
    def test_missing_key_keeps_manual_form_available(self, suggest):
        self.assertEqual(self.ask().status_code, 503)
        self.assertNotContains(self.client.get(self.add_url), 'id="challenge-ai"')
        self.assertContains(self.client.get(self.add_url), 'name="problem"')
        suggest.assert_not_called()

    def test_assistant_only_appears_on_organizer_challenge_creation(self):
        page = self.client.get(self.add_url)
        self.assertContains(page, "M'aider à rédiger avec l'IA")
        self.assertContains(page, 'challenge-suggest.js')
        self.assertContains(page, 'aria-live="polite"')
        self.assertNotContains(page, 'test-only-key')
        self.assertNotContains(self.client.get(reverse('hackathons:track-add', args=[self.event.slug])), 'challenge-suggest.js')
        challenge = Challenge.objects.create(track=self.track, proposed_by=self.owner, **SUGGESTION)
        self.assertNotContains(self.client.get(reverse('hackathons:challenge-edit', args=[self.event.slug, challenge.pk])), 'challenge-suggest.js')

    def test_manual_validation_preserves_ai_inputs_and_existing_values(self):
        page = self.client.post(self.add_url, {'track': self.track.pk, 'title': 'Mon titre',
            'idea': 'Mon idée', 'audience': 'Débutants', 'duration': '48 heures'})
        self.assertEqual(page.status_code, 200)
        for value in ('Mon titre', 'Mon idée', 'Débutants', '48 heures'):
            self.assertContains(page, value)
        self.assertFalse(page.context['suggestion_form'].is_bound)
        self.assertFalse(Challenge.objects.exists())

    def test_english_interface_and_generation_language(self):
        self.client.post(reverse('set_language'), {'language': 'en', 'next': '/'})
        self.addCleanup(translation.deactivate)
        page = self.client.get(self.add_url)
        self.assertContains(page, 'Help me draft with AI')
        with patch('hackathons.ai.suggest_challenge', return_value=SUGGESTION) as suggest:
            self.ask()
        self.assertEqual(suggest.call_args.kwargs['language'], 'en')
