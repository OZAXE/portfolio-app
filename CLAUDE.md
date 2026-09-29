# Mémoire Claude du projet Portfolio Insights

Lue automatiquement par Claude Code au début de chaque session (sur le PC ou sur le web).
C'est la mémoire partagée du projet : les sessions web ne voient pas la mémoire locale du PC,
donc tout ce qui doit survivre d'une session à l'autre va ici. À mettre à jour quand on apprend
quelque chose d'utile ou qu'on prend une décision de conception.

## Le projet

Appli perso de suivi de portefeuille et d'analyse d'actions (esprit Baggr / Mungr), installable sur
téléphone, utilisée par Enzo (propriétaire, étudiant ingénieur énergie, investisseur actions en direct)
et quelques amis (un code d'accès = un utilisateur = un Google Sheet). Tout est en **français** :
interface (tutoiement), commentaires, messages de commit, docs. Le README décrit fonctionnalités,
architecture, configuration Render / GitHub / Google : le lire avant un gros changement.

- `backend/app/` : API FastAPI sur Render (plan gratuit, s'endort après 15 min).
  `data.py` (Yahoo via yfinance), `valuation.py` (DCF, prix juste, score), `sectors.py` (familles de
  secteurs, paliers du score, PER normal), `sheets.py` / `workbook.py` (Google Sheet), `main.py` (routes).
- `frontend/index.html` : **toute** l'appli dans un seul fichier (HTML, CSS, JS, Chart.js), site statique.
- `screener/run.py` : calcul nocturne (GitHub Actions, `.github/workflows/screener.yml`) qui publie
  `screener.json` et `history.json` sur la branche `screener-data`, lue directement par l'appli.
  Ne jamais committer à la main sur `screener-data`.
- `tests/` : pytest, lancé par la CI à chaque push sur `main` et sur les PR.

## Commandes

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q                                    # doit rester vert avant tout push
cd backend && uvicorn app.main:app --reload                  # API locale
python screener/run.py --data-dir data --max-fundamentals 20 # mini screener local
```

Pour voir le front sans backend : servir `frontend/` (`python -m http.server`) et intercepter
`SCREENER_URL` avec un `screener.json` (Playwright `page.route`). Le vrai fichier se récupère sur
`https://raw.githubusercontent.com/OZAXE/portfolio-app/screener-data/screener.json`.

## Règles à respecter

- **Calculs en double Python / JavaScript.** Le front refait certains calculs pour appliquer les
  hypothèses DCF personnelles de l'utilisateur sans appeler l'API. Toute modification d'un côté doit
  être reportée de l'autre, constantes comprises :
  - `compute_dcf` (valuation.py) ↔ `dcfValue` (index.html) ;
  - `blend_fair_value` / `fair_value_verdict` ↔ `fairValueOf` ;
  - `RELIABLE_RATIO_MIN/MAX` (0,4 / 2,5) ↔ `RELIABLE_MIN/MAX`, `VERDICT_BAND`, `DIVERGENCE_MAX`.
- **Fondamentaux et cours n'ont pas le même rythme.** Chaque nuit, le cours de toutes les actions est
  rafraîchi (`refresh_with_price`), mais les fondamentaux seulement pour ~600 actions (les plus
  anciennes) : une fiche est réanalysée tous les 3-4 jours. Donc :
  - stocker des valeurs **par action** (valeur intrinsèque, `fair_value_pe`...) et recalculer ce qui
    dépend du cours (marge, verdict) dans `refresh_with_price` et dans le front ;
  - un nouveau champ n'existe sur une fiche qu'après sa prochaine analyse : le code doit tolérer
    son absence (anciennes fiches) sans planter ni afficher de faux chiffre.
- **Données Yahoo non fiables.** Gratuites et non officielles : ratios parfois aberrants (PER de 0,0007,
  cours / valeur comptable de 0,001), PER prévisionnel en pence à Londres, devises des comptes
  différentes de la cotation (Shell, Novartis). Toujours borner, filtrer, et préférer « N/A » à un
  chiffre faux. Sur Render, `quoteSummary` est souvent bloqué : `data.py` recalcule alors les ratios
  depuis les états financiers (`STATEMENTS_SOURCE`, pas de PER prévisionnel ni de devise des comptes).
- **Aide contextuelle.** Un libellé de ligne `.analysis .row > span:first-child` égal à une clé du
  `GLOSSARY` ouvre son explication : ajouter l'entrée du lexique avec chaque nouvel indicateur.
- **CSS des fiches.** `.analysis .row span:last-child` impose la couleur du texte : utiliser les
  classes `span.positive` / `span.negative` / `span.muted` (règles dédiées) pour colorer une valeur.
- **Pas un conseil en investissement** : garder ce ton prudent dans les textes (« paraît », « indicatif »).
- Style : commentaires qui expliquent le *pourquoi* avec un exemple réel (ticker), fonctions courtes,
  tests nommés en français avec des valeurs calculées à la main dans le commentaire.

## Décisions de conception

- **Prix juste (septembre 2026).** Moyenne simple des méthodes disponibles, chacune écartée si elle
  donne moins de 0,4 ou plus de 2,5 fois le cours (même règle que la fiabilité du DCF, élimine les
  données Yahoo aberrantes) :
  1. DCF (valeur intrinsèque existante) ;
  2. bénéfice par action × PER normal du secteur (`ScoreProfile.fair_pe`, ex. 25 techno, 19 industrie,
     11 banques). BPA = moyenne des BPA passé et prévisionnel retrouvés via cours / PER ; si les deux
     diffèrent de plus d'un facteur 3, seul le passé est gardé ;
  3. banques / assurances seulement : valeur comptable × P/B justifié `(ROE − 2 %) / (r − 2 %)`,
     r = coût des fonds propres MEDAF, borné entre 0,3 et 3.
  Verdict : cours < 85 % du prix juste → sous-évaluée, > 115 % → surévaluée, sinon correcte.
  « Divergent » quand la méthode la plus haute dépasse le double de la plus basse (affiché en italique).
  Choix validés par Enzo : mix de méthodes, seuil ±15 %, affichage fiche + liste + positions.
  Limite connue : les entreprises de qualité durablement chères (Air Liquide, Hermès) ressortent
  surévaluées face au PER moyen de leur secteur. Piste possible : PER normal ajusté par la qualité
  ou la croissance (attention, le score qualité contient déjà un pilier PER : risque de circularité).
- **DCF** : deux phases, croissance qui décroît vers 2 %, FCF moyenné sur 3 ans, actualisation MEDAF
  bornée 7-11 %, non calculé pour banques / assurances / ETF.

## Pistes non faites

- Notification ntfy quand une action suivie passe « sous-évaluée » au sens du prix juste
  (aujourd'hui les alertes se basent sur la valeur intrinsèque seule, voir `screener/notify.py`).
- Ajouter le prix juste à l'historique hebdomadaire (`update_history`) et au graphique de la fiche.
