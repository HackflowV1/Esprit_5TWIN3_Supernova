# M2 — recommandations locales de coéquipiers

**Mise à jour budget 0 :** le moteur actuel est all-MiniLM-L6-v2 anglais, ONNX q8.
Voir `docs/M2_ENGLISH_LOW_MEMORY.md`. Les descriptions et biographies IA sont en
anglais ; l’interface reste bilingue. La section technique multilingue ci-dessous
conserve la configuration du pilote historique.

Pour la présentation dans l’événement normal avec Sami et Horizon, suivre
**[le scénario Sami](M2_SAMI_DEMO.md)**. Team Lab reste un terrain de test complémentaire.

## Démarrer

```powershell
uv sync --locked
uv run --locked python manage.py check_database
uv run --locked python manage.py migrate
uv run --locked python manage.py seed_m2_matching_demo
uv run --locked python manage.py prepare_m2_matching
uv run --locked python manage.py runserver
```

La migration reçue `projects.0003_projectaianalysis` appartient à M3. Ce changement
M2 réutilise les tables existantes : aucune migration artificielle n’est ajoutée.
Git partage les commandes de seed et migrations, jamais la base locale ni le modèle.

Tester **Team Lab**, compte `m2.demo.01`, mot de passe des nouveaux comptes
`Demo-Team#2026` → Mon équipe → Trouver des coéquipiers.
Salma et Amina partagent les compétences déclarées d’Omar, mais leur contexte
alimentaire/associatif correspond mieux à Passerelle. Lea a un contexte pertinent,
mais son niveau Mobile 2/5 reste inférieur au besoin essentiel 3/5.
Ce sont des exemples fictifs, pas une mesure de performance sur des personnes réelles.

## Classement explicable

1. Calculer les besoins que les membres actifs ne couvrent pas au niveau demandé.
2. Garder seulement les comptes actifs, inscrits acceptés, dans cette édition,
   sans équipe et sans conflit de rôle juré (services M2 existants).
3. Classer d’abord par nombre de besoins essentiels satisfaits, puis présents.
4. Pour les profils comparables, grouper la couverture pondérée par quarts, puis
   combiner 85 % de couverture et 15 % de similarité cosinus. Ces poids sont une
   règle de classement interne, pas des probabilités ou des métriques apprises.
5. Départager de façon stable par identifiant. Aucun recrutement automatique.

Le sélecteur **Compétences seules / Compétences + projet** conserve les mêmes
candidats, besoins et règles de couverture. Le mode UI `skills` retire seulement
le signal sémantique du classement hybride ; il n’est pas le mode historique
`rules` utilisé pour l’évaluation V1. Les progressions affichées comparent les
positions réelles sur le même filtre et ne paraissent que si le modèle est prêt.
Sans idée décrite, état `no_context` et invitation à la préciser, sans prétendre
adapter les profils au projet. Les biographies et centres d’intérêt passent avant
les expériences longues pour ne pas être éliminés par la troncature du modèle.

Le modèle préentraîné est `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`,
exécuté localement par FastEmbed/ONNX, CPU deux threads, vecteurs 384 dimensions.
Ce n’est pas un modèle entraîné par notre groupe. Il rapproche notamment les textes
FR/EN et leur sens ; les déclarations structurées restent la preuve des compétences.
La puce de contexte utilise un seuil heuristique conservateur de 0,65, sans
calibration ni affirmation de fiabilité statistique.

Entrées : besoins déclarés + idée de l’équipe ; compétences/expériences déclarées,
biographie et centres d’intérêt du candidat. Ni emails, ni messages de candidature,
ni contacts. Texte limité ; le modèle tronque à 128 tokens. Aucune compétence,
langue, disponibilité ou personnalité n’est déduite comme un fait.
Les textes utilisateur restent échappés dans les templates.

## Cache, panne et asynchronisme

`prepare_m2_matching` télécharge explicitement environ 220 Mo et vérifie le modèle.
Après cela, aucun téléchargement ni appel d’API n’a lieu dans le parcours HTTP.
L’inférence force `local_files_only=True`. Le calcul des vecteurs manquants passe
par un unique worker de fond par processus, sans file d’attente non bornée,
avec au plus 128 textes par tâche. Les requêtes restent sur le classement par
compétences tant que le calcul n’est pas prêt. Un échec impose une pause de 60 s
avant une nouvelle tentative et garde le parcours manuel opérationnel.

Les embeddings, sans texte brut ni identifiants, sont mis en cache disque sept jours
dans `.cache/`, ignoré par Git. Les clés incluent le contenu, la version du moteur
et le modèle : un changement de profil ou de besoins invalide les vecteurs concernés.
Le cache n’accorde jamais de droits : les candidats et la couverture sont relus
à chaque requête. Sans besoin manquant, pas d’inférence ni de faux classement.

`M2_MATCHING_ENABLED=0` désactive l’IA. Le worker Python suffit à ce petit classement
local ; il n’est pas une file de tâches durable. À plus grande échelle : worker
séparé/Redis et suivi des tâches, sans modifier les services de recrutement.

## Évaluation à faire avec le groupe

`docs/m2_human_review.csv` contient 32 paires fictives distinctes du seed, dans quatre
cas. Ne pas entraîner sur ces exemples. Un membre du groupe lit l’idée, les besoins,
les compétences et la biographie **avant de regarder les classements**, puis remplit :

- `relevance` : 0 = non pertinent ; 1 = partiel/à discuter ; 2 = bon candidat.
- `reviewer` : nom du relecteur ; `notes` : raison courte.

Idéalement, deux personnes notent indépendamment et discutent les désaccords.
Le fichier livré est volontairement vide : aucun jugement humain n’est inventé.

```powershell
# Latence et classements réels, sans prétendre mesurer la qualité
uv run --locked python manage.py evaluate_m2_matching --output .cache/m2-evaluation.json
# Après annotation humaine complète
uv run --locked python manage.py evaluate_m2_matching --labels docs/m2_human_review.csv --output .cache/m2-evaluation-reviewed.json
```

Le rapport compare mots-clés, règles V1 et hybride : Precision@3 (notes 1/2 =
pertinentes), NDCG@3 (pertinence graduée), moyennes et latences de classement.
Il distingue première exécution et moyenne/p95 sur cache chaud. Ces temps ne sont
pas la latence HTTP complète. Le premier lancement inclut le chargement local du
modèle ; les calculs froids sont hors requête utilisateur.
Un fichier incomplet ou sans relecteur est refusé. Sans labels, statut
`awaiting_human_review`, aucun chiffre de qualité. Si le modèle manque, le rapport
signale le repli et ne présente pas celui-ci comme une comparaison IA valide.
Ce petit jeu aide à valider le prototype ; il ne prouve pas sa généralisation.

## Interface et vérifications

La question de l’écran : « Qui peut compléter les besoins de mon équipe ? ».
Le besoin réel précède la liste, les niveaux et l’indice de contexte restent près
de chaque personne. Le parcours public garde le choix de l’équipe pendant la
connexion/création du compte et l’inscription explicite. Membres et messages privés.

Design existant conservé : Signal orange & mist, Plus Jakarta Sans, Hugeicons,
thèmes et préférences d’accessibilité partagés. Taste : editorial-greeting,
seed 415163636, palette/type conservés ; la navbar approuvée reste commune.
La signature est la couverture réelle des besoins, pas une jauge de compatibilité.
Le petit libellé d’équipe sert de contexte, d’où l’avertissement de lint accepté.
Pas de nouvelle illustration ou de nouveau système de navigation.
