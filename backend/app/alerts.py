"""
Alertes sur tes positions et ta watchlist, calculées à partir des résultats du
screener nocturne (screener.json) et des super investisseurs (superinvestors.json).

Deux familles :
- les événements, qui comparent le calcul de la nuit à celui de la veille
  (champs prev_* du screener) : ils ne se déclenchent qu'une fois, et ce sont
  eux qui partent en notification ;
- les opportunités, un état permanent (action surveillée actuellement sous sa
  valeur intrinsèque), affichées dans l'appli sans notification.

Fonctions pures : utilisées par l'API (/alerts) et par screener/notify.py.
"""

UNDERVALUED_MARGIN = 20.0  # % de marge de sécurité à partir duquel une action est jugée sous-évaluée
BIG_DROP = -0.07  # baisse sur une séance
SCORE_DROP = 3.0  # points de score qualité perdus

SUPERINVESTOR_MOVES = {
    "nouvelle": "a pris une nouvelle position dans",
    "renforcée": "a renforcé",
    "allégée": "a allégé",
    "vendue": "a vendu toute sa position dans",
}


def _undervalued(margin, reliable) -> bool:
    return bool(reliable) and margin is not None and margin >= UNDERVALUED_MARGIN


def compute_alerts(positions: set[str], watchlist: set[str], screener: dict, investors: dict | None) -> dict:
    """positions / watchlist : tickers au format Yahoo. Renvoie {"events": [...], "opportunities": [...]}."""
    followed = positions | watchlist
    stocks = {s["ticker"]: s for s in screener.get("stocks", []) if s["ticker"] in followed and not s.get("error")}
    events, opportunities = [], []

    def origin(ticker):
        return "position" if ticker in positions else "watchlist"

    for ticker, s in stocks.items():
        name = s.get("name") or ticker
        base = {"ticker": ticker, "name": name, "origin": origin(ticker)}

        if _undervalued(s.get("margin_of_safety"), s.get("dcf_reliable")):
            opportunities.append({**base, "margin": s["margin_of_safety"], "quality_score": s.get("quality_score")})
            if "prev_margin_of_safety" in s and not _undervalued(s.get("prev_margin_of_safety"), s.get("prev_dcf_reliable")):
                events.append({**base, "type": "sous-évaluée",
                               "message": f"{name} passe sous sa valeur intrinsèque (marge de sécurité {s['margin_of_safety']:.0f} %)"})

        price, prev_price = s.get("price"), s.get("prev_price")
        if price and prev_price:
            move = price / prev_price - 1
            if move <= BIG_DROP:
                events.append({**base, "type": "baisse",
                               "message": f"{name} recule de {abs(move) * 100:.1f} % sur la dernière séance"})

        score, prev_score = s.get("quality_score"), s.get("prev_quality_score")
        if score is not None and prev_score is not None and prev_score - score >= SCORE_DROP:
            events.append({**base, "type": "score",
                           "message": f"Score qualité de {name} en baisse : {prev_score:.1f} → {score:.1f} / 20"})

    for fund in (investors or {}).get("funds", []):
        if not fund.get("new_filing"):
            continue
        moves = [(p["ticker"], p["name"], p["change"], p.get("change_pct")) for p in fund["positions"]]
        moves += [(p["ticker"], p["name"], "vendue", None) for p in fund.get("sold", [])]
        for ticker, name, change, pct in moves:
            if ticker not in followed or change not in SUPERINVESTOR_MOVES:
                continue
            detail = f" ({pct * 100:+.0f} % d'actions)" if pct is not None and change in ("renforcée", "allégée") else ""
            events.append({"ticker": ticker, "name": name, "origin": origin(ticker), "type": "super investisseur",
                           "message": f"{fund['manager']} {SUPERINVESTOR_MOVES[change]} {name}{detail}"})

    opportunities.sort(key=lambda o: -o["margin"])
    return {"events": events, "opportunities": opportunities}
