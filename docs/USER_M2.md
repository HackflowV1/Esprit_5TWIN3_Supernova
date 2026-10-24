# M2 — participer et construire son équipe

## Le parcours simple

1. Ouvrir un hackathon et cliquer **M’inscrire au hackathon**.
2. Lire le règlement et les conditions, les accepter, puis confirmer.
3. L’inscription est acceptée immédiatement si la période est ouverte, qu’il
   reste une place et que le compte n’a pas le rôle juré dans cette édition.
4. La page **Les équipes** propose deux chemins : créer son équipe ou candidater
   auprès d’une équipe qui recrute.
5. Le créateur devient capitaine et premier membre. Il présente l’idée,
   déclare les compétences recherchées, invite des participants et traite
   les candidatures sur la fiche de l’équipe.
6. Chaque participant retrouve ses invitations et candidatures dans une seule
   boîte. Une acceptation confirme sa place et annule ses autres demandes en
   attente dans le même hackathon.
7. **Mon équipe** apparaît dans la navigation de l’édition. L’équipe est prête
   dès que le minimum de membres fixé par M1 est atteint ; les compétences ne
   bloquent pas cette condition de taille.

**Mes inscriptions**, dans la navbar et le menu du compte, rassemble les éditions
auxquelles on s’est réellement inscrit. Un rôle attribué manuellement ne crée
pas automatiquement une inscription.

## Pour le capitaine

- **Modifier** : présentation, nom et ouverture du recrutement.
- **Les talents recherchés** : ajouter, modifier ou retirer une compétence,
  son niveau souhaité (1 à 5) et sa priorité. Les compétences personnelles
  restent gérées par leur propriétaire dans le profil.
- Les besoins couverts affichent les membres qui atteignent le niveau demandé.
  Le besoin reste enregistré : un départ peut le rendre à nouveau non couvert.
- **Trouver des coéquipiers** : participants acceptés et sans équipe, classés
  selon les besoins non couverts. Chaque correspondance explique la compétence
  et le niveau. Il s’agit de règles, pas d’un modèle IA ou d’un pourcentage de
  compatibilité. On peut toujours inviter manuellement.
- **Nommer capitaine**, **Retirer** et **Quitter l’équipe** : confirmations avant
  mutation. Le capitaine doit transférer son rôle avant de partir si d’autres
  membres restent. Le dernier départ ferme l’équipe et conserve son historique.

Une invitation expire après 7 jours, ou à la fin de la formation des équipes si
celle-ci arrive avant. Elle ne réserve aucune place. Une acceptation vérifie à
nouveau toutes les conditions, y compris la dernière place disponible.

## Les règles retenues

- Une inscription et une seule équipe active par personne et par hackathon.
- Les inscriptions suivent la phase **REGISTRATION** et les dates M1.
- Création, recrutement, départ, exclusion, besoins et transfert du capitaine
  sont autorisés uniquement pendant **TEAM_FORMATION**.
- L’annulation d’inscription est possible pendant les inscriptions ou la
  formation, mais jamais après la fin de formation. Quitter l’équipe d’abord.
- Après le gel ou dans une archive : consultation, aucune mutation M2.
- L’annulation retire le rôle participant de cette édition ; elle conserve les
  autres rôles. Le rôle participant d’un inscrit accepté ne peut pas être
  retiré directement depuis M1 : passer par l’annulation M2.
- Les équipes et compétences des participants ne sont visibles qu’aux inscrits
  acceptés de la même édition et à ses organisateurs. Aucun email/contact privé
  dans les annuaires. Les candidatures/messages sont réservés à leur auteur,
  au capitaine concerné et aux organisateurs.

## Pour l’organisateur

Depuis le pilotage ou la fiche du hackathon : **Inscriptions et équipes**.
Cette page donne les inscriptions réelles, les équipes et les accès de gestion.
Elle permet l’annulation d’une inscription en respectant les mêmes règles.

La Control Tower reçoit les compteurs M2 : inscrits acceptés, équipes,
équipes incomplètes et participants sans équipe. Les archives utilisent leurs
compteurs enregistrés ; une ancienne archive sans M2 indique leur absence.

L’admin Django permet d’inspecter les données, chercher et filtrer. Les fiches
M2 sont en lecture seule pour éviter de contourner les règles. L’action
d’annulation des inscriptions utilise les mêmes services ; la gestion d’une
équipe renvoie vers son espace métier.

## Démonstration locale

```powershell
uv run --locked python manage.py migrate
uv run --locked python manage.py seed_demo
# Ou, si les comptes et événements de démo existent déjà :
uv run --locked python manage.py seed_m2_demo
```

Ces commandes sont destinées au développement. Elles ne déplacent pas les dates
d’un événement existant et ne contournent pas les périodes fermées.

Dans **AI Challenge 2026** : Ahmed dirige **Nova**, cherche UI/UX et React,
et reçoit une candidature de Mariem. Sami dirige **Horizon**, cherche Mobile
et invite Ines. Les actions de démonstration peuvent déjà avoir fait évoluer
ces états ; relancer la commande ne réinitialise pas le travail existant.

Les comptes `ahmed`, `mariem`, `sami`, `ines` utilisent le mot de passe de démo
annoncé par `seed_demo`. Aucun compte ni mot de passe existant n’est remplacé.

Les pages réutilisent les thèmes, palettes d’accessibilité, champs et menus
communs, les icônes Hugeicons, le fil d’Ariane et les traductions FR/EN.
