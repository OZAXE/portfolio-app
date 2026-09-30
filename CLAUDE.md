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

## Workflow Git (consigne d'Enzo, permanente)

- Travailler sur une branche, pousser, ouvrir une pull request vers `main` avec une description en
  français (pourquoi, ce que fait la PR, vérification).
- **Enzo autorise Claude à fusionner lui-même ses pull requests sur `main`, à chaque fois, sans
  redemander confirmation** (consigne donnée le 29/09/2026). Conditions : tests locaux verts, check
  `pytest` de la PR vert, PR sans conflit. Fusion en « merge » (pas de squash) pour garder les commits.
- La fusion met en ligne : Render redéploie l'appli depuis `main`, et le screener de la nuit tourne
  sur `main`. Le dire à Enzo après la fusion, avec ce qui change pour lui.
- Ne jamais pousser directement sur `main` sans PR, ni toucher à la branche `screener-data`.

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
     r = coût des fonds propres MEDAF, borné entre 0,3 et 3 ;
  4. (septembre 2026) BPA du dernier exercice × **PER historique de l'action** (médiane de ses 10 dernières
     années au plus, au moins 3 exercices bénéficiaires, PER > 100 écartés) : `historical_pe` dans
     `screener/financials.py`, archivé chaque semaine dans `financials/<ticker>.json` (`pe_history`), lu par le
     screener (`load_pe_history`) et par l'API pour les analyses en direct (`_pe_history`). PER d'une année = cours
     moyen de l'année civile (clôtures mensuelles Yahoo corrigées des divisions, pence ramenés en livres) ÷
     bénéfice net par action. Nombre d'actions ramené à la base actuelle (`adjusted_shares` : produit des
     divisions le plus proche du nombre d'actions actuel du screener), car les vieux 10-K ne sont pas retraités
     (Apple 2015-2017 à 5,8 milliards d'actions, 2018 et après à 20). BPA actuel = bénéfice du dernier exercice ÷
     nombre d'actions actuel du screener (l'exercice 2025 d'Air Liquide est sur l'ancienne base, 579 M d'actions,
     alors que les cours sont corrigés de l'attribution gratuite de juin 2025 : 638 M aujourd'hui) ; une division
     pendant l'exercice compte aussi dans `adjusted_shares`. Pas de
     PER historique si comptes et cotation sont dans deux devises (Shell), comme le DCF. Vérifié sur les vrais
     comptes : Apple médiane 25 ; Air Liquide autour de 29-31 selon les cours moyens retenus.
     Rachats d'actions (`shares_trend`, même base) : évolution annuelle du nombre d'actions sur 5 exercices,
     `shares_cagr` dans la fiche (Apple −3,1 %/an).
  Verdict : cours < 85 % du prix juste → sous-évaluée, > 115 % → surévaluée, sinon correcte.
  « Divergent » quand la méthode la plus haute dépasse le double de la plus basse (affiché en italique).
  Choix validés par Enzo : mix de méthodes, seuil ±15 %, affichage fiche + liste + positions.
  Limites signalées à l'utilisateur (demande d'Enzo) : avertissements ciblés dans la fiche
  (`fairCaveats` : méthodes divergentes, méthode unique, qualité ≥ 14 jugée surévaluée, cyclique ou
  score < 8 jugés sous-évalués) et entrée « Limites du prix juste » du lexique, liée sous chaque prix
  juste. Toute nouvelle limite identifiée doit y être ajoutée.
  Limite principale : les entreprises de qualité durablement chères (Air Liquide, Hermès) ressortent
  surévaluées face au PER moyen de leur secteur ; la méthode 4 (PER historique) corrige en partie ce biais,
  au prix d'une autre hypothèse (le marché payait l'action au bon prix en moyenne sur 10 ans). Les fiches ne
  l'ont qu'après le passage de `financials.py` (400 actions par nuit) puis la réanalyse suivante.
- **DCF** : deux phases, croissance qui décroît vers 2 %, FCF moyenné sur 3 ans, actualisation MEDAF
  bornée 7-11 %, non calculé pour banques / assurances / ETF.

- **Import Trade Republic (septembre 2026).** L'export CSV donne l'enveloppe dans `account_type`
  (`PEA`, ou `DEFAULT` = CTO) : chaque opération reçoit son enveloppe et `route_accounts` la range dans
  un compte de cette enveloppe (de préférence même courtier), comme pour le relevé PDF. Sans compte de
  cette enveloppe, statut `no_account` et import bloqué. Opérations sur titres (`CORPORATE_ACTION`, ex.
  actions gratuites Air Liquide) signalées, à saisir à la main. Dividende : `amount` = brut converti en
  euros (vérifié sur Meta : 0,528 $ par action), `tax` = toutes les retenues (pays d'origine + France).
- **Impôt estimé du CTO** (`realized.py`, `dividend_tax`) = impôt **restant à payer** (négatif :
  à récupérer, affiché comme tel) : plus-values positives × flat tax + somme, dividende par dividende, de
  (dû − prélevé en France). La colonne Taxes (un seul total, comme l'export Trade Republic) est séparée
  ainsi : un établissement français prélève soit rien, soit les prélèvements sociaux seuls (dispense
  d'acompte), soit en plus l'acompte de 12,8 % ; on garde le plus grand de ces montants qui laisse au
  pays d'origine au moins le taux de la convention, le reste est la retenue étrangère. Dû = prélèvements
  sociaux + max(0, 12,8 % − min(retenue étrangère, taux de la convention)). Taux de la convention par
  place de cotation (`treaty_credit`) : 15 % par défaut, 10 % Japon / Taïwan, 0 France / Royaume-Uni /
  Hong Kong et ETF cotés en Europe (irlandais ou luxembourgeois). Choix d'Enzo : calcul « carré » sans
  toucher au Sheet (pas de colonne retenue étrangère : ni l'export ni les amis ne l'auraient).
  Conséquence : chez Trade Republic, l'acompte de 12,8 % prélevé sur un dividende américain est en trop
  et ressort « à récupérer ». Limites : un ADR (TSMC) est compté américain, et sur quelques centimes
  l'arrondi peut faire hésiter entre deux cas.

- **Onglet Positions : une ligne par titre et par compte** (septembre 2026). Avant, une ligne par ticker :
  une action sur le PEA et le CTO était additionnée et rangée dans l'enveloppe du premier compte. Les
  formules (`POSITION_FORMULAS`) trient les couples « ticker|compte » et les coupent en A et C ; quantité
  et PRU filtrent aussi sur le compte. Les anciens Sheets sont mis à niveau à la première lecture
  (`ensure_position_formulas`, une vérification par Sheet et par démarrage). Côté appli, un même ticker
  peut donc avoir deux lignes : rendement par ligne dans `returns.positions_by_envelope`, dédoublonner
  ce qui est rangé par titre (poche de l'Allocation, frais courants des ETF).
  PRU (octobre 2026, bug signalé par Enzo sur Alphabet C) : la colonne F rejoue les opérations dans l'ordre
  (`REDUCE` sur quantité / coût, comme `history.reconstruct` et `realized.py`) ; avant, elle moyennait tous les
  achats, donc une ligne vendue puis rachetée gardait l'ancien PRU (+52 % affichés au lieu de +2 %). Anciens
  Sheets mis à niveau par `ensure_position_formulas` (`is_old_pru_formula`). Pas de nombre décimal dans les
  formules (séparateur selon la région du Sheet).

- **Courbe du portefeuille** : l'onglet Historique s'arrête à la veille (relevé nocturne après chaque
  jour de bourse, « Reconstituer l'historique » jusqu'à hier). Le front ajoute un point « en direct »
  pris sur les positions actuelles (`withLivePoint`), sinon une vente du jour (Evan, 29/09) laissait la
  courbe au-dessus de la valeur affichée en haut jusqu'au relevé de la nuit.
  Puces sous le graphique (Total, PEA, CTO, Investi ; en comparaison à un indice : portefeuille, indice,
  montant investi), même mécanisme que la fiche (`lineChip`, `settings.hiddenLines`). « Investi » (demande
  d'Enzo) = colonnes investi de l'onglet Historique (prix payé pour les titres détenus ce jour-là, frais
  compris, pas les versements en espèces que l'appli ne suit pas) : une courbe en pointillés par enveloppe
  affichée, de sa couleur ; grisée en mode Performance et sur un historique à l'ancien format.

- **Secteur et zone des titres** : pris dans le screener (`sector`, `country`) à la saisie manuelle et à
  l'import (`write_import(profiles=...)`). Les titres importés avant (secteur vide, « Non classé ») sont
  complétés à l'affichage par `fill_sectors` sans écrire dans le Sheet ; un ETF hors screener est rangé
  « ETF (plusieurs secteurs) ». Un titre absent du screener (ADR comme TSMC) reste à compléter à la main
  dans l'onglet Titres.

- **Interface (septembre 2026, maquette validée par Enzo).** Inspirée des applis bancaires et d'analyse :
  - Marché : accueil en sections (`MARKET_PRESETS` : Tes actions, Ta watchlist, Solides et sous-évaluées, Les
    plus solides, Dividendes réguliers), recherche + panneau de filtres (`renderFilterSheet`, puces supprimables),
    lignes `marketRow` (logo, cours, verdict en mots via `verdictPill`, qualité en mots) ;
  - mode Simple / Détaillé (`settings.marketDensity`) : Détaillé ajoute les chiffres aux lignes et ouvre toutes
    les rubriques des fiches, Simple ajoute une phrase d'explication sous chaque ratio ;
  - fiche action plein écran (`openStock`, vue `view-stock`, retour du téléphone géré par `history.pushState`) :
    verdict en une phrase + jauge (`fairSummary`), puis 5 rubriques colorées (`pillar` : Valorisation, Qualité,
    Rentabilité, Santé financière, Dividende ; seuils dans le lexique). Depuis une position, carte « Ta position »
    en tête (`positionCard`) ; ETF et crypto ont une fiche réduite (`minimal`) ;
  - Portefeuille : cloche des alertes, 3 boutons d'action, courbe, puis sous-onglets Positions / Répartition /
    Revenus / Fiscalité (`showPortfolioTab`) ; cartes PEA / CTO = filtre des positions ;
  - Réglages : rubriques groupées ouvrant chacune leur page (`openSettingsPage`) ; outils rares (doublons,
    repartir de zéro, reconstituer l'historique) dans « Opérations avancées » ;
  - logos (`logoUrls`) : dépôt nvstly/icons via jsDelivr pour les tickers américains, les cryptos et les ADR
    vérifiés (`ADR_LOGOS`), puis Financial Modeling Prep (couvre aussi Paris : Air Liquide, LVMH vérifiés
    par Enzo), puis initiales (`logoFallback`). Jamais de correspondance devinée (« AI » = C3.ai, pas Air
    Liquide). Affichés en entier (`object-fit: contain`, marge plus large si pas carrés) ; un logo blanc sur
    fond transparent (Apple, Amazon, Visa) reçoit un fond sombre (`isLightLogo` lit ses pixels, possible
    seulement avec CORS : `crossorigin` pour jsDelivr, retiré pour l'autre source) ;
  - Super investisseurs : mêmes lignes que le Marché (`investorRow`), fonds en cartes dépliables ;
  - mode discret : des points (« •••• € ») à la place du flou, préférés par Enzo. Tout montant affiché doit
    passer par `eur.format` ou `hideable(texte, masque)` pour être masqué ;
  - l'appli installée sert sa dernière copie si le réseau met plus de 4 s (`service-worker.js`) : juste après
    une mise en ligne, fermer et rouvrir l'appli pour voir la nouvelle version.
  Pour tester le front : servir `frontend/`, intercepter l'API (réponses générées avec les fonctions du backend)
  et le screener avec Playwright, comme décrit dans « Commandes ».

- **Courbe de cours et présentation de la fiche (septembre 2026, demande d'Enzo).**
  - Courbe en tête de fiche (`priceChartBlock`, `drawPriceChart`) : 10 ans de clôtures quotidiennes via
    l'API `/prices/{ticker}` (`prices.py`, API chart de Yahoo, qui répond sur Render ; gardées 6 h). Cours non
    ajustés des dividendes (comme un courtier), divisions corrigées, pence de Londres ramenés en livres
    (`MINOR_CURRENCIES`). Périodes 1M à 10A mémorisées (`settings.pricePeriod`), variation colorée sur la
    période, moyenne 200 jours et phrase de tendance (±2 % autour de la moyenne = « sans tendance
    nette »), prix juste actuel en pointillés seulement s'il reste entre 0,8 × le plus bas et 1,25 × le plus
    haut de la période (sinon il écraserait la courbe : cité dans la légende).
  - Puces sous les graphiques de la fiche (`lineChip`, choix d'Enzo) pour afficher / masquer chaque courbe :
    moyenne 200 j (allumable sur toutes les périodes) et prix juste sur la courbe de cours ; cours, prix juste
    et valeur intrinsèque sur l'historique du screener (remplacent la légende Chart.js). Une courbe éteinte
    le reste sur toutes les fiches (`settings.hiddenLines`). Puce grisée quand la courbe ne peut pas être
    tracée (prix juste trop loin de la courbe, pas encore relevé dans l'historique). Aussi sur la fiche réduite
    (ETF, crypto) avec le ticker Yahoo.
  - Présentation (`loadProfile`) : `longBusinessSummary` de Yahoo, en anglais, avec site et effectif, lien
    « Traduire en français » (Google Traduction). Seulement via quoteSummary, donc archivée par le screener
    dans `profiles/<ticker>.json` (un fichier par action : dans screener.json elle triplerait sa taille) ; un
    fichier n'est remplacé que par une présentation non vide. Une analyse en direct l'apporte directement.
    Les fiches se remplissent au fil des réanalyses (3-4 jours pour tout l'univers).
    En français (octobre 2026, demande d'Enzo) : `screener/translate_profiles.py`, étape du workflow de nuit (800
    par nuit, 20 min), traduit par l'API publique de Google Traduction (`translate_a/single`, client gtx, gratuite
    et sans clé, morceaux de 1 500 caractères coupés entre deux phrases) et range `summary_fr` + `summary_fr_of`
    (empreinte du texte anglais traduit) dans le même fichier. `save_profile` garde la traduction tant que le texte
    anglais ne change pas (`keep_translation`), sinon chaque réanalyse l'effacerait. La fiche lit d'abord le
    fichier archivé (seul à avoir le français), original anglais repliable ; sans traduction, anglais + lien.
    Service injoignable depuis le conteneur de dev : vérifier le premier passage de nuit.

- **Prix juste dans l'historique hebdomadaire (septembre 2026).** 6e valeur des relevés de `history.json`
  (`update_history`), calculée avec les hypothèses standard ; les relevés plus anciens restent à 5 valeurs et
  le front lit `p[5] ?? null`. Graphique « Historique du screener » : cours, prix juste (bleu, tirets) et
  valeur intrinsèque (orange, pointillés).

- **Performance et risque (septembre 2026, demande d'Enzo, sous-onglet « Perf. » du Portefeuille).** `stats.py`,
  route `/portfolio/stats?benchmark=` (gardée 6 h, recalculée après chaque écriture dans le Sheet), chargée à la
  première ouverture de l'onglet (cours Yahoo de chaque titre sur 5 ans).
  - Périodes (1 mois, depuis le 1er janvier = depuis la clôture du 31/12, 1, 3, 5 ans, début) en performance
    **pondérée par le temps** (TWR) : rendement du jour = (valeur − flux du jour) / valeur de la veille − 1, flux =
    achats (+), ventes et dividendes (−). Le dividende est donc un gain, comme dans un indice dividendes réinvestis.
    Base = onglet Historique + point du jour tiré des positions (comme `withLivePoint`). Période indisponible si
    l'historique commence après sa date de départ. Gain en euros = valeur fin − valeur début − flux.
    Le TRI (`returns.py`) reste affiché en haut : il répond à « combien a rapporté mon argent ».
  - Risque sur 12 mois : volatilité (écart-type quotidien × √252, seulement les écarts ≤ 5 jours entre relevés,
    au moins 40), Sharpe (taux sans risque 2 %, au moins 6 mois d'historique), bêta face à l'indice choisi ; pire
    baisse et baisse actuelle depuis le début, les mêmes pour l'indice.
  - Contribution par ligne (enveloppe, titre) : gain = valeur actuelle − quantité au départ × clôture Yahoo en euros
    − flux ; en points = gain / capital moyen de Dietz modifié du portefeuille (la somme des lignes = total). Cours de
    départ manquant : ligne signalée (`missing`), comptée comme achetée pendant la période.

- **Analyse d'actions (septembre 2026, demande d'Enzo).**
  - Consensus des analystes et date des résultats (`_fill_consensus` dans `data.py`, quoteSummary seulement, donc
    surtout via le screener) : objectif moyen / bas / haut ramenés en unité principale (pence -> livres), ignorés
    hors de 0,2 à 5 fois le cours ou sous 3 analystes ; recommandation moyenne 1 à 5. Champs du screener
    `target_price`, `target_low`, `target_high`, `recommendation`, `analyst_count`, `earnings_date`. Potentiel vs
    cours recalculé dans le front (le cours change chaque nuit). Lignes de la Valorisation (`consensusRows`) et
    carte « Résultats à venir » (onglet Revenus : positions + watchlist, 45 jours devant, 7 derrière).
  - Comparaison côte à côte (`renderCompare`, vue `view-compare`) : bouton « ⇄ Comparer » en haut de la fiche,
    4 actions au plus (`settings.compare`, la plus ancienne sort), meilleure valeur de chaque ligne en couleur
    d'accent (pas en vert : « −21 % » n'est pas une bonne nouvelle parce que c'est le moins pire), noms courts
    (`shortName` retire les formes juridiques). Raccourci « Comparer (n) » dans le Marché.

- **Espèces (septembre 2026, choix d'Enzo : versements dans Opérations).** Types `Versement`, `Retrait`,
  `Intérêts` dans l'onglet Opérations (`CASH_TYPES`, `cash_row` : sans ticker, quantité 1, montant en prix
  unitaire, formules des montants gardées). Liste stricte de la colonne Type complétée à la première écriture
  (`ensure_operation_types`). Lus à part (`Ledger.cash`, `read_cash`) : `Ledger.operations` ne contient que
  achats / ventes / dividendes, sinon le TRI et la performance prendraient un versement pour un dividende.
  Solde (`cash.py`) = versements − retraits + intérêts − achats + ventes + dividendes, pour les comptes ayant
  au moins un versement ; le plus bas solde négatif = versements manquants (compte « incomplet », non compté).
  Plafond PEA sur les versements réels quand il y en a (`pea_deposits`), sinon estimé d'après les achats.
  Import CSV Trade Republic : catégorie CASH (hors dividendes) regroupée par jour, enveloppe et sens (le compte
  titres TR est aussi un compte courant : cartes, virements) ; doublon d'espèces = même jour et même montant au
  centime. Les espèces ne sont pas dans l'onglet Historique ni dans la performance (titres seulement).
  Intérêts (octobre 2026, demande d'Enzo) : montant **brut** en prix unitaire et prélèvements du courtier en
  Taxes (net = brut − taxes) ; `CashMovement.gross` / `taxes`. Impôt du CTO (`compute_realized(cash=...)`) :
  + brut × flat tax de l'année − prélevé (`interest_tax_remaining`), intérêts du PEA ignorés. Les intérêts
  importés avant étaient nets : doublon reconnu sur le brut ou le net (`Entry.net`).

- **Patrimoine et projection (septembre 2026, choix d'Enzo : assurance-vie et PER en valeur saisie à la main).**
  Onglet `Épargne` (`SAVINGS_HEADERS` : nom, montant, type Livret / Assurance-vie / PER / Autre, versé, mis à
  jour) ; l'ancien onglet `Livret` reste lu (nom et montant seulement, autres colonnes ignorées) et est renommé
  et complété à la première sauvegarde depuis l'appli (`save_savings`, route `/savings`). Éditeur dans
  Répartition > Épargne et patrimoine : la date de la valeur passe à aujourd'hui quand la valeur change, rappel
  après 90 jours. Patrimoine financier = titres + espèces + épargne.
  Projection (front seul, `projectValues`) : capital de départ + versement mensuel, rendement constant
  capitalisé chaque mois, en euros d'aujourd'hui par défaut ((1 + r) / 1,02 − 1), scénarios à ±2 points (ordre
  de grandeur, pas une probabilité), objectif facultatif, revenu possible par la règle des 4 %. Réglages dans
  `settings.projection`. Montants arrondis à l'euro.
  Hausse du versement (octobre 2026, demande d'Enzo) : `settings.projection.raise`, % par an appliqué chaque
  année (`monthlyAt` : 200 € à +3 % -> 269 € la 11e année), diminué de l'inflation en euros d'aujourd'hui comme
  le rendement ; total versé par année dans `paidValues`. Choisi plutôt que des paliers (saisie plus lourde).

- **Actualités de la fiche (octobre 2026, demande d'Enzo).** `news.py`, route `/news/{ticker}?name=` (gardée
  1 h, échecs non gardés) : flux RSS de Google Actualités en français (`"<nom>" when:30d`), sinon recherche Yahoo
  (anglais). Nom d'usage sans forme juridique (`company_name`) ; un titre n'est gardé que s'il cite l'entreprise
  (`mentions` : premier mot du nom s'il est distinctif, sinon les deux premiers : « Air Liquide », « Société
  Générale »), liens https seulement, doublons de titres retirés, 8 au plus. Rubrique repliée sous « À propos »
  (`loadNews`). Google et Yahoo étant bloqués depuis le conteneur de dev, lecteurs testés sur des extraits au
  format des flux : vérifier sur l'appli en ligne après une mise en ligne.

- **Cours de secours (octobre 2026).** GOOGLEFINANCE ne connaît pas tous les ETF européens (Amundi MSCI
  World IT, LU0533033667, offert par Trade Republic) : la ligne restait à « N/A », hors du total, et le relevé de
  nuit (`snapshot_totals`) refusait tout le relevé, donc la courbe n'avançait plus. `fill_missing_values`
  (`prices.py`) valorise une ligne sans cours sur la dernière clôture Yahoo en euros (`yahoo_price_eur`, gardée
  1 h) dans l'aperçu, le rendement et le relevé ; `quote_source = "Yahoo"` affiché « cours Yahoo » sur la
  ligne. Sans cours Yahoo non plus, pas de relevé (jour manquant plutôt que total faux). Quantités sous 1e-9
  ignorées (`QUANTITY_EPSILON` : Bitcoin vendu en totalité à « -0,00 € »).

- **Divisions et actions gratuites (octobre 2026, compte-rendu « ce qui manque » validé par Enzo).** Types
  `Division` et `Actions gratuites` (`workbook.SHARE_TYPES`) : colonne Quantité = actions reçues (négative pour un
  regroupement), prix 0, montant net 0. Formules Positions : E2 les ajoute, F2 les passe dans la branche achat
  (quantité en plus, coût inchangé) ; anciens Sheets mis à niveau par `ensure_position_formulas`
  (`is_old_quantity_formula`). Côté Python, **deux listes** dans le `Ledger` :
  - `operations` = `apply_splits(raw)` : sans divisions, quantités d'avant chaque division ramenées sur la base
    d'aujourd'hui (rapport = (détenu + reçu) / détenu, par compte). Pour les montants (PRU, plus-values, TRI,
    espèces, dividendes à venir) et les calculs sur cours **corrigés** des divisions (`download_closes` : comparaison
    à un indice, graphique des achats) ;
  - `raw` = telles que saisies, divisions comprises : pour les calculs sur cours **réels** (`eur_closes` remet les
    cours non corrigés via `unsplit` : `history.reconstruct`, contributions de `stats.py`) et pour les doublons à
    l'import (`read_operations(raw=True)`). Ne pas mélanger : quantités ramenées x cours réels = faux avant la division.
  Saisie (`_add_shares`) : titre détenu dans ce compte à cette date ; le formulaire calcule les actions reçues depuis
  la parité et la quantité actuelle (`/settings` renvoie `holdings`). Import CSV Trade Republic : `BONUS_ISSUE`
  -> Actions gratuites (`shares` = actions reçues) ; autres `CORPORATE_ACTION` (format inconnu) toujours signalées.
- **Écran Transactions (octobre 2026).** Bouton du Portefeuille, vue `view-transactions` (`transactions.py`, routes
  `/transactions`, `/transactions/update`, `/transactions/delete`). Une ligne = son numéro dans l'onglet + son
  empreinte (`fingerprint` : date, type, titre, quantité, prix) ; le serveur refuse si la ligne ne correspond plus
  (Sheet modifié à la main entre-temps). Correction = `add_operation(row=...)`, mêmes contrôles que la saisie, la
  ligne corrigée exclue du calcul de la quantité détenue. Après écriture : courbe reconstituée depuis la plus
  ancienne des deux dates. Retour du téléphone : `popstate` ignoré quand on retombe sur l'entrée `{transactions}`
  (fiche ouverte depuis le journal).
- **Variation du jour et effet du change (octobre 2026).** `daily.py`, route `/portfolio/daily` (10 min). Variation
  = valeur de l'onglet Positions x variation Yahoo des deux dernières clôtures (titre et taux de change), corrigée
  des achats / ventes de la séance (`line_day_change`). Effet du change = valeur x (1 - taux payé / taux actuel),
  taux payé = coût en euros / coût en devise, chaque achat converti au taux Yahoo de son jour (les imports TR sont en
  euros sans taux). Seule la devise de **cotation** compte (un ETF en euros n'en a pas). `HoldingLine.quantity`
  ajouté (onglet Positions). Front : ligne « Aujourd'hui » (`renderDaily`), tri « Jour » des positions (`dailyKey` =
  enveloppe|ticker), cases de la carte « Ta position », carte « Effet du change » de l'onglet Perf.
  Limite : une ligne vendue en totalité dans la séance n'est plus dans Positions, donc pas comptée.
- **Journal de trading et analyse technique (octobre 2026).** `journal.py`, onglet « Journal » créé au premier
  enregistrement, une ligne par titre (thèse, objectif, stop dans la devise de cotation, horizon, date de revue,
  bilan) ; routes `/journal`. Carte « Ton journal » dans la fiche (`renderJournalCard`, écarts au cours, motifs
  Pourquoi / Terme des opérations), alertes de prix proposées sur l'objectif et le stop (`journalAlerts`, sans
  doublon), onglet Journal de l'écran Transactions (`renderJournalList`). Analyse technique calculée dans le front
  sur les clôtures de `/prices` (`technicals` : RSI de Wilder 14 j, moyennes 50 / 200 j et dernier croisement sur
  un an, plus haut / bas sur 252 séances, momentum 1 / 3 / 6 / 12 mois), rubrique `pillar` sous la courbe, puce
  « Moyenne 50 j ». Ton prudent : jamais un signal d'achat ou de vente.

- **Ratios complémentaires du screener (octobre 2026, demande d'Enzo).** `metrics.py` (fonctions pures, bornées :
  hors bornes -> None). Depuis les comptes archivés par `financials.py` (`archive_metrics(years)`) : **ROIC** = résultat
  opérationnel x (1 - impôt effectif, 25 % par défaut, borné 0-50 %) / (fonds propres + dettes long et court terme -
  trésorerie), dette absente = 0, pas de ROIC si capital investi <= 0 ; médiane sur 5 exercices (au moins 3) ;
  **couverture des intérêts** ; **croissance du chiffre d'affaires** (`cagr` : 5 ans, sinon 3 au moins, départ et fin
  positifs). **Croissance du BPA** dans `historical_pe` (`eps_cagr`, BPA de chaque exercice sur la base d'actions
  actuelle via `adjusted_shares`). Depuis Yahoo du jour : **dette nette / EBITDA** (`CompanyFinancials.ebitda`, converti
  avec la dette) et **rendement du cash-flow libre** : on garde `fcf_per_share` (cash-flow libre / (capitalisation /
  cours), devise de cotation seulement) et le rendement est recalculé avec le cours (`refresh_with_price`,
  `fcfYieldOf` dans le front). Banques / assurances : seulement la croissance. Nouvelles lignes archivées
  (`short_term_debt`, `cash`, `pretax_income`, `income_tax`, `interest_expense`) : le ROIC et la couverture n'existent
  qu'après le prochain passage hebdomadaire de l'action dans `financials.py` puis sa réanalyse. `evaluate_company(cf,
  pe_history, years)` ; l'API lit l'archive entière (`_archive`). Front : rubrique **Croissance**, ROIC prioritaire sur
  le ROE pour la couleur de Rentabilité, dette nette / EBITDA prioritaire sur dette / fonds propres pour la Santé
  financière (seuils 1,5 / 3 : `NET_DEBT_LOW/HIGH`), filtres et tris du screener, lignes de la comparaison, lexique.
  Le score qualité sur 20 n'a pas changé (recalibrer ses paliers serait un autre chantier).

- **Concentration et rééquilibrage (octobre 2026, demande d'Enzo).** Tout dans le front, sans toucher au Sheet.
  Concentration (`concentrationOf`, carte de l'onglet Répartition, `renderConcentration`) : poids par titre, PEA et
  CTO additionnés (`holdingsByTitle`) ; plafonds sur l'appareil (`settings.concentration`, 15 % par action, 40 % par
  secteur) ; un ETF n'est jamais une ligne concentrée ; secteurs avec le contenu des ETF quand il est chargé
  (`lookthroughRows`) ; entreprise trop lourde en direct + via les ETF (`companyExposure`, extrait de `renderExposure`) ;
  nombre effectif de lignes = 1 / somme des poids² sur les actions en direct ; `trimSuggestion` (vendre l'excédent
  réinvesti ailleurs, ou investir ailleurs sans vendre) ; phrase quand le plafond est inatteignable faute de lignes.
  Alertes sous la cloche (`concentrationAlerts`, regroupées au-delà de 2 lignes) fusionnées avec celles du serveur
  (`renderAlertsList`, `serverAlerts`). Rééquilibrage (`rebalancePlan`, mode « Rééquilibrer » de l'allocation,
  `settings.allocMode`) : écart = cible x (valeur des poches ciblées + versement) - valeur ; ventes d'une poche dans
  l'ordre PEA, CTO en moins-value, CTO du plus petit au plus grand % de plus-value (`sellOrder`) ; impôt = plus-values
  nettes des ventes du CTO x PFU ; avertissement quand une poche à acheter n'a de lignes que dans une autre enveloppe
  que les ventes. Poches sans cible exclues. Écart sous 1 % du portefeuille marqué facultatif.

- **Rendement sur PRU et revenu annuel (octobre 2026, demande d'Enzo).** `compute_calendar` renvoie `lines` (revenu
  projeté sur 12 mois par enveloppe et titre, dividende par action en devise de cotation). Front, onglet Revenus :
  carte « Rendement de tes lignes » (`renderYieldCard` : revenu / investi = sur PRU, revenu / valeur = au cours, par
  ligne via `holdingOf` ; revenu dans 5 ans = somme des revenus x (1 + croissance du dividende sur 5 ans du screener,
  bornée à ±20 %, 0 si inconnue)^5) et « Revenu annuel » (`renderIncomeCard` : dividendes et intérêts bruts perçus par
  année d'après `/portfolio/realized`, 8 ans au plus, plus la projection des 12 mois ; croissance de la dernière année
  complète sur la précédente).

## Tester le front (banc Playwright)

Le conteneur de dev n'atteint ni Yahoo ni jsDelivr : Chart.js se récupère par `npm pack chart.js@4.4.4`, le
`screener.json` par raw.githubusercontent. Le plus fiable : vraie API (`TestClient(main.app)`) sur un faux Sheet en
mémoire (patcher `sheets.sheets_client` et `workbook.sheets_client`, `main.resolve`), `performance.download_closes` et
`prices.fetch_price_history` remplacés par des cours synthétiques, requêtes vers l'API Render redirigées vers le
TestClient par `page.route`. Créer le contexte avec `service_workers="block"`, sinon le service worker intercepte
`screener.json` avant Playwright (« Screener pas encore disponible »).

## Pistes non faites

- Notification ntfy quand une action suivie passe « sous-évaluée » au sens du prix juste
  (aujourd'hui les alertes se basent sur la valeur intrinsèque seule, voir `screener/notify.py`).
- Suite du compte-rendu d'octobre 2026 (points non retenus pour l'instant) : moins-values reportables dans l'impôt
  du CTO (Enzo n'en a pas encore), intégrer ROIC / cash-flow libre au score qualité, notification ntfy de
  concentration (aujourd'hui seulement sous la cloche), rééquilibrage par enveloppe, export CSV / récap fiscal, momentum
  comme filtre du screener, import des divisions Trade Republic (format du CSV à observer sur un vrai cas).
- Tracer le prix juste hebdomadaire sur la courbe de cours de la fiche (aujourd'hui seulement le prix juste
  actuel, en ligne horizontale), une fois l'historique assez long pour être utile.
