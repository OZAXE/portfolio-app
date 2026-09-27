"""
Rendement réel du portefeuille, qui tient compte de la date de chaque apport (TRI, ou XIRR).

La plus-value rapportée au montant investi est faussée par les apports réguliers : 1 000 €
ajoutés hier « diluent » la performance des euros investis depuis un an. Le TRI est le taux
annuel qui, appliqué à chaque flux depuis sa date, redonne la valeur actuelle : c'est le
rendement réellement obtenu sur l'argent placé, comparable à celui d'un livret ou d'un ETF.

Flux vus par l'investisseur : achat = argent sorti (négatif), vente et dividende = argent
récupéré (positif), valeur actuelle des titres = flux positif final, aujourd'hui.
Calculé pour tout le portefeuille, par enveloppe et par titre.
"""

from collections import defaultdict
from datetime import date

from .realized import Operation, read_operations
from .sheets import UNFORMATTED, _open_sheet, _worksheet, is_v2, parse_positions_v2

DAYS_PER_YEAR = 365.0


def xirr(flows: list[tuple[date, float]]) -> float | None:
    """Taux annuel r tel que la somme des flux actualisés à leur date soit nulle.
    None sans flux entrant et sortant, ou sur une durée de moins d'un jour."""
    flows = [(d, a) for d, a in flows if a]
    if not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return None
    start = min(d for d, _ in flows)
    timed = [((d - start).days / DAYS_PER_YEAR, a) for d, a in flows]
    if max(t for t, _ in timed) == 0:
        return None

    def npv(rate: float) -> float:
        return sum(a / (1 + rate) ** t for t, a in timed)

    # Dichotomie : plus lente que Newton, mais converge toujours quand une solution est encadrée
    low, high = -0.9999, 1000.0
    f_low = npv(low)
    if f_low * npv(high) > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2
        f_mid = npv(mid)
        if (f_mid > 0) == (f_low > 0):
            low, f_low = mid, f_mid
        else:
            high = mid
        if high - low < 1e-9:
            break
    return (low + high) / 2


class _Bucket:
    def __init__(self):
        self.flows: list[tuple[date, float]] = []
        self.bought = self.sold = self.dividends = self.value = 0.0
        self.missing_price = False

    def summary(self, today: date) -> dict:
        start = min((d for d, _ in self.flows), default=today)
        rate = xirr(self.flows + [(today, self.value)])
        days = (today - start).days
        return {
            "since": start.isoformat(),
            "days": days,
            "bought": round(self.bought, 2),
            "sold": round(self.sold, 2),
            "dividends": round(self.dividends, 2),
            "value": round(self.value, 2),
            # Gain total : plus-values latentes et réalisées, dividendes compris
            "gain": round(self.value + self.sold + self.dividends - self.bought, 2),
            "xirr": round(rate, 6) if rate is not None else None,
            # Même rendement, non annualisé : ce qu'a rapporté l'argent sur la période
            "period_return": round((1 + rate) ** (days / DAYS_PER_YEAR) - 1, 6) if rate is not None else None,
            "incomplete": self.missing_price,
        }


def compute_returns(operations: list[Operation], envelopes: dict[str, str],
                    prices: dict[str, float | None], today: date) -> dict:
    """prices : cours actuel en euros de chaque titre détenu (None s'il est inconnu)."""
    total, by_envelope, by_ticker = _Bucket(), defaultdict(_Bucket), defaultdict(_Bucket)
    quantities: dict[tuple[str, str], float] = defaultdict(float)  # (enveloppe, titre) -> quantité

    for op in sorted(operations, key=lambda o: o.day):
        envelope = envelopes.get(op.account, "Autre")
        buckets = (total, by_envelope[envelope], by_ticker[op.ticker])
        if op.kind == "Achat":
            quantities[(envelope, op.ticker)] += op.quantity
            flow = -op.net
        elif op.kind == "Vente":
            quantities[(envelope, op.ticker)] -= op.quantity
            flow = op.net
        else:
            flow = op.net
        for b in buckets:
            b.flows.append((op.day, flow))
            if op.kind == "Achat":
                b.bought += op.net
            elif op.kind == "Vente":
                b.sold += op.net
            else:
                b.dividends += op.net

    # Valeur actuelle recalculée par enveloppe (un même titre peut être sur le PEA et le CTO)
    for (envelope, ticker), quantity in quantities.items():
        if quantity <= 1e-9:
            continue
        price = prices.get(ticker)
        for b in (total, by_envelope[envelope], by_ticker[ticker]):
            if price is None:
                b.missing_price = True
            else:
                b.value += quantity * price

    return {
        "total": total.summary(today) if operations else None,
        "envelopes": {name: b.summary(today) for name, b in sorted(by_envelope.items())},
        "positions": {ticker: b.summary(today) for ticker, b in sorted(by_ticker.items())},
    }


def returns_summary(sheet_id: str) -> dict | None:
    """None pour un Sheet à l'ancien format (sans onglet Opérations)."""
    sheet = _open_sheet(sheet_id)
    if not is_v2(sheet):
        return None
    operations, envelopes, _ = read_operations(sheet_id)
    positions = parse_positions_v2(_worksheet(sheet, "Positions").get_values(value_render_option=UNFORMATTED))
    prices = {h.ticker.upper(): (h.value / quantity if h.value is not None else None) for h, quantity in positions}
    return compute_returns(operations, envelopes, prices, date.today())
