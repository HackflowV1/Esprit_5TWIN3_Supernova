# M2 — suggestions de besoins depuis une description

Plan et relecture du 26 octobre 2026, avant implémentation.

## Périmètre

Le capitaine décrit le travail technique de son équipe ; l’assistant suggère des
besoins parmi les 13 compétences existantes. Il confirme chaque compétence,
choisit niveau et priorité, puis enregistre via les services M2. Aucun profil
personnel modifié, aucune nouvelle compétence créée, aucune certification.

## Étapes

1. Dataset synthétique FR/EN produit par le sous-agent GPT-6 Luna demandé :
   train/validation/test séparés par familles de scénarios, labels du référentiel,
   exemples négatifs et cas ambigus. Provenance et absence de revue humaine explicites.
2. Valider schéma, noms, doublons, groupes, support par compétence et échantillons.
   Créer en plus une feuille de revue humaine indépendante, sans faux résultats humains.
3. Réutiliser MiniLM ONNX local et figé pour obtenir les embeddings, puis entraîner
   13 régressions logistiques. Comparer TF-IDF et une référence mots-clés/alias.
   Ajuster les seuils seulement sur validation ; évaluer le test une seule fois.
4. Sauver coefficients et métadonnées en JSON portable plutôt qu’un pickle chargé
   depuis le web : labels, seuils, version modèle, empreinte dataset, dépendances et
   métriques. Aucun entraînement dans une requête HTTP. Script reproductible.
5. Intégrer un écran M2 depuis les besoins de l’équipe : description → suggestions
   à cocher → niveaux/priorités → confirmation explicite. États vide, préparation,
   modèle absent, compétence déjà déclarée ; aucun écrasement implicite.
6. Tester permissions, phase, CSRF, labels autorisés, validation et absence de
   mutation avant confirmation. Mesurer précision/rappel/F1 micro/macro/par label,
   latence chaude/froide et mémoire. Vérifier FR/EN, mobile, clavier et repli manuel.
7. Documenter lancement, entraînement, limites, petit PC et Render : téléchargement
   au build, artefact livré, cache éphémère reconstructible, mémoire réelle et pas
   de promesse sur une instance gratuite de 512 Mo. Ne pas modifier la base ou le
   déploiement des autres modules.

## Relecture unique

Vérifié : M2 possède les besoins, accounts possède les compétences personnelles.
Tous les labels proviennent de Skill ; les niveaux restent choisis par la personne.
Le sous-agent produit seulement les données ; sa sortie n’est pas une validation
humaine. Les scores issus du test synthétique ne sont pas une précision réelle
sur utilisateurs. TF-IDF/mots-clés sont des comparaisons nécessaires : publier
les résultats même si le modèle n’est pas meilleur. Une idée vague n’impose pas
de technologie ; une sortie vide est valide. Les seuils ne sont pas des probabilités
calibrées et ne seront pas affichés comme des pourcentages de confiance.

Choix après relecture : exporter le petit classifieur en JSON pour servir sans
charger scikit-learn en mémoire ; garder scikit-learn dans les dépendances
d’entraînement. Réutiliser l’unique instance ONNX existante et limiter les entrées.

## Résultats observés

- Dataset réellement rédigé par GPT-6 Luna : petit pilote puis complément multilabel.
  Version finale : 140 train, 46 validation, 39 test final. L’ancien test de
  développement est conservé et distinct du test final. Cinq descriptions train
  corrigées après audit IA ; aucune revue humaine revendiquée.
- Revue de l’approche après le pilote : les mentions explicites complètent le
  classifieur et sont identifiées séparément dans l’interface. Les résultats des
  règles ne sont pas attribués à l’apprentissage. Architecture et seuil minimal
  fixés avant l’évaluation du nouveau test final.
- F1 micro synthétique : MiniLM + tête entraînée 86,5 %, TF-IDF 69,7 %,
  mots-clés 75,8 %, hybride réellement servi 93,7 %. Référence complète et
  empreinte des données dans `artifacts/team-skill-needs/v1/evaluation.json`.
- Aucun quasi-doublon textuel train/validation → test final au seuil SequenceMatcher
  0,90 ; cela ne garantit pas l’indépendance sémantique de données du même générateur.
- 63 tests M2/interface réussis ; `check` et migrations à blanc sans modification
  de schéma. Prévisualisation réelle avec Sami : UI/UX proposée sans ce terme dans
  le texte, Figma déjà déclaré préservé, aucune écriture avant confirmation.
- Benchmark processus neuf : 638 Mo RSS sans scikit-learn chargé, premier appel
  2,37 s, texte non caché modèle chaud 36,4 ms. Pas de garantie sur Render Free
  512 Mo ; l’exigence ultérieure de budget 0 nécessite une adaptation d’hébergement.
  Une variante ONNX plus compacte a été sondée hors application : 471 Mo RSS,
  pic 555 Mo, donc insuffisante pour promettre une exécution dans 512 Mo.
- Le code en navigateur a été identifié comme option pour déporter la RAM sur
  le poste utilisateur ; il n’est pas implémenté dans ce checkpoint local.
