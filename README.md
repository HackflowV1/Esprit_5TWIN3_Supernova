# HackFlow — USER + M1

Monolithe Django 5.2 (MVT), Templates, ModelForms, vues génériques et PostgreSQL.
Le modèle original `accounts.User(AbstractUser)` et sa migration initiale sont conservés.

**Interface commune aux cinq modules : [DESIGN.md](DESIGN.md).**
L’application démarre en français. Le menu « Langue et apparence » propose l’anglais
et les thèmes clair, sombre ou système. Les icônes Hugeicons et les images sont locales.
Après modification des traductions, lancer `uv run python scripts/compile_translations.py`.

## Démarrage local

Dans le dépôt existant, avec Python 3.11+ et `uv` :

```powershell
uv sync --locked
Copy-Item .env.example .env  # seulement si .env n’existe pas
```

Configurer `.env` avec les secrets locaux, sans les versionner :

```dotenv
DJANGO_SECRET_KEY=REPLACE_WITH_LOCAL_SECRET
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DATABASE_URL=postgresql://postgres:LOCAL_PASSWORD@127.0.0.1:5432/hackflow_db
```

Créer exclusivement `hackflow_db` dans PostgreSQL local si elle n’existe pas.
Les caractères spéciaux du mot de passe doivent être encodés dans l’URL.
La configuration refuse les autres noms de bases, les hôtes distants, les autres ports,
les options d’URL et SQLite. Aucune connexion aux données d’un autre projet n’est requise.

```powershell
uv run python manage.py check_database
if ($LASTEXITCODE -eq 0) { uv run python manage.py migrate }
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test --keepdb
uv run python manage.py runserver
```

Les tests utilisent exclusivement `test_hackflow_db`, séparée de `hackflow_db`.
Le compte PostgreSQL doit pouvoir créer cette base. `--keepdb` la conserve pour les
prochaines exécutions. Réserver ce nom à la suite HackFlow : les tests transactionnels
nettoient leurs propres tables. Ne jamais fournir une autre base au runner.
Vérifier `check_database` immédiatement avant chaque migration.

Application : <http://127.0.0.1:8000/>. Administration : <http://127.0.0.1:8000/admin/>.
Les réglages par défaut servent au développement local ; un déploiement nécessite
HTTPS, `DEBUG=False`, un vrai secret, les cookies sécurisés et la configuration des médias.

## Première utilisation

Créer un superutilisateur technique avec `uv run python manage.py createsuperuser`.
Un utilisateur peut ensuite s’inscrire sans aucun rôle ni accès organisateur.
Le superutilisateur attribue la permission **accounts / Peut créer un hackathon**
aux personnes autorisées. La création de l’événement leur attribue transactionnellement
le rôle ORGANIZER dans cette édition. Les formulaires publics ne peuvent accorder
ni `is_staff`, ni `is_superuser`, ni des permissions globales.

Depuis le pilotage : créer un track, un challenge, le valider puis le publier,
et configurer les phases Inscriptions, Développement, Soumissions et Évaluations.
Publier ensuite le hackathon. Les phases Constitution des équipes et Résultats sont
également disponibles. Un événement incomplet ne peut pas être publié.

Le superutilisateur gère le référentiel Skill et les SponsorMembership.
Pour proposer un challenge sponsorisé, un compte doit cumuler une appartenance active
à l’organisation (avec droit de proposition), le rôle SPONSOR_REPRESENTATIVE dans
l’événement et un partenariat confirmé. L’organisateur valide puis publie la proposition.

## Fonctionnalités

- USER : inscription, sessions, profil, avatar contrôlé, changement du mot de passe,
  compétences de niveau 1–5, rôles contextualisés et historique d’affectation.
- M1 : événements, recherche et filtres, calendrier, tracks, challenges,
  organisations sponsors, partenariats et workflow de validation.
- M2 : inscriptions réelles, équipes, invitations/candidatures, capitaine,
  annuaire d’idées consultable avant inscription, reprise de candidature,
  compétences recherchées et recommandations locales de coéquipiers (textes IA en anglais).
- Cycle : brouillon → publié → en cours → terminé → archivé ; un événement publié
  dont la date de fin est passée peut aussi être terminé directement.
- Control Tower : compteurs issus de la base, échéances, phases et alertes de configuration.
- Historique paginé, archive avec indicateurs figés et comparaison de deux éditions.
- Administration réservée au superutilisateur technique, avec recherches, filtres,
  inlines et actions de publication/archivage réutilisant les règles métier.

- M4 : assistance, mentorat et ateliers : demandes d'aide des équipes, expertises et créneaux
  des mentors, réservation sans double réservation, séance avec compte rendu, retour de l'équipe
  et résolution, ateliers publiés par le mentor ou l'organisateur avec inscriptions individuelles, capacité
  garantie et relevé de présence ; suggestion de thème et de description d'atelier par Gemini
  (clé `GOOGLE_API_KEY` dans `.env`, facultative).

Les modules et intégrations IA ont leurs propres guides : M3 dans `projects/README.md`,
M4 dans `docs/USER_M4.md`, M5 dans `docs/M5.md`. Le moteur M2 local décrit ci-dessous
est indépendant des services Gemini des autres modules.

Pour essayer M2, lancer les migrations puis `uv run python manage.py seed_demo`
en développement et ouvrir **Mes inscriptions** ou une édition ouverte. La phase
**Constitution des équipes** doit être configurée pour autoriser le recrutement.
Voir [le parcours M2](docs/USER_M2.md) et [les contrats M3/M4](docs/M2_CONTRACTS.md).

Deux scénarios permettent de tester M2, après `uv sync --locked` et les migrations.

Pour la démonstration avec **Sami et Horizon dans AI Challenge**, suivre
[le scénario de présentation](docs/M2_SAMI_DEMO.md). Le sélecteur compare les
compétences seules avec le contexte du projet et affiche les changements réels de rang.
Le seed ci-dessous est le terrain de test supplémentaire Team Lab :

```powershell
uv run --locked python manage.py seed_m2_matching_demo
uv run --locked python manage.py prepare_m2_matching
```

Ouvrir **Team Lab · Trouvez vos coéquipiers**. Le premier téléchargement du modèle
est explicite ; ensuite, le classement fonctionne localement, sans clé d’API.
Le moteur commun utilise maintenant le petit MiniLM anglais ONNX pour limiter la
RAM : [configuration et mesures actuelles](docs/M2_ENGLISH_LOW_MEMORY.md). Les textes
IA sont en anglais ; l’interface reste FR/EN.
Les profils fictifs et comptes de test, le repli sans IA et l’évaluation humaine
sont expliqués dans [le guide de recommandations M2](docs/M2_MATCHING.md).

M2 propose aussi un [assistant de besoins entraîné](docs/M2_SKILL_SUGGESTIONS.md) :
description technique → suggestions → confirmation des compétences/niveaux/priorités.
Son petit classifieur JSON est livré ; MiniLM se prépare par la commande habituelle.
L’entraînement reproductible utilise `uv run --locked --group ml python manage.py train_m2_skill_model`.
Les métriques synthétiques et les limites de mémoire/déploiement sont documentées.

Pour essayer M4, après `migrate`, lancer en développement :

```powershell
uv run python manage.py seed_demo                          # comptes, compétences, éditions historiques (+ M2)
uv run python manage.py seed_m4_demo --user VOTRE_COMPTE   # édition « Mentoring Lab 2026 » ouverte aujourd'hui
```

La seconde commande crée deux équipes complètes (Nova Live, Horizon Live), des mentors avec
expertises et créneaux, des demandes d'aide, un rendez-vous réservé, une séance terminée qui attend
le retour de l'équipe et deux ateliers (un complet). Elle est idempotente. Les comptes de démonstration
partagent le mot de passe annoncé par `seed_demo`. Voir [le parcours M4](docs/USER_M4.md) et
[les contrats M4](docs/M4_CONTRACTS.md). Les tests de M4 sont dans `mentoring/tests/`.

## Intégration et validation

Voir [les contrats USER + M1](docs/USER_M1.md) pour les relations, permissions,
services, fournisseurs d’indicateurs/alertes et choix de conception.
Les tests couvrent les parcours, les refus, les échéances exactes, les contraintes SQL,
le CSRF, les uploads, l’administration et deux scénarios PostgreSQL concurrents.
Les mots de passe présents dans les tests sont exclusivement des valeurs fictives de fixtures.
