from decimal import Decimal
from types import SimpleNamespace
from django.core.exceptions import ValidationError
from django.template.loader import get_template
from django.test import SimpleTestCase
from evaluations.scoring import weighted_total, mean_score
from evaluations.forms import EvaluationForm, CriterionFormSet


class ScoringTests(SimpleTestCase):
    def setUp(self):
        self.criteria = [SimpleNamespace(pk=1, name='Innovation', weight=Decimal(30), max_score=Decimal(20)), SimpleNamespace(pk=2, name='Technique', weight=Decimal(70), max_score=Decimal(10))]

    def test_normalizes_different_maxima(self):
        self.assertEqual(weighted_total(self.criteria, {1: Decimal(18), 2: Decimal(8)}), Decimal('83.0000'))

    def test_mean_rounds_half_up(self):
        self.assertEqual(mean_score([Decimal('80.0050'), Decimal('80.0050')]), Decimal('80.01'))
        self.assertIsNone(mean_score([]))

    def test_missing_negative_excess_and_nonfinite_scores(self):
        for scores in [{1: Decimal(10)}, {1: -1, 2: 5}, {1: 21, 2: 5}, {1: Decimal('NaN'), 2: 5}, {1: Decimal('Infinity'), 2: 5}, {1: 10, 2: 5, 3: 3}]:
            with self.subTest(scores=scores), self.assertRaises(ValidationError):
                weighted_total(self.criteria, scores)

    def test_invalid_weight_total(self):
        self.criteria[0].weight = Decimal(20)
        with self.assertRaises(ValidationError):
            weighted_total(self.criteria, {1: 10, 2: 5})

    def test_draft_optional_final_complete(self):
        self.assertTrue(EvaluationForm({'action': 'draft', 'score_1': 10}, criteria=self.criteria).is_valid())
        self.assertFalse(EvaluationForm({'action': 'finalize', 'score_1': 10}, criteria=self.criteria).is_valid())
        self.assertFalse(EvaluationForm({'score_1': 21}, criteria=self.criteria).is_valid())

    def test_all_templates_compile(self):
        for name in ['shell', 'hub', 'dashboard', 'table', 'rubric', 'assignments', 'evaluate', 'ranking', 'anomalies', 'review', 'prizes', 'results']:
            get_template('evaluations/' + name + '.html')

    def test_invalid_score_has_one_inline_error_for_both_actions(self):
        for action in ['draft', 'finalize']:
            for value in ['21', '-1', 'abc', '1.234']:
                with self.subTest(action=action, value=value):
                    form = EvaluationForm({'action': action, 'score_1': value, 'score_2': '8'}, criteria=self.criteria)
                    self.assertFalse(form.is_valid())
                    self.assertEqual(len(form.errors['score_1']), 1)
                    self.assertEqual(form['score_1'].value(), value)

    def test_score_boundaries_are_accepted(self):
        form = EvaluationForm({'action': 'finalize', 'score_1': '0', 'score_2': '10'}, criteria=self.criteria)
        self.assertTrue(form.is_valid(), form.errors)

    def test_evaluation_form_disables_browser_validation(self):
        template = get_template('evaluations/evaluate.html')
        self.assertIn('class="m5-form" novalidate', template.template.source)

    def test_all_m5_forms_disable_native_validation(self):
        from html.parser import HTMLParser
        from pathlib import Path
        from django.conf import settings

        class FormParser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag == 'form':
                    self_forms.append(dict(attrs))

        for path in (settings.BASE_DIR / 'templates' / 'evaluations').glob('*.html'):
            self_forms = []
            FormParser().feed(path.read_text(encoding='utf-8'))
            for attrs in self_forms:
                with self.subTest(template=path.name):
                    self.assertIn('novalidate', attrs)

    def test_other_forms_reject_invalid_input_on_server(self):
        from evaluations.forms import CriterionForm, CampaignForm, ReasonForm
        for data in [
            {'name': '', 'weight': '10', 'max_score': '5', 'display_order': '0'},
            {'name': 'Impact', 'weight': '101', 'max_score': '5', 'display_order': '0'},
            {'name': 'Impact', 'weight': '10', 'max_score': '0', 'display_order': '-1'},
        ]:
            with self.subTest(data=data):
                self.assertFalse(CriterionForm(data).is_valid())
        form = CampaignForm({'divergence_threshold': '101', 'minimum_jurors': '0'})
        self.assertFalse(form.is_valid())
        self.assertIn('divergence_threshold', form.errors)
        self.assertIn('minimum_jurors', form.errors)
        for reason in ['', '   ', 'x' * 2001]:
            self.assertFalse(ReasonForm({'reason': reason}).is_valid())
