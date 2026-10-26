from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from accounts.models import User, Skill, Profile, UserSkill
from hackathons.test_helpers import make_event
from .tests import SetupMixin
from .models import Registration, JoinRequest, Team
from . import services, matching, evaluation


@override_settings(M2_MATCHING_ENABLED=False)
class TeamDiscoveryTests(SetupMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.target = self.team()
        self.a.first_name = 'PRIVATE_MEMBER_NAME'
        self.a.email = 'private@example.test'
        self.a.save()
        Profile.objects.update_or_create(user=self.a, defaults={'biography':'PRIVATE_BIO'})
        self.skill = Skill.objects.create(name='Django', category='Backend')
        services.save_need(actor=self.a, team=self.target, skill=self.skill, level=3, priority=3)

    def test_anonymous_browse_is_read_only_and_does_not_reveal_members(self):
        count = Registration.objects.count()
        response = self.client.get(reverse('teams:list',args=[self.event.slug]))
        self.assertContains(response, 'Nova')
        response = self.client.get(self.target.get_absolute_url())
        self.assertContains(response, 'Django')
        self.assertTemplateUsed(response, 'teams/preview.html')
        for private in ('PRIVATE_MEMBER_NAME','private@example.test','PRIVATE_BIO'):
            self.assertNotContains(response,private)
        self.assertEqual(Registration.objects.count(),count)
        self.assertEqual(self.client.get(reverse('teams:candidates',args=[self.event.slug,self.target.pk])).status_code,302)

    def test_resume_registration_then_explicit_application(self):
        self.client.force_login(self.b)
        apply_url = reverse('teams:apply',args=[self.event.slug,self.target.pk])
        register_url = reverse('teams:register',args=[self.event.slug])+f'?team={self.target.pk}'
        self.assertRedirects(self.client.get(apply_url),register_url)
        self.assertFalse(Registration.objects.filter(user=self.b).exists())
        self.assertEqual(self.client.post(register_url,{}).status_code,200)
        self.assertFalse(Registration.objects.filter(user=self.b).exists())
        response = self.client.post(register_url,{'accept_conditions':'on'})
        self.assertRedirects(response,apply_url)
        self.assertFalse(JoinRequest.objects.filter(registration__user=self.b).exists())
        response = self.client.post(apply_url,{'message':'Je souhaite contribuer au backend.'})
        self.assertRedirects(response,reverse('teams:inbox',args=[self.event.slug]))
        self.assertEqual(JoinRequest.objects.get(registration__user=self.b).team,self.target)
        # A duplicate application leads back to the inbox, rather than a confusing form.
        self.assertRedirects(self.client.get(apply_url),reverse('teams:inbox',args=[self.event.slug]))

    def test_return_team_is_scoped_and_closed_target_does_not_register(self):
        self.client.force_login(self.b)
        other = make_event(self.owner,slug='other')
        wrong = reverse('teams:register',args=[other.slug])+f'?team={self.target.pk}'
        self.assertEqual(self.client.get(wrong).status_code,404)
        services.update_team(actor=self.a,team=self.target,name='Nova',description='',recruiting=False)
        url = reverse('teams:register',args=[self.event.slug])+f'?team={self.target.pk}'
        self.assertRedirects(self.client.post(url,{'accept_conditions':'on'}),self.target.get_absolute_url())
        self.assertFalse(Registration.objects.filter(user=self.b).exists())

    def test_signup_preserves_team_return_and_rejects_external_redirect(self):
        target = reverse('teams:apply',args=[self.event.slug,self.target.pk])
        response = self.client.get(reverse('accounts:login')+'?next='+target)
        self.assertContains(response,'signup/?next=')
        payload = dict(username='freshparticipant',first_name='New',last_name='Participant',email='new@example.test',
            password1='Specific-test#48',password2='Specific-test#48',next=target)
        response = self.client.post(reverse('accounts:signup'),payload)
        self.assertRedirects(response,target,fetch_redirect_response=False)
        self.assertFalse(Registration.objects.filter(user__username='freshparticipant').exists())
        self.client.logout()
        payload.update(username='otherparticipant',email='other@example.test',next='https://evil.example/steal')
        self.assertRedirects(self.client.post(reverse('accounts:signup'),payload),reverse('accounts:profile'))

    def test_private_candidate_directory_authorization_and_eligibility(self):
        self.reg(self.b)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse('teams:candidates',args=[self.event.slug,self.target.pk])).status_code,403)
        other_team = services.create_team(actor=self.b,event=self.event,name='Other team')
        self.reg(self.c)
        self.assertEqual([r['registration'].user for r in services.recommendations(actor=self.a,team=self.target)], [self.c])
        self.c.is_active = False
        self.c.save()
        self.assertEqual(services.recommendations(actor=self.a,team=self.target),[])


class RankingTests(SimpleTestCase):
    def test_skills_comparison_uses_same_formula_and_never_requests_embeddings(self):
        team,needs,regs = evaluation.inputs(evaluation.CASES[0])
        with patch('teams.matching.vectors') as vectors:
            baseline = matching.rank(team=team,needs=needs,candidates=regs,mode='skills')
            vectors.assert_not_called()
        with patch('teams.matching.vectors',return_value=(None,'unavailable')):
            fallback = matching.rank(team=team,needs=needs,candidates=regs)
        self.assertEqual([r['registration'].pk for r in baseline],[r['registration'].pk for r in fallback])

    def test_missing_project_context_does_not_claim_semantic_ranking(self):
        team,needs,regs = evaluation.inputs(evaluation.CASES[0])
        team.description = '   '
        with patch('teams.matching.vectors') as vectors:
            results = matching.rank(team=team,needs=needs,candidates=regs)
            vectors.assert_not_called()
        self.assertTrue(all(r['matching_state']=='no_context' for r in results))

    def test_biography_is_not_truncated_away_by_long_skill_experiences(self):
        team,needs,regs = evaluation.inputs(evaluation.CASES[0])
        user = regs[0].user
        user.profile.biography = 'Unique project context first.'
        for skill in user.user_skills.all():
            skill.experience = 'Extensive unrelated experience. ' * 80
        self.assertTrue(matching.profile_text(user).startswith('Unique project context first.'))

    def test_semantic_context_can_reorder_equal_skills_but_cannot_invent_skills(self):
        team, needs, regs = evaluation.inputs(evaluation.CASES[0])
        # Deterministic vectors test ranking math, not model quality.
        with patch('teams.matching.vectors',return_value=([[1,0]]+[[0,1],[1,0],[0,1],[0,1],[0,1],[0,1],[0,1],[1,0]],'ready')):
            results = matching.rank(team=team,needs=needs,candidates=regs)
        self.assertEqual(results[0]['registration'].pk,'eval-b')
        novice = next(r for r in results if r['registration'].pk == 'eval-h')
        self.assertEqual(novice['matches'],[])
        self.assertFalse(novice['context_signal'])
        self.assertEqual(results[-1]['registration'].pk,'eval-h')

    def test_essential_declared_skill_dominates_secondary_skill_and_similarity(self):
        team,needs,regs = evaluation.inputs(evaluation.CASES[0])
        with patch('teams.matching.vectors',return_value=([[1,0]]+[[0,1],[0,1],[1,0],[1,0],[0,1],[0,1],[0,1],[1,0]],'ready')):
            results = matching.rank(team=team,needs=needs,candidates=regs)
        self.assertEqual({r['registration'].pk for r in results[:2]},{'eval-a','eval-b'})

    def test_no_needs_does_not_call_model_and_fallback_is_usable(self):
        team,needs,regs = evaluation.inputs(evaluation.CASES[0])
        with patch('teams.matching.vectors') as vector:
            results = matching.rank(team=team,needs=[],candidates=regs)
            vector.assert_not_called()
        self.assertTrue(all(r['score']==0 and r['matching_state']=='no_needs' for r in results))
        with patch('teams.matching.vectors',return_value=(None,'unavailable')):
            results = matching.rank(team=team,needs=needs,candidates=regs)
        self.assertEqual(results[0]['registration'].pk,'eval-a')
        self.assertFalse(any(r['context_signal'] for r in results))

    @override_settings(M2_MATCHING_ENABLED=True)
    def test_unprepared_model_never_loads_or_downloads_in_request(self):
        with TemporaryDirectory() as directory, override_settings(M2_MODEL_CACHE=Path(directory)):
            with patch('teams.matching._model') as model:
                self.assertEqual(matching.vectors(['test']),(None,'unavailable'))
                model.assert_not_called()

    def test_content_and_model_version_invalidate_embedding_cache(self):
        old = matching.cache_key('original biography')
        self.assertNotEqual(old,matching.cache_key('changed biography'))
        with override_settings(M2_MODEL_NAME='new-model'):
            self.assertNotEqual(old,matching.cache_key('original biography'))

    @override_settings(M2_MATCHING_ENABLED=True)
    def test_http_misses_schedule_one_bounded_job_without_loading_model(self):
        from unittest.mock import MagicMock
        cache = MagicMock()
        cache.get.return_value = None
        with TemporaryDirectory() as directory, override_settings(M2_MODEL_CACHE=Path(directory)):
            (Path(directory)/'READY').write_text('prepared')
            with patch('teams.matching.caches',{'m2_embeddings':cache}), patch('teams.matching._busy',False), \
                    patch('teams.matching._executor.submit') as submit, patch('teams.matching._model') as model:
                texts = [f'profile {i}' for i in range(200)]
                self.assertEqual(matching.vectors(texts),(None,'warming'))
                self.assertEqual(len(submit.call_args.args[1]),128)
                matching.vectors(texts)
                submit.assert_called_once()
                model.assert_not_called()

    @override_settings(M2_MATCHING_ENABLED=True)
    def test_cached_embeddings_need_no_worker_and_failed_inference_falls_back(self):
        from unittest.mock import MagicMock
        cache = MagicMock()
        cache.get.return_value = [1.0,0.0]
        with TemporaryDirectory() as directory, override_settings(M2_MODEL_CACHE=Path(directory)):
            (Path(directory)/'READY').write_text('prepared')
            with patch('teams.matching.caches',{'m2_embeddings':cache}), patch('teams.matching._executor.submit') as submit:
                self.assertEqual(matching.vectors(['hello']),([[1.0,0.0]],'ready'))
                submit.assert_not_called()
            cache.get.return_value = None
            with patch('teams.matching.caches',{'m2_embeddings':cache}), patch('teams.matching._compute',side_effect=RuntimeError):
                self.assertEqual(matching.vectors(['hello'],background=False),(None,'unavailable'))

    def test_metrics_and_blank_review_rejected(self):
        result = evaluation.metrics(['a','b','c'],{'a':2,'b':1,'c':0,'d':2})
        self.assertAlmostEqual(result['precision_at_3'],2/3)
        self.assertLess(result['ndcg_at_3'],1)
        with TemporaryDirectory() as directory:
            path = Path(directory)/'review.csv'
            evaluation.export_sheet(path)
            with self.assertRaises(ValueError):
                evaluation.read_labels(path)
            with self.assertRaises(FileExistsError):
                evaluation.export_sheet(path)


@override_settings(DEBUG=True,M2_MATCHING_ENABLED=False)
class MatchingSeedTests(TestCase):
    def test_seed_repeats_without_resetting_password_bio_or_cancellation(self):
        call_command('seed_m2_matching_demo',stdout=StringIO())
        event = Team.objects.get(name='Passerelle').hackathon
        self.assertEqual(event.registrations.count(),28)
        self.assertEqual(event.teams.count(),6)
        captain = User.objects.get(username='m2.demo.01')
        self.assertEqual(len(services.recommendations(actor=captain,team=Team.objects.get(name='Passerelle'))),16)
        user = User.objects.get(username='m2.demo.13')
        user.set_password('My-changed-password#81')
        user.save()
        Profile.objects.filter(user=user).update(biography='My edited biography')
        services.cancel_registration(actor=user,registration=Registration.objects.get(user=user,hackathon=event))
        call_command('seed_m2_matching_demo',stdout=StringIO())
        user.refresh_from_db()
        self.assertTrue(user.check_password('My-changed-password#81'))
        self.assertEqual(user.profile.biography,'My edited biography')
        self.assertEqual(Registration.objects.get(user=user,hackathon=event).status,'CANCELLED')
        self.assertEqual(event.teams.count(),6)


@override_settings(M2_MATCHING_ENABLED=True)
class ComparisonScreenTests(SetupMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.target = self.team()
        self.reg(self.b)
        self.reg(self.c)
        skill = Skill.objects.create(name='Data Science',category='Data')
        services.save_need(actor=self.a,team=self.target,skill=skill,level=3,priority=3)
        for user in (self.b,self.c):
            UserSkill.objects.create(user=user,skill=skill,level=3)
        Profile.objects.update_or_create(user=self.b,defaults={'biography':'Sports analytics.'})
        Profile.objects.update_or_create(user=self.c,defaults={'biography':'Community meal redistribution.'})
        self.client.force_login(self.a)
        self.url = reverse('teams:candidates',args=[self.event.slug,self.target.pk])

    def embeddings(self,texts,**kwargs):
        return [[1.,0.]] + [[1.,0.] if text.startswith('Community') else [0.,1.] for text in texts[1:]], 'ready'

    def test_comparison_changes_only_context_and_displays_measured_movement(self):
        with patch('teams.matching.vectors',side_effect=self.embeddings):
            response = self.client.get(self.url)
        rows = list(response.context['page_obj'])
        self.assertEqual([r['registration'].user for r in rows],[self.c,self.b])
        self.assertEqual((rows[0]['position'],rows[0]['skills_position'],rows[0]['rank_gain']),(1,2,1))
        self.assertContains(response,'1 place gagnée avec le contexte')
        self.assertNotContains(response,'Compétences en commun avec vos besoins')
        with patch('teams.matching.vectors') as vectors:
            response = self.client.get(self.url,{'ranking':'skills'})
            vectors.assert_not_called()
        self.assertEqual([r['registration'].user for r in response.context['page_obj']],[self.b,self.c])
        self.assertNotContains(response,'place gagnée avec le contexte')
        self.client.cookies['hackflow_language'] = 'en'
        self.assertContains(self.client.get(self.url,{'ranking':'skills'}),'Skills only')

    def test_filter_uses_same_population_for_both_positions(self):
        with patch('teams.matching.vectors',side_effect=self.embeddings):
            response = self.client.get(self.url,{'q':'carol','ranking':'hybrid'})
        row = list(response.context['page_obj'])[0]
        self.assertEqual((row['position'],row['skills_position'],row['rank_gain']),(1,1,0))
        self.assertContains(response,'name="ranking" value="hybrid"')


@override_settings(DEBUG=True,M2_MATCHING_ENABLED=False)
class SamiShowcaseSeedTests(TestCase):
    def test_sami_showcase_preserves_users_and_only_configures_team_explicitly(self):
        call_command('seed_demo',stdout=StringIO())
        sami = User.objects.get(username='sami')
        horizon = Team.objects.get(name='Horizon',hackathon__slug='ai-challenge-2026')
        original_members = list(horizon.memberships.values_list('registration_id','ended_at'))
        call_command('seed_m2_sami_showcase',configure_team=True,stdout=StringIO())
        need = horizon.skill_needs.get(skill__name='Data Science')
        self.assertEqual((need.level,need.priority),(4,3))
        self.assertEqual(list(horizon.memberships.values_list('registration_id','ended_at')),original_members)
        self.assertTrue(sami.check_password('Demo-Hack#2026'))
        four = list(User.objects.filter(username__in=['horizon.amine','horizon.lina','horizon.omar','horizon.yasmine']))
        self.assertEqual(len(four),4)
        declarations = [list(u.user_skills.order_by('skill__name').values_list('skill__name','level')) for u in four]
        self.assertTrue(all(row==declarations[0] for row in declarations))
        lina = User.objects.get(username='horizon.lina')
        Profile.objects.filter(user=lina).update(biography='User edited biography')
        services.cancel_registration(actor=lina,registration=Registration.objects.get(user=lina,hackathon=horizon.hackathon))
        services.update_team(actor=sami,team=horizon,name=horizon.name,description='My edited project',recruiting=True)
        call_command('seed_m2_sami_showcase',stdout=StringIO())
        horizon.refresh_from_db()
        self.assertEqual(horizon.description,'My edited project')
        self.assertEqual(lina.profile.biography,'User edited biography')
        self.assertEqual(Registration.objects.get(user=lina,hackathon=horizon.hackathon).status,'CANCELLED')
