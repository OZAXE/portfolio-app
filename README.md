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
| **Accueil** | Salutation, valeur des placements, variation du jour (change compris), plus-value et TRI, mini-courbe sur un an, « À regarder » (concentration trop forte, alertes de la nuit, thèses du journal à relire, résultats dans les 7 jours, chaque ligne mène où agir), tuiles prochain dividende et revenu sur 12 mois, alertes de prix, mode discret (points à la place des montants). |
| **Portefeuille** | PEA / CTO (filtre des positions), espèces, bouton « + Opération », courbe d'évolution (un relevé par jour de bourse, comparaison à un indice : même argent aux mêmes dates dans un ETF MSCI World, S&P 500 ou CAC 40). Sous-onglets : **Positions** (tri par valeur, perf. ou variation du jour, fiche de chaque ligne avec effet du change, graphique des achats) ; **Perf.** (performance pondérée par le temps de 1 mois à 5 ans face à l'indice, volatilité, pire baisse, Sharpe, bêta, effet du change par devise, contribution de chaque ligne) ; **Répartition** (secteur, zone, devise, poche, contenu des ETF, exposition par entreprise, concentration (plafonds par action et par secteur, nombre effectif de lignes), espèces de chaque compte). Saisie des achats, ventes, dividendes, divisions et actions gratuites, versements, retraits et intérêts (frais proposés selon le barème du courtier et TTF). |
| **Suivi** | **Opérations** (toutes les opérations, à corriger, supprimer ou exporter en CSV), **Journal** de trading (thèse, objectif, stop, bilan de chaque titre), **Revenus** (dividendes à venir, rendement sur PRU de chaque ligne, revenu annuel perçu par année et projeté, résultats à venir), **Fiscalité** (plus-values, dividendes et intérêts, impôt restant estimé du CTO, récap des cases de la déclaration et export CSV, plafond PEA, frais). Bouton **Importer** : Trade Republic (PDF, CSV avec les espèces et les actions gratuites) et Boursorama. |
| **Marché** | Accueil en sections (tes actions, watchlist, solides et sous-évaluées, plus solides, dividendes réguliers), screener (recherche, filtres région / secteur / DCF fiable / sous-évaluées / score / dividende / super investisseurs / watchlist, tris) et fiche par action : courbe du cours (1 mois à 10 ans, moyennes 50 et 200 jours, prix juste en repère), analyse technique (RSI, croisement des moyennes, plus haut / bas sur un an, momentum), ROIC, rendement du cash-flow libre, dette nette / EBITDA, couverture des intérêts, croissance du chiffre d'affaires et du BPA sur 5 ans (aussi en filtres et tris du screener), ton journal (thèse, objectif, stop), présentation de l'entreprise, ratios, score qualité calibré par secteur, prix juste avec verdict sous-évaluée / correcte / surévaluée (DCF, PER du secteur, PER historique de l'action, valeur comptable), consensus et objectif des analystes, date des résultats, actualités (Google Actualités en français), comparaison côte à côte de 4 actions, DCF, dividende et rachats, historique hebdomadaire, comptes annuels. Vue « Super investisseurs » (déclarations 13F de 27 fonds). |
| **Guides** | [Guide d'utilisation](docs/guide-utilisation.md), [installation pour un nouvel utilisateur](docs/tutoriel-amis.md), [gestion des utilisateurs](docs/ajouter-un-ami.md). |
| **Plus** | Affichage **Essentiel / Complet** (masque l'onglet Perf., l'exposition par entreprise et l'analyse technique, Marché en Simple) et taille du texte (A− / A+). **Mon patrimoine** : épargne saisie à la main (livrets, assurance-vie, PER, patrimoine financier), projection, allocation cible avec rééquilibrage (ventes choisies pour limiter l'impôt). **Briefs hebdo** (déposés par une tâche Claude Cowork dans un dossier Google Drive, visibles s'il y en a). Réglages : comptes et courtiers, notifications ntfy, apparence (thème, couleur, mode Simple / Détaillé, icône), hypothèses personnelles du DCF (recalcul instantané), opérations avancées (doublons, repartir de zéro, reconstituer l'historique), code d'accès, inscription, lexique, guides. |

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
  (Sheet modèle et migration), `operations.py` (saisie), `transactions.py` (liste, correction et suppression
  des opérations), `journal.py` (journal de trading), `performance.py` (comparaison à un indice),
  `stats.py` (performance par période, risque, contributions), `metrics.py` (ROIC, croissance, cash-flow libre, dette nette / EBITDA), `daily.py` (variation du jour, effet du change),
  `alerts.py`, `briefs.py`, `users.py` (un code d'accès = un utilisateur = un Sheet).
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
| `APP_ACCESS_TOKEN` | Code d'accès du propriétaire quand `USERS_JSON` n'est pas défini. Au moins 30 caractères aléatoires (`python -c "import secrets; print(secrets.token_urlsafe(32))"`) : rien ne limite les essais. Le même dans le secret GitHub du même nom. |
| `ALLOW_OPEN_API` | `1` pour laisser l'API répondre sans code d'accès (installation, essai en local). Jamais sur Render : sans elle, une API sans code configuré refuse tout. |
| `SIGNUP_OPEN` | `0` ferme l'inscription libre (ouverte par défaut, 50 comptes au plus avec `MAX_SIGNUPS`). |
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

Inscription libre depuis Plus > Créer un compte (`backend/app/signup.py`) : la personne copie le Sheet modèle, le partage
avec le compte de service et prouve qu'il est à elle en y collant un code ; les comptes sont rangés dans
l'onglet « Utilisateurs » du Sheet du propriétaire.

## Workflows GitHub

- **Screener** (chaque nuit vers 3 h, ou à la main) : relevé du jour dans l'onglet Historique de chaque
  utilisateur (`screener/snapshot.py`, plus-value de la semaine le vendredi), super investisseurs, screener, comptes annuels,
  notifications, puis publication sur la branche `screener-data`. Dernière étape (`screener/night_report.py`) : si une
  étape a échoué (relevé refusé, screener planté, publication ratée), notification ntfy « Calcul de nuit : n étapes
  en échec » sur le sujet du secret `NTFY_TOPIC`, avec le lien du journal du workflow.
- **Tests** : à chaque modification de `main` et sur chaque PR : tests du backend, plus un test de fumée du front
  (`tests/test_front.py` : l'appli ouverte dans Chromium sur un faux portefeuille, les cinq onglets parcourus, échec à
  la moindre erreur JavaScript ou erreur 500 de l'API).
- **Admin** (à la main) : construit un Sheet modèle vide, ou migre un ancien Sheet vers le modèle.

```bash
gh workflow run screener.yml                                   # relancer le screener
gh workflow run admin.yml -f target=<ID du Sheet> -f migrate_from=   # nouveau Sheet modèle vierge
```

## Développement local

```bash
python -m venv backend/.venv && backend/.venv/Scripts/activate   # Windows (source backend/.venv/bin/activate ailleurs)
pip install -r requirements-dev.txt
python -m playwright install chromium                           # navigateur du test du front (sinon test ignoré)
python -m pytest tests -q
cd backend && ALLOW_OPEN_API=1 uvicorn app.main:app --reload    # API sur http://localhost:8000, sans code
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
- Le PRU du Sheet suit la méthode du prix moyen pondéré, en rejouant les opérations dans l'ordre (une vente
  totale remet le PRU à zéro, une division le baisse sans changer le montant investi).
- Divisions : importées de Trade Republic seulement pour les actions gratuites ; une division se saisit à la
  main (type Division). La variation du jour et l'effet du change viennent de Yahoo : sans cours Yahoo, la
  ligne est signalée et pas comptée.
