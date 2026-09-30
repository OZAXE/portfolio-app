from app.news import company_name, google_news_url, latest, mentions, parse_google_rss, parse_yahoo_search

# Extrait au format du flux RSS de Google Actualités (RSS 2.0, élément <source> et titre « Titre - Source »)
GOOGLE_RSS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<generator>NFE/5.0</generator><title>"Air Liquide" when:30d - Google Actualités</title>
<item><title>Air Liquide signe un contrat d'hydrogène en Normandie - Zonebourse</title>
<link>https://news.google.com/rss/articles/CBMiAAA?oc=5</link><guid isPermaLink="false">CBMiAAA</guid>
<pubDate>Mon, 28 Sep 2026 07:30:00 GMT</pubDate><description>&lt;a href="x"&gt;...&lt;/a&gt;</description>
<source url="https://www.zonebourse.com">Zonebourse</source></item>
<item><title>AIR LIQUIDE : objectif relevé par un analyste - Boursier.com</title>
<link>https://news.google.com/rss/articles/CBMiBBB?oc=5</link>
<pubDate>Tue, 29 Sep 2026 16:05:00 GMT</pubDate><source url="https://www.boursier.com">Boursier.com</source></item>
<item><title>Les gaz industriels face à la hausse de l'énergie - Les Echos</title>
<link>https://news.google.com/rss/articles/CBMiCCC?oc=5</link>
<pubDate>Sun, 27 Sep 2026 09:00:00 GMT</pubDate><source url="https://www.lesechos.fr">Les Echos</source></item>
</channel></rss>"""


def test_nom_d_usage_sans_forme_juridique():
    assert company_name("L'Air Liquide S.A.") == "Air Liquide"
    assert company_name("Hermès International Société en commandite par actions") == "Hermès International"
    assert company_name("Alphabet Inc. Class A") == "Alphabet"
    assert company_name("L'Oréal S.A.") == "Oréal"
    assert company_name("ASML Holding N.V.") == "ASML"


def test_titre_qui_cite_l_entreprise():
    assert mentions("HERMES : ventes en hausse", "Hermès International")  # premier mot distinctif, sans accents
    assert mentions("LVMH : le luxe ralentit", "LVMH Moët Hennessy - Louis Vuitton")
    # Premier mot générique : les deux premiers exigés
    assert mentions("SOCIETE GENERALE : rachat d'actions", "Société Générale")
    assert not mentions("La société française de transport recrute", "Société Générale")
    assert not mentions("Le trafic air repart", "Air Liquide")
    assert mentions("L'Oréal publie ses résultats", "Oréal")
    assert not mentions("Le prix des oranges flambe", "Orange")  # mot entier seulement


def test_flux_google_actualites():
    articles = latest(parse_google_rss(GOOGLE_RSS, "Air Liquide"))
    # Article sur le secteur sans le nom : écarté ; plus récent d'abord ; source retirée du titre
    assert [(a["title"], a["source"]) for a in articles] == [
        ("AIR LIQUIDE : objectif relevé par un analyste", "Boursier.com"),
        ("Air Liquide signe un contrat d'hydrogène en Normandie", "Zonebourse"),
    ]
    assert articles[0]["published"] == "2026-09-29T16:05:00+00:00"
    assert articles[0]["url"].startswith("https://news.google.com/")


def test_recherche_google_sur_le_nom_entre_guillemets():
    assert google_news_url("Air Liquide") == "https://news.google.com/rss/search?q=%22Air+Liquide%22+when%3A30d&hl=fr&gl=FR&ceid=FR:fr"


def test_secours_yahoo_et_doublons():
    data = {"news": [
        {"title": "Apple unveils new iPhone", "publisher": "Reuters", "link": "https://finance.yahoo.com/a", "providerPublishTime": 1790000000},
        {"title": "Apple Unveils New iPhone", "publisher": "AP", "link": "https://finance.yahoo.com/b", "providerPublishTime": 1789990000},
        {"title": "Nasdaq closes higher", "publisher": "Reuters", "link": "https://finance.yahoo.com/c", "providerPublishTime": 1790000100},
        {"title": "Apple sans lien sûr", "publisher": "X", "link": "javascript:alert(1)", "providerPublishTime": 1790000200},
    ]}
    articles = latest(parse_yahoo_search(data, "Apple"))
    # Même titre repris par deux sites : un seul ; sans le nom : écarté ; lien non https : écarté
    assert [(a["title"], a["source"]) for a in articles] == [("Apple unveils new iPhone", "Reuters")]
