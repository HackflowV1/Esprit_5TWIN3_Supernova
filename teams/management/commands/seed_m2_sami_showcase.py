"""A reproducible semantic-ranking demonstration in the normal AI Challenge flow.

Fictional profiles only. No candidate IDs, usernames, or expected ordering enter
the ranking code. Equal declarations isolate the model's contextual contribution.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from accounts.models import User, Profile, Skill, UserSkill
from teams import services
from teams.models import Registration, Team, TeamSkillNeed
from hackathons.models import Hackathon, EventPhase
from hackathons.services import phase_is_open

PASSWORD = 'Demo-Horizon#2026'
DESCRIPTION = ('Moins de gaspillage, plus de solidarité. Nous construisons un outil pour relier les commerces '
    'aux associations : anticiper les surplus de produits frais et organiser les collectes de repas. '
    'Nous cherchons une personne capable de prévoir les quantités à redistribuer et de rendre les données utiles aux bénévoles.')
DECLARATIONS = {'Data Science':4, 'Python':4, 'Machine Learning':3, 'Figma':2, 'Mobile':3}
SKILL_DESCRIPTIONS = {
    'Data Science':'Préparer, explorer et analyser des données pour répondre à une question métier.',
    'Python':'Développer des scripts et services, manipuler des données et automatiser des traitements.',
    'Machine Learning':'Construire et évaluer des modèles prédictifs sur des données adaptées.',
    'Figma':'Créer des maquettes et prototypes d’interfaces puis partager les parcours avec l’équipe.',
    'Mobile':'Construire des interfaces et fonctionnalités utilisables sur téléphone.',
}
PEOPLE = [
    ('horizon.amine', 'Amine', 'Ben Salah',
     'Je construis des modèles pour analyser les rendements boursiers et suivre les portefeuilles financiers.',
     'Finance quantitative, marchés et investissement.'),
    ('horizon.lina', 'Lina', 'Trabelsi',
     'I forecast perishable stock and coordinate meal donations between grocery stores and charities. '
     'My goal is to make redistribution reliable for volunteers.',
     'Community logistics, surplus forecasting and food rescue.'),
    ('horizon.omar', 'Omar', 'Gharbi',
     'J’analyse les performances des joueurs et les résultats des compétitions de football pour préparer les matchs.',
     'Sport, statistiques de compétition et jeux vidéo.'),
    ('horizon.yasmine', 'Yasmine', 'Kallel',
     'J’aide les épiceries à estimer leurs invendus et les collectifs solidaires à planifier les tournées de dons alimentaires.',
     'Économie circulaire, prévision des surplus et bénévolat.'),
    ('horizon.nader', 'Nader', 'Hamdi',
     'I am learning how to forecast grocery surpluses and help charities collect donated meals.',
     'Food rescue and solidarity.'),
]


class Command(BaseCommand):
    help = 'Seed realistic fictional candidates for Sami / Horizon in AI Challenge. DEBUG only; reruns preserve edits.'

    def add_arguments(self, parser):
        parser.add_argument('--configure-team', action='store_true',
            help='Explicitly set Horizon’s food-redistribution idea and Data Science 4/5 essential need. Other needs stay unchanged.')

    @transaction.atomic
    def handle(self, **options):
        if not settings.DEBUG:
            raise CommandError('This fictional showcase requires DEBUG=True.')
        sami = User.objects.filter(username='sami',is_active=True).first()
        event = Hackathon.objects.filter(slug='ai-challenge-2026').first()
        if not sami or not event:
            raise CommandError('Run seed_demo first to create Sami and AI Challenge.')
        team = services.active_team(sami,event)
        if team and not services.is_captain(sami,team):
            raise CommandError('Sami is not captain of his current team; no membership will be changed.')
        if not phase_is_open(event,EventPhase.Kind.REGISTRATION) or not services.formation_open(event):
            raise CommandError('Registration and team formation must be open. Existing dates will not be changed.')
        skill_map = {name:Skill.objects.filter(name__iexact=name).first() or Skill.objects.create(name=name,category='Data' if name in ('Data Science','Machine Learning') else 'Développement') for name in DECLARATIONS}
        for name, skill in skill_map.items():
            if not skill.description:
                skill.description = SKILL_DESCRIPTIONS[name]
                skill.save(update_fields=['description'])
        users = []
        for username, first, last, bio, interests in PEOPLE:
            user, created = User.objects.get_or_create(username=username,defaults={'first_name':first,'last_name':last,'email':username+'@example.test'})
            if created:
                user.set_password(PASSWORD)
                user.save()
                Profile.objects.update_or_create(user=user,defaults={'biography':bio,'interests':interests,'university':'ESPRIT'})
                for name, level in DECLARATIONS.items():
                    UserSkill.objects.create(user=user,skill=skill_map[name],level=2 if username=='horizon.nader' and name=='Data Science' else level)
            users.append(user)
        list(User.objects.select_for_update(no_key=True).filter(pk__in=[sami.pk,*[u.pk for u in users]]).order_by('pk'))
        if not services.accepted_registration(sami,event):
            reg = Registration.objects.filter(user=sami,hackathon=event).first()
            if reg:
                raise CommandError('Sami’s registration was cancelled; it will not be reactivated by the seed.')
            services.register(actor=sami,event=event,accept_conditions=True)
        if team is None:
            team = services.create_team(actor=sami,event=event,name='Horizon',description=DESCRIPTION)
            configure = True
        else:
            configure = options['configure_team']
        if configure:
            services.update_team(actor=sami,team=team,name=team.name,description=DESCRIPTION,recruiting=team.recruiting)
            need = TeamSkillNeed.objects.filter(team=team,skill=skill_map['Data Science']).first()
            services.save_need(actor=sami,team=team,skill=skill_map['Data Science'],level=4,priority=3,need=need)
        for user in users:
            if not Registration.objects.filter(user=user,hackathon=event).exists():
                services.register(actor=user,event=event,accept_conditions=True)
        self.stdout.write(self.style.SUCCESS(f'Candidates seeded in {event.title} / {team.name}. No automatic team admissions.'))
        self.stdout.write(f'Open: /participation/{event.slug}/teams/{team.pk}/candidates/')
        self.stdout.write('Four equal skill profiles, different interests; one lower-level candidate. Run prepare_m2_matching to warm the model.')
        self.stdout.write('Existing accounts, edits, passwords and cancellations preserved. --configure-team explicitly updates the idea and Data Science need.')
