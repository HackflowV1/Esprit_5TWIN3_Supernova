# M2 — assistant de besoins et classifieur entraîné

## Utiliser l’assistant

Sami → AI Challenge → Horizon → **Suggérer des besoins depuis notre idée**.
Décrire le travail technique, analyser, puis cocher les suggestions utiles et choisir
niveau/priorité. Rien n’est ajouté avant confirmation. Un besoin existant n’est pas
écrasé et aucune compétence personnelle n’est modifiée.

Exemple à saisir : « Nous voulons tester les parcours utilisateurs, vérifier la
compréhension des écrans et rendre la navigation accessible au clavier.
Les maquettes seront faites dans Figma. »
L’assistant peut proposer UI/UX même sans ce mot dans le texte. Figma est une
mention explicite ; si déjà déclaré, il est signalé et n’est pas proposé une seconde fois.

Les sources sont visibles : **Mentionné dans votre texte** pour les règles d’alias,
**Suggestion du modèle ML** pour les suggestions supplémentaires du classifieur.
Une suggestion est une piste à discuter, jamais une exigence ou un niveau inféré.
Une phrase vague ou sans indice technique peut ne donner aucun résultat.

## Ce qui a été entraîné

- MiniLM multilingue reste préentraîné et figé ; on réutilise le modèle ONNX de M2.
- Les embeddings normalisés de 384 dimensions alimentent 13 régressions logistiques
  One-vs-Rest, entraînées localement avec scikit-learn (C=10, classes équilibrées).
- Seuils par compétence choisis sur validation uniquement, F0.5 pour privilégier
  la précision, seuil minimal 0,55. Ces scores ne sont pas des probabilités calibrées.
- Le service combine mentions explicites et classifieur ; les exclusions courantes
  FR/EN sont filtrées par une règle limitée, qui n’est pas une compréhension générale
  de toutes les négations. La confirmation humaine reste nécessaire.

Le sous-agent **GPT-6 Luna**, demandé par le responsable M2, a rédigé les données.
Les noms sont exactement les 13 compétences déjà présentes dans Skill. Aucun nouveau
référentiel ni donnée réelle d’utilisateur n’a servi à entraîner le modèle.

Jeu final : **140 descriptions d’entraînement, 46 de validation, 39 de test**.
Le premier jeu de test de développement est conservé dans `test.jsonl` ; les
résultats publiés utilisent **`final_test.jsonl`**, créé après la stabilisation de
l’approche hybride et sans communiquer les résultats au sous-agent. Les anciens
essais ne sont pas présentés comme une évaluation finale indépendante.
L’audit IA a corrigé cinq descriptions d’entraînement ambiguës ; ce n’est pas
une annotation humaine. Les scénarios et textes exacts ne traversent pas les splits.
Les variantes proches et les biais de génération restent une limite d’un petit jeu synthétique.

## Résultats réellement mesurés

Sur les **39 cas synthétiques de test**, pour 41 labels attendus :

| Méthode | Précision micro | Rappel micro | F1 micro |
| --- | ---: | ---: | ---: |
| Mots-clés/alias | 100,0 % | 61,0 % | 75,8 % |
| TF-IDF + régressions logistiques | 92,0 % | 56,1 % | 69,7 % |
| MiniLM figé + classifieur entraîné | 97,0 % | 78,0 % | 86,5 % |
| Hybride servi : mentions + classifieur | 97,4 % | 90,2 % | 93,7 % |

Ces résultats concernent seulement les exemples synthétiques, avec 3–4 occurrences
par compétence dans le test. **Ils ne mesurent pas la précision sur de vrais utilisateurs.**
Le détail macro, par compétence, erreurs et prédictions est dans
`artifacts/team-skill-needs/v1/evaluation.json`. Aucune performance humaine n’est inventée.
`datasets/team_skill_needs/human_review.csv` attend les jugements réels du groupe.

Le benchmark local séparé a mesuré : chargement + première inférence **2,37 s**,
texte nouveau avec modèle chaud **36,4 ms** en moyenne, résultat déjà en cache
**0,72 ms** en moyenne. Le petit classifieur seul prenait environ **0,27 ms**.
Ce ne sont pas des mesures HTTP en concurrence ni un benchmark Render.

## Fichiers et reproduction

```powershell
uv sync --locked --group ml
uv run --locked --group ml python scripts/download_m2_model.py
uv run --locked --group ml python manage.py train_m2_skill_model
uv run --locked --group ml python scripts/benchmark_m2_inference.py
uv run --locked python manage.py runserver
```

En production, `uv sync --locked --no-dev` suffit pour les dépendances d’inférence.
Le groupe optionnel `ml` contient scikit-learn et psutil pour l’entraînement/benchmark.
Le code web ne charge pas scikit-learn ; cette absence a été vérifiée par le benchmark.

- `teams/skill_suggestions.py` : chargement JSON, tête linéaire, règles explicites.
- `teams/management/commands/train_m2_skill_model.py` : audit, entraînement, validation et évaluation.
- `artifacts/team-skill-needs/v1/classifier.json` : coefficients, seuils, labels,
  modèle, version scikit-learn et empreinte du dataset ; petit fichier versionné.
- `.cache/m2-model/` : poids MiniLM, téléchargés explicitement, ignorés par Git.
- `.cache/m2-embeddings/` : vecteurs temporaires, invalidés par contenu/version.
- `scripts/download_m2_model.py` : préparation sans connexion à la base de données.

Le premier calcul d’un nouveau texte se fait via le worker existant. La page peut
actualiser uniquement l’analyse, au plus cinq fois, et s’arrête si le texte change.
Le script ne soumet jamais la confirmation des besoins. Sans modèle, ajout manuel disponible.

## Petit ordinateur et Render

Oui, inférence CPU, sans GPU. Sur la machine testée (environ 16 Go de RAM, six CPU
logiques), le processus Django + ONNX utilisait environ **638 Mo RSS** ; le processus
d’entraînement avec scikit-learn environ **767 Mo**. Garder de la marge pour le
système, le navigateur et les autres modules ; la taille disque n’est pas la RAM.
Ces mesures Windows ne garantissent pas la même consommation sur un autre ordinateur.

Le composant ML peut fonctionner sur Render avec les conditions suivantes :

1. Inclure `classifier.json` dans la livraison et préparer MiniLM au build ou dans
   une image ; ne pas télécharger ou entraîner dans une requête utilisateur.
2. Prévoir assez de RAM. Le service Free a 512 Mo : ne pas promettre qu’il supportera
   ce processus mesuré à 638 Mo. Un budget d’environ 2 Go offre une marge plus raisonnable.
3. Commencer avec un seul processus web chargeant MiniLM, car plusieurs workers
   peuvent dupliquer ses poids. Ajuster ensuite d’après les mesures Linux réelles.
4. Le stockage Render par défaut est éphémère : les modèles doivent être livrés ou
   recréés au build ; le cache temporaire peut être reconstruit. Les confirmations
   de besoins restent en PostgreSQL, pas dans un fichier local.

**L’application entière n’est pas encore prête à déployer telle quelle** : son
`config/database.py` protège actuellement la base locale et refuse une URL distante.
Il faudra des paramètres de production séparés (PostgreSQL Render, secrets, statiques
et médias, serveur WSGI), en conservant la protection locale/test. Aucun déploiement
payant ni assouplissement de cette protection n’a été effectué ici.

Sources officielles : [Render Free](https://render.com/docs/free),
[mémoire des instances](https://render.com/pricing),
[stockage éphémère](https://render.com/docs/deploys#ephemeral-filesystem).
