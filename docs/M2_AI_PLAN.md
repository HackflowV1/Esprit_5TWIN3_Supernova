# M2 — parcours équipe et recommandations

Plan du 26 octobre 2026. Branche : `codex/m2-smart-matching`.
Préparation terminée : corrections navbar/tableau poussées sur main (5486e87).

## Parcours à livrer

Hackathon → Trouver une équipe → découvrir son idée et ses besoins →
candidater → connexion si nécessaire → accepter les règles du hackathon →
retrouver la même équipe → envoyer sa candidature → réponse du capitaine.

La consultation ne crée aucune inscription. Avant inscription : seulement idée,
besoins et places ; les membres, messages et profils restent privés.
Un identifiant d’équipe de la même édition remplace les URL de retour arbitraires.

## Exécution

1. Appliquer les migrations reçues après vérification de la base locale.
2. Ouvrir l’annuaire et une fiche publique réduite ; conserver les contrôles métier
   existants et reprendre la candidature après inscription explicite.
3. Ajouter un moteur local multilingue FastEmbed / MiniLM (ONNX). Les compétences
   déclarées couvrant les besoins manquants dominent le classement ; la similarité
   des textes départage les profils comparables. Aucun niveau n’est inféré.
4. Préparer le modèle par commande explicite, jamais par téléchargement HTTP
   pendant une requête utilisateur. Cache par contenu, modèle et version ; retour
   au classement déterministe si indisponible. Pas de stockage des emails/messages.
5. Afficher les besoins restants, les niveaux déclarés et des explications sobres.
   Distinguer soutien sémantique et compétence vérifiable ; aucun faux pourcentage.
   Sans besoin déclaré, proposer de préciser les besoins, sans classement IA.
6. Ajouter une commande de démo répétable : 28 participants fictifs FR/EN,
   six équipes et des profils contrastés ; ne pas réinitialiser les données existantes.
7. Préparer une évaluation distincte : recherche par mots, règles, hybride ;
   jugements humains indépendants, Precision@3 / NDCG@3 et latence. Fournir un
   fichier à annoter, ne jamais inventer les annotations ou un gain mesuré.
8. Vérifier permissions, reprise d’inscription, éligibilité, classement/cache/repli,
   idempotence du seed ; contrôler le parcours en navigateur, FR/EN et mobile.
   Mettre à jour USER_M2, contrats et commandes de démarrage.

## Relecture unique avant exécution — 26 octobre 2026

Vérifié : périmètre limité à M2 ; M1/M3/M4 et comptes réutilisés ; consentement,
événement de retour, confidentialité et contraintes de capacité conservés.
Précision ajoutée après relecture : ne pas afficher un profil sans compétence
déclarée comme répondant à un besoin uniquement grâce à sa biographie ; le contexte
sémantique est un complément explicite. L’évaluation humaine reste à remplir par
le groupe, tandis que l’intégration et les mesures de latence sont exécutables.
Le modèle doit être téléchargé avant activation et le classement utilisable hors ligne.

## Validation réalisée

- Migrations reçues appliquées à `hackflow_db` après `check_database` :
  `projects.0003_projectaianalysis`. Aucun nouveau schéma M2 nécessaire.
- `seed_m2_matching_demo` : 28 inscrits, six équipes, 16 candidats disponibles ;
  relance et préservation des changements vérifiées par test PostgreSQL.
- `prepare_m2_matching` : modèle ONNX téléchargé, inférence locale vérifiée et
  cache des équipes rempli. Démonstration réelle FR/EN sur Passerelle.
- 64 tests ciblés puis **501 tests** de l’ensemble du projet : tous réussis.
  `check` et `makemigrations --check --dry-run` : sans erreur, pas de changement de schéma.
- Évaluation exécutée sans labels : modèle prêt ; moyenne initiale sur cache chaud
  environ 1,37 ms pour le petit classement isolé (hors HTTP/SQL), première exécution
  environ 2,05 s avec chargement du modèle. Fichier local `.cache/m2-evaluation.json`.
  Ces mesures dépendent de la machine. Qualité : **à annoter par le groupe**.
- Lint Taste des deux nouveaux écrans : zéro échec. Avertissement de contexte
  d’équipe conservé volontairement ; contrôle visuel via navigateur, pas par un
  navigateur automatisé externe. Guide de validation dans `docs/M2_MATCHING.md`.
- Après les derniers ajustements : 11 tests écrans/classement, puis huit tests
  ciblés du moteur (dont deux nouveaux contrôles cache/worker) réussis. Vérification
  navigateur en FR/EN, clair/sombre, desktop/tablette/téléphone : pas de débordement
  horizontal de page ; disclosure utilisable avec Entrée. Capture conservée dans
  l’espace de travail de la conversation, hors dépôt.
