from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings, Client
from django.urls import reverse

from evaluations.models import CriterionScore, Evaluation, ResultPublication, Award, ReviewHistory
from evaluations import services
from .test_workflow import WorkflowTests


@override_settings(GOOGLE_API_KEY='test-only-key')
class DisagreementAITests(TestCase):
    setUpTestData = classmethod(WorkflowTests.setUpTestData.__func__)
    configure = WorkflowTests.configure
    assign = WorkflowTests.assign
    evaluate = WorkflowTests.evaluate

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        override = override_settings(M5_AI_RESULTS_DIR=temporary.name)
        override.enable()
        self.addCleanup(override.disable)
        self.configure()
        self.evaluate()
        self.evaluate(self.assign(self.other), low=True)
        self.client.force_login(self.owner)
        self.url = reverse('evaluations:analyze-divergence', args=[self.event.slug, self.sub.pk])

    @patch('evaluations.ai.genai.Client')
    def test_analysis_payload_page_and_no_database_writes(self, client):
        client.return_value.__enter__.return_value.models.generate_content.return_value = SimpleNamespace(
            text='Les écarts portent sur la technique. Recommandations : discuter des critères et des preuves.')
        models = (CriterionScore, Evaluation, ResultPublication, Award, ReviewHistory)
        before = [list(model.objects.values()) for model in models]
        ranking = services.ranking(self.event)
        page = self.client.get(reverse('evaluations:anomalies', args=[self.event.slug]))
        self.assertContains(page, 'Analyser avec l’IA')
        self.assertContains(page, self.url)
        self.assertContains(page, 'renderJuryAnalysis')
        self.assertNotContains(page, 'test-only-key')
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Recommandations', response.json()['analysis'])
        self.assertEqual(before, [list(model.objects.values()) for model in models])
        self.assertEqual(ranking, services.ranking(self.event))
        client.assert_called_once()
        self.assertEqual(client.call_args.kwargs['api_key'], 'test-only-key')
        call = client.return_value.__enter__.return_value.models.generate_content.call_args
        self.assertEqual(call.kwargs['model'], 'gemini-2.5-flash')
        self.assertIn('Innovation', call.kwargs['contents'])
        self.assertIn('poids_pourcent', call.kwargs['contents'])
        self.assertNotIn('PRIVATE_COMMENT', call.kwargs['contents'])
        self.assertNotIn(self.juror.username, call.kwargs['contents'])
        self.assertIn('français', call.kwargs['config'].system_instruction)

    @patch('evaluations.ai.genai.Client')
    def test_saved_analysis_is_reloaded_replaced_and_preserved_on_error(self, client):
        from pathlib import Path
        from django.conf import settings
        generate = client.return_value.__enter__.return_value.models.generate_content
        page_url = reverse('evaluations:anomalies', args=[self.event.slug])
        generate.return_value = SimpleNamespace(text='Première analyse enregistrée')
        self.assertEqual(self.client.post(self.url).status_code, 200)
        self.assertContains(self.client.get(page_url), 'Première analyse enregistrée')
        generate.assert_called_once()
        generate.return_value = SimpleNamespace(text='Nouvelle analyse enregistrée')
        self.assertEqual(self.client.post(self.url).status_code, 200)
        page = self.client.get(page_url)
        self.assertContains(page, 'Nouvelle analyse enregistrée')
        self.assertNotContains(page, 'Première analyse enregistrée')
        self.assertContains(page, 'Régénérer l’analyse')
        self.assertEqual(len(list(Path(settings.M5_AI_RESULTS_DIR).glob('*.json'))), 1)
        generate.side_effect = RuntimeError('provider unavailable')
        self.assertEqual(self.client.post(self.url).status_code, 503)
        self.assertContains(self.client.get(page_url), 'Nouvelle analyse enregistrée')
        self.client.force_login(self.juror)
        self.assertEqual(self.client.get(page_url).status_code, 403)

    @patch('evaluations.ai.genai.Client')
    def test_changed_scores_hide_old_analysis_and_write_failure_preserves_it(self, client):
        from evaluations.ai_storage import load_analysis
        generate = client.return_value.__enter__.return_value.models.generate_content
        generate.return_value = SimpleNamespace(text='Analyse initiale')
        self.assertEqual(self.client.post(self.url).status_code, 200)
        row = services.ranking(self.event)[0]
        self.assertEqual(load_analysis(self.event, {**row, 'review_key': 'changed'}), '')
        generate.return_value = SimpleNamespace(text='Analyse suivante')
        with patch('evaluations.ai_storage.os.replace', side_effect=OSError('disk full')):
            self.assertEqual(self.client.post(self.url).status_code, 503)
        self.assertEqual(load_analysis(self.event, row), 'Analyse initiale')

    @patch('evaluations.ai.genai.Client')
    def test_access_method_csrf_and_other_event(self, client):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(self.url).status_code, 403)
        for user in (self.juror, self.participant, self.stranger):
            self.client.force_login(user)
            self.assertEqual(self.client.post(self.url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.client.force_login(self.owner)
        from hackathons.test_helpers import make_event
        event = make_event(self.owner, slug='autre-edition', complete=True)
        url = reverse('evaluations:analyze-divergence', args=[event.slug, self.sub.pk])
        self.assertEqual(self.client.post(url).status_code, 404)
        client.assert_not_called()

    @patch('evaluations.ai.genai.Client')
    def test_non_divergent_is_rejected(self, client):
        Evaluation.objects.filter(assignment__juror=self.other).update(status='DRAFT')
        self.assertEqual(self.client.post(self.url).status_code, 400)
        client.assert_not_called()

    @patch('evaluations.ai.genai.Client')
    def test_missing_key_empty_response_and_provider_failure(self, client):
        with override_settings(GOOGLE_API_KEY=''):
            self.assertEqual(self.client.post(self.url).status_code, 503)
        client.assert_not_called()
        generate = client.return_value.__enter__.return_value.models.generate_content
        generate.return_value = SimpleNamespace(text=None)
        self.assertEqual(self.client.post(self.url).status_code, 503)
        generate.side_effect = RuntimeError('secret provider details test-only-key')
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('test-only-key', response.content.decode())
