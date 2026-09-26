"""
Super investisseurs : portefeuilles publiés chaque trimestre par les grands
fonds américains auprès de la SEC (formulaire 13F), avec les mouvements du
trimestre (nouvelles positions, renforcements, allègements, ventes).

Lancé avec le screener nocturne :
    python screener/superinvestors.py --data-dir data

Limites à garder en tête :
- un 13F est publié jusqu'à 45 jours après la fin du trimestre : les positions
  ont souvent déjà bougé depuis ;
- seules les actions cotées aux États-Unis y figurent (pas les positions
  européennes ou asiatiques, ni les ventes à découvert).

Les identifiants CUSIP des titres sont convertis en tickers via l'API publique
OpenFIGI, avec un cache pour ne demander que les nouveaux.
"""

import argparse
import json
import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path

import requests

# La SEC exige un contact dans l'en-tête des programmes qui interrogent EDGAR
SEC_HEADERS = {"User-Agent": "portfolio-app enzocabos192004@gmail.com", "Accept-Encoding": "gzip, deflate"}
SEC_DELAY = 0.15  # la SEC tolère 10 requêtes par seconde
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_BATCH = 10  # maximum sans clé d'API
OPENFIGI_DELAY = 2.6  # 25 requêtes par minute sans clé

MAX_POSITIONS_PER_FUND = 100
STALE_AFTER_DAYS = 200  # fonds qui ne publient plus : écartés automatiquement

# (identifiant, nom affiché, gérant ou fonds phare, CIK EDGAR)
FUNDS = [
    ("berkshire", "Berkshire Hathaway", "Warren Buffett", 1067983),
    ("pershing", "Pershing Square", "Bill Ackman", 1336528),
    ("appaloosa", "Appaloosa", "David Tepper", 1656456),
    ("baupost", "Baupost Group", "Seth Klarman", 1061768),
    ("himalaya", "Himalaya Capital", "Li Lu", 1709323),
    ("fundsmith", "Fundsmith", "Terry Smith", 1569205),
    ("duquesne", "Duquesne Family Office", "Stanley Druckenmiller", 1536411),
    ("pabrai", "Dalal Street", "Mohnish Pabrai", 1549575),
    ("akre", "Akre Capital", "Akre Focus Fund", 1112520),
    ("ruane", "Ruane, Cunniff & Goldfarb", "Sequoia Fund", 1720792),
    ("oaktree", "Oaktree Capital", "Howard Marks", 949509),
    ("thirdpoint", "Third Point", "Dan Loeb", 1040273),
    ("icahn", "Icahn Enterprises", "Carl Icahn", 921669),
    ("valueact", "ValueAct", "Mason Morfit", 1418814),
    ("gates", "Gates Foundation Trust", "Fondation Gates", 1166559),
    ("lonepine", "Lone Pine Capital", "Stephen Mandel", 1061165),
    ("viking", "Viking Global", "Andreas Halvorsen", 1103804),
    ("tweedy", "Tweedy, Browne", "Tweedy, Browne", 732905),
    ("firsteagle", "First Eagle", "First Eagle Global", 1325447),
    ("polen", "Polen Capital", "Polen Focus Growth", 1034524),
    ("oakmark", "Harris Associates", "Bill Nygren (Oakmark)", 813917),
    ("markel", "Markel Group", "Tom Gayner", 1096343),
    ("semper", "Semper Augustus", "Chris Bloomstran", 1115373),
    ("giverny", "Giverny Capital", "François Rochon", 1641864),
    ("trian", "Trian Fund Management", "Nelson Peltz", 1345471),
    ("tiger", "Tiger Global", "Chase Coleman", 1167483),
    ("coatue", "Coatue Management", "Philippe Laffont", 1135730),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("superinvestors")


def sec_get(url: str) -> requests.Response:
    time.sleep(SEC_DELAY)
    response = requests.get(url, headers=SEC_HEADERS, timeout=60)
    response.raise_for_status()
    return response


def latest_13f_filings(cik: int, count: int = 2) -> list[dict]:
    """Derniers dépôts 13F-HR (hors amendements), un par trimestre, du plus récent au plus ancien."""
    recent = sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()["filings"]["recent"]
    filings, periods = [], set()
    for form, accession, filed, period in zip(recent["form"], recent["accessionNumber"], recent["filingDate"], recent["reportDate"]):
        if form == "13F-HR" and period not in periods:
            periods.add(period)
            filings.append({"accession": accession, "filed": filed, "period": period})
        if len(filings) == count:
            break
    return filings


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def fetch_holdings(cik: int, accession: str) -> dict[str, dict]:
    """Table des positions d'un dépôt, agrégée par CUSIP (un titre peut apparaître sur plusieurs lignes).
    Les options (puts / calls) sont écartées : ce ne sont pas des positions en actions."""
    folder = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}"
    items = sec_get(f"{folder}/index.json").json()["directory"]["item"]
    xml_names = [i["name"] for i in items if i["name"].lower().endswith(".xml") and i["name"].lower() != "primary_doc.xml"]
    if not xml_names:
        raise ValueError(f"table des positions introuvable dans {folder}")
    root = ET.fromstring(sec_get(f"{folder}/{xml_names[0]}").content)

    holdings: dict[str, dict] = {}
    for entry in root.iter():
        if _local(entry.tag) != "infoTable":
            continue
        fields = {_local(child.tag): child for child in entry.iter()}
        if "putCall" in fields and (fields["putCall"].text or "").strip():
            continue
        cusip = fields["cusip"].text.strip().upper()
        value = float(fields["value"].text)
        shares = float(fields["sshPrnamt"].text) if "sshPrnamt" in fields else 0.0
        h = holdings.setdefault(cusip, {"cusip": cusip, "name": fields["nameOfIssuer"].text.strip(), "value": 0.0, "shares": 0.0})
        h["value"] += value
        h["shares"] += shares
    return holdings


def map_cusips(cusips: set[str], cache: dict[str, str | None]) -> None:
    """CUSIP -> ticker (format Yahoo) via OpenFIGI, en complétant le cache."""
    todo = sorted(c for c in cusips if c not in cache)
    log.info("CUSIP à convertir : %d (déjà en cache : %d)", len(todo), len(cusips) - len(todo))
    for i in range(0, len(todo), OPENFIGI_BATCH):
        batch = todo[i:i + OPENFIGI_BATCH]
        payload = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in batch]
        for attempt in range(3):
            response = requests.post(OPENFIGI_URL, json=payload, timeout=60)
            if response.status_code != 429:
                break
            time.sleep(30 * (attempt + 1))
        if not response.ok:
            log.warning("OpenFIGI en erreur (%s), conversion reportée", response.status_code)
            return
        for cusip, result in zip(batch, response.json()):
            data = result.get("data") or []
            ticker = next((d.get("ticker") for d in data if d.get("ticker")), None)
            cache[cusip] = ticker.replace("/", "-").replace(" ", "-") if ticker else None
        time.sleep(OPENFIGI_DELAY)


def classify(current: dict | None, previous: dict | None) -> tuple[str, float | None]:
    """Mouvement du trimestre, mesuré en nombre d'actions (la valeur bouge aussi avec le cours)."""
    if previous is None:
        return "nouvelle", None
    if current is None:
        return "vendue", -1.0
    if not previous["shares"]:
        return "inchangée", None
    change = current["shares"] / previous["shares"] - 1
    if change > 0.02:
        return "renforcée", change
    if change < -0.02:
        return "allégée", change
    return "inchangée", change


def build_fund(fund: tuple, cache: dict) -> dict | None:
    fund_id, name, manager, cik = fund
    filings = latest_13f_filings(cik)
    if not filings:
        return None
    age = (date.today() - date.fromisoformat(filings[0]["filed"])).days
    if age > STALE_AFTER_DAYS:
        log.info("%s : dernier 13F vieux de %d jours, écarté", name, age)
        return None

    current = fetch_holdings(cik, filings[0]["accession"])
    previous = fetch_holdings(cik, filings[1]["accession"]) if len(filings) > 1 else {}
    map_cusips(set(current) | set(previous), cache)

    total = sum(h["value"] for h in current.values()) or 1.0
    previous_total = sum(h["value"] for h in previous.values()) or 1.0
    positions = []
    for cusip, h in current.items():
        change, change_pct = classify(h, previous.get(cusip)) if previous else ("inchangée", None)
        positions.append({
            "ticker": cache.get(cusip), "cusip": cusip, "name": h["name"], "value": h["value"],
            "shares": h["shares"], "weight": h["value"] / total, "change": change, "change_pct": change_pct,
        })
    positions.sort(key=lambda p: -p["value"])
    sold = sorted(
        ({"ticker": cache.get(c), "cusip": c, "name": h["name"], "previous_weight": h["value"] / previous_total}
         for c, h in previous.items() if c not in current),
        key=lambda p: -p["previous_weight"],
    )
    return {
        "id": fund_id, "name": name, "manager": manager, "cik": cik,
        "period": filings[0]["period"], "filed": filings[0]["filed"],
        "previous_period": filings[1]["period"] if len(filings) > 1 else None,
        "total_value": total, "positions_count": len(positions),
        "positions": positions[:MAX_POSITIONS_PER_FUND], "sold": sold[:30],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    cache_path = data_dir / "cusip_tickers.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}

    # Dépôts déjà connus : un fonds dont le 13F a changé depuis la veille est marqué "new_filing",
    # c'est ce qui déclenche les alertes (une seule fois par nouveau trimestre)
    out = data_dir / "superinvestors.json"
    known_filings = {}
    if out.exists():
        known_filings = {f["id"]: f["filed"] for f in json.loads(out.read_text(encoding="utf-8")).get("funds", [])}

    funds = []
    for fund in FUNDS:
        try:
            result = build_fund(fund, cache)
        except Exception as e:
            log.warning("%s en erreur : %s", fund[1], e)
            continue
        if result:
            result["new_filing"] = fund[0] in known_filings and known_filings[fund[0]] != result["filed"]
            funds.append(result)
            log.info("%s : %d positions au %s", result["name"], result["positions_count"], result["period"])
        cache_path.write_text(json.dumps(cache, sort_keys=True), encoding="utf-8")

    # Index par ticker : qui détient quoi, pour l'afficher sur la fiche de chaque action
    by_ticker: dict[str, list] = {}
    for f in funds:
        for p in f["positions"]:
            if p["ticker"]:
                by_ticker.setdefault(p["ticker"], []).append(
                    {"fund": f["id"], "weight": p["weight"], "change": p["change"], "change_pct": p["change_pct"]}
                )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "funds": funds,
        "by_ticker": by_ticker,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("%d fonds écrits dans %s", len(funds), out)


if __name__ == "__main__":
    main()
