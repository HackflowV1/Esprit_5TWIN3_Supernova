# M4 — assistance, mentorat et ateliers

## En une phrase

Une équipe bloquée demande de l'aide, un membre de l'équipe réserve un mentor, le mentor anime la séance et écrit
un compte rendu, l'équipe dit si le problème est résolu. À côté, des ateliers animés par des mentors.
Le menu principal n'a qu'une entrée, **Mentorat**, qui ouvre directement la page de votre rôle (équipe : Assistance ;
mentor : Mes rendez-vous ; sinon : Ateliers). Il n'y a pas de page d'ensemble. Les onglets du module n'affichent que
ce qui vous concerne : Assistance (équipe ou organisateur) · Mes rendez-vous · Ateliers · (mentor) Mes expertises · Mes créneaux.
Les longues listes sont paginées. Chaque demande affiche un fil en 4 étapes (Demande ouverte → Rendez-vous réservé →
Séance terminée → Problème résolu) avec l'étape en cours ; les couleurs sont toujours doublées d'un texte.

## Qui fait quoi

| Rôle | Ce qu'il fait |
|---|---|
| **Membre d'une équipe** (capitaine ou non, tous les mêmes droits) | Ouvre ou annule une demande d'aide (même si l'équipe est incomplète), réserve ou annule le rendez-vous, donne son retour après la séance. |
| **Mentor** | Déclare ses expertises, publie ses créneaux, **publie, modifie et annule ses propres ateliers**, écrit le compte rendu, peut annuler un rendez-vous avant son début. |
| **Organisateur** | Peut aussi publier ou gérer un atelier pour n'importe quel mentor de l'édition, suit les blocages critiques et les compétences redemandées, peut intervenir sur une réservation (l'action est tracée). |
| **Participant** | S'inscrit individuellement aux ateliers (inscription M2 acceptée requise). |

## Le parcours d'aide

1. **Demander de l'aide** : sujet, description, compétence, priorité. Possible pendant la phase de développement.
2. **Réserver un mentor** (n'importe quel membre) : la liste montre les vrais créneaux libres, par jour, avec les expertises
   déclarées. Le filtre par compétence restreint la liste, il ne classe pas les mentors. La réservation est
   confirmée tout de suite.
3. **Séance** : après son début, le mentor la termine en écrivant le compte rendu (visible par l'équipe) ;
   ses notes privées ne sont visibles que de lui et des organisateurs.
4. **Retour** : un membre note la séance et confirme si le problème est résolu. Si non, la demande est
   rouverte et l'équipe peut réserver un nouveau rendez-vous ; la séance précédente reste dans l'historique.

Statuts d'une demande : Ouverte → Rendez-vous réservé → Accompagnement en cours → Résolue
(ou Annulée tant qu'elle est ouverte). Statuts d'une séance : Réservée → Terminée, ou Annulée.

## Règles à connaître

- Une demande n'a qu'une réservation active ; un créneau n'accueille qu'une séance active (aussi garanti en base).
- Annulation d'un rendez-vous : possible avant son début, par un membre de l'équipe, le mentor ou un organisateur ;
  le créneau est libéré, la demande rouverte, la séance annulée est conservée.
- Une équipe n'a pas deux rendez-vous en même temps ; un mentor n'accompagne pas sa propre équipe ni pendant
  un atelier qu'il anime ; deux créneaux d'un même mentor ne se chevauchent jamais, même entre éditions.
- Créneaux et ateliers se situent pendant la phase de développement ; plus de réservation après la phase
  ni dans une édition archivée (consultation seulement).
- Confidentialité : une demande n'est visible que par son équipe active, le mentor de sa séance et les
  organisateurs. Un ancien membre perd l'accès, les demandes de l'équipe restent conservées.
- Atelier : capacité garantie même à plusieurs inscriptions simultanées ; pas de chevauchement avec un autre
  atelier ni avec un rendez-vous de l'équipe ; l'horaire d'un atelier qui a des inscrits est figé ;
  annuler un atelier libère toutes les places ; la présence se relève à partir du début, par le formateur
  ou un organisateur.

## Données de démonstration

```powershell
uv run python manage.py migrate
uv run python manage.py seed_demo
uv run python manage.py seed_m4_demo --user VOTRE_COMPTE
```

Mot de passe commun des comptes de démonstration : celui annoncé par `seed_demo`.
`ahmed` (capitaine de Nova) a un rendez-vous réservé et une séance terminée qui attend son retour ;
`sami` (capitaine d'Horizon) a des demandes ouvertes à réserver ; `mentor.django` et `mentor.front` ont des
rendez-vous ; l'organisatrice voit le pilotage ; « Atelier UI/UX en 1 heure » est complet.

## Hors périmètre de cette livraison

La suggestion de mentors par le moteur commun `intelligence/` et l'envoi des blocages M4 vers la Control
Tower de M1 ne sont pas livrés : le choix du mentor est manuel, et les indicateurs M4 sont visibles dans
la page Assistance de l'organisateur.
