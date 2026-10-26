# Démonstration M1 — assistant de rédaction de challenge

Durée visée : 3 à 5 minutes. Contribution présentée : uniquement l’assistant Gemini
du formulaire **Ajouter un challenge**, pas les assistants des autres modules.

## Préparer l’environnement

Depuis PowerShell :

```powershell
Set-Location D:\DJANGO
uv run python manage.py check_database
uv run python manage.py runserver
```

Ouvrir <http://127.0.0.1:8000/accounts/login/> et utiliser son compte organisateur.
Il faut une affectation ORGANIZER active dans une édition non archivée, un track
actif, JavaScript et une clé Gemini configurée uniquement sur le serveur.
Ne jamais afficher `.env` pendant la présentation.

Une édition locale disponible lors de la préparation est `recette-m1`, avec le
track **Innovation durable**. Vérifier que son compte peut toujours la gérer.
Le compte local `recette_m1` possède un rôle organisateur actif ; utiliser son mot
de passe existant, sans le réinitialiser pour la démonstration.
Le chemin complet est : **Hackathons → édition → Pilotage → Ajouter un challenge**.

- Pilotage : <http://127.0.0.1:8000/hackathons/recette-m1/manage/>
- Formulaire : <http://127.0.0.1:8000/hackathons/recette-m1/challenge/add/>
- Pour une autre édition, remplacer `recette-m1` par son slug.

Garder le pilotage ouvert dans un deuxième onglet. Noter le nombre de challenges
avant la génération ; ne pas utiliser de filtre qui masquerait les brouillons.
Éviter de multiplier les répétitions juste avant le passage : dix demandes par
utilisateur et par fenêtre horaire sont autorisées, y compris les échecs.

## Données à saisir

| Champ | Valeur de démonstration |
| --- | --- |
| Track | Innovation durable |
| Idée ou thème | Concevoir un outil web simple pour signaler les petites fuites d’eau sur le campus, suivre leur traitement et sensibiliser les étudiants aux économies d’eau, sans dépendre de capteurs réels. |
| Public visé | Étudiants débutants en développement web |
| Durée envisagée | 48 heures |
| Titre, avant l’appel IA | Mon idée de campus économe |
| Problématique, avant l’appel IA | Les petites fuites d’eau sont signalées trop tard sur le campus. |
| Objectifs et livrables | Laisser vides pour observer leur remplissage |

La durée est une indication rédactionnelle : elle ne change aucune date du hackathon.

## Séquence et discours

### 0:00–0:40 — Présenter le besoin

Depuis le pilotage, cliquer sur **Ajouter un challenge**, puis sélectionner le track.

> « Ma contribution aide l’organisateur à transformer une idée courte en consignes
> de challenge structurées. Elle réutilise le formulaire et le workflow M1 existants. »

### 0:40–1:20 — Donner le contexte

Saisir les données du tableau, notamment le titre et la problématique personnels.
Cliquer sur **M'aider à rédiger avec l'IA**. Attendre le résultat sans recliquer.

> « Django vérifie mes droits et le track avant d’appeler Gemini. L’idée, le public
> et la durée servent de contexte. La clé API ne part jamais dans le navigateur. »

### 1:20–2:15 — Montrer les quatre propositions

Montrer le titre et la problématique proposés dans l’aperçu, puis les objectifs et
les livrables remplis dans les champs initialement vides. Le texte exact varie.

> « Gemini renvoie un JSON contenant exactement quatre textes. Le serveur vérifie
> les champs obligatoires, leurs types et leurs longueurs avant de les transmettre
> au formulaire. La validation du format ne garantit pas la justesse du contenu. »

### 2:15–2:55 — Montrer la confirmation sélective

Constater que le titre et la problématique déjà saisis sont toujours présents.
Cocher **Titre** uniquement, puis cliquer sur **Confirmer les remplacements sélectionnés**.
Montrer le nouveau titre et la problématique personnelle conservée. Modifier un
objectif à la main pour montrer que les textes restent entièrement éditables.

> « Aucun texte personnel n’est remplacé sans mon accord. Je peux accepter un seul
> champ et garder les autres. Si je modifie un champ après l’avoir sélectionné,
> son autorisation de remplacement est retirée. »

### 2:55–3:25 — Prouver l’absence d’enregistrement automatique

Passer au deuxième onglet et actualiser le pilotage. Le nombre de challenges n’a
pas augmenté ; aucun nouveau challenge ne correspond à cette génération. Revenir
au formulaire sans le recharger, pour conserver les propositions en cours.

> « Même après avoir appliqué les propositions, aucun brouillon n’existe en base.
> La génération et la confirmation ne modifient que les champs de ce formulaire. »

### 3:25–4:00 — Enregistrer normalement

Cliquer sur **Enregistrer**. Le pilotage affiche le message
**Challenge enregistré ; validation requise.** et le nouveau challenge **Brouillon**.
Ne pas cliquer sur les actions de validation ou de publication.

> « Seul ce clic utilise le service métier existant et enregistre le brouillon avec
> son historique. L’IA ne peut ni approuver ni publier le challenge. »

### 4:00–4:30 — Expliquer l’architecture

> « Le navigateur envoie une demande POST protégée par CSRF. Django contrôle
> l’organisateur et le track, limite les appels, puis contacte Gemini côté serveur.
> Le JSON est validé, les textes reviennent au formulaire, et l’humain confirme.
> L’enregistrement final reste une opération M1 distincte. »

**Django → Gemini → JSON validé → formulaire → confirmation humaine → brouillon M1**.

## Cinq questions probables

1. **Où se trouve la clé API ?** Dans `.env`, ignoré par Git, puis dans les settings
   Django. Elle n’est jamais intégrée au HTML ou au JavaScript.
2. **Pourquoi demander un JSON ?** Pour obtenir quatre champs exploitables et
   vérifier leur structure : titre de 1 à 200 caractères et trois textes de 1 à
   4 000 caractères. Une réponse invalide est refusée sans écriture métier.
3. **Peut-on utiliser le track d’une autre édition ?** Non : le serveur exige un
   organisateur actif de l’édition et sélectionne le track parmi ses tracks actifs.
   Les éditions archivées sont refusées ; le POST exige aussi CSRF.
4. **L’IA peut-elle publier ou écraser mes données ?** Non : seules quatre valeurs
   textuelles sont acceptées. Les champs renseignés demandent confirmation et le
   service d’enregistrement impose un brouillon non approuvé.
5. **Que se passe-t-il si Gemini ne répond pas ?** L’appel HTTP a un timeout de
   20 secondes, le navigateur abandonne l’attente après 25 secondes, et le
   formulaire reste utilisable manuellement. Les échecs comptent dans la limite
   de dix demandes par utilisateur et par fenêtre horaire.

## Trois points forts

- Contrôle humain : remplacement sélectif et enregistrement explicitement séparé.
- Intégration M1 : permissions, formulaire, historique et brouillon existants,
  sans nouveau modèle ni migration.
- Robustesse démontrable : JSON strict, erreurs sans perte de saisie, timeout,
  quota, traductions FR/EN et tests avec Gemini simulé.

## Limites à annoncer honnêtement

- Gemini peut être indisponible, limité par son quota ou proposer un contenu
  inexact. L’organisateur doit relire ; aucune qualité pédagogique n’est certifiée.
- La rédaction utilise le premier modèle configuré, sans basculement automatique.
- Le quota repose sur le cache local du processus ; plusieurs processus doivent
  utiliser un cache partagé pour disposer d’une limite commune.
- L’assistant est réservé à l’ajout par un organisateur. Il ne modifie pas les
  formulaires sponsor ou d’édition d’un challenge existant.
- Les propositions non enregistrées restent dans le formulaire courant : recharger
  ou quitter la page les perd. Le formulaire manuel fonctionne sans JavaScript.
