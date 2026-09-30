# Portfolio Insights

Appli perso de suivi et d'analyse d'actions, installable sur téléphone, dans l'esprit de Baggr et Mungr :
suivi du portefeuille à partir d'un Google Sheet, screener d'environ 2 000 actions (Europe, US, Asie)
avec score qualité, valeur intrinsèque et prix juste, dividendes, comptes annuels, super investisseurs,
watchlist, alertes et briefs marchés hebdomadaires.

- Appli : https://portfolio-front-8t6m.onrender.com
- API : https://portfolio-app-blvx.onrender.com (`/health` pour vérifier qu'elle répond)

## Fonctionnalités

| Onglet | Contenu |
|---|---|
| **Portefeuille** | Valeur, plus-value, PEA / CTO, courbe d'évolution (un relevé par jour de bourse), mode discret qui floute les montants, comparaison à un indice (même argent aux mêmes dates dans un ETF MSCI World, S&P 500 ou CAC 40), positions détaillées, performance par période pondérée par le temps (1 mois à 5 ans, face à l'indice), risque (volatilité, pire baisse, Sharpe, bêta), contribution de chaque ligne, alertes, actions surveillées, répartition par secteur, livrets. Espèces de chaque compte (versements, retraits, intérêts, importés du CSV Trade Republic). Saisie des achats, ventes et dividendes, avec frais proposés selon le barème du courtier et TTF. |
| **Marché** | Screener (recherche, filtres région / secteur / DCF fiable / sous-évaluées / score / dividende / super investisseurs / watchlist, tris) et fiche par action : courbe du cours (1 mois à 10 ans, moyenne 200 jours, prix juste en repère), présentation de l'entreprise, ratios, score qualité calibré par secteur, prix juste avec verdict sous-évaluée / correcte / surévaluée (DCF, PER du secteur, PER historique de l'action, valeur comptable), consensus et objectif des analystes, date des résultats, rachats d'actions, comparaison côte à côte de 4 actions, DCF, dividende, historique hebdomadaire, comptes annuels. Vue « Super investisseurs » (déclarations 13F de 27 fonds). |
| **Briefs** | Briefs marchés hebdomadaires déposés par une tâche Claude Cowork dans un dossier Google Drive. |
| **Guides** | [Guide d'utilisation](docs/guide-utilisation.md), [installation pour un nouvel utilisateur](docs/tutoriel-amis.md), [gestion des utilisateurs](docs/ajouter-un-ami.md). |
| **Réglages** | Code d'accès, hypothèses personnelles du DCF (recalcul instantané de toutes les valeurs). |

Notifications chaque nuit sur le téléphone (appli ntfy) : action sous sa valeur intrinsèque, forte baisse,
score en baisse, dividende réduit, mouvement d'un super investisseur sur une action suivie, alertes de prix,
et chaque vendredi soir la plus-value de la semaine (apports exclus).

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

- **`backend/app/`** : API. `data.py` (Yahoo via yfinance), `valuation.py` (DCF, prix juste, score), `sectors.py`
  (paliers et PER normal par secteur), `sheets.py` (lecture du Sheet, ancien et nouveau format), `workbook.py`
  (Sheet modèle et migration), `operations.py` (saisie), `performance.py` (comparaison à un indice),
  `stats.py` (performance par période, risque, contributions), `alerts.py`, `briefs.py`, `users.py` (un code d'accès = un utilisateur = un Sheet).
- **`frontend/index.html`** : toute l'appli (HTML, CSS, JS, graphiques Chart.js).
- **`screener/`** : scripts du calcul nocturne. `build_universe.py` construit la liste des actions
  (`universe.csv`) à partir des indices ; à relancer à la main de temps en temps.
- **`tests/`** : tests automatiques, lancés par GitHub à chaque modification (`.github/workflows/tests.yml`).

### Sources de données

| Donnée | Source | Remarque |
|---|---|---|
| Cours, ratios, cash-flows, dividendes | Yahoo Finance (yfinance) | Gratuit et non officiel : données parfois manquantes hors US. |
| Courbe de cours de la fiche | Yahoo (API chart), via le backend (`/prices`) | 10 ans de clôtures quotidiennes, gardées 6 h. |
| Présentation des entreprises | Yahoo (quoteSummary), archivée par le screener | Un fichier par action (`profiles/`), en anglais, ajouté à la prochaine analyse de chaque action. |
| Comptes annuels US (~20 ans) | SEC, API XBRL | Europe / Asie : 4 ans Yahoo, archivés et fusionnés au fil des ans. |
| Super investisseurs | SEC, formulaires 13F | Jusqu'à 45 jours de décalage, actions américaines uniquement. |
| Composition des indices | Wikipedia, Xtrackers (Stoxx 600), OpenFIGI | Voir `screener/build_universe.py`. |
| Cours dans le Sheet | GOOGLEFINANCE | |

## Configuration

### Render : service backend (`portfolio-app`)

| Variable | Rôle |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Chemin du fichier de clé du compte de service, ajouté en *Secret File* (`/etc/secrets/google-credentials.json`). |
| `USERS_JSON` | Compte administrateur (voir [docs/ajouter-un-ami.md](docs/ajouter-un-ami.md)) ; les autres utilisateurs s'inscrivent depuis l'appli. Si absente : utilisateur unique avec `APP_ACCESS_TOKEN` et `SHEET_ID`. |
| `APP_ACCESS_TOKEN` | Code d'accès du propriétaire quand `USERS_JSON` n'est pas défini. |
| `SHEET_ID`, `BRIEFS_FOLDER` | Sheet et dossier Briefs du propriétaire, seulement sans `USERS_JSON`. |

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

Inscription libre depuis Réglages (`backend/app/signup.py`) : la personne copie le Sheet modèle, le partage
avec le compte de service et prouve qu'il est à elle en y collant un code ; les comptes sont rangés dans
l'onglet « Utilisateurs » du Sheet du propriétaire.

## Workflows GitHub

- **Screener** (chaque nuit vers 3 h, ou à la main) : relevé du jour dans l'onglet Historique de chaque
  utilisateur (`screener/snapshot.py`, plus-value de la semaine le vendredi), super investisseurs, screener, comptes annuels,
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
- Le prix juste compare notamment au PER « normal » du secteur : une entreprise de grande qualité, que le marché
  paie durablement plus cher que son secteur (Air Liquide, Hermès), ressortira souvent surévaluée. Le PER
  historique de l'action (4e méthode, médiane sur 10 ans) corrige en partie ce biais quand il est connu. Il
  ignore aussi la croissance propre à l'entreprise (sauf via le DCF) et se laisse tromper par les
  cycliques en haut de cycle. Ces limites sont affichées dans la fiche (`fairCaveats`) et dans le
  lexique (« Limites du prix juste »).
  Ce n'est pas un conseil en investissement.
- L'API gratuite de Render s'endort après 15 minutes : la première ouverture prend 30 s à 1 min.
- Le PRU du Sheet suit la méthode du prix moyen pondéré sur l'ensemble des achats (approximation
  si l'on rachète un titre après en avoir vendu une partie).
