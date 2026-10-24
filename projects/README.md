# M3 — Projets, progression et soumissions

Le travail M3 est contenu dans `projects/`. La seule extension partagée est un
bloc de navigation vide dans `templates/base.html`, ajouté à la demande de
l’utilisateur pour afficher Mes projets dans le menu. Aucun fichier métier
existant de M1, M2, accounts, core ou config n’est modifié.
Les modèles, services et templates existants sont réutilisés en lecture/import.

## Lancer M3 sans modifier le travail des autres membres

Depuis la racine du projet, après configuration de PostgreSQL dans `.env` :

```bash
uv run python manage.py check --settings=projects.settings_m3
uv run python manage.py check_database --settings=projects.settings_m3 && uv run python manage.py migrate --settings=projects.settings_m3
uv run python manage.py runserver 127.0.0.1:8001 --settings=projects.settings_m3
```

Ouvrir `/projects/` pour les projets privés et `/projects/gallery/` pour la galerie.
Le paramètre `--settings=projects.settings_m3` active M3 explicitement ; le
lancement habituel conserve la configuration des autres membres. Le port 8001
permet de garder le serveur initial sur le port 8000.
Les migrations ajoutent uniquement les tables M3, avec des relations vers les
tables existantes. Aucune migration d’un autre membre n’est réécrite.

## Parcours

1. Un participant rejoint une équipe valide M2.
2. Pendant la phase développement ou soumission, un membre crée sa fiche projet
   depuis `/projects/`, en choisissant un challenge publié du même événement.
3. Les membres planifient les étapes et leur progression dans le kanban.
   Le pourcentage détermine automatiquement l’état : 0 % à faire, 1–99 % en cours,
   100 % terminé.
4. Ils créent une version et y ajoutent dépôt, présentation, vidéo ou démo.
5. Le capitaine soumet pendant la phase soumission, strictement avant la deadline.
6. La fiche, les exigences et les références des livrables sont enregistrées dans
   un snapshot officiel. Le hash Git complet du dépôt évalué est obligatoire.
7. Le capitaine autorise la publication des livrables ; l’organisateur valide
   leur publication dans la galerie.

Un organisateur peut réouvrir un projet avec justification et une limite future
avant la fin de l’événement. La précédente version officielle reste figée et
consultable par les personnes autorisées. La publication est retirée, et la
substitution est historisée. Les éditions archivées sont en lecture seule.

## Démonstration locale

```bash
uv run python manage.py seed_m3_demo --settings=projects.settings_m3
```

Cette commande crée seulement une édition distincte `m3-project-lab`, deux
équipes et cinq comptes de démonstration. Une seconde exécution ne modifie rien.
Les événements et comptes préexistants ne sont pas réinitialisés.

- `m3.captain` : Campus Care, progression 60 %, version 3 officielle et publiée.
- `m3.captain2` : Campus Share, version 1 en brouillon pour essayer les formulaires.
- `m3.builder` / `m3.designer` : membres des équipes correspondantes.
- `m3.organizer` : revue de publication et dérogations.

Mot de passe local de démonstration : `Demo-M3#2026`. Les URL et commits présents
dans la démo sont fictifs. Le seed est refusé si `DEBUG=False`.

## Relations M3

```mermaid
erDiagram
    Team ||--o| Project : possede
    Challenge ||--o{ Project : inspire
    Project ||--o{ Milestone : planifie
    Project ||--o{ Submission : versionne
    Submission ||--o{ Deliverable : contient
    Project ||--o{ ProjectActivity : historise
    Project }o--o| Submission : officielle_designee
```

Les liens sont contrôlés localement (HTTPS, sans identifiants ni adresses privées
littérales), sans requête réseau. Le capitaine confirme leur accessibilité au jury
et le respect des exigences textuelles du challenge ; leur contenu distant n’est
pas automatiquement vérifié ni archivé. Le commit fixe la référence du code.
Les fichiers PDF/ZIP/MP4 sont limités à 20 Mo avec contrôle de signature et SHA-256.
Ce contrôle ne constitue pas une analyse antivirus.

## Fichiers et permissions

Les fichiers sont stockés dans `projects/private_files/`, exclu par le
`.gitignore` propre à M3 et situé hors de `MEDIA_ROOT`. Les téléchargements
passent par une vue autorisée ; les anciennes versions privées ne deviennent pas
publiques avec la version actuellement publiée. L’admin M3 est consultatif.
Les écritures passent par `projects.services`, avec verrou utilisateur puis
événement puis projet, compatible avec l’ordre des verrous M2.

## Contrats M5 et IA

`Project.official_submission` désigne la version officielle courante.
`Submission.snapshot` et ses livrables sont figés après officialisation.
M5 devra contrôler ses affectations et conflits avant d’utiliser cette référence.
Aucun accès global n’est accordé aux utilisateurs ayant seulement le rôle JURY.

`projects.services.copilot_input(actor=..., project=...)` fournit le problème,
la solution, la stack et le pitch aux personnes autorisées. Aucun moteur IA ni
transfert externe n’est effectué. Le moteur collectif reste une intégration future.

`projects.services.metrics(event)` expose les compteurs M3 au fournisseur M1.
Le fichier `settings_m3.py` l’active sans remplacer le fournisseur M2.

La configuration M3 ajoute aussi `integration_templates/` devant les templates
partagés. Son `base.html` hérite de la base existante et ajoute Mes projets au
menu principal (Galerie pour les visiteurs). La base partagée possède seulement
un bloc d’extension vide `project_navigation`, ajouté à la demande de l’utilisateur.
Le serveur initial garde son menu habituel quand M3 n’est pas activé.

## Validation

```bash
uv run python manage.py test projects --keepdb --noinput --settings=projects.settings_m3
uv run python manage.py makemigrations --check --dry-run --settings=projects.settings_m3
uv run python manage.py test --keepdb --noinput --settings=projects.settings_m3
```

Les tests utilisent exclusivement `test_hackflow_db`. Ils couvrent permissions,
deadline exacte, dérogations, versions figées, fichiers privés, publication,
CSRF, parcours des écrans et numérotation concurrente.

Pour passer entre la configuration commune et `projects.settings_m3`, exécuter
les tests sans `--keepdb` : leurs applications installées et leurs schémas de
test diffèrent. Django recrée uniquement `test_hackflow_db`. Les tests M3 sont
ignorés dans la configuration commune où l’application n’est pas activée.

Revue de fusion du 24 octobre 2026 contre `origin/main` (`be25f45`) : fusion
simulée dans un checkout isolé sans conflit, 417 tests avec M3 passent et la
suite commune passe (385 tests, dont un module M3 ignoré). Les 207 fichiers
déjà présents sur `origin/main` sont conservés à l’identique, à l’exception
du seul ajout du bloc vide `project_navigation` dans `templates/base.html`.
Le menu Mentorat de M4 est conservé. Les contrôles Django, des migrations,
de syntaxe JavaScript et `git diff --check` passent. Cette revue ne fusionne
ni ne pousse la branche et n’active pas M3 dans la configuration commune.

Validation du 24 octobre 2026 : 124 tests de régression passent, dont 23 tests
M3. Le contrôle Django ne signale aucune anomalie et aucune migration ne manque.
Les deux serveurs répondent HTTP 200 : projet initial sur 8000, galerie M3 sur 8001.
Après correction de l’édition du pourcentage : 24 tests M3 passent, dont un test
du formulaire pour 4 %, 99 %, 100 %, retour à 0 % et refus des valeurs hors limites.

Les traductions françaises/anglaises M3 sont autonomes dans `projects/locale/` ;
les fichiers `.po` et `.mo` sont livrés sans modifier le catalogue commun.
Les vérifications HTTP locales couvrent la galerie dans les deux langues, la
connexion de démonstration, le tracker, les versions et le chargement du CSS.
La revue visuelle mobile/bureau reste à faire dans un navigateur : aucun
navigateur n’était connecté aux outils de cette session.

## Intégration collective ultérieure

Après revue par l’équipe, le responsable de l’intégration pourra reprendre dans
la configuration commune les ajouts explicites de `settings_m3.py` et la route
de `urls_m3.py`, puis ajouter les liens de navigation souhaités. Ces fichiers
communs sont volontairement laissés intacts dans cette livraison isolée.

## Tableau de suivi

Le tracker commence par un tableau à trois listes, avec compteurs réels, cartes
compactes, progression et dates. Les liens de titre ouvrent l’édition ; le menu
de chaque carte regroupe modifier/supprimer. Ajouter une étape depuis une liste
préremplit sa progression (0 %, 1 % ou 100 %). Sur mobile, les listes défilent
horizontalement. Les liens À propos, Versions et Activité rejoignent leurs
sections. Les thèmes et couleurs partagés sont réutilisés sans les modifier.

## Espace de soumission

La page d’une version affiche d’abord ses livrables enregistrés, leur URL et leur
commit complet dépliable. Le sélecteur de versions indique combien de livrables
contient chacune. Le formulaire d’ajout et la soumission officielle sont séparés,
avec une confirmation explicite après l’enregistrement d’un livrable en brouillon.
Le dépôt de code exige un lien et un SHA complet ; les erreurs sont associées aux
champs concernés. Le formulaire adapte ses champs au type avec JavaScript, tout
en conservant la validation Django sans JavaScript. Le bouton officiel attend un
dépôt enregistré et la confirmation du capitaine. Aucune connexion GitHub ni
copie automatique entre versions n’est effectuée.

Après cette amélioration, les 25 tests M3 passent, la syntaxe JavaScript est
vérifiée, et les pages de version et livrables publics répondent HTTP 200.

## Liste des projets et galerie

Mes projets présente des compteurs filtrables (tous, en préparation, soumis,
publiés), une recherche par projet/équipe/hackathon et des cartes avec progression,
étapes, versions, échéance et accès direct au tableau ou à la soumission officielle.
Les projets sont triés par dernière modification. Le badge de soumission reflète
la présence d’une version officielle, même si le statut de préparation est READY.

La galerie affiche les technologies et les contenus du snapshot officiel,
avec recherche et filtre par hackathon. Aucun contenu privé courant n’est inclus
dans la recherche publique. Les filtres sont conservés pendant la pagination.
Les 27 tests M3 couvrent notamment les filtres et leurs frontières de permissions.

## Supprimer un brouillon

Le capitaine utilise Supprimer le brouillon sur une page de version, puis confirme
sur une page dédiée. Le brouillon est retiré des listes et du compteur de versions,
sans supprimer ses fichiers ni réutiliser son numéro. Il reste restaurable depuis
Brouillons supprimés sur le tableau ou une autre version. La suppression et la
restauration sont historisées et sérialisées avec les autres opérations M3.
Les soumissions officielles, y compris historiques, restent protégées. Une version
officielle courante n’empêche pas de retirer un autre brouillon inutilisé.
Les changements restent réservés au capitaine pendant une période de modification
ouverte ; les éditions archivées sont en lecture seule. Les 29 tests M3 couvrent
le cycle suppression/restauration, les permissions, le CSRF et la conservation
des numéros et livrables.

## Déplacer une étape

Le tableau permet de glisser une carte entre les trois colonnes. Terminé fixe la
progression à 100 %, À faire à 0 %, et En cours conserve un pourcentage intermédiaire
ou commence à 1 %. Le serveur enregistre le changement avant de remplacer le
tableau et l’activité par leurs rendus à jour. Une erreur laisse la carte en place.
Le menu de chaque carte propose aussi Déplacer vers, au clavier, sur écran tactile
et sans JavaScript. Les écritures POST exigent CSRF, membre actif et période ouverte.

Le déplacement met à jour uniquement la progression du tableau vivant. Il peut
continuer après un dépôt officiel pendant la période autorisée : le snapshot
officiel, son pourcentage enregistré, sa fiche et ses livrables ne changent pas.
La modification complète de la fiche, des étapes ou du dépôt reste soumise aux
règles de réouverture existantes. Le mouvement est historisé avec l’état et le
pourcentage précédents.

Validation : 32 tests M3 passent, dont les transitions, permissions, CSRF,
frontières de deadline, POST classique/AJAX et immutabilité du snapshot officiel.
La syntaxe JavaScript et la disponibilité des contrôles français/anglais sont
vérifiées. Le geste de glissement reste à essayer manuellement dans le navigateur,
aucun navigateur n’étant connecté aux outils de cette session.

## Progression vivante et progression soumise

Mes projets affiche séparément Progression du tableau (calculée sur les tâches
actuelles) et Progression au dépôt (figée), lue dans le snapshot officiel. Le
tableau rappelle la valeur de la version officielle et la page de soumission
l’affiche dans son panneau principal. Exemple testé : dépôt officiel à 36 %,
tableau porté ensuite à 100 %, soumission toujours enregistrée et affichée à 36 %.
Les 33 tests M3 couvrent cette distinction jusque dans les réponses HTML.
