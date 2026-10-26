# M2 — participer et construire son équipe

## Le parcours simple

1. Ouvrir un hackathon et cliquer **Trouver une équipe**. On peut consulter les
   idées, besoins et places avant de s’inscrire, puis choisir **Candidater**.
2. Se connecter ou créer un compte, lire le règlement et les conditions, les
   accepter, puis confirmer. Le choix de l’équipe est conservé pendant ce parcours.
3. L’inscription est acceptée immédiatement si la période est ouverte, qu’il
   reste une place et que le compte n’a pas le rôle juré dans cette édition.
4. Après confirmation, retrouver la candidature à l’équipe choisie et envoyer
   son message. Consulter une équipe ou s’inscrire ne crée jamais une candidature.
   On peut aussi s’inscrire directement puis créer sa propre équipe.
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
- **Suggérer des besoins depuis notre idée** : décrire le travail prévu, examiner
  les suggestions, cocher celles à garder et choisir niveau/priorité. Les mentions
  explicites et les suggestions du modèle sont distinguées. Les besoins existants
  ne sont pas écrasés et aucune écriture n’a lieu avant confirmation. Voir
  `docs/M2_SKILL_SUGGESTIONS.md` pour le modèle entraîné et ses limites.
- Les besoins couverts affichent les membres qui atteignent le niveau demandé.
  Le besoin reste enregistré : un départ peut le rendre à nouveau non couvert.
- **Trouver des coéquipiers** : participants acceptés et sans équipe, classés
  selon les besoins non couverts. Chaque correspondance explique la compétence
  et le niveau. Un petit modèle anglais local complète les compétences déclarées
  avec le contexte des biographies et centres d’intérêt : les besoins essentiels
  passent avant la similarité du texte. L’IA n’invente aucun niveau, ne recrute
  personne et n’affiche pas de faux pourcentage. On peut toujours inviter manuellement.
  Sans besoin manquant, l’annuaire reste consultable sans classement personnalisé.
  **Compétences seules / Compétences + projet** permet de voir l’effet du contexte
  sur les mêmes profils. Une progression de position n’apparaît que si elle est réelle.
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
- Les idées d’équipes, besoins et places sont consultables publiquement dans les
  éditions visibles. Les identités et compétences des membres restent réservées
  aux inscrits acceptés de la même édition et à ses organisateurs. Aucun email/contact privé
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

Pour une présentation avec **Sami → AI Challenge → Horizon**, voir
`docs/M2_SAMI_DEMO.md` : cinq profils fictifs réalistes, même niveau pour quatre
d’entre eux et comparaison visible dans le parcours normal de l’application.

```powershell
uv run --locked python manage.py migrate
uv run --locked python manage.py seed_demo
# Ou, si les comptes et événements de démo existent déjà :
uv run --locked python manage.py seed_m2_demo
# Nouveau terrain de test indépendant : 28 participants, six équipes
uv run --locked python manage.py seed_m2_matching_demo
# Préparer une fois le modèle local et mettre les suggestions en cache
uv run --locked python manage.py prepare_m2_matching
```

Ces commandes sont destinées au développement. Elles ne déplacent pas les dates
d’un événement existant et ne contournent pas les périodes fermées.

Dans **AI Challenge 2026** : Ahmed dirige **Nova**, cherche UI/UX et React,
et reçoit une candidature de Mariem. Sami dirige **Horizon**, cherche Mobile
et invite Ines. Les actions de démonstration peuvent déjà avoir fait évoluer
ces états ; relancer la commande ne réinitialise pas le travail existant.

Les comptes `ahmed`, `mariem`, `sami`, `ines` utilisent le mot de passe de démo
annoncé par `seed_demo`. Aucun compte ni mot de passe existant n’est remplacé.

Dans **Team Lab · Trouvez vos coéquipiers** (`/participation/m2-team-lab/teams/`),
`m2.demo.01` dirige Passerelle ; `m2.demo.13` est une candidate encore disponible.
Mot de passe des nouveaux comptes : `Demo-Team#2026`. Chaque compte est fictif.
Le seed conserve les modifications, mots de passe et annulations existants.
Les dates sont fixées à la création, jamais déplacées lors d’une relance.

Le téléchargement du modèle se fait uniquement par commande explicite.
Si le cache d’un profil change, le recalcul s’effectue en arrière-plan : le classement
par compétences reste disponible et un lien permet d’actualiser. Sans modèle,
l’application fonctionne aussi. Voir `docs/M2_MATCHING.md` pour les mesures et l’évaluation humaine.

Les pages réutilisent les thèmes, palettes d’accessibilité, champs et menus
communs, les icônes Hugeicons, le fil d’Ariane et les traductions FR/EN.
