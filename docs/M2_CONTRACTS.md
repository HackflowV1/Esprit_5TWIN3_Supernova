# M2 — contrats pour M3, M4 et le moteur commun

## Propriété des données

`accounts` possède User, Skill, UserSkill et les rôles contextuels.
`hackathons` possède l’événement, ses limites et ses phases.
`teams` possède Registration, Team, TeamMembership, TeamInvitation,
JoinRequest, TeamSkillNeed et TeamHistory.

Les identifiants et relations existants ne changent pas. La migration M2 ajoute
ses tables ; aucune migration des collègues n’est réécrite. Aucun rôle participant
historique n’est converti silencieusement en inscription.

## Lectures communes

```python
from teams import services

registration = services.accepted_registration(user, event)  # Registration ou None
team = services.active_team(user, event)                    # Team ou None
members = services.active_members(team)                     # QuerySet de memberships
captain = services.is_captain(user, team)                    # bool, sans rôle organisateur
ready = services.team_is_ready(team)                        # bool calculé, jamais copié
coverage = services.skill_coverage(team)                     # besoins avec covered_by
```

Le consommateur contrôle aussi ses autorisations. Une relation Team ne donne
pas automatiquement l’accès à un projet privé ou à une réservation. Le mentor
accompagnant une équipe n’est pas un TeamMembership.

M3 peut exiger `team_is_ready(team)` avant de créer un projet et réutiliser les
membres actifs pour l’accès. M4 peut autoriser l’aide à une équipe encore en
formation ; ses créneaux, disponibilités et réservations restent chez M4.
Ni projet ni rendez-vous factice n’est créé par M2.

## Recrutement et moteur commun

```python
candidates = services.eligible_candidates(actor=viewer, team=team)
suggestions = services.recommendations(actor=viewer, team=team)
```

L’acteur doit être inscrit accepté dans la même édition ou organisateur.
Les candidats sont des comptes actifs, inscrits acceptés, sans équipe et sans
conflit juré dans cette édition. Ne pas exposer leurs emails.

Le moteur utilise les besoins non couverts. Le champ `score` conserve la somme V1
`priority * min(candidate_level, requested_level)` pour compatibilité ; il n’est
pas un pourcentage. Le classement hybride privilégie les compétences essentielles
déclarées et leur niveau, puis la couverture pondérée et le contexte sémantique
local de profils comparables. Les champs `matches`, `registration` et `score`
restent disponibles. `matching_state` indique ready/warming/unavailable/disabled/no_needs.
`context_signal` est un indice de contexte, jamais une compétence certifiée.
`recommendation_comparison(actor=..., team=..., mode='hybrid')` renvoie le classement
choisi, la référence `skills` (même logique sans sémantique), et les besoins manquants.
Le mode UI `skills` et l’état `no_context` complètent les états décrits ci-dessus.

L’assistant de besoins utilise `teams.skill_suggestions.suggest(text)` pour une
prévisualisation, jamais pour modifier un profil personnel. Après confirmation,
`save_suggested_needs(actor=..., team=..., proposals=[{skill,level,priority}])`
réutilise les mêmes verrous, permissions, phases et historique que `save_need`.
Les besoins déjà présents sont ignorés, pas mis à jour implicitement.
Le formulaire n’accepte que les labels de sa prévisualisation de session,
valable 20 minutes. Les modèles sont en JSON et ONNX ; aucun pickle utilisateur chargé.
Le mode `rules` garde le classement V1 pour la comparaison ; `keywords` est la
référence textuelle. Le recrutement manuel reste indépendant du modèle.
Voir `docs/M2_MATCHING.md` pour le contrat complet et les limites.

L’annuaire d’idées et la fiche réduite sont publics pour les éditions visibles ;
les profils, candidatures, messages et recommandations restent protégés. Les
identifiants et transitions d’inscription/adhésion M3/M4 ne changent pas.

## Mutations et concurrence

Toutes les routes d’écriture sont POST, avec CSRF et autorisation serveur.
Réutiliser exclusivement `teams.services` pour les écritures métier :
`register`, `cancel_registration`, `create_team`, `update_team`, `recruit`,
`decide`, `leave_team`, `transfer_captain`, `save_need`, `delete_need`.

Ordre des verrous PostgreSQL : utilisateurs concernés par identifiant croissant,
puis hackathon. Le verrou du hackathon sérialise les contrôles de capacité et
la composition des équipes. Ne pas ajouter de verrou utilisateur après avoir
verrouillé un événement dans une nouvelle opération.

Contraintes uniques : une inscription utilisateur/édition, une adhésion active
par inscription, un nom d’équipe insensible à la casse par édition, un besoin
par compétence/équipe et une invitation/candidature en attente par paire.
Les relations entre éditions sont validées dans les services et `clean()`.

La synchronisation du rôle participant est une opération `accounts` dédiée à
une inscription persistée, sans élargir le service général `set_role`.
L’historique M2 enregistre les décisions, adhésions, départs et transferts.
Les changements de capacité M1 refusent d’invalider les inscriptions ou équipes
existantes. Le gel TEAM_FORMATION et l’archivage sont vérifiés à chaque mutation.

## Validation livrée

Tests PostgreSQL des transitions, permissions et intégrations M1/accounts,
deux langues, CRUD des besoins et compteurs d’archive. Trois tests de concurrence
avec connexions indépendantes couvrent les dernières places d’inscription,
la dernière place d’équipe et l’adhésion simultanée à deux équipes.

```powershell
uv run --locked python manage.py check
uv run --locked python manage.py makemigrations --check --dry-run
uv run --locked python manage.py test --keepdb --noinput
```

Les tests n’utilisent que `test_hackflow_db`. Les données locales restent dans
`hackflow_db` et ne sont pas partagées par Git ; les migrations et commandes de
démo permettent aux collègues d’obtenir la même structure et des exemples.
