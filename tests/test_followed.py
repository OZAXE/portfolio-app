"""Titres de watchlist hors univers ajoutés au calcul de nuit (screener/followed.py, run.py, financials.py)."""

from app.data import CompanyFinancials

import followed
import run

UNIVERSE = {"AI.PA", "NVDA", "MC.PA"}


def test_watchlists_de_tous_les_utilisateurs_moins_l_univers():
    # Enzo suit Alstom (absente du petit univers du test), Air Liquide (déjà analysée) et Shopify en minuscules ;
    # un ami suit aussi Alstom, plus Soitec : 3 titres à ajouter, sans doublon
    users = [{"name": "Enzo", "watchlist": ["ALO.PA", "AI.PA", "shop"]},
             {"name": "Evan", "watchlist": ["ALO.PA", "SOI.PA"]},
             {"name": "Sheet illisible", "error": "403"}]
    entries = followed.followed_entries(users, UNIVERSE)
    assert [e["ticker"] for e in entries] == ["ALO.PA", "SHOP", "SOI.PA"]
    assert all(e["followed"] and e["indices"] == "" for e in entries)


def test_crypto_indice_et_texte_libre_ecartes():
    # Le Sheet est saisi à la main : rien qui ne puisse être une action cotée
    users = [{"watchlist": ["BTC-EUR", "^FCHI", "EURUSD=X", "=IMPORTRANGE(1)", "", "  ", "ESE.PA"]}]
    assert [e["ticker"] for e in followed.followed_entries(users, UNIVERSE)] == ["ESE.PA"]  # l'ETF est écarté à l'analyse


def test_region_et_pays_d_apres_le_suffixe():
    assert followed.place("ALO.PA") == ("Europe", "France")
    assert followed.place("SHOP") == ("US", "États-Unis")
    assert followed.place("6758.T") == ("Asie", "Japon")
    assert followed.place("SHOP.TO") == ("", "Canada")  # aucun filtre de région ne la retient, mais elle reste trouvable
    assert followed.place("XYZ.ZZ") == ("", "")


def test_garde_fou_du_nombre_de_titres(monkeypatch):
    monkeypatch.setattr(followed, "MAX_FOLLOWED", 2)
    users = [{"watchlist": ["C.PA", "A.PA", "B.PA"]}]
    assert [e["ticker"] for e in followed.followed_entries(users, set())] == ["A.PA", "B.PA"]


def test_api_injoignable_garde_les_titres_suivis_la_veille(monkeypatch):
    # Render en panne une nuit : Alstom, suivie la veille, ne doit pas disparaître du Marché jusqu'au lendemain
    import notify

    def down(path, token):
        raise RuntimeError("API injoignable : /notifications/users")

    monkeypatch.setenv("APP_ACCESS_TOKEN", "code-admin")
    monkeypatch.setattr(notify, "api_get", down)
    previous = {"ALO.PA": {"ticker": "ALO.PA", "name": "Alstom SA", "followed": True},
                "AI.PA": {"ticker": "AI.PA", "name": "L'Air Liquide S.A."}}
    entries = followed.load_followed(previous, UNIVERSE)
    assert [(e["ticker"], e["name"]) for e in entries] == [("ALO.PA", "Alstom SA")]


def test_titre_retire_quand_plus_personne_ne_le_suit(monkeypatch):
    import notify

    monkeypatch.setenv("APP_ACCESS_TOKEN", "code-admin")
    monkeypatch.setattr(notify, "api_get", lambda path, token: [{"watchlist": ["SOI.PA"]}])
    previous = {"ALO.PA": {"ticker": "ALO.PA", "followed": True}}
    assert [e["ticker"] for e in followed.load_followed(previous, UNIVERSE)] == ["SOI.PA"]


def test_sans_code_d_acces_en_local_la_liste_de_la_veille(monkeypatch):
    monkeypatch.delenv("APP_ACCESS_TOKEN", raising=False)
    previous = {"ALO.PA": {"ticker": "ALO.PA", "followed": True}}
    assert [e["ticker"] for e in followed.load_followed(previous, UNIVERSE)] == ["ALO.PA"]


def test_analyse_d_un_titre_suivi_marquee(monkeypatch):
    monkeypatch.setattr(run, "fetch_company_financials",
                        lambda t: CompanyFinancials(ticker=t, name="Alstom SA", quote_type="EQUITY", currency="EUR",
                                                    current_price=25.0, sector="Industrials"))
    record = run.analyze(followed.entry("ALO.PA"))
    assert record["followed"] is True and record["error"] is None
    assert record["name"] == "Alstom SA" and record["region"] == "Europe" and record["country"] == "France"
    assert record["indices"] == [] and record["price"] == 25.0


def test_etf_suivi_en_erreur_donc_absent_du_marche(monkeypatch):
    # ESE.PA (ETF S&P 500 BNP Paribas Easy) en watchlist : pas de comptes d'entreprise, la fiche est écartée par le
    # front (filtre !s.error) et l'ETF reste trouvable dans « Tes autres titres »
    monkeypatch.setattr(run, "fetch_company_financials",
                        lambda t: CompanyFinancials(ticker=t, name="BNP Paribas Easy S&P 500", quote_type="ETF",
                                                    currency="EUR", current_price=27.0))
    record = run.analyze(followed.entry("ESE.PA"))
    assert record["error"] == "pas une action (ETF)" and record["followed"] is True
    assert "quality_score" not in record and "fundamentals_updated" in record


def test_action_de_l_univers_non_marquee(monkeypatch):
    monkeypatch.setattr(run, "fetch_company_financials",
                        lambda t: CompanyFinancials(ticker=t, name="Air Liquide", quote_type="EQUITY", current_price=170.0))
    entry = {"ticker": "AI.PA", "name": "Air Liquide", "sector": "Materials", "region": "Europe", "country": "France",
             "indices": "CAC 40|STOXX Europe 600"}
    record = run.analyze(entry)
    assert "followed" not in record and record["indices"] == ["CAC 40", "STOXX Europe 600"]


def test_nuit_complete_ajoute_puis_retire_le_titre_suivi(monkeypatch, tmp_path):
    # Nuit 1 : Alstom en watchlist -> analysée avec Air Liquide. Nuit 2 : plus suivie -> absente de screener.json
    import json

    monkeypatch.setattr(run, "load_universe", lambda: [{"ticker": "AI.PA", "name": "Air Liquide", "sector": "Materials",
                                                         "region": "Europe", "country": "France", "indices": "CAC 40"}])
    monkeypatch.setattr(run, "fetch_prices", lambda tickers: {})
    monkeypatch.setattr(run, "fetch_company_financials",
                        lambda t: CompanyFinancials(ticker=t, name=t, quote_type="EQUITY", currency="EUR", current_price=50.0))
    monkeypatch.setattr(run.time, "sleep", lambda s: None)
    monkeypatch.setattr("sys.argv", ["run.py", "--data-dir", str(tmp_path)])

    def night(watched):
        monkeypatch.setattr(run, "load_followed", lambda previous, universe: [followed.entry(t) for t in watched])
        run.main()
        return {s["ticker"]: s for s in json.loads((tmp_path / "screener.json").read_text(encoding="utf-8"))["stocks"]}

    stocks = night(["ALO.PA"])
    assert set(stocks) == {"AI.PA", "ALO.PA"} and stocks["ALO.PA"]["followed"] and "followed" not in stocks["AI.PA"]
    assert set(night([])) == {"AI.PA"}
