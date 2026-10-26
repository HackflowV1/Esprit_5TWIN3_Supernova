from io import StringIO
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
import json
import os

from django.core.management import call_command
from django.core.exceptions import PermissionDenied,ValidationError
from django.test import SimpleTestCase,TestCase,Client,override_settings
from django.conf import settings
from django.urls import reverse
from accounts.models import Skill
from .tests import SetupMixin
from . import services,skill_suggestions


def example_artifact():
    return {'schema':1,'embedding_model':settings.M2_MODEL_NAME,
        'dimension':384,'labels':['Django'],'coefficients':[[2.]+[0.]*383],
        'intercepts':[0.],'thresholds':[.7],'max_suggestions':5}


class PredictorTests(SimpleTestCase):
    def test_json_classifier_uses_trained_weights_without_sklearn(self):
        data=example_artifact()
        self.assertEqual(skill_suggestions.classify(data,[1.]+[0.]*383)[0]['label'],'Django')
        self.assertEqual(skill_suggestions.classify(data,[-1.]+[0.]*383),[])

    def test_mentions_are_separate_from_ml_and_handle_common_negation(self):
        data=skill_suggestions.combine('Une API REST Django, sans React.',[{'label':'UI/UX','score':.8},{'label':'React','score':.99}])
        self.assertEqual({r['label'] for r in data},{'API REST','Django','UI/UX'})
        self.assertEqual(next(r['source'] for r in data if r['label']=='Django'),'explicit')
        self.assertEqual(next(r['source'] for r in data if r['label']=='UI/UX'),'ml')
        self.assertNotIn('API REST',skill_suggestions.mentions('We need the rest of the team tomorrow.')[0])
        self.assertNotIn('Django',skill_suggestions.mentions('Do not use Django, but use React.')[0])
        self.assertIn('React',skill_suggestions.mentions('Do not use Django, but use React.')[0])

    def test_missing_or_invalid_artifact_abstains(self):
        with TemporaryDirectory() as directory,override_settings(M2_SKILL_MODEL_PATH=Path(directory)/'classifier.json'):
            self.assertEqual(skill_suggestions.suggest('Nous avons une idée technique pour notre équipe.')['state'],'untrained')
            (Path(directory)/'classifier.json').write_text('{}')
            self.assertIsNone(skill_suggestions.artifact())

    def test_artifact_validation_and_async_reuse(self):
        with TemporaryDirectory() as directory,override_settings(M2_SKILL_MODEL_PATH=Path(directory)/'classifier.json'):
            path=Path(directory)/'classifier.json'
            path.write_text(json.dumps(example_artifact()))
            with patch('teams.skill_suggestions.matching.vectors',return_value=(None,'warming')) as vectors:
                self.assertEqual(skill_suggestions.suggest('Construire des vues avec Django et des modèles.')['state'],'warming')
                vectors.assert_called_once()
            previous=path.stat()
            wrong=example_artifact(); wrong['coefficients']=[[float('nan')]*384]
            path.write_text(json.dumps(wrong))
            # Cache invalidation uses mtime; rapid Windows writes can share a timestamp.
            os.utime(path,ns=(previous.st_atime_ns,previous.st_mtime_ns+1_000_000_000))
            self.assertIsNone(skill_suggestions.artifact())


@override_settings(M2_MATCHING_ENABLED=False)
class SuggestionFlowTests(SetupMixin,TestCase):
    def test_add_page_contains_manual_and_idea_paths(self):
        url = reverse('teams:need-add', args=[self.event.slug, self.target.pk])
        response = self.client.get(url)
        self.assertTemplateUsed(response, 'teams/need_add.html')
        self.assertContains(response, '?mode=idea')
        response = self.client.get(url + '?mode=idea')
        self.assertTemplateUsed(response, 'teams/need_suggestions.html')
        self.assertContains(response, 'm2-description-form')
        with patch('teams.skill_suggestions.suggest', return_value={'state':'ready','suggestions':[{'label':'Django','source':'ml'},{'label':'React','source':'explicit'}]}):
            response = self.client.post(url + '?mode=idea', {'action':'analyze','text':'Build a reliable web application for volunteers.'})
        self.assertContains(response, 'needs-0-skill')
        self.assertEqual(self.target.skill_needs.count(), 0)
        self.assertRedirects(self.client.post(url + '?mode=idea', self.payload()), self.target.get_absolute_url())
        self.assertEqual(self.target.skill_needs.count(), 1)

    def setUp(self):
        super().setUp()
        self.target=self.team()
        self.django=Skill.objects.create(name='Django',category='Backend')
        self.react=Skill.objects.create(name='React',category='Frontend')
        self.url=reverse('teams:need-suggestions',args=[self.event.slug,self.target.pk])
        self.client.force_login(self.a)

    def analyze(self):
        with patch('teams.skill_suggestions.suggest',return_value={'state':'ready','suggestions':[{'label':'Django','source':'ml'},{'label':'React','source':'explicit'}]}):
            return self.client.post(self.url,{'action':'analyze','text':'Nous construirons une API Django avec une interface React.'})

    def payload(self):
        return {'action':'save','needs-TOTAL_FORMS':'2','needs-INITIAL_FORMS':'2','needs-MIN_NUM_FORMS':'0','needs-MAX_NUM_FORMS':'13',
            'needs-0-selected':'on','needs-0-skill':str(self.django.pk),'needs-0-level':'3','needs-0-priority':'2',
            'needs-1-skill':str(self.react.pk),'needs-1-level':'','needs-1-priority':''}

    def test_preview_never_saves_and_selection_requires_levels(self):
        response=self.analyze()
        self.assertContains(response,'Suggestion du modèle ML')
        self.assertContains(response,'Mentionné dans votre texte')
        self.assertEqual(self.target.skill_needs.count(),0)
        payload=self.payload(); payload['needs-0-level']=''
        self.assertEqual(self.client.post(self.url,payload).status_code,200)
        self.assertEqual(self.target.skill_needs.count(),0)
        self.assertRedirects(self.client.post(self.url,self.payload()),self.target.get_absolute_url())
        self.assertEqual(list(self.target.skill_needs.values_list('skill__name','level','priority')),[('Django',3,2)])

    def test_cannot_tamper_with_suggested_labels_or_reuse_other_team_session(self):
        self.analyze()
        other=Skill.objects.create(name='Unknown',category='Other')
        payload=self.payload(); payload['needs-0-skill']=str(other.pk)
        self.assertEqual(self.client.post(self.url,payload).status_code,200)
        self.assertEqual(self.target.skill_needs.count(),0)
        self.client.session.flush()
        self.client.force_login(self.a)
        self.assertRedirects(self.client.post(self.url,self.payload()),self.url)
        self.assertEqual(self.target.skill_needs.count(),0)

    def test_existing_needs_and_closed_phase_are_preserved(self):
        self.analyze()
        services.save_need(actor=self.a,team=self.target,skill=self.django,level=5,priority=3)
        self.client.post(self.url,self.payload())
        need=self.target.skill_needs.get(skill=self.django)
        self.assertEqual((need.level,need.priority),(5,3))
        self.analyze()
        from django.utils import timezone
        from datetime import timedelta
        self.event.phases.filter(kind='TEAM_FORMATION').update(end=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(ValidationError):
            services.save_suggested_needs(actor=self.a,team=self.target,proposals=[{'skill':self.react,'level':3,'priority':2}])
        self.assertEqual(self.target.skill_needs.count(),1)

    def test_permissions_csrf_and_empty_model_results(self):
        self.reg(self.b)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(self.url).status_code,403)
        self.client.force_login(self.a)
        csrf=Client(enforce_csrf_checks=True); csrf.force_login(self.a)
        self.assertEqual(csrf.post(self.url,{'action':'analyze','text':'A sufficiently long description here.'}).status_code,403)
        with patch('teams.skill_suggestions.suggest',return_value={'state':'ready','suggestions':[]}):
            self.assertContains(self.client.post(self.url,{'action':'analyze','text':'Une idée générale sans outil technique choisi.'}),'Aucun nouveau besoin à proposer')
