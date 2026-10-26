# M2 — version anglaise légère, budget d’hébergement 0

## Décision et plan revu

Le responsable M2 a accepté les textes IA en anglais pour éviter le coût mémoire
du modèle multilingue. La piste navigateur est conservée comme exploration, mais
**n’a pas été implémentée** : elle n’est plus nécessaire pour réduire la RAM du serveur.

Plan exécuté : mesurer un petit modèle dans Django complet → vérifier son comportement
en anglais → traduire le dataset via GPT-6 Luna → réentraîner la tête du classifieur →
remplacer le moteur commun aux deux fonctions → préparer les exemples et vérifier
les permissions, l’interface et les nouvelles mesures.

Relecture : ne pas confondre poids disque et RAM, mesurer le pic de chargement ;
ne pas réutiliser les anciens coefficients avec un autre espace d’embeddings ;
ne pas présenter un modèle anglais comme multilingue ; préserver le français dans
l’interface ; ne pas transformer un benchmark Windows en promesse de déploiement Render.

## Moteur commun aux deux fonctions

- Base : **sentence-transformers/all-MiniLM-L6-v2**, anglaise, 384 dimensions.
- Poids : ONNX q8 `Xenova/all-MiniLM-L6-v2`, révision
  `751bff37182d3f1213fa05d7196b954e230abad9`, environ 23 Mo plus tokenizer/config.
- Exécution : **ONNX Runtime CPU + tokenizers**, sans PyTorch, Sentence Transformers
  ou FastEmbed à l’exécution. Un thread, un texte à la fois, 128 tokens maximum.
- `teams/encoder.py` mutualise la session ; aucune nouvelle instance par candidat.
  Arena CPU et memory pattern désactivés pour limiter la rétention mémoire.
- L’éligibilité, les niveaux déclarés et les confirmations restent des règles Django.
- Les descriptions de projet et biographies doivent être en anglais pour le
  classement contextuel. L’assistant de besoins attend aussi une description anglaise.
  Aucune traduction automatique des textes utilisateurs n’est effectuée.

Les deux fonctions continuent à fonctionner côté serveur : pas de téléchargement
de 135 Mo dans le navigateur, pas de service d’inférence payant, pas de transmission
des descriptions à un fournisseur de modèle. Le build télécharge uniquement des poids publics.

## Chargement et mémoire

Les poids sont téléchargés **au build**, par commande explicite, jamais dans une
requête utilisateur. La session ONNX est chargée paresseusement au premier calcul,
puis réutilisée. Le worker existant calcule les vecteurs manquants ; l’interface
garde le classement par compétences ou propose l’ajout manuel pendant la préparation.

Le lazy loading retarde le coût mémoire ; il ne diminue pas magiquement la RAM
nécessaire. Le gain vient surtout du modèle plus petit, de la quantification et
du runtime léger. Un préchargement dans chaque worker dupliquerait les poids.

Benchmark final local, processus neuf incluant **Django et ses imports URL/vues** :

| Mesure | Résultat |
| --- | ---: |
| RAM RSS après inférence | 165,5 Mo |
| Pic de RAM du processus | 170,1 Mo |
| Premier calcul avec chargement | 379 ms |
| Texte nouveau, modèle chaud | 36,0 ms en moyenne |
| Résultat déjà en cache | 0,55 ms en moyenne |

`torch` et `sklearn` n’étaient pas importés dans ce processus de service.
Le serveur de développement réellement utilisé par le navigateur, après les deux
fonctions IA, a aussi été mesuré : environ **179 Mo RSS / 183 Mo de pic**.
Ces chiffres Windows ne comprennent pas une charge concurrente Render. Ils donnent
une marge plausible sous 512 Mo avec un seul processus web, à confirmer sur Linux
après déploiement. Les uploads et les autres modules partagent aussi la mémoire.

## Classifieur réentraîné

Le dataset anglais est dans `datasets/team_skill_needs_en/` : **140 train / 46
validation / 39 test final**, mêmes scénarios et labels que le pilote bilingue,
avec traduction GPT-6 Luna tracée pour les phrases françaises. Il reste synthétique
et non validé par des humains. Le jeu bilingue historique est conservé.

La tête One-vs-Rest Logistic Regression a été réentraînée sur les nouveaux
embeddings, puis exportée en JSON dans `artifacts/team-skill-needs/v2-en/`.
Les seuils sont choisis sur validation uniquement, F0.5 avec seuil plancher 0,55.

| Méthode | Précision micro | Rappel micro | F1 micro |
| --- | ---: | ---: | ---: |
| Mots-clés/alias | 100,0 % | 61,0 % | 75,8 % |
| TF-IDF + régressions logistiques | 100,0 % | 58,5 % | 73,8 % |
| MiniLM anglais + tête entraînée | 96,8 % | 73,2 % | 83,3 % |
| Hybride réellement servi | 97,3 % | 87,8 % | 92,3 % |

Ce sont des **résultats exploratoires sur 39 cas synthétiques**, pas une précision
validée sur de vrais utilisateurs. Le changement de langue/modèle a été comparé
pendant le développement ; le groupe doit encore réaliser une évaluation humaine
indépendante. Le détail par compétence et les erreurs sont dans `evaluation.json`.
La feuille `datasets/team_skill_needs_en/human_review.csv` attend les annotations
du groupe. Les prédictions restent reproductibles pour un modèle/texte fixés,
mais cela ne signifie pas qu’elles soient certaines ou toujours correctes.

## Reproduire et déployer plus tard

```powershell
# Installation normale pour servir : pas de scikit-learn nécessaire
uv sync --locked
uv run --locked python scripts/download_m2_model.py
uv run --locked python manage.py prepare_m2_matching

# Entraînement hors requête web, en local
uv run --locked --group ml python manage.py train_m2_skill_model
uv run --locked --group ml python scripts/benchmark_m2_inference.py

# Scénario Sami/Horizon en anglais, uniquement sur les données fictives
uv run --locked python manage.py seed_m2_sami_showcase --configure-team --english
```

Pour Render Free : préparer les poids dans l’image/build, livrer le classifieur
JSON, commencer par **un seul processus web** et peu de threads, garder les calculs
bornés, puis surveiller la RAM réelle. Ne pas entraîner à chaque démarrage et ne
pas initialiser une instance du modèle par requête. Le cache éphémère est reconstructible.

Le problème mémoire de notre ancien modèle est ainsi réduit dans les mesures
locales. Le déploiement global reste à préparer : `config/database.py` refuse
actuellement les bases distantes pour protéger la base locale/test ; il faudra des
paramètres de production séparés, statiques/médias et un serveur WSGI. Aucun service
payant n’a été créé et aucun déploiement externe n’est revendiqué.

Validation locale finale : **63 tests M2/interface réussis**, contrôle Django sans
erreur et aucune nouvelle migration nécessaire. Dans le navigateur, l’assistant
propose UI/UX depuis un texte anglais qui ne contient pas ce label, sans ajouter
de besoin avant confirmation. Le classement Horizon en contexte place Lina puis
Yasmine devant les profils finance et sport, contre un ordre par identifiant à
compétences seules. Aucun nom n’est pris en compte par le score sémantique.

Sources : [modèle anglais](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2),
[poids ONNX](https://huggingface.co/Xenova/all-MiniLM-L6-v2/tree/main/onnx),
[limites Render Free](https://render.com/docs/free).
