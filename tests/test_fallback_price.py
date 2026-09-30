from app.prices import fill_missing_values
from app.sheets import parse_positions_v2

HEADER = ["Ticker", "Nom", "Compte", "Enveloppe", "Quantité", "PRU €", "Investi €", "Cours", "Devise", "Taux €",
          "Valeur €", "Plus-value €", "Plus-value %", "Secteur", "Zone"]


def row(ticker, envelope, quantity, invested, value):
    return [ticker, ticker, "CTO TR", envelope, quantity, 0, invested, "", "EUR", 1, value, "", "", "", ""]


def test_valeur_recalculee_sur_le_cours_yahoo():
    # 0,0357 part à 550 € = 19,64 € ; investi 24,83 € -> -5,19 € (-20,9 %)
    lines = parse_positions_v2([HEADER, row("MWO.PA", "CTO", 0.0357, 24.83, "")])
    fill_missing_values(lines, price_eur=lambda ticker: 550.0)
    line = lines[0][0]
    assert (line.value, line.gain, line.quote_source) == (19.64, -5.19, "Yahoo")
    assert round(line.gain_pct, 3) == -0.209


def test_ligne_avec_cours_google_inchangee():
    lines = parse_positions_v2([HEADER, row("NVDA", "CTO", 1, 150, 195.19)])
    fill_missing_values(lines, price_eur=lambda ticker: 999.0)
    assert lines[0][0].value == 195.19 and lines[0][0].quote_source is None


def test_miette_de_quantite_apres_une_vente_ignoree():
    # Bitcoin acheté puis vendu en totalité : -1e-10 restant, la ligne affichait « -0,00 € »
    lines = parse_positions_v2([HEADER, row("BTC-EUR", "CTO", -1e-10, 0, -0.0000001), row("NVDA", "CTO", 0.0001, 1, 0.02)])
    assert [h.ticker for h, _ in lines] == ["NVDA"]  # une vraie petite quantité reste
