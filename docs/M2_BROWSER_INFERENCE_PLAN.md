# MiniLM en navigateur — adaptation au budget 0

**Piste remplacée avant implémentation.** Le responsable M2 a accepté l’IA en
anglais. Le modèle anglais L6-v2 ONNX quantifié, testé à environ 170 Mo de pic
avec Django, permet de garder le calcul sur le serveur sans imposer un gros
téléchargement au visiteur. Ce document conserve seulement la piste étudiée.
Voir `docs/M2_ENGLISH_LOW_MEMORY.md` pour la solution retenue.

Checkpoint local entraîné : `fde2ed5`. Plan avant portage, 26 octobre 2026.

## Objectif

Les deux usages de MiniLM (classement contextuel et besoins suggérés) exécutent
les embeddings dans un Web Worker du navigateur, sans modèle chargé par Django.
La politique métier, l’éligibilité, le classifieur JSON et les confirmations restent
sur le serveur. Le calcul navigateur est une aide non fiable pour les autorisations :
il ne donne aucun accès et ne crée aucune adhésion/compétence de lui-même.

## Exécution

1. Utiliser Transformers.js 3.8.1, modèle MiniLM multilingue ONNX q8 compatible,
   révision fixe. Worker séparé, CPU/WASM, max 128 tokens, pooling moyen, normalisation.
   Cache navigateur des poids (~118 Mo) et tokenizer (~17 Mo), chargement à la demande.
2. Préparer une page de parité de développement : vecteurs, prédictions sur les
   39 cas finaux synthétiques et classement Horizon. Mesurer premier chargement et
   usage suivant ; n’affirmer l’équivalence qu’après mesure.
3. Mode configurable `server`/`browser`. En mode navigateur, aucun import/chargement
   de FastEmbed/ONNX côté Django au cours des deux parcours web.
4. Confirmer les entrées dans une session signée/horodatée ; vérifier dimension,
   valeurs finies et nombre de vecteurs. Refuser les résultats devenus périmés après
   modification du projet, de l’éligibilité ou des profils. Ne pas mettre en cache
   global des vecteurs fournis par un client.
5. UI : activer l’IA explicitement lors du premier usage, progression lisible,
   annulation, repli compétences/manuellement. Réutiliser les poids sur les pages
   suivantes, mais annoncer les limites (cache supprimé, navigation privée,
   stockage évincé et réinitialisation de la session d’inférence).
6. Tests permissions, absence de téléchargement côté serveur, payloads modifiés,
   expiration, cache, FR/EN, clavier/mobile et classement réel. Mesurer le processus
   Django sans poids. La préparation du déploiement global reste distincte.

## Relecture

Vérifié : le budget 0 exige de déplacer les deux appels au modèle, pas uniquement
le nouveau classifieur. Le modèle q8 a la même base mais une autre quantification :
mesurer les écarts et les erreurs plutôt que réutiliser aveuglément les métriques.
La page ne doit pas envoyer descriptions/biographies à un service d’inférence externe.
L’activation télécharge des fichiers statiques publics, sans texte utilisateur.
Le cache est une optimisation, pas une promesse de téléchargement unique éternel.
L’application ne devient pas automatiquement prête pour Render : les paramètres
PostgreSQL de production et les médias devront être configurés séparément.
