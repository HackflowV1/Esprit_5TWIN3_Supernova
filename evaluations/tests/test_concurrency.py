from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections
from django.core.exceptions import ValidationError
from django.test import TransactionTestCase
from evaluations.models import Evaluation, CriterionScore, Award
from evaluations import services
from . import test_workflow


class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        test_workflow.WorkflowTests.setUpTestData.__func__(self)
        test_workflow.WorkflowTests.configure(self)

    def race(self, operation):
        barrier = Barrier(2)
        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                try:
                    return operation()
                except ValidationError:
                    return 'locked'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(lambda _: run(), range(2)))

    def test_double_finalization_is_serialized(self):
        assignment = test_workflow.WorkflowTests.assign(self)
        criteria = list(self.event.evaluation_criteria.all())
        results = self.race(lambda: services.save_evaluation(actor=self.juror, assignment=assignment, scores={criteria[0].pk: 18, criteria[1].pk: 8}, finalize=True).pk)
        self.assertEqual(results.count('locked'), 1)
        self.assertEqual(Evaluation.objects.filter(status='VALIDATED').count(), 1)
        self.assertEqual(CriterionScore.objects.count(), 2)

    def test_double_assignment_has_one_record(self):
        results = self.race(lambda: services.assign(actor=self.owner, event=self.event, submission=self.sub, juror=self.juror).pk)
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.sub.jury_assignments.count(), 1)
