# Contrats USER + M1

## Références et arbitrages

La conception suit le dossier HackFlow (9 pages), les deux prompts de mission et de
gouvernance, et les techniques de [AU-26-27-5TWIN3](https://github.com/DoussRim/AU-26-27-5TWIN3)
(Person/Event : models, forms, views, urls, admin, services, templates et migrations).
Les choix fonctionnels non arrêtés collectivement dans le PDF sont explicités ci-dessous.

| Sujet | Décision appliquée | Origine |
|---|---|---|
| Identité | Conserver `accounts.User(AbstractUser)`, username de connexion ; email public obligatoire et unique sans distinction de casse | Dépôt et mission prioritaires |
| Application M1 | `hackathons`, au lieu de `events` proposé dans le PDF | Mission explicite |
| Base | PostgreSQL local `hackflow_db`, tests `test_hackflow_db` ; aucun fallback SQLite | Sécurité de la mission |
| Méthode | MVT, UserCreationForm, LoginView/LogoutView, ModelForms, CBV CRUD, ORM, services, Admin | Méthode du professeur |
| Publication | Au moins un track actif et un challenge validé/publié ; quatre phases obligatoires | Politique V1 de complétude |
| Rôles incompatibles | PARTICIPANT et JURY incompatibles dans une même édition ; autres cumuls permis | Politique prudente V1 ; autres conflits restent dans les domaines propriétaires |
| Création | Permission globale dédiée, accordée par le superutilisateur ; rôle organisateur ensuite contextualisé | Résolution du besoin d’autorisation avant qu’un hackathon existe |
| Archivage | Seulement après la date de fin et le statut terminé ; configuration figée | Parcours métier PDF |
| Git | Branche `feature/M1-hackathons`, push/PR/merge après validation technique autorisés explicitement | Dernière autorisation utilisateur remplaçant les confirmations antérieures |

Les erreurs du dépôt pédagogique ne sont pas reproduites : pas de mutation métier par GET,
de compteur d’inscriptions fictif, de chemin de fichier fourni par le navigateur ouvert
sur le serveur ou de clé API dans le code. La migration initiale User n’est pas réécrite.

## Modèles et propriété

| Propriétaire | Modèle | Relation / invariant |
|---|---|---|
| accounts | User | Identité Django commune ; aucune classe SponsorUser/JuryUser |
| accounts | Profile | OneToOne User : biographie, université, avatar, intérêts |
| accounts | Skill / UserSkill | Référentiel unique ; relation User/Skill unique, niveau 1–5, expérience |
| accounts | RoleAssignment | User + Hackathon + rôle unique ; ACTIVE/REVOKED ; auteur et dates |
| accounts | RoleAssignmentHistory | Historique des changements de statut et de leur auteur |
| accounts | SponsorMembership | User + SponsorOrganization unique ; état et droit de proposer |
| hackathons | Hackathon | Dates, règlement, conditions, capacité, tailles des équipes, cycle de vie et archive |
| hackathons | Track | FK Hackathon, nom unique dans l’édition, actif |
| hackathons | Challenge | FK Track, consignes, FK Sponsorship facultative, auteur et validation organisateur |
| hackathons | EventPhase | FK Hackathon, type unique, début/fin ; état calculé |
| hackathons | SponsorOrganization | Organisation globale, logo, secteur, site et contacts privés |
| hackathons | Sponsorship | Organisation/Hackathon unique, contribution, valeur/devise, état, confirmation, informations pour M5 |
| hackathons | EventHistory | Journal daté privé par événement ; acteur, action, cible, détails avant/après pour configurations |

Utiliser `settings.AUTH_USER_MODEL` pour les relations externes à accounts et
`get_user_model()` pour obtenir la classe utilisateur. Ne pas dupliquer les compétences.
Les modèles historiques et les relations métier utilisent PROTECT lorsque la suppression
pourrait faire perdre une référence. Les suppressions publiques de ressources sont limitées
aux brouillons non référencés. Les autres opérations passent par retrait, révocation ou archive.

## Autorisations et mutations

```python
from accounts.permissions import has_role, is_member, require_organizer, HackathonRoleMixin
from accounts.models import Role
from accounts.services import set_role
from hackathons.services import require_open_phase, phase_is_open
```

`has_role(user, hackathon, *roles)` vérifie utilisateur authentifié et actif, rôle ACTIVE
dans l’événement cible, ou superutilisateur actif. `is_member` signifie rôle actif,
pas inscription M2. `HackathonRoleMixin` demande `get_hackathon()` et `required_roles`.
Il ne remplace pas le filtrage des objets enfants par le hackathon de l’URL.

`require_organizer(..., mutable=True)` refuse également toute mutation d’une archive.
`mutable=False` sert à la consultation de l’historique, du dashboard et du contexte IA.
Le rôle ORGANIZER ne donne aucun accès à l’administration technique.

Les changements métier passent par les services :

- `create_hackathon(actor=..., event=...)` crée aussi le rôle organisateur et son historique.
- `save_configuration(actor=..., event=...)` met à jour uniquement les champs éditables.
- `save_resource(actor=..., resource=...)` valide les enfants sous verrou du parent ;
  une ressource existante ne peut changer d’événement. Modifier un challenge retire sa validation.
- `set_role(actor=..., user=..., hackathon=..., role=..., status=...)` sérialise les
  changements de rôles ; le dernier organisateur ne peut être retiré.
- `propose_challenge`, `review_challenge` : contrôle de la représentation, validation,
  publication ou retrait ; un représentant sponsor ne peut publier lui-même.
- `transition(actor=..., event=..., target=...)` contrôle les dates, la complétude et le cycle.

Les écritures UI utilisent des transactions et les mêmes services que l’administration.
Les formulaires filtrent leurs FK par événement. Les services doivent rester le point
d’entrée des écritures intermodules : `QuerySet.update()` et `bulk_create()` contournent
les validations Python, l’historique et les contrôles d’archivage ; ne pas les utiliser
pour modifier ces objets métier. Les contraintes SQL restent une défense complémentaire.

## Calendrier et consommation par M2–M5

Les intervalles sont `[début, fin[` en dates conscientes du fuseau ; l’affichage est
Africa/Tunis. La fin exacte est fermée. Le statut dérivé d’une phase n’est pas stocké.
Inscription et formation peuvent précéder le début du hackathon. La phase inscription
reproduit exactement les deux dates du Hackathon. La phase soumission finit exactement
à `submission_deadline`. Les évaluations commencent après cette deadline.
Développement/soumission peuvent se chevaucher ; évaluation/résultats ne peuvent se
chevaucher ni chevaucher développement/soumission. Les résultats suivent l’évaluation.

| Consommateur | Contrat à réutiliser | Reste à sa charge |
|---|---|---|
| M2 | FK Hackathon, UserSkill, `require_open_phase(h, EventPhase.Kind.REGISTRATION)` / TEAM_FORMATION | Registration, Team, adhésions, invitations, capacité réellement occupée, verrouillage des acceptations |
| M3 | FK Challenge, Track.hackathon, règlement, SUBMISSION et deadline | Project, versions, fichiers, droits équipe et dérogations tracées |
| M4 | calendrier, Role.MENTOR, Skill/UserSkill | expertises, créneaux, séances, ateliers, réservations |
| M5 | Role.JURY, Challenge, EVALUATION, Sponsorship.prize_information | affectations de projets, conflits d’intérêts détaillés, grilles, notes, résultats et prix |

`require_open_phase` est un garde calendrier. Il n’inscrit personne et ne vérifie pas
une capacité M2 encore inexistante. M2 doit l’appeler dans sa transaction, avec le
verrou sur l’événement avant son calcul de capacité. Un rôle PARTICIPANT ne remplace
jamais Registration. Les phases sont autorisées seulement si l’événement est PUBLISHED/ONGOING.

## Dashboard, archive et comparaison

`metrics(event)` lit les tracks, challenges, sponsors confirmés et rôles participants.
Ce dernier compteur est explicitement distinct des inscriptions. Les éditions archivées
conservent ce dictionnaire dans `archive_metrics`, avec `archived_at`. Le dashboard et
la comparaison utilisent ce snapshot pour les archives, les compteurs actuels autrement.
Seuls les organisateurs des éditions sélectionnées peuvent comparer leurs données privées.
Les données d’un module non connecté restent indisponibles, sans inventer un zéro.

Pour connecter les agrégats en lecture :

```python
HACKFLOW_METRIC_PROVIDERS = {
    # 'M2': 'teams.services.control_tower_counts',
    # 'M3': 'projects.services.control_tower_counts',
    # 'M5': 'evaluations.services.control_tower_counts',
}
```

Chaque callable reçoit un Hackathon et renvoie `dict[str, int]` de compteurs réels,
entiers positifs ou nuls (pas de booléens). Par exemple : registrations, incomplete_teams,
participants_without_team, projects_without_deliverables, pending_evaluations.
Les fournisseurs doivent filtrer exclusivement cet événement, respecter la confidentialité
et ne réaliser aucune écriture. Un contrat invalide ou une erreur rend le module indisponible.

## Contribution aux deux moteurs IA

### Assistant individuel de rédaction de challenge

Dans **Pilotage → Ajouter un challenge**, l’organisateur choisit un track actif,
décrit une idée et peut préciser le public et la durée. **M'aider à rédiger avec l'IA**
demande à Gemini un titre, une problématique, des objectifs et des livrables en FR/EN.
Seul ce contexte limité est envoyé, sans contacts, comptes ni projets privés.

Les champs vides sont remplis. Pour les champs déjà renseignés, la proposition est
affichée séparément : cocher chaque remplacement puis confirmer, ou garder les valeurs
actuelles. Modifier un champ retire le consentement à son remplacement ; changer le
track ou l’idée invalide les propositions en attente. **Enregistrer** utilise toujours
le formulaire et le service existants : brouillon, historique, validation puis publication
par l’organisateur. La génération seule ne réalise aucune écriture métier.

Configuration : `GOOGLE_API_KEY` et premier modèle de `GEMINI_MODELS` (modèle de repli
si liste vide : `gemini-2.5-flash`). Le serveur impose 20 secondes, une sortie JSON avec
exactement quatre chaînes non vides (titre ≤ 200 caractères, autres champs ≤ 4000), et
10 demandes par utilisateur et fenêtre horaire, y compris les échecs. Cette limite
réutilise le cache local du projet ; un déploiement multi-processus devra employer un
cache partagé pour une limite commune. Sans clé ou en cas d’erreur, le formulaire manuel
reste utilisable. Les exceptions du fournisseur et les secrets ne sont jamais journalisés.

Vérification : `python manage.py test hackathons.test_ai --keepdb` et
`node scripts/test_challenge_suggest.cjs`. Aucun modèle ni migration ajouté.

`intelligence_context(actor=..., event=...)` fournit un contrat versionné (v1) :
calendrier, tracks actifs, capacité/tailles, conditions d’éligibilité et challenges publics
validés avec leurs objectifs et livrables. L’appel exige un organisateur et ne transmet
ni emails, ni contacts sponsor, ni projets privés. Les dates sont des objets datetime
conscients du fuseau ; utiliser DjangoJSONEncoder si le consommateur sérialise en JSON.
IA1 peut consommer les tracks/calendriers/contraintes ; IA2 les exigences des challenges.
Les algorithmes, embeddings, scores, résumés et décisions restent dans intelligence/
et les domaines M2–M5, qui ne sont pas créés par M1.

`HACKFLOW_ALERT_PROVIDER = 'intelligence.services.control_tower_alerts'` permet
ultérieurement d’intégrer des alertes réelles au dashboard. Le callable reçoit le hackathon
et renvoie une liste de dictionnaires `code`, `message`, `severity` (info/warning/error).
Ses résultats sont affichés échappés par Django ; ils ne changent ni les notes ni les droits.
En son absence le dashboard indique « Fournisseur non connecté ».

## Recette et limites

La suite Django comporte un parcours de bout en bout (compte → événement → rôle →
track → challenge validé/publié → phases → sponsor → publication → refus d’un autre compte),
des tests unitaires/HTTP/SQL et des tests concurrents PostgreSQL réels.
Le navigateur sert aussi à vérifier l’interface de ces opérations sur des données fictives
dans hackflow_db. Les scénarios d’archivage après échéance sont automatisés avec une horloge
contrôlée ; ils ne nécessitent pas de modifier l’horloge du serveur ou les autres bases.

La recette intermodules complète de la page 9 (équipes, projets, mentorat, jury, prix)
nécessite les futures livraisons M2–M5. Les tests de fournisseur vérifient leur contrat
avec des valeurs contrôlées ; ils ne prétendent pas tester ces modules inexistants.
