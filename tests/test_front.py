"""Test de fumée du front (frontend/index.html) : l'appli s'ouvre sur un faux portefeuille, on parcourt les cinq
onglets et les écrans principaux, et aucune erreur JavaScript ni erreur 500 de l'API ne doit apparaître.

Sans ce test, une faute de frappe dans index.html (6 000 lignes) passait la CI : seul le backend était testé.
Lancé par la CI avec Chromium (FRONT_TESTS_REQUIRED=1 : échec si le navigateur manque, au lieu d'être ignoré).
En local : pip install playwright, puis python -m playwright install chromium (ou CHROMIUM_PATH=chemin du binaire).
Chart.js est téléchargé depuis jsDelivr ; sans accès (conteneur de dev), CHART_JS_PATH=.../chart.umd.js, sinon
le test est ignoré en local."""

import os
import re
from pathlib import Path

import pytest

import front_bench

REQUIRED = os.environ.get("FRONT_TESTS_REQUIRED") == "1"


def launch_browser(pw):
    """Chromium de Playwright, sinon celui indiqué par CHROMIUM_PATH ou préinstallé dans le conteneur de dev."""
    candidates = [None, os.environ.get("CHROMIUM_PATH"), "/opt/pw-browsers/chromium"]
    last = None
    for path in candidates:
        if path is not None and not Path(path).exists():
            continue
        try:
            return pw.chromium.launch(executable_path=path) if path else pw.chromium.launch()
        except Exception as e:  # navigateur absent ou d'une autre version
            last = e
    if REQUIRED:
        raise RuntimeError(f"Chromium introuvable : {last}")
    pytest.skip("Chromium introuvable pour le test du front")


@pytest.fixture
def app_page(monkeypatch):
    """Page de l'appli ouverte sur le faux portefeuille ; renvoie (page, erreurs JS, appels à l'API)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if REQUIRED:
            raise
        pytest.skip("playwright non installé")
    chart = front_bench.chart_js()
    if chart is None:
        if REQUIRED:
            raise RuntimeError("Chart.js injoignable (jsDelivr)")
        pytest.skip("Chart.js injoignable : donner CHART_JS_PATH")
    client, _ = front_bench.make_client(monkeypatch)
    url, server = front_bench.serve_front()
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        # Service worker bloqué : sinon il sert screener.json avant l'aiguillage du test
        context = browser.new_context(service_workers="block", viewport={"width": 390, "height": 844}, locale="fr-FR")
        page = context.new_page()
        page.set_default_timeout(20000)
        errors, api_calls = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        front_bench.route_all(page, client, api_calls, chart)
        page.goto(url)
        page.wait_for_selector("#home-content:not([hidden])")
        yield page, errors, api_calls
        browser.close()
    server.shutdown()


def visible_count(page, selector):
    return page.locator(selector).evaluate_all("(els) => els.filter((e) => e.offsetParent !== null).length")


def test_parcours_des_cinq_onglets_sans_erreur(app_page):
    page, errors, api_calls = app_page

    # Accueil : valeur (22 Air Liquide à 180 + 2 LVMH à 600 + 6 Apple à 230 $ x 0,86 = 6 346,80 €), puis
    # « À regarder » (Air Liquide pèse 62 %, thèse dont la revue est passée) et les deux tuiles des dividendes
    page.wait_for_function("document.getElementById('total-value').textContent.includes('346,80')")
    page.wait_for_selector("#alerts .watch-row")
    assert "Relire ta thèse" in page.inner_text("#alerts")
    page.wait_for_function("document.getElementById('alerts').textContent.includes('à catégoriser dans ton budget')")
    page.wait_for_selector("#home-tiles .tile")
    assert "Revenu sur 12 mois" in page.inner_text("#home-tiles")

    # Masquer une ligne de « À regarder », puis tout réafficher
    before = page.locator("#alerts .watch-row").count()
    page.click("#alerts .watch-hide >> nth=0")
    assert page.locator("#alerts .watch-row").count() == before - 1
    page.click("[data-watch-unhide]")
    assert page.locator("#alerts .watch-row").count() == before

    # Portefeuille : trois lignes, puis les sous-onglets Perf. et Répartition
    page.click("#tabbar [data-view=portfolio]")
    page.wait_for_function("document.querySelectorAll('#positions [data-position]').length === 3")
    page.click("#portfolio-tabs [data-ptab=performance]")
    page.wait_for_function("!/Chargement|Ouvre cet onglet/.test(document.getElementById('stats-periods').textContent)")
    page.click("#portfolio-tabs [data-ptab=repartition]")
    assert page.is_visible("#concentration")

    # Fiche d'une position, puis retour
    page.click("#portfolio-tabs [data-ptab=positions]")
    page.click("#positions [data-position] >> nth=0")
    page.wait_for_selector("#view-stock:not([hidden])")
    page.go_back()
    page.wait_for_selector("#view-portfolio:not([hidden])")

    # Marché : lignes du screener
    page.click("#tabbar [data-view=market]")
    page.wait_for_function("document.querySelectorAll('#view-market [data-open-stock], #view-market .mrow').length > 0")

    # Suivi : les quatre rubriques
    page.click("#tabbar [data-view=suivi]")
    page.wait_for_function("document.querySelectorAll('#tx-list [data-tx]').length > 0 || /Achat/.test(document.getElementById('tx-list').textContent)")
    for tab in ["journal", "revenus", "fiscalite"]:
        page.click(f"#suivi-tabs [data-stab={tab}]")
        assert visible_count(page, f'#view-suivi .stab[data-spane="{tab}"]') == 1
    assert "Air Liquide" in page.inner_text("#journal-list") or "AI.PA" in page.inner_text("#journal-list")

    # Plus : les pages du patrimoine s'ouvrent et se referment avec le retour du téléphone
    page.click("#tabbar [data-view=settings]")
    for name in ["patrimoine", "projection", "goals", "accounts", "appearance"]:
        page.click(f'#settings-home [data-spage="{name}"]')
        page.wait_for_selector(f'.spage[data-page="{name}"]:not([hidden])')
        page.go_back()
        page.wait_for_selector("#settings-home:not([hidden])")

    # Plus > Budget (administrateur) : s'ouvre sur le dernier mois complet (1 500 - 780 = +720 €, 48 % mis de côté),
    # une catégorie se déplie jusqu'aux opérations, le mois suivant est marqué incomplet
    page.click('#settings-home [data-spage="budget"]')
    page.wait_for_selector("#budget .bud-big")
    assert "720" in page.inner_text("#budget .bud-big") and "48 %" in page.inner_text("#budget .bud-kpis")
    assert "mois complet" in page.inner_text("#budget .bud-nav")
    page.click("#budget details.bud-cat >> nth=0")
    page.click("#budget [data-bud-ops] >> nth=0")
    assert "Agence Immo" in page.inner_text("#budget .bud-ops >> nth=0")
    page.click('#budget [data-bud-month="1"]')
    assert "Mois incomplet" in page.inner_text("#budget")
    assert "CB NOUVEAU COMMERCE" in page.inner_text("#budget")
    page.go_back()
    page.wait_for_selector("#settings-home:not([hidden])")

    # Essentiel masque l'onglet Perf., Complet le remet
    page.click("#detail-mode [data-detail=essentiel]")
    page.click("#tabbar [data-view=portfolio]")
    assert not page.is_visible("#portfolio-tabs [data-ptab=performance]")
    page.click("#tabbar [data-view=settings]")
    page.click("#detail-mode [data-detail=complet]")

    # Lien direct vers un onglet (rechargement : changer seulement le # ne relance pas la page)
    page.goto(page.url.split("#")[0] + "#suivi")
    page.reload()
    page.wait_for_selector("#view-suivi:not([hidden])")
    assert page.inner_text("#tabbar button.active").strip() == "Suivi"

    assert errors == [], f"erreurs JavaScript : {errors}"
    server_errors = [c for c in api_calls if c[2] >= 500]
    assert server_errors == [], f"erreurs 500 de l'API : {server_errors}"
    called = {re.sub(r"\?.*", "", path) for _, path, _ in api_calls}
    assert {"/portfolio/overview", "/portfolio/dividends", "/transactions", "/journal", "/budget"} <= called
