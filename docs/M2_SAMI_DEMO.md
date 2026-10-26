# Démonstration M2 avec Sami

## Préparer les données

Après installation des dépendances et migrations habituelles :

```powershell
uv run --locked python manage.py seed_demo
uv run --locked python manage.py seed_m2_sami_showcase --configure-team
uv run --locked python manage.py prepare_m2_matching
```

Le scénario est dans **AI Challenge 2026 → Horizon**, en base PostgreSQL normale.
Compte : `sami` ; mot de passe initial de `seed_demo` : `Demo-Hack#2026`.
Un mot de passe existant n’est jamais réinitialisé.

`--configure-team` configure explicitement l’idée de redistribution alimentaire et
le besoin essentiel **Data Science 4/5**. Sami a déjà 3/5 : un besoin à 3/5 serait
couvert par lui, donc ne constituerait pas une compétence manquante.
Les autres besoins, membres, invitations et candidatures sont conservés.
Les inscriptions et la constitution d’équipes doivent être ouvertes dans le calendrier M1.

Pour relancer uniquement le seed sans écraser une idée modifiée :

```powershell
uv run --locked python manage.py seed_m2_sami_showcase
```

Cinq comptes fictifs réalistes sont créés, inscrits à cette édition et laissés
sans équipe. Leurs profils existants, mots de passe et annulations sont préservés.
Les descriptions du référentiel de compétences ne sont remplies que si vides.
Les quatre premiers candidats ont exactement les mêmes compétences et niveaux ;
leurs biographies et centres d’intérêt diffèrent.

## Montrer au professeur

1. Se connecter comme Sami et ouvrir **AI Challenge → Mon équipe (Horizon) →
   Trouver des coéquipiers**. Laisser la recherche vide.
2. Cliquer **Compétences seules** : les quatre profils de même niveau sont
   équivalents et départagés par identifiant, sans modèle.
3. Cliquer **Compétences + projet** : mêmes participants, mêmes compétences,
   mêmes règles de couverture ; seule la similarité sémantique est ajoutée.
4. Montrer la progression calculée sur la carte de Yasmine, puis la biographie
   anglaise de Lina et le besoin français de l’équipe.
5. Montrer Nader : son idée est proche du projet, mais Data Science 2/5 ne remplace
   pas le niveau essentiel 4/5. L’IA n’invente pas une compétence.

Résultat observé sur la base locale le 26 octobre 2026 :

| Candidat | Contexte | Compétences seules | Avec le projet |
| --- | --- | --- | --- |
| Amine Ben Salah | Finance | 1 | 3 |
| Lina Trabelsi | Collecte de repas, profil en anglais | 2 | 2 |
| Omar Gharbi | Sport | 3 | 4 |
| Yasmine Kallel | Prévision des invendus et dons | 4 | 1 |

Les positions sont toujours calculées depuis les données actuelles. Aucun nom,
identifiant de candidat ou ordre attendu n’entre dans le code du classement.
Les invitations restent manuelles et ne réservent aucune place.

## Variante interactive

Modifier l’idée de l’équipe vers la prévision des rendements boursiers et le suivi
des portefeuilles financiers, puis rouvrir les suggestions. Actualiser si le contexte
se prépare en arrière-plan. Amine doit alors devenir plus pertinent pour cette idée.
Le test local de ce contexte a placé Amine premier ; l’idée réelle d’Horizon a été
conservée pendant cette vérification. Pour retrouver le scénario initial : relancer
le seed avec `--configure-team`, puis préparer le cache.

Ce scénario contrôlé démontre l’effet du modèle. La qualité générale des recommandations
se mesure séparément avec l’évaluation humaine de `docs/m2_human_review.csv`.

## Si le professeur souhaite voir le code

- `teams/matching.py` : textes d’entrée, vecteurs locaux MiniLM, cosinus et classement.
- `teams/services.py::recommendation_comparison` : mêmes candidats et besoins,
  comparaison avec/sans contexte, sans changer les règles sur les niveaux.
- `teams/views.py::candidates` : positions réellement comparées sur le même filtre,
  aucune progression affichée si le modèle est indisponible ou le classement inchangé.
- `seed_m2_sami_showcase` : données fictives normales, jamais de score prédéfini.

Vérifications : 43 tests M2 réussis ; contrôle Django et migrations sans changement
de schéma ; ordre réellement observé dans le navigateur avec Sami.
