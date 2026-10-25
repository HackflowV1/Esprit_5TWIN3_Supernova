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
