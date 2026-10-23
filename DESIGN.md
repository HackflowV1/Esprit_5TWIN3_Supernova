# Design commun de HackFlow

Ce guide sert aux cinq membres du groupe. Chaque nouveau module réutilise les mêmes
composants : on ne recrée pas sa propre navbar, ses boutons ou son thème.

## L’esprit du design

Une interface calme, lisible et simple, inspirée de Notion et d’Apple : palette Signal orange & mist, typographie système, peu d’effets et des actions
faciles à comprendre. Les surfaces sont gris clair froid, les actions principales
orange profond et les illustrations conservent leurs traits noirs avec des accents orange.
La page d’accueil peut être plus visuelle ; les écrans de travail restent sobres.
Références : [Taste Skill](https://www.tasteskill.dev/) et
[Hugeicons](https://hugeicons.com/).

Éviter les dégradés décoratifs, les halos, les cartes multicolores et les compteurs
inventés. Une fonctionnalité à venir doit être annoncée clairement. Un module non
connecté affiche « indisponible », pas un faux zéro.

## Les fichiers à réutiliser

L’administration Django utilise `templates/admin/` et `static/css/admin.css` pour
garder les mêmes couleurs, contrôles et icônes. Son thème partage la préférence
`hackflow-theme` avec l’application. La connexion utilise une illustration dédiée :
`static/images/hackflow-admin-orange.webp`. Garder les formulaires, permissions,
filtres et protections CSRF de Django ; personnaliser leur présentation.

Les deux navbars réutilisent `shared/nav_language.html`, `shared/nav_account.html`
et `static/css/nav-menus.css`. Le globe ouvre directement les langues ; cliquer
une langue l’applique immédiatement. L’apparence reste dans le menu du compte
(ou le menu Préférences avant connexion). Ne pas dupliquer le choix de langue
dans le profil.

| Besoin | Fichier |
| --- | --- |
| Structure, navbar, compte, préférences, footer | `templates/base.html` |
| Couleurs, tailles, composants, responsive | `static/css/base.css` |
| Accueil public uniquement | `templates/core/home.html`, `static/css/landing.css` |
| Choix du thème avant l’affichage | `static/js/theme.js` |
| Menus, onglets, erreurs, interactions | `static/js/base.js` |
| Fil d’Ariane | `templates/shared/breadcrumbs.html` |
| Champ accessible et résumé des erreurs | `shared/field.html`, `shared/form_errors.html` |
| Icônes et rendu des champs | `core/templatetags/ui.py` |
| Traduction anglaise | `locale/en/LC_MESSAGES/django.po` et `.mo` |

## Couleurs et dimensions

La source commune est `static/css/palette.css`, chargée par l’application et
l’administration. `base.css` et `admin.css` adaptent ses tokens à leurs composants.
Clair : fond `#F7F8FA`, surfaces blanches, texte `#242729`, action `#C94B16`
avec texte blanc, fond secondaire orange `#FFF0E8`. Sombre : fond `#18191B`,
surfaces `#202225`, texte `#F1F2F3`, action `#FFAB78` avec texte foncé.
L’orange accompagne une action importante, un lien ou un focus ; les titres restent
en couleur de texte. Les états erreur/succès conservent leurs couleurs sémantiques.
Ne pas employer les teintes d’illustration, plus vives, pour du petit texte.

Toujours utiliser les variables CSS. Les mêmes noms fonctionnent dans les deux thèmes.

| Variable | Utilisation |
| --- | --- |
| `--bg`, `--surface`, `--raised` | Page, panneau, zone secondaire |
| `--ink`, `--muted` | Texte principal, texte secondaire |
| `--line` | Séparation discrète entre contenus |
| `--control` | Contour visible des champs et contrôles |
| `--primary`, `--on-primary` | Action principale et son texte |
| `--danger`, `--success`, `--warning` | États qui ont un sens métier |
| `--focus` | Contour du focus clavier |

Contenu : 1120 px maximum. Espacements courants : 8, 12, 16, 24, 32 et 48 px.
Angles : 6 px pour les contrôles, 8 px pour les panneaux. Corps de texte : 15–16 px ;
titres d’écran : environ 30 px. L’accueil utilise des titres plus grands.
Les boutons et champs ont une hauteur minimale de 44 px.

## Une nouvelle page

```django
{% extends 'base.html' %}
{% load i18n ui %}
{% block title %}{% translate 'Mes équipes' %} — HackFlow{% endblock %}
{% block content %}
<header class="page-head">
  <h1>{% translate 'Mes équipes' %}</h1>
</header>
<section class="panel" aria-labelledby="teams-title">
  <h2 id="teams-title">{% translate 'Équipes de cette édition' %}</h2>
  <!-- Contenu réel du module -->
</section>
{% endblock %}
```

Ajouter les titres et parents des nouvelles routes dans
`core/context_processors.py` et `shared/breadcrumbs.html`. Le dernier élément du
fil d’Ariane indique la page actuelle. Garder un seul `h1` et des titres dans l’ordre.

## Boutons, CRUD et icônes

Une action principale par zone ; `secondary` pour les autres ; `danger` pour une
action destructive. Garder un texte visible avec l’icône.

```django
<a class="button secondary" href="...">{% icon 'edit' %}{% translate 'Modifier' %}</a>
<button type="submit" class="danger">{% icon 'delete' %}{% translate 'Supprimer' %}</button>
```

Icônes disponibles : `add`, `edit`, `delete`, `view`, `search`, `save`, `close`,
`check`, `arrow-right`, `arrow-left`, `chevron-down`, `chevron-right`, `home`,
`calendar`, `users`, `user`, `logout`, `settings`, `globe`, `sun`, `moon`,
`monitor`, `menu`, `code`, `dashboard`, `clock`, `archive`, `help`, `shield`,
`link`, `filter`, `compare`, `history`, `upload`, `building`, `award`.

Elles viennent de **Hugeicons Core Free 4.3.5**, sous licence MIT conservée dans
`static/icons/LICENSE-hugeicons.md`. Le sprite SVG est local : aucun CDN requis.
Pour une icône seule, donner au bouton un `aria-label` traduit et précis.
Pour plusieurs lignes, préciser l’objet : « Modifier l’équipe Alpha ».
Les icônes décoratives sont cachées aux lecteurs d’écran par le helper.

## Formulaires et listes déroulantes

```django
<form method="post" novalidate>
  {% csrf_token %}
  {% include 'shared/form_errors.html' %}
  {% for field in form %}{% render_field field %}{% endfor %}
  <button type="submit">{% icon 'save' %}{% translate 'Enregistrer' %}</button>
</form>
```

Le helper associe label, aide et erreur au champ. Le résumé reçoit le focus après
un envoi invalide. Garder la validation et les autorisations côté serveur.
Le lien « Annuler » utilise une URL Django explicite ; éviter `history.back()`.

Utiliser de vrais `<select>`. Les navigateurs compatibles affichent notre popup
avec `appearance: base-select` ; les autres gardent leur sélecteur natif avec les
couleurs du thème. Conserver les raccourcis clavier et les choix multiples natifs.
Ne pas remplacer une liste par un simple `<div>` cliquable.

## Français, anglais et thèmes

Le français est la langue de départ, même si le navigateur est en anglais. Le menu
du globe permet de choisir directement l’anglais ; Django conserve ce choix dans
le cookie `hackflow_language`. Les URL et les permissions restent identiques.

Dans les templates : `{% translate 'Texte français' %}`. Pour une phrase avec des
variables ou un pluriel, utiliser `blocktranslate`, sans couper la phrase en morceaux.
En Python : `gettext_lazy` pour les labels et `gettext` pour un message évalué dans
une fonction. Traduire les libellés, jamais les codes métier (`PUBLISHED`, `MENTOR`),
les titres de projets ou les textes écrits par les utilisateurs.

Après ajout ou modification de textes :

```powershell
uv run python manage.py makemessages -l en --ignore=.venv --ignore=.taste-skill --ignore=static --ignore=docs --no-obsolete --no-wrap
# Compléter et vérifier les msgstr du fichier .po.
uv run python scripts/compile_translations.py
```

L’extraction `makemessages` demande les outils GNU gettext. La compilation du projet
utilise `polib` via `uv`, donc ne demande pas `msgfmt` sur les postes des collègues.
Versionner `.po` **et** `.mo` : les traductions sont alors utilisables dès le clone.

Les thèmes clair, sombre et système utilisent les mêmes variables. Le choix est
enregistré dans `localStorage['hackflow-theme']`. Ne pas coder le thème page par page.
L’administration et le site réutilisent le même sélecteur dans le menu du compte.

## Accessibilité et vérification rapide

- Contraste du texte courant : au moins 4,5:1 ; contrôles et focus : au moins 3:1.
- Ne jamais donner une information uniquement par une couleur ou une icône.
- Parcours au clavier : Tab, Maj+Tab, Entrée, Espace et Échap pour fermer un menu.
- Menus du compte et préférences : `details/summary`, utilisables sans JavaScript.
- Onglets du pilotage : flèches, Début et Fin ; sections visibles sans JavaScript.
- Labels visibles, aides associées, erreurs précises et un état vide utile.
- Images informatives : texte alternatif ; images décoratives : `alt=""`.
- Respecter `prefers-reduced-motion`, le zoom et le mode de couleurs forcées.
- Vérifier mobile, tablette et bureau dans les deux langues et les deux thèmes.

Le hero présente le texte à gauche et une illustration à droite. Sur téléphone,
le texte précède l’image. Garder le texte dans le HTML, jamais dans une image.
Les visuels sont des illustrations éditoriales au trait avec des accents orange.
Utiliser la classe `ink-illustration` : aucun filtre de couleur. Sur le thème sombre, un fond papier gris clair permet
de conserver les traits noirs, les visages et les vêtements orange sans les inverser.
Aucun filtre ne doit être appliqué au texte ou aux contrôles.
Les fichiers `hackflow-hero-orange.webp`, `hackflow-project-orange.webp` et
`hackflow-admin-orange.webp` sont locaux, transparents et distincts. Les anciens
visuels restent conservés mais ne sont plus affichés.

Avant de partager une modification :

```powershell
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test --keepdb
```

Les tests utilisent uniquement `test_hackflow_db`. Un changement visuel ne doit pas
changer les règles des rôles, la logique des phases ou les données de `hackflow_db`.
