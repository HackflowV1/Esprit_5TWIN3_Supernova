from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.core.exceptions import ValidationError
from accounts.models import User, Role
from accounts.services import set_role
from projects.tests import ProjectSetup
from evaluations import services
from evaluations.models import Evaluation, CriterionScore, Prize


class M3IntegrationTests(ProjectSetup, TestCase):
    def test_real_m1_m2_m3_services_then_m5_and_private_download(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from projects import services as m3
        project = self.project()
        version = self.version(project)
        self.repo(version)
        deliverable = m3.save_deliverable(actor=self.a, submission=version, kind='SLIDES', file=SimpleUploadedFile('slides.pdf', b'%PDF-1.7\nexample'))
        m3.submit(actor=self.a, submission=version, confirm_requirements=True)
        version.refresh_from_db()
        juror = User.objects.create_user('m5juror')
        set_role(actor=self.owner, user=juror, hackathon=self.event, role=Role.JURY)
        services.configure_rubric(actor=self.owner, event=self.event, rows=[{'name': 'Impact', 'weight': Decimal(100), 'max_score': Decimal(20), 'display_order': 0}], threshold=25, minimum_jurors=1, validate=True)
        assignment = services.assign(actor=self.owner, event=self.event, submission=version, juror=juror)
        self.client.force_login(juror)
        response = self.client.get(reverse('evaluations:evaluate', args=[assignment.pk]))
        self.assertContains(response, 'Campus Care')
        self.assertContains(response, 'Shared support')
        self.assertContains(response, 'Télécharger le fichier')
        url = reverse('evaluations:download', args=[assignment.pk, deliverable.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.7\nexample')
        criterion = self.event.evaluation_criteria.get()
        response = self.client.post(reverse('evaluations:evaluate', args=[assignment.pk]), {'action': 'finalize', f'score_{criterion.pk}': '17.25', 'comment': 'Confidentiel'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Evaluation.objects.get(assignment=assignment).total, Decimal('86.2500'))
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(url).status_code, 403)
        with patch('evaluations.services.timezone.now', return_value=self.event.submission_deadline+timedelta(minutes=1)):
            publication = services.validate_ranking(actor=self.owner, event=self.event)
            services.publish(actor=self.owner, publication=publication)
        self.assertContains(self.client.get(reverse('evaluations:results', args=[self.event.slug])), '86.25')


class HttpFormTests(TestCase):
    def setUp(self):
        from .test_workflow import WorkflowTests
        WorkflowTests.setUpTestData.__func__(self)
        self.client.force_login(self.owner)

    def test_rubric_assignment_evaluation_publication_and_prize_forms(self):
        rubric = {'form-TOTAL_FORMS': 1, 'form-INITIAL_FORMS': 0, 'form-0-name': 'Impact', 'form-0-weight': '100', 'form-0-max_score': '20', 'form-0-display_order': 0, 'divergence_threshold': '25', 'minimum_jurors': 1, 'action': 'validate'}
        response = self.client.post(reverse('evaluations:rubric', args=[self.event.slug]), rubric)
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse('evaluations:assignments', args=[self.event.slug]), {'submission': self.sub.pk, 'juror': self.juror.pk})
        self.assertEqual(response.status_code, 302)
        a = self.sub.jury_assignments.get()
        c = self.event.evaluation_criteria.get()
        self.client.force_login(self.juror)
        response = self.client.post(reverse('evaluations:evaluate', args=[a.pk]), {'action': 'finalize', f'score_{c.pk}': '21'})
        self.assertContains(response, '20')
        self.assertFalse(Evaluation.objects.exists())
        response = self.client.post(reverse('evaluations:evaluate', args=[a.pk]), {'action': 'finalize', f'score_{c.pk}': '15'})
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.owner)
        with patch('evaluations.services.timezone.now', return_value=self.event.submission_deadline+timedelta(minutes=1)):
            self.assertEqual(self.client.post(reverse('evaluations:ranking', args=[self.event.slug])).status_code, 302)
            p = self.event.result_publications.get()
            self.assertEqual(self.client.post(reverse('evaluations:publish', args=[self.event.slug, p.pk])).status_code, 302)
        self.assertEqual(self.client.post(reverse('evaluations:prizes', args=[self.event.slug]), {'action': 'prize', 'name': 'Innovation', 'description': 'Bravo', 'sponsorship': ''}).status_code, 302)
        prize = Prize.objects.get()
        self.assertEqual(self.client.post(reverse('evaluations:prizes', args=[self.event.slug]), {'action': 'award', 'prize': prize.pk, 'submission': self.sub.pk}).status_code, 302)
        self.assertContains(self.client.get(reverse('evaluations:results', args=[self.event.slug])), 'Innovation')

    def test_csrf_and_wrong_method_publication_protected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(reverse('evaluations:ranking', args=[self.event.slug])).status_code, 403)
        self.assertEqual(client.get(reverse('evaluations:publish', args=[self.event.slug, 999])).status_code, 405)
