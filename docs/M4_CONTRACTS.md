# M4 — contrats

## Propriété des données

`mentoring` possède : `MentorExpertise`, `MentorSlot`, `SupportRequest`, `MentoringSession`, `Workshop`,
`WorkshopRegistration`, `M4History`. Il lit sans les copier : `accounts` (User, Skill, rôles), `hackathons`
(événement, phases, `phase_is_open`, `require_organizer`) et `teams` (inscription acceptée, équipe active,
membres, capitaine). Aucun rôle ni compétence n'est dupliqué : `MentorExpertise` dit ce qu'une personne
accepte de *mentorer*, `UserSkill` ce qu'elle *sait*.

## Modèle

- `MentorSlot` : disponibilité **calculée** (`availability` : AVAILABLE / BOOKED / WITHDRAWN) depuis la séance
  active ; le retrait est `withdrawn_at`. Entre 15 minutes et 2 heures, dans la phase DEVELOPMENT.
- `SupportRequest` : OPEN → BOOKED → IN_PROGRESS → RESOLVED, ou CANCELLED. Équipe et hackathon cohérents.
- `MentoringSession` : l'équipe (`request.team`) et le mentor (`slot.mentor`) sont **déduits**. Compte rendu
  partagé, notes privées, retour séparé du statut. Index uniques partiels : une séance BOOKED par créneau
  et par demande.
- `Workshop` : formateur = mentor actif de l'édition, DEVELOPMENT, capacité jamais inférieure aux inscrits.
- `WorkshopRegistration` : liée à `teams.Registration` ; une ligne par participant et atelier, réutilisée
  après annulation. `M4History` : auteur, action (code stable), objet, détails.

## Services (écritures uniquement par `mentoring.services`)

| Fonction | Qui | Règles principales |
|---|---|---|
| `create_slot`, `update_slot`, `cancel_slot` | mentor | rôle actif, édition ouverte, futur, pas de chevauchement ; seul un créneau libre se modifie |
| `open_request`, `cancel_request` | membre actif / auteur, capitaine, organisateur | phase de développement ; seule une demande OPEN s'annule |
| `book_session` | capitaine (ou organisateur, tracé) | demande OPEN, créneau libre et futur, mentor actif et hors équipe, pas de conflit équipe/atelier |
| `cancel_session` | capitaine, mentor, organisateur | avant le début ; libère le créneau, rouvre la demande |
| `complete_session`, `update_report` | mentor de la séance | après le début ; compte rendu obligatoire |
| `give_feedback` | membre actif de l'équipe | séance terminée ; une seule fois ; note 1–5 ; résolu ou rouverte |
| `create_workshop`, `update_workshop`, `cancel_workshop` | formateur lui-même, ou organisateur | formateur mentor de l'édition (un mentor ne peut pas confier l'atelier à un collègue) ; annulation libère les places |
| `register_to_workshop`, `cancel_workshop_registration` | participant inscrit | capacité sous verrou, conflits, avant le début |
| `mark_attendance` | formateur ou organisateur | à partir du début |

Lectures publiques : `visible_requests`, `visible_sessions`, `visible_workshops`, `bookable_slots`,
`requestable_teams`, `support_insights`, `can_book`, `can_cancel_*`, `can_give_feedback`.

## Concurrence

Ordre des verrous, commun à `accounts.set_role` et `teams.services` : utilisateurs concernés triés par
identifiant, puis événement, puis ressources (demande, créneau, séance, atelier). Le verrou du mentor
protège ses créneaux et ses réservations entre éditions. Les contraintes uniques partielles restent la
dernière défense. Tests PostgreSQL à connexions indépendantes : deux équipes sur un créneau, deux
participants sur la dernière place, deux créneaux ou ateliers qui se chevauchent.

## Confidentialité

Les requêtes `visible_*` filtrent en base : un objet invisible renvoie 404. L'ancien membre perd l'accès.
Le mentor ne voit que les demandes de ses séances ; l'organisateur celles de ses éditions.
Les notes privées ne s'affichent qu'au mentor et aux organisateurs.

## Non livré

La suggestion de mentors par le moteur commun et les alertes M4 dans la Control Tower de M1 : le contrat
d'indicateurs M1 parcourt M2/M3/M5, ajouter une clé M4 aux réglages ne suffit pas ; cette extension reste
à décider avec le responsable M1.
