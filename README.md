# Esprit_5TWIN3_Supernova

## HackFlow — Plateforme web de gestion des hackathons étudiants

Projet HackFlow développé dans le cadre du cours 5TWIN3 à ESPRIT.  
HackFlow est une plateforme web permettant la gestion complète des hackathons étudiants.

---

## Contexte général

Ce repository contient le socle technique du projet HackFlow, une application web Django destinée à la gestion des hackathons étudiants à ESPRIT. Le développement des modules fonctionnels interviendra dans les phases suivantes.

**État actuel : socle technique uniquement.** Aucune logique métier n'est présente.

---

## Stack technique

| Composant | Technologie | Version |
|-----------|-------------|---------|
| Backend | Python | 3.13+ |
| Framework | Django (MVT) | 5.2 |
| Base de données | SQLite | (développement local) |
| ORM | Django ORM | natif |
| Frontend | Django Templates + HTML/CSS/JS | natif |
| Authentification | Django Authentication + Admin | natif |
| Gestion dépendances | uv | 0.13+ |
| Variables d'environnement | python-dotenv | 1.0+ |
| IA (préparation) | Google Generative AI SDK | 0.8+ |

---

## Prérequis

- Python 3.11 ou supérieur
- [uv](https://docs.astral.sh/uv/) installé globalement
- Git

---

## Configuration

### 1. Cloner le repository

```bash
git clone https://github.com/HackflowV1/Esprit_5TWIN3_Supernova.git
cd Esprit_5TWIN3_Supernova
```

### 2. Créer l'environnement virtuel

```bash
uv venv .venv
```

### 3. Installer les dépendances

```bash
uv pip install -r pyproject.toml
```

Ou depuis le lock file :

```bash
uv sync
```

### 4. Configurer les variables d'environnement

```bash
cp .env.example .env
```

Éditer `.env` et renseigner les valeurs :

```env
DJANGO_SECRET_KEY=your-secret-key-here
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
GOOGLE_API_KEY=your-google-api-key-here
```

### 5. Appliquer les migrations

```bash
uv run python manage.py migrate
```

---

## Démarrage

```bash
uv run python manage.py runserver
```

L'application est accessible à : http://127.0.0.1:8000/  
Interface d'administration : http://127.0.0.1:8000/admin/

---

## Structure des dossiers

```
D:\DJANGO\
│
├── config/              # Configuration Django (settings, urls, wsgi, asgi)
├── core/                # App principale — page d'accueil technique
├── accounts/            # Infrastructure d'authentification — modèle User personnalisé
├── templates/           # Templates HTML Django
│   ├── base.html
│   └── core/
│       └── home.html
├── static/              # Fichiers statiques (CSS, JS, images)
│   ├── css/
│   ├── js/
│   └── images/
├── media/               # Fichiers uploadés (non versionnés)
├── .venv/               # Environnement virtuel Python (non versionné)
├── .env                 # Variables d'environnement locales (non versionné)
├── .env.example         # Template des variables d'environnement
├── .gitignore
├── manage.py
├── pyproject.toml       # Déclaration du projet et des dépendances
├── uv.lock              # Lock file reproductible
└── README.md
```

---

## Variables d'environnement

| Variable | Description | Obligatoire |
|----------|-------------|-------------|
| `DJANGO_SECRET_KEY` | Clé secrète Django | Oui |
| `DJANGO_DEBUG` | Mode debug (`True`/`False`) | Oui |
| `DJANGO_ALLOWED_HOSTS` | Hôtes autorisés (séparés par virgule) | Oui |
| `GOOGLE_API_KEY` | Clé API Google Gemini (intégration future) | Non |

---

## Vérification Django

```bash
uv run python manage.py check
uv run python manage.py showmigrations
```

---

## État actuel

✅ Socle technique Django 5.2 initialisé  
✅ Modèle User personnalisé (`accounts.User`)  
✅ Authentification et Admin Django configurés  
✅ SQLite configuré  
✅ Templates et fichiers statiques configurés  
✅ Variables d'environnement préparées (dont IA)  
⏳ Modules métier HackFlow — à développer dans les phases suivantes
