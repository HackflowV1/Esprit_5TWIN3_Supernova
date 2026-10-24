# Plan M2 — inscriptions, équipes et compétences

Statut : V1 implémentée sur `codex/module-2` (24 octobre 2026).

Les propositions V1 ci-dessous ont été retenues pour cette implémentation à la
demande du responsable M2. Le moteur IA partagé reste une intégration future :
le classement livré est déterministe et expliqué. Voir `docs/USER_M2.md` pour
le parcours et `docs/M2_CONTRACTS.md` pour les contrats M3/M4.

Références : dossier clarifié, pages 2, 4, 8 et 9 ; code actuel de accounts/,
hackathons/ ; docs/USER_M1.md et DESIGN.md. Les règles V1 ci-dessous sont appliquées ; le groupe peut les faire évoluer
ensemble avant d’étendre le périmètre.

## Objectif et limites

Parcours : compte → inscription acceptée au hackathon → création ou recherche
d’équipe → invitation/candidature → adhésion → compétences et besoins visibles.

M1 crée les hackathons. M2 possède les inscriptions, équipes et recrutements.
accounts garde User, Skill, UserSkill et les rôles contextualisés.
M3 réutilise les équipes pour ses projets ; M4 les réutilise pour l’assistance.
Le mentor ne devient pas membre de l’équipe qu’il accompagne.

## Décisions V1 retenues

| Sujet | Proposition simple pour V1 |
| --- | --- |
| Admission | Inscription immédiatement acceptée si période ouverte, place disponible et aucun conflit de rôle. Validation organisateur uniquement si le groupe la souhaite. Pas de liste d’attente automatique en V1. |
| Validité d’une équipe | Création possible avec le capitaine seul. Équipe prête lorsque la taille minimale est atteinte et les inscriptions des membres sont acceptées. La taille maximale reste impérative. |
| Changements d’équipe | Création, recrutement, départ et exclusion pendant TEAM_FORMATION. Après fermeture : composition figée ; toute dérogation future devra être explicite, tracée et coordonnée avec M3/M4. |
| Départ du capitaine | Transfert à un membre actif avant son départ ; si l’équipe est vide après départ, fermeture avec historique conservé. |
| Annulation d’inscription | Pendant la période autorisée, quitter d’abord l’équipe et régler le transfert du capitaine. Ne pas retirer les autres rôles du compte. Après gel, pas d’annulation autonome qui invaliderait projets ou réservations. |
| Visibilité | Annuaire des participants/recrutement réservé aux inscrits acceptés du même événement et organisateurs ; pas d’email ni de contact privé public. |
| Assistance M4 | Proposer que toute équipe en formation puisse demander de l’aide ; M3 peut exiger une équipe prête pour créer un projet. À confirmer avec les responsables. |

Les conditions d’éligibilité de M1 sont actuellement du texte libre : les afficher
et demander leur acceptation ; ne pas prétendre les vérifier automatiquement.
Des critères structurés nécessiteraient une décision commune.

## Étape 1 — contrat et modèles

- Créer une branche codex/module-2 depuis main et l’application teams/.
- Documenter les états et transitions retenus après discussion.
- Construire les six modèles prévus : Registration, Team, TeamMembership,
  TeamInvitation, JoinRequest, TeamSkillNeed, avec migrations propres.
- Registration : une ligne par utilisateur/hackathon, état et dates ; réactivation
  éventuelle de cette ligne, avec historique des transitions.
- TeamMembership : relier l’inscription et l’équipe ; une seule adhésion active par
  inscription, donc par utilisateur/hackathon. Refuser toute incohérence d’événement.
- Le capitaine est aussi un membre actif ; ses actions ne donnent pas le rôle ORGANIZER.
- Invitations et candidatures : états attente/acceptée/refusée/annulée, expiration
  des invitations, prévention des doublons actifs. Historiser auteur, décision et date.
- TeamSkillNeed réutilise Skill ; aucune copie des compétences personnelles.
- Ajouter un journal M2 minimal pour adhésions, décisions, départs et transferts.
- Fixer les services de lecture réutilisables par M3/M4 : inscription acceptée,
  équipe active d’un utilisateur, membres actifs, capitaine, équipe prête.

Sortie : schéma et contrats stables, migrations vérifiées sur PostgreSQL.

## Étape 2 — inscriptions

- Bouton « S’inscrire » sur la page d’un hackathon ; page « Mes inscriptions ».
- Vérifier compte actif, statut public de l’événement, phase REGISTRATION,
  capacité réelle et absence de rôle JURY incompatible.
- Dans la même transaction : inscription acceptée + rôle PARTICIPANT actif + historique.
- Ajouter une opération accounts dédiée à cette synchronisation, avec contrôles
  précis, sans relâcher l’autorisation du service général set_role.
- Respecter un ordre commun de verrous User/Hackathon pour éviter les interblocages
  avec accounts.services.set_role. Les places sont comptées sous verrou du hackathon.
- Annulation/réinscription selon les décisions ci-dessus, sans doublon ni perte d’historique.
- Un rôle PARTICIPANT attribué manuellement ne remplace pas une Registration :
  ne pas convertir silencieusement les rôles existants en inscriptions acceptées.

Sortie : compte → inscription → droit de participer, sans dépassement de capacité.

## Étape 3 — équipes

- Annuaire filtré par hackathon : recherche, places disponibles et besoins de compétences.
- Créer une équipe, afficher sa fiche, modifier ses informations et fermer son recrutement.
- Le créateur est inscrit accepté et devient capitaine + membre, atomiquement.
- Calculer l’effectif depuis les adhésions actives ; distinguer équipe en formation
  et équipe prête. Une capacité personnalisée ne peut dépasser le maximum de M1.
- Transfert du capitaine, départ, exclusion et fermeture, selon les règles retenues.
- Contrôler les droits côté serveur, les phases et les objets de l’événement de l’URL.

Sortie : les équipes ont une composition cohérente et des droits distincts.

## Étape 4 — invitations et candidatures

- Le capitaine invite un participant inscrit ; seul l’invité répond à son invitation.
- Un participant demande à rejoindre une équipe ; le capitaine ou organisateur
  autorisé accepte/refuse la candidature.
- Une invitation en attente ne réserve pas une place.
- À chaque acceptation : recontrôler période, inscription, expiration, autorisation,
  équipe unique et dernière place disponible, dans une transaction verrouillée.
- Une ancienne demande/invitation ne peut pas être réutilisée pour forcer une adhésion.
- Prévoir annulation, refus, expiration et demandes devenues impossibles après adhésion
  ailleurs ; afficher un état compréhensible et conserver la trace des décisions.
- Centraliser toutes les acceptations dans le même service d’adhésion.

Sortie : deux acceptations simultanées ne créent ni surcapacité ni double équipe.

## Étape 5 — Team Skills et matching

- Afficher les compétences déclarées des membres, leurs niveaux et les besoins de l’équipe.
- Le capitaine ajoute/modifie/supprime les besoins : compétence, niveau et priorité.
- Fournir à intelligence/ des données autorisées et des candidats réellement éligibles.
- Préparer un score de complémentarité explicable et un petit jeu de cas connu,
  puis brancher le Smart Matching commun en coordination avec son responsable.
- Si seul un classement par règles est disponible, le présenter comme tel, sans
  inventer de pourcentage ni prétendre disposer d’un modèle IA avancé.
- Les recommandations n’acceptent jamais un membre et le recrutement manuel
  reste utilisable si le moteur est absent ou en erreur.
- M2 fournit le matching coéquipiers ; les disponibilités et réservations mentors
  restent dans M4, qui réutilisera le moteur commun.

Sortie : Team Skills et contrat de matching fonctionnent ; l’intégration du moteur
partagé est distinguée de la livraison des données et du classement initial.

## Étape 6 — intégration et démonstration

- Relier la navigation au contexte hackathon et à « Mon équipe ».
- Ajouter gestion organisateur des inscriptions/équipes dans le pilotage existant.
- Brancher HACKFLOW_METRIC_PROVIDERS['M2'] : inscriptions acceptées, équipes,
  équipes incomplètes, participants sans équipe, avec vrais compteurs filtrés par événement.
- Les lectures d’archives restent possibles ; les écritures sont refusées et les
  compteurs archivés suivent le snapshot M1.
- Ajouter Django Admin avec recherches/filtres et mutations utilisant les mêmes services.
- Réutiliser templates, champs accessibles, breadcrumbs, Hugeicons, FR/EN, modes
  clair/sombre et menus partagés de DESIGN.md.
- Mettre à jour seed_demo : les participants de démonstration ont de vraies
  inscriptions ; équipe incomplète, besoin UI/UX, invitation et candidature d’exemple.
- Fournir les contrats M3/M4 et un guide de démonstration. Aucun faux projet,
  atelier ou rendez-vous n’est créé pour simuler les modules absents.

Sortie : un parcours démontrable, utilisable et intégré au socle existant.

## Vérifications utiles

- Inscription hors période, événement complet ou conflit JURY : refus.
- Deux inscriptions pour la dernière place : une seule est acceptée.
- Un utilisateur ne peut rejoindre deux équipes du même hackathon, même simultanément.
- Deux acceptations pour la dernière place d’équipe : une seule réussit.
- Invitation expirée, demande déjà traitée ou mauvaise personne : refus.
- Un membre de A ne peut gérer B ; aucun accès privé entre hackathons.
- Capitaine toujours membre ; transfert/départ et annulation cohérents avec les rôles.
- Pas de modification après gel ni dans une archive ; historique conservé.
- Contraintes de base et intégration accounts/M1 testées, puis parcours navigateur
  et vérification ciblée FR/EN, clavier, mobile et clair/sombre.
- Utiliser seulement test_hackflow_db pour les tests ; ne pas réécrire les migrations existantes.

## Exemple de recette

Ahmed et Mariem s’inscrivent à AI Challenge. Ahmed crée Nova : l’équipe commence
avec un membre. Il déclare un besoin UI/UX. Mariem trouve Nova et candidate ;
Ahmed accepte. L’effectif atteint le minimum configuré, Team Skills affiche leurs
compétences complémentaires. M3 pourra créer le projet de cette équipe et M4
permettra à ses membres autorisés de demander une aide, selon leurs contrats.

Les règles d’admission, de gel et de transfert ci-dessus sont maintenant appliquées.
Toute évolution décidée par le groupe devra modifier les services et leurs tests.
