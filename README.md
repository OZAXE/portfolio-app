# Portfolio Insights

Appli perso de suivi et d'analyse d'actions, installable sur téléphone, dans l'esprit de Baggr et Mungr :
suivi du portefeuille à partir d'un Google Sheet, screener d'environ 2 000 actions (Europe, US, Asie)
avec score qualité et valeur intrinsèque, dividendes, comptes annuels, super investisseurs,
watchlist, alertes et briefs marchés hebdomadaires.

- Appli : https://portfolio-front-8t6m.onrender.com
- API : https://portfolio-app-blvx.onrender.com (`/health` pour vérifier qu'elle répond)

## Fonctionnalités

| Onglet | Contenu |
|---|---|
| **Portefeuille** | Valeur, plus-value, PEA / CTO, courbe d'évolution, comparaison à un indice (même argent aux mêmes dates dans un ETF MSCI World, S&P 500 ou CAC 40), positions détaillées, alertes, actions surveillées, répartition par secteur, livrets. Saisie des achats, ventes et dividendes, avec frais proposés selon le barème du courtier et TTF. |
| **Marché** | Screener (recherche, filtres région / secteur / DCF fiable / score / dividende / super investisseurs / watchlist, tris) et fiche par action : ratios, score qualité calibré par secteur, DCF, dividende, historique hebdomadaire, comptes annuels. Vue « Super investisseurs » (déclarations 13F de 27 fonds). |
| **Briefs** | Briefs marchés hebdomadaires déposés par une tâche Claude Cowork dans un dossier Google Drive. |
| **Réglages** | Code d'accès, hypothèses personnelles du DCF (recalcul instantané de toutes les valeurs). |

Notifications chaque nuit sur le téléphone (appli ntfy) : action sous sa valeur intrinsèque, forte baisse,
score en baisse, dividende réduit, mouvement d'un super investisseur sur une action suivie.

## Architecture

```
Google Sheet (un par utilisateur)          GitHub Actions (chaque nuit)
  Opérations, Titres, Positions...           screener/ : super investisseurs, screener,
        │  compte de service Google                     comptes annuels, notifications
        ▼                                             │  publie sur la branche screener-data
backend/ (FastAPI sur Render)  ◄──────────────────────┘  (lue directement par l'appli)
  positions, analyses, opérations,
  alertes, briefs, performance
        ▲
frontend/ (site statique sur Render, installable sur téléphone)
```

- **`backend/app/`** : API. `data.py` (Yahoo via yfinance), `valuation.py` (DCF, score), `sectors.py`
  (paliers par secteur), `sheets.py` (lecture du Sheet, ancien et nouveau format), `workbook.py`
  (Sheet modèle et migration), `operations.py` (saisie), `performance.py` (comparaison à un indice),
  `alerts.py`, `briefs.py`, `users.py` (un code d'accès = un utilisateur = un Sheet).
- **`frontend/index.html`** : toute l'appli (HTML, CSS, JS, graphiques Chart.js).
- **`screener/`** : scripts du calcul nocturne. `build_universe.py` construit la liste des actions
  (`universe.csv`) à partir des indices ; à relancer à la main de temps en temps.
- **`sheet-template/historique.gs`** : script Google Apps Script du relevé hebdomadaire, à installer dans chaque Sheet.
- **`tests/`** : tests automatiques, lancés par GitHub à chaque modification (`.github/workflows/tests.yml`).

### Sources de données

| Donnée | Source | Remarque |
|---|---|---|
| Cours, ratios, cash-flows, dividendes | Yahoo Finance (yfinance) | Gratuit et non officiel : données parfois manquantes hors US. |
| Comptes annuels US (~20 ans) | SEC, API XBRL | Europe / Asie : 4 ans Yahoo, archivés et fusionnés au fil des ans. |
| Super investisseurs | SEC, formulaires 13F | Jusqu'à 45 jours de décalage, actions américaines uniquement. |
| Composition des indices | Wikipedia, Xtrackers (Stoxx 600), OpenFIGI | Voir `screener/build_universe.py`. |
| Cours dans le Sheet | GOOGLEFINANCE | |

## Configuration

### Render : service backend (`portfolio-app`)

| Variable | Rôle |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Chemin du fichier de clé du compte de service, ajouté en *Secret File* (`/etc/secrets/google-credentials.json`). |
| `USERS_JSON` | Liste des utilisateurs (voir [docs/ajouter-un-ami.md](docs/ajouter-un-ami.md)). Si absente : utilisateur unique avec `APP_ACCESS_TOKEN` et `SHEET_ID`. |
| `APP_ACCESS_TOKEN` | Code d'accès du propriétaire quand `USERS_JSON` n'est pas défini. |
| `SHEET_ID` | Sheet du propriétaire (facultatif, défaut dans `backend/app/users.py`). |

Commande de démarrage : `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (répertoire racine `backend`).
Le frontend est un site statique Render (répertoire `frontend`, sans commande de build).

### GitHub : secrets du repo (Settings > Secrets and variables > Actions)

| Secret | Rôle |
|---|---|
| `APP_ACCESS_TOKEN` | Code d'accès du propriétaire, pour que le calcul nocturne lise positions et watchlist. |
| `NTFY_TOPIC` | Nom du canal ntfy qui reçoit les notifications. |

### Google

Un compte de service (Google Cloud, API Google Sheets et Google Drive activées) : chaque Sheet
utilisateur et le dossier Drive des briefs sont partagés avec son adresse, en Éditeur pour le Sheet.

## Workflows GitHub

- **Screener** (chaque nuit vers 3 h, ou à la main) : super investisseurs, screener, comptes annuels,
  notifications, puis publication sur la branche `screener-data`.
- **Tests** : à chaque modification de `main`.
- **Admin** (à la main) : construit un Sheet modèle vide, ou migre un ancien Sheet vers le modèle.

```bash
gh workflow run screener.yml                                   # relancer le screener
gh workflow run admin.yml -f target=<ID du Sheet> -f migrate_from=   # nouveau Sheet modèle vierge
```

## Développement local

```bash
python -m venv backend/.venv && backend/.venv/Scripts/activate   # Windows (source backend/.venv/bin/activate ailleurs)
pip install -r requirements-dev.txt
python -m pytest tests -q
cd backend && uvicorn app.main:app --reload                     # API sur http://localhost:8000
python screener/run.py --data-dir data --max-fundamentals 20    # mini screener local
```

## Partager l'appli

Chaque ami a son propre Sheet et son propre code d'accès sur la même appli :
[tutoriel pour les amis](docs/tutoriel-amis.md) et [procédure pour les ajouter](docs/ajouter-un-ami.md).

## Limites connues

- Données Yahoo non officielles : certaines valeurs peuvent manquer ou être fausses, surtout hors US.
- Le DCF est volontairement simple : il est marqué « non fiable » quand il s'écarte trop du cours.
  Ce n'est pas un conseil en investissement.
- L'API gratuite de Render s'endort après 15 minutes : la première ouverture prend 30 s à 1 min.
- Le PRU du Sheet suit la méthode du prix moyen pondéré sur l'ensemble des achats (approximation
  si l'on rachète un titre après en avoir vendu une partie).
