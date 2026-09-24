# Portfolio Insights — squelette de départ

Outil perso de suivi/valorisation d'actions, inspiré de Baggr et Mungr,
branché sur ton Google Sheet "Investissement".

## Structure

```
backend/
  app/
    main.py       -> API FastAPI (endpoints)
    data.py        -> récupération des fondamentaux via yfinance
    valuation.py    -> DCF, marge de sécurité, score de qualité
    sheets.py       -> lecture du Google Sheet "Investissement"
  requirements.txt
frontend/
  index.html        -> écran principal (liste des positions + scores)
  manifest.json      -> rend l'appli installable sur téléphone
  service-worker.js
```

## Ce qui reste à faire (dans l'ordre logique)

1. **Tester en local** : `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload`,
   puis vérifier `http://localhost:8000/analysis/MC.PA` (LVMH) dans le navigateur pour valider que yfinance répond bien.
2. **Brancher le vrai Google Sheet** : créer un compte de service Google, partager le Sheet "Investissement" avec son email,
   et adapter les noms de colonnes dans `sheets.py` à la structure réelle de ta feuille (je n'ai pas encore vu sa mise en page exacte).
3. **Ajuster le scoring** : les seuils dans `compute_quality_score` sont un point de départ générique, à affiner
   sectoriellement si tu veux quelque chose de plus fin que Baggr/Mungr.
4. **Déployer le backend sur Render** (gratuit) : connecter le repo GitHub, définir la commande de démarrage
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, et ajouter la variable d'environnement `GOOGLE_SERVICE_ACCOUNT_JSON`.
5. **Mettre à jour `API_BASE_URL`** dans `frontend/index.html` avec l'URL Render, déployer le frontend (Render static site
   ou Netlify, gratuit aussi), puis "Ajouter à l'écran d'accueil" depuis ton téléphone.
6. **Optionnel plus tard** : ajouter un endpoint `/super-investors` basé sur les 13F de la SEC (EDGAR, gratuit,
   décalé de 45 jours) pour retrouver la fonctionnalité "super investisseurs" de Mungr.

## Limites connues à garder en tête

- yfinance est non-officiel : les données peuvent parfois manquer ou changer de format sans préavis. Le code est
  écrit pour dégrader proprement (champs à `None`) plutôt que planter, mais ça reste à surveiller.
- Le free tier Render s'endort après 15 min d'inactivité : le premier appel après une pause prendra ~1 minute.
- Les hypothèses du DCF (croissance, taux d'actualisation) sont volontairement simples et à ajuster à la main
  selon l'entreprise analysée, pas à prendre pour argent comptant.
