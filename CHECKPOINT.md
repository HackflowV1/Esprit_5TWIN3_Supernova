# État actuel — illustrations monochromes intégrées

Dernière demande : noir et blanc, texte du hero à gauche, illustration à droite,
intégration sur l’accueil et la connexion, redémarrage rapide et vérifications ciblées.
Cette consigne remplace l’ancienne demande de photo en arrière-plan ci-dessous.

Réalisé : deux illustrations approuvées intégrées en WebP avec transparence,
filtre monochrome et encre inversée en mode sombre ; nouveau hero en deux colonnes,
parcours illustré et visuel sur les pages de connexion/inscription.
Les correctifs de reprise (comparaison, suppression des brouillons, traduction de
« Non renseigné », CSS lisible) sont aussi intégrés.
Serveur relancé sur http://127.0.0.1:8000/. Vérification Django et pages ciblées,
sans relancer la suite complète conformément à la demande de l’utilisateur.

---

## Ancien checkpoint conservé pour historique

# Checkpoint — refonte de l’interface HackFlow

Arrêt demandé par l’utilisateur le **23 octobre 2026**. Reprendre depuis ce point,
sans recommencer la refonte. Le projet reste en cours : il reste une dernière passe
de finition visuelle avant de déclarer la demande initiale entièrement terminée.

## Où reprendre

- Dépôt local : `C:\Users\hamma\Documents\GitHub\Esprit_5TWIN3_Supernova`.
- Branche : `codex/design-foundation`. Checkpoint local, rien envoyé sur GitHub.
- Application principale : <http://127.0.0.1:8000/>.
- Guide commun pour les cinq membres : [DESIGN.md](DESIGN.md).
- Environnement et PostgreSQL déjà configurés. `.env` reste ignoré par Git.

Si le serveur a été arrêté :

```powershell
Set-Location C:\Users\hamma\Documents\GitHub\Esprit_5TWIN3_Supernova
uv sync --locked
uv run python manage.py runserver 127.0.0.1:8000
```

## Déjà réalisé

- Mise en page commune sobre, nouveaux boutons et champs, responsive, fil d’Ariane.
- Menu du compte et préférences langue/thème dans la navbar.
- Hugeicons Free 4.3.5 stocké localement, licence MIT conservée, icônes CRUD.
- Français par défaut ; anglais via Django gettext, **485 messages traduits**.
  Les fichiers `.po` et `.mo` sont présents. Compilation portable avec
  `uv run python scripts/compile_translations.py`.
- Thèmes clair, sombre et système. Les couleurs reposent sur des variables communes.
- Listes déroulantes avec popup stylée via `appearance: base-select` quand disponible,
  et sélecteur natif de secours. Clavier et formulaires Django conservés.
- Champs avec labels, aide et erreurs associées ; résumé des erreurs avec focus.
- Onglets du pilotage au clavier, menus fermables avec Échap, lien d’évitement,
  styles de focus, réduction des animations et couleurs forcées.
- Templates existants de comptes, catalogue, détail, pilotage, comparaison,
  historique, formulaires, confirmation et erreurs actualisés. Admin neutralisé en CSS.
- Accueil enrichi : éditions réelles, guide interactif des cinq rôles, parcours,
  FAQ et actions utiles. Les fonctionnalités futures sont signalées clairement.
- Quatre images illustratives générées avec l’outil intégré, encodées en WebP local
  (environ 380 Ko au total), chargement différé hors hero.

### Dernière préférence explicite de l’utilisateur

**Le hero doit avoir la photo en arrière-plan et le texte devant.** C’est maintenant
le cas. Ne pas revenir au précédent bloc photo au-dessus du texte.
Un voile noir uniforme à 62 % garantit au texte blanc un contraste minimum de
**6,2:1**, même sur un pixel blanc de l’image. Les boutons ont leur propre fond.
Le texte reste complètement opaque pendant les animations.

## Vérifications déjà effectuées

- `manage.py check` : OK ; `makemigrations --check --dry-run` : aucun changement.
- **Les 74 tests passent ensemble** sur la version du checkpoint (29,9 secondes),
  après nettoyage des données de prévisualisation de la base de test.
- Les nouveaux tests vérifient notamment le français initial malgré un navigateur
  anglais, le changement de langue, les pluriels, CSRF/redirection, les pages
  authentifiées dans les deux langues, les erreurs accessibles et le menu du compte.
- Vérification navigateur de l’accueil en français/anglais, clair/sombre ; catalogue
  et popup ; profil et menu ; pilotage ; formulaire de rôles sur téléphone.
- Vérification concrète du déplacement des onglets avec les flèches et du focus
  sur le résumé d’un formulaire invalide. Aucun débordement horizontal observé
  sur les écrans examinés, notamment le formulaire à environ 390 px.
- Le voile du hero a été vérifié par calcul de contraste, pas par estimation visuelle.

## À terminer au retour

1. Faire la dernière revue de **tout l’accueil**, surtout le hero final sur téléphone,
   aux largeurs 1440, 768 et 390, dans les deux langues et thèmes. Revoir les captures,
   les retours à la ligne et le contenu sous la ligne de flottaison.
2. Vérifier le détail d’un événement, la comparaison remplie, un formulaire long
   et l’administration dans le navigateur ; les tests de rendu sont déjà présents.
3. Finir quelques détails repérés : le libellé `Non renseigné` de partenariat reste
   à traduire ; les sélecteurs de comparaison doivent conserver les éditions choisies ;
   les liens « Supprimer le brouillon » du pilotage sont encore proposés hors brouillon,
   alors que le service refuse déjà ces suppressions. Aligner leur affichage sur la règle
   existante, sans changer les autorisations ni le cycle métier.
4. Améliorer la lisibilité des feuilles CSS, actuellement compactes. Relancer le lint
   de Taste Skill et documenter les éventuelles adaptations justifiées. Son inspecteur
   Chrome autonome n’a pas été exécuté : utiliser les outils CUA pour les contrôles
   navigateur et ne pas annoncer un résultat d’inspecteur non obtenu.
5. Relancer les vérifications si du code change, puis livrer le bilan final et une
   capture de la version finale. Ne pas pousser sur GitHub sans demande.

## Données et serveur de contrôle

La base principale **hackflow_db** et son schéma n’ont pas été modifiés par cette
refonte. Aucune nouvelle migration. Une prévisualisation temporaire sur le port 8001
utilisait uniquement **test_hackflow_db** ; elle a été arrêtée et ses données ont été
nettoyées. Ne pas la laisser tourner pendant les tests : `--keepdb` conserve les
données initiales, ce qui avait causé des collisions avec les fixtures du premier
essai final. Aucun problème de ce type ne concernait la base principale.

Le script de prévisualisation, si nécessaire, est hors dépôt :
`C:\Users\hamma\Documents\ChatGPT\Django HackFlow\tmp\design_preview.py`.
Il force et vérifie `test_hackflow_db`. Ne jamais lancer son jeu de données dans
la base principale sans demande explicite. Les comptes de prévisualisation étaient
des comptes de test, pas des comptes utilisateur à conserver.

## Références visuelles et outils

- Skill demandé : <https://www.tasteskill.dev/> ; copie de travail hors dépôt dans
  `C:\Users\hamma\Documents\ChatGPT\Django HackFlow\tmp\taste-skill`.
- Application : direction **achromatic-ledger**, seed **1021052549**.
- Accueil : direction **editorial-report**, seed **1413632897** ; un redessin du hero
  motivé par la demande d’images, puis la préférence explicite pour une image de fond.
- Ne pas appliquer les effets de page marketing aux formulaires et écrans de travail.
- Images : collaboration en bibliothèque, carnet de maquettes, développement sur
  ordinateur et présentation de prototype ; lumière naturelle, tons neutres, sans logos
  ni texte. Elles illustrent le projet et ne documentent pas un événement réel.
- Originaux générés conservés dans le dossier Codex `generated_images` du chat.
- Captures de contrôle :
  `C:\Users\hamma\Documents\ChatGPT\Django HackFlow\output\design`.
  `checkpoint-hero.png` montre le dernier hero ; certaines autres captures sont
  antérieures à sa dernière modification.
- Utiliser CUA pour le navigateur. Le viewport temporaire a été réinitialisé.

Au retour, « reprends depuis CHECKPOINT.md » suffit pour retrouver ce contexte.
