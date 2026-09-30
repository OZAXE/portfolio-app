# Guide d'utilisation de Portfolio Insights

Ce guide explique comment se servir de l'appli au quotidien, onglet par onglet. Pour l'installer et créer
ton compte, suis d'abord le [guide d'installation](tutoriel-amis.md).

L'appli a quatre onglets en bas de l'écran : **Portefeuille**, **Marché**, **Briefs** et **Réglages**.

> Astuce : les mots soulignés en pointillés (PRU, PER, volatilité…) s'expliquent quand tu les touches.
> Tous sont aussi dans **Réglages > Lexique des indicateurs**.

**Sommaire**

1. [Le haut du Portefeuille](#1-le-haut-du-portefeuille)
2. [Enregistrer mes opérations](#2-enregistrer-mes-opérations)
3. [Les sous-onglets du Portefeuille](#3-les-sous-onglets-du-portefeuille) : Positions, Perf., Répartition, Revenus, Fiscalité
4. [Trouver et analyser des actions (Marché)](#4-trouver-et-analyser-des-actions-onglet-marché)
5. [Alertes et notifications](#5-alertes-et-notifications)
6. [Briefs](#6-briefs)
7. [Réglages](#7-réglages)
8. [Questions fréquentes](#questions-fréquentes)

---

## 1. Le haut du Portefeuille

### Ce que montre la carte du haut

- **Valeur des placements** : ce que valent aujourd'hui toutes tes lignes (PEA + CTO).
- La ligne verte ou rouge en dessous : ta **plus-value latente**, ce que tu gagnerais (ou perdrais) en
  vendant tout maintenant, en euros et en %, par rapport à l'argent investi.
- **Aujourd'hui** : ce que ton portefeuille a gagné ou perdu depuis la clôture précédente, en euros et en %,
  taux de change compris (cours Yahoo, rafraîchis toutes les 10 minutes environ). Un achat du jour ne compte
  que ce qu'il a gagné depuis que tu l'as fait. Le week-end, c'est la variation de la dernière séance.
- **Rendement annualisé** (ou **rendement réel** la première année) : ce qu'a rapporté ton argent, en
  tenant compte de la date de chaque versement.
- **Gain total** : plus-value + dividendes touchés + gains des ventes déjà faites.
- Une case par enveloppe (**PEA**, **CTO**) avec sa valeur et sa performance. Touche-la pour ne voir que
  les positions de cette enveloppe ; touche-la à nouveau pour tout revoir.
- **Espèces** : l'argent qui attend sur tes comptes, si tu as activé leur suivi (voir la partie 2).

Les valeurs viennent de ton Google Sheet, qui suit les cours de bourse (avec environ 20 minutes de retard).

### Mode discret

Touche l'**œil** en haut : tous les montants en euros et les quantités sont remplacés par des points
(« •••• € »), les pourcentages restent visibles. Pratique pour montrer l'appli à quelqu'un. Touche à nouveau
l'œil pour tout réafficher. Le réglage est mémorisé sur ton téléphone.

### Les quatre boutons

- **Opération** : saisir un achat, une vente, un dividende, une division, un versement… (partie 2).
- **Importer** : importer un relevé de ta banque (partie 2).
- **Transactions** : toutes tes opérations, pour les relire, les corriger ou les supprimer, et ton
  **journal** de trading (partie 2).
- **Objectifs** : aller directement à ton allocation cible (sous-onglet Répartition).

### La courbe d'évolution

- **Valeur** : l'évolution de tes placements en euros (total, PEA, CTO), avec en pointillés le montant
  **investi** de chaque enveloppe.
- **Performance** : la même chose en %.
- **Comparer au MSCI World / S&P 500 / CAC 40** : l'appli rejoue ton historique comme si chaque euro
  avait été placé le même jour dans un ETF de l'indice. Si ta courbe est au-dessus, tes choix battent
  l'indice ; en dessous, un simple ETF aurait fait mieux.
- Les **puces** sous le graphique (Total, PEA, CTO, Investi) affichent ou masquent chaque courbe.

Un point est ajouté chaque nuit après un jour de bourse, et le point du jour est pris sur tes positions
actuelles. Quand tu importes un relevé ou saisis une opération passée, la courbe est **reconstituée**
depuis la date de l'opération, avec les cours de clôture de chaque jour.

---

## 2. Enregistrer mes opérations

### Un achat, une vente ou un dividende

Bouton **Opération** :

1. Choisis le **type**, la **date** et le **compte**.
2. Tape le **titre** au format Yahoo : `MC.PA` pour LVMH, `AI.PA` pour Air Liquide, `AAPL` pour Apple,
   `SAP.DE` pour SAP, `BTC-EUR` pour le Bitcoin. La liste propose les titres que tu as déjà. Une crypto se
   range dans ton CTO ; elle n'a ni prix juste ni score.
3. Indique la **quantité** et le **prix unitaire**. Pour un titre en dollars, choisis la devise : le taux de
   change se remplit tout seul.
4. Les **frais** et **taxes** (dont la taxe sur les transactions financières de 0,4 % sur les grandes
   entreprises françaises) sont proposés d'après la grille de ta banque. Les champs en pointillés sont
   calculés : corrige-les si ton relevé indique autre chose.
5. **Enregistrer dans le Sheet**. Le portefeuille se met à jour.

Pour un **dividende** : le montant brut, et en taxes la retenue ou le prélèvement indiqué sur ton relevé.

### Une division ou des actions gratuites

Quand une entreprise divise son action (Apple : 4 pour 1 en 2020, chaque action devient 4) ou distribue des
actions gratuites (Air Liquide : 1 nouvelle pour 10 détenues en juin 2025), tu reçois des actions sans rien
payer. Sans cette saisie, ta quantité serait fausse et la ligne afficherait une grosse perte le jour même.

Bouton **Opération**, type **Division** ou **Actions gratuites**, puis le titre, le compte, la date et la
**parité** : « 4 pour 1 » pour une division, « 1 pour 10 » pour des actions gratuites, « 1 pour 10 » aussi
pour un regroupement (10 actions n'en font plus qu'une). Le nombre d'**actions reçues** est calculé sur ta
quantité actuelle : corrige-le d'après ton relevé (rompus arrondis, achats faits depuis). Le montant investi
ne change pas, ton PRU baisse d'autant. L'import CSV de Trade Republic apporte déjà les actions gratuites.

### Un versement, un retrait ou des intérêts (espèces)

Pour savoir combien d'argent attend sur chaque compte, l'appli a besoin de tes mouvements d'espèces.
Bouton **Opération**, puis le type :
- **Versement** : l'argent que tu déposes sur le compte ;
- **Retrait** : l'argent que tu retires (chez Trade Republic, un paiement par carte aussi) ;
- **Intérêts** : la rémunération de tes espèces. Mets le montant **brut**, et en **Taxes** ce que le courtier
  a déjà prélevé : l'appli en a besoin pour estimer l'impôt restant (sous-onglet Fiscalité).

Le formulaire se réduit alors à la date, au compte et au montant. Saisis **tous les versements depuis
l'ouverture du compte** : si l'appli voit que tu as acheté avec plus d'argent que tu n'en avais versé, elle
te signale le montant qui manque au minimum. Chez Trade Republic, le plus simple est d'importer l'export CSV,
qui contient déjà tout (voir ci-dessous).

### Importer un relevé de ta banque

Bouton **Importer**, choisis le compte puis le ou les fichiers :
- **Trade Republic** : relevé de compte PDF (Profil > Documents) ou **export CSV des transactions**, depuis
  l'ouverture du compte. Les deux contiennent le CTO et le PEA : chaque opération est rangée dans le compte
  de la bonne enveloppe. L'export CSV apporte en plus tes **versements, retraits, paiements par carte et
  intérêts**, regroupés par jour : ton solde d'espèces doit alors correspondre à celui de l'appli Trade
  Republic. Les actions gratuites sont importées ; une division ne l'est pas encore : saisis-la avec le
  type **Division** (voir plus haut) ;
- **Boursorama** : avis d'opéré PDF (Espace client > Documents), tous d'un coup. Ils ne contiennent pas
  les versements : saisis-les à la main pour suivre les espèces du PEA.

Touche **Analyser** : l'appli liste les opérations trouvées **sans rien écrire**. Les opérations déjà
enregistrées sont repérées et décochées (pour les espèces : même jour et même montant au centime). Décoche
ce que tu ne veux pas, complète un ticker manquant s'il est encadré en rouge, puis valide. Pour les autres
banques, utilise le bouton **Opération**.

### Relire, corriger ou supprimer une opération (Transactions)

Bouton **Transactions** : toutes tes opérations, des plus récentes aux plus anciennes, rangées par mois. Tu
peux chercher un titre ou une note, et filtrer par type (achats et ventes, dividendes, espèces, divisions) ou
par compte. **Touche une ligne** pour ouvrir sa fiche de correction : change ce qui est faux, puis
**Enregistrer**, ou **Supprimer** la ligne. Le portefeuille et la courbe sont recalculés. Si ton Sheet a été
modifié entre-temps (ligne ajoutée à la main), l'appli refuse d'écrire et te demande de recharger la liste :
elle ne touche jamais une autre ligne que celle affichée.

### Ton journal de trading

Dans la fiche d'une action, la carte **Ton journal** : écris **pourquoi** tu achètes (ta thèse), ton
**objectif** de vente et ton **stop** (le cours où tu reconnaîtrais t'être trompé), ton horizon et une date
pour **revoir** ta thèse. L'appli peut créer les **alertes de prix** correspondantes. Après une vente, note
le **bilan** : ce qui s'est passé comme prévu, ou pas. Les motifs saisis à chaque achat (« Pourquoi »,
« Terme ») sont rappelés sous la thèse.

L'onglet **Journal** de l'écran Transactions rassemble toutes tes thèses : écart du cours à l'objectif et au
stop, thèses **à revoir**, et pour un titre vendu, ce que ses ventes ont rapporté. Relire ses thèses est ce
qui fait le plus progresser.

### Supprimer des opérations en double, repartir de zéro

Ces outils rares sont dans **Réglages > Opérations avancées** :

- **Rechercher les doublons dans mes opérations** : l'appli liste les opérations en double (même titre ou
  même montant, dates à quelques jours près) et coche la copie à supprimer, de préférence celle qui vient
  d'un import. Vérifie : deux ordres identiques le même jour peuvent être réels, décoche-les alors. Elle
  propose aussi, **décochées**, les lignes de même titre et même quantité à quelques semaines d'écart, et
  repère les achats **« Date à préciser »** repris de l'ancien Sheet quand tes relevés contiennent les vrais.
- **Repartir de zéro** (aussi accessible par le lien « Tout effacer et réimporter » du panneau
  **Importer**) : efface les opérations d'un compte ou de tous, après une copie dans un onglet
  « Sauvegarde … » de ton Sheet. La case **Seulement les lignes importées** est cochée par défaut : elle
  garde tes saisies à la main et les lignes reprises de l'ancien Sheet. **Décoche-la pour tout effacer.**
  **Annuler : remettre mes opérations** remet tout comme avant.
- **Reconstituer l'historique depuis mes opérations** : recalcule toute la courbe depuis ton premier achat.

### Ajouter une banque ou corriger des frais

**Réglages > Comptes et courtiers** : ajoute un compte (ex : « PEA Fortuneo », enveloppe PEA), puis la
grille de frais de la banque, recopiée depuis sa grille tarifaire. Un compte qui a déjà des opérations ne
peut être ni supprimé ni renommé.

---

## 3. Les sous-onglets du Portefeuille

Sous la courbe, cinq sous-onglets : **Positions**, **Perf.**, **Répartition**, **Revenus**, **Fiscalité**.

### Positions

Tes lignes, triées par **Valeur**, par **Perf.** (depuis l'achat) ou par variation du **Jour**. Touche une
ligne pour ouvrir sa fiche : en tête, la carte **Ta position** (valeur, plus-value, investi, quantité, gain
total, rendement de la ligne, variation du jour et, pour un titre en devise, l'**effet du change**) et le
bouton **📈 Graphique des achats** (le cours depuis ton premier achat, avec chaque achat, chaque vente et
ton PRU). En dessous, la fiche complète de l'action (partie 4). Un ETF ou une crypto a une fiche réduite.

### Perf. : performance et risque

- **Performance par période** : 1 mois, depuis le 1er janvier, 1, 3, 5 ans et depuis le début, pour le
  total, le PEA ou le CTO, face à l'indice de ton choix (MSCI World, S&P 500, CAC 40). Elle est « pondérée
  par le temps » : tes versements ne la faussent pas, elle se compare donc directement à l'indice.
  L'écart avec l'indice est donné en points, et le gain de la période en euros.
- **Risque** (12 derniers mois) : la **volatilité** (l'amplitude habituelle des variations), la **pire
  baisse** que ton portefeuille a encaissée depuis un sommet, l'écart avec ton plus haut, le **ratio de
  Sharpe** (le rendement obtenu par unité de risque) et le **bêta** (ta sensibilité à l'indice), avec une
  phrase en clair. Il faut quelques semaines de relevés quotidiens avant qu'ils s'affichent.
- **Effet du change** (si tu as des titres cotés en dollars, livres…) : la part de ta plus-value latente qui
  vient du taux de change depuis tes achats, par devise et par ligne, et ce qui vient de l'action elle-même.
  Exemple : Apple +82 € = +164 € venus de l'action et −82 € de change, parce que le dollar a baissé.
- **Ce qui a fait ta performance** : le gain de chaque ligne sur la période choisie, en euros et en
  points. La somme des lignes donne le total.

Le calcul prend quelques secondes à la première ouverture de l'onglet (il récupère les cours de chaque
titre sur 5 ans).

### Répartition

- **Répartition** : ton portefeuille par **secteur**, **zone**, **devise** ou **poche**. **Voir à travers
  les ETF** compte le contenu réel de tes ETF (un ETF S&P 500 compte alors comme 500 entreprises
  américaines).
- **Exposition par entreprise** : tes plus grosses entreprises, en direct et via tes ETF (utile pour
  repérer si tu es trop exposé à Apple ou Nvidia sans le savoir).
- **Concentration** : le poids de chacune de tes lignes (PEA et CTO additionnés), la part de tes 5 plus
  grosses lignes et le **nombre effectif de lignes** (combien de lignes de même poids auraient la même
  diversification). Une action au-dessus de ton **plafond** (15 % par défaut, réglable : 10 à 25 %) est en rouge,
  avec ce qu'il faudrait alléger ou investir ailleurs pour y revenir ; un secteur au-dessus de 40 % (réglable)
  et une entreprise trop lourde une fois ses parts dans tes ETF ajoutées sont signalés. Les ETF ne comptent pas
  comme une ligne concentrée. Les dépassements apparaissent aussi sous la **cloche**.
- **Allocation cible** : **Définir mes cibles** crée des **poches** (ex : « ETF Monde » 60 %, « Actions
  France » 20 %, « Actions US » 20 %, total 100 %) et range chaque ligne dans une poche. Le tableau compare
  ta répartition à tes cibles, puis deux modes :
  - **Sans vendre** : tape le montant que tu vas investir, l'appli te dit combien mettre dans chaque poche ;
  - **Rééquilibrer** : ce qu'il faut acheter et vendre pour revenir exactement à tes cibles (avec un versement
    facultatif). Les ventes commencent par le PEA (pas d'impôt tant que tu ne retires rien), puis les lignes du
    CTO en moins-value, puis les moins en plus-value, et l'impôt du CTO est estimé. L'appli te prévient quand
    l'argent devrait passer d'une enveloppe à l'autre (impossible : une vente sur le PEA se réinvestit sur le PEA).
- **Espèces** : le solde de chaque compte suivi (versé, retiré, intérêts), et l'alerte si des versements
  manquent.
- **Épargne et patrimoine** : **Ajouter mon épargne** (ou **Mettre à jour mon épargne**) enregistre tes
  livrets, ton assurance-vie et ton PER : la valeur de ton dernier relevé et, si tu veux, le total versé
  pour voir ta plus-value. L'appli date chaque valeur et te rappelle de la mettre à jour après 3 mois. Le
  **patrimoine financier** additionne titres, espèces et épargne. (Ton ancien onglet **Livret** du Sheet est
  repris et devient l'onglet **Épargne**.)
- **Projection** : ce que pourrait devenir ton patrimoine avec un versement chaque mois. Choisis le point de
  départ, le versement, un rendement prudent (3 %), équilibré (5 %), dynamique (7 %) ou le tien, la durée
  et, si tu veux, un objectif. Le calcul est en euros d'aujourd'hui (inflation de 2 % retirée), avec une
  fourchette à 2 points de moins et de plus, et le revenu mensuel possible ensuite (règle des 4 %). Un ordre
  de grandeur, pas une prévision.

### Revenus

- **Dividendes à venir** : les dividendes attendus sur 12 mois, mois par mois (touche une barre pour le
  détail), et le revenu annuel estimé. L'estimation suppose que chaque entreprise versera comme l'an
  dernier. Les ETF capitalisants ne versent rien : c'est normal.
- **Résultats à venir** : les dates de publication des résultats de tes actions et de ta watchlist sur les
  45 prochains jours. Le cours bouge souvent fort ce jour-là.

### Fiscalité

- **Plus-values réalisées et dividendes** : par année et par enveloppe, les gains de tes ventes, les
  dividendes et les **intérêts** touchés. Pour le CTO, l'appli estime l'**impôt restant à payer** (flat tax
  de 31,4 % en 2026), dividende par dividende et avec les intérêts : un montant négatif est à récupérer (par
  exemple l'acompte de 12,8 % prélevé en trop sur un dividende américain chez Trade Republic). Sur le PEA,
  rien n'est imposé tant que tu ne retires pas d'argent. C'est une estimation : ton IFU fait foi.
- **Plafond PEA et frais** : ce que tu as versé sur les 150 000 € autorisés (calculé sur tes vrais
  versements s'ils sont saisis, sinon estimé d'après tes achats), les frais payés par année (courtage,
  taxes, retenues) et les frais courants de tes ETF.

---

## 4. Trouver et analyser des actions (onglet Marché)

### L'accueil du Marché

Près de 2 000 actions (grands indices américains, européens et asiatiques) analysées chaque nuit, rangées
en sections : **Tes actions**, **Ta watchlist**, **Solides et sous-évaluées**, **Les plus solides**,
**Dividendes réguliers**. **Tout voir** affiche une section en entier, et **Voir les … actions**, tout le
screener.

- **Rechercher** une action par nom ou ticker. Une action absente ? Tape son ticker Yahoo puis
  **Analyser « … » en direct**.
- **Filtres** : estimation (sous-évaluée, prix correct, chère, DCF fiable), qualité minimum, région,
  secteur, tes listes (positions, watchlist, super investisseurs), dividende en hausse depuis 5 ans, ROIC
  minimum, rendement du cash-flow libre minimum, croissance minimum, peu endettée, et le tri (qualité, potentiel
  estimé, marge de sécurité, rendement, taille, PER, ROIC, cash-flow libre, croissance). Chaque filtre actif apparaît en
  puce, que tu peux retirer d'un toucher.
- En haut à droite, **Simple** ou **Détaillé** : Détaillé ajoute les chiffres aux lignes et ouvre toutes les
  rubriques des fiches ; Simple ajoute une phrase d'explication sous chaque ratio.
- **⇄ Comparer (n)** apparaît dès que tu as choisi deux actions à comparer (voir plus bas).

### Lire la fiche d'une action

Touche une action pour l'ouvrir en plein écran (le bouton retour du téléphone la ferme) :

- **La courbe du cours** sur 1 mois à 10 ans, avec les moyennes 50 et 200 jours et le prix juste en
  pointillés (puces sous le graphique pour les afficher ou les masquer), et une phrase sur la tendance.
- **Analyse technique** : le **RSI** (au-dessus de 70, le cours a beaucoup monté très vite ; sous 30, il a
  beaucoup baissé), les moyennes 50 et 200 jours et leur dernier **croisement**, le plus haut et le plus bas
  sur un an, et le **momentum** (variation sur 1, 3, 6 et 12 mois). Ils décrivent le passé récent du cours,
  pas la valeur de l'entreprise : à croiser avec le prix juste.
- **Ton journal** : ta thèse, ton objectif et ton stop sur ce titre (partie 2).
- **À propos de l'entreprise** : sa présentation en français (traduite automatiquement, l'original anglais
  est à un toucher), son site et son effectif.
- **Actualités** : les titres des 30 derniers jours qui citent l'entreprise (Google Actualités, en
  français), avec leur source et un lien vers l'article.
- **Le verdict en une phrase** et sa jauge : l'action paraît sous-évaluée, à son juste prix ou chère.
- **Six rubriques colorées** (vert, orange, rouge) :
  - **Valorisation** : le **prix juste** et le potentiel, le **PER**, le PER prévisionnel, le **PER
    historique** (le PER habituel de l'action sur ses dernières années), le cours / valeur comptable, le
    VE / EBITDA, l'**objectif des analystes** et leur **avis**, la date des **résultats**, puis la valeur
    intrinsèque (DCF) ;
  - **Qualité** : le **score qualité sur 20** (rentabilité, marges, dette, prix, comparés au secteur ;
    au-dessus de 14, l'entreprise est solide) ;
  - **Rentabilité** : le **ROIC** (ce que rapporte chaque euro investi par les actionnaires et les prêteurs ;
    au-dessus de 15 %, l'entreprise crée beaucoup de valeur), le ROE et la marge opérationnelle ;
  - **Croissance** : hausse annuelle moyenne du **chiffre d'affaires** et du **bénéfice par action** sur 5 ans ;
  - **Santé financière** : la **dette nette / EBITDA** (en années de résultat ; sous 1,5, peu endettée), la
    **couverture des intérêts** et la dette / fonds propres ;
  - **Dividende et rachats** : rendement, régularité, croissance, historique sur 12 ans, et les **rachats
    d'actions** (l'entreprise rachète-t-elle ses actions, ou en émet-elle ?) avec le rendement total pour
    l'actionnaire.
- Puis la **watchlist**, les **alertes de prix**, l'**historique du screener** (cours, prix juste et valeur
  intrinsèque chaque semaine) et les **comptes annuels** sur plusieurs années.

**Le prix juste** est la moyenne de plusieurs estimations : le DCF, le bénéfice × le PER normal du secteur,
le bénéfice × le PER historique de l'action, et la valeur comptable pour les banques. Dans la Valorisation,
le **rendement du cash-flow libre** dit ce que l'action rapporterait si toute la trésorerie produite était
distribuée (au-dessus de 5 %, peu chère au regard de ce qu'elle produit). Cours plus de 15 % en
dessous : **sous-évaluée** ; plus de 15 % au-dessus : **chère** ; entre les deux : **prix correct**. En
italique, les méthodes divergent beaucoup. C'est une estimation automatique, avec ses limites signalées dans
la fiche quand elles concernent l'action (entreprise de qualité durablement chère, secteur cyclique, action
décotée pour de bonnes raisons) : touche **limites de la méthode** sous le prix juste pour la liste complète.

Certaines informations (PER historique, analystes, résultats, rachats, présentation) arrivent avec la
prochaine analyse de nuit de chaque action : une fiche peut ne pas encore les avoir.

Aucun indicateur ne suffit seul : une action peu chère l'est parfois pour une bonne raison.

### Comparer des actions

En haut de la fiche, **⇄ Comparer** ajoute l'action à ta comparaison (4 au plus). Dès deux actions,
**Voir la comparaison** affiche un tableau côte à côte : cours, verdict, prix juste, score qualité, PER et
PER face à son historique, rentabilité, dette, dividende, rachats, objectif des analystes, taille. La
meilleure valeur de chaque ligne est mise en couleur. **Retirer ✕** enlève une action.

### Surveiller une action (watchlist)

Dans la fiche, **☆ Surveiller** l'ajoute à ta watchlist (section **Ta watchlist** du Marché, filtre, et
agenda des résultats). Tu seras alerté si elle passe sous sa valeur intrinsèque. Touche **★ Surveillée**
pour la retirer.

### Les super investisseurs

**Marché > Super investisseurs** : ce qu'achètent et vendent 27 grands gérants (Warren Buffett, Bill
Ackman…), d'après leurs déclarations trimestrielles aux États-Unis : les plus achetés ce trimestre, les plus
détenus, et le portefeuille de chaque fonds. Ces déclarations ont jusqu'à 45 jours de retard : c'est une
source d'idées, pas un signal d'achat.

---

## 5. Alertes et notifications

### Les alertes

La **cloche** en haut du Portefeuille (un point rouge quand il y a du nouveau) : chaque jour, l'appli
signale sur tes positions et ta watchlist une forte baisse, une action qui passe sous sa valeur
intrinsèque, un score qualité en baisse, un dividende réduit ou un super investisseur qui achète ou vend.

### Les alertes de prix

Dans la fiche d'une action, **🔔 Alerte de prix** : choisis « sous » ou « au-dessus » d'un prix, avec une
note si tu veux (« renforcer sous 150 € »). Elles sont listées sous la cloche, dans **Mes alertes de prix**,
où tu peux les supprimer ou les réactiver après déclenchement. Le prix est vérifié chaque nuit sur le cours
de clôture.

### Recevoir les notifications sur ton téléphone

Configure-les dans **Réglages > Notifications ntfy** (voir le guide d'installation). Tu reçois alors chaque
nuit tes alertes, et chaque vendredi soir ta **plus-value de la semaine** (l'argent versé pendant la semaine
n'est pas compté).

---

## 6. Briefs

L'onglet **Briefs** propose chaque semaine un point sur les marchés : actualité économique, graphiques, un
sujet pour apprendre et l'agenda de la semaine.

---

## 7. Réglages

Les réglages sont rangés en rubriques ; chacune ouvre sa page :

- **Comptes et courtiers** : tes comptes (PEA, CTO) et les grilles de frais de tes banques.
- **Allocation cible** : tes poches et leurs objectifs (même éditeur que dans Répartition).
- **Opérations avancées** : doublons, repartir de zéro, reconstituer l'historique (partie 2).
- **Notifications ntfy** : ton sujet de notifications.
- **Apparence et affichage** : le thème (**Auto** suit le téléphone, **Sombre**, **Clair**, **Noir** pour les
  écrans OLED), la couleur, la taille du texte, le mode **Simple** ou **Détaillé** et l'icône de l'appli. Pour
  voir une nouvelle icône, retire l'appli de l'écran d'accueil puis ajoute-la à nouveau.
- **Hypothèses du DCF** : pour les curieux, remplace les hypothèses automatiques (croissance, actualisation,
  croissance à long terme) par les tiennes ; toutes les valeurs intrinsèques et prix justes sont recalculés.
- **Code d'accès** : à saisir une fois par appareil. Perdu ? Refais l'inscription avec le même Sheet.
- **Créer un compte** : l'inscription d'un nouvel utilisateur.
- **Lexique des indicateurs** : la définition de chaque terme, avec des repères chiffrés.
- **Guide d'utilisation** : ce guide et le guide d'installation.

---

## Questions fréquentes

**L'appli met du temps à s'ouvrir.** Le serveur gratuit s'endort après 15 minutes sans visite et met
30 secondes à une minute à se réveiller. Pendant ce temps, l'appli affiche tes dernières valeurs connues
(« Valeurs du … · mise à jour… »).

**Je ne vois pas la nouveauté annoncée.** L'appli installée garde une copie pour s'ouvrir vite : ferme-la
complètement puis rouvre-la.

**Ça marche sans réseau ?** Oui en lecture : l'appli s'ouvre et affiche tes dernières valeurs et le
screener de la veille. Il faut du réseau pour enregistrer une opération.

**Je modifie mon Sheet à la main : l'appli le voit ?** Oui : valeurs, positions et opérations en moins
d'une minute. La performance, la comparaison à un indice et les dividendes à venir, plus longs à calculer,
sont recalculés dans la journée (ou tout de suite si tu enregistres l'opération depuis l'appli).

**Mon solde d'espèces est faux.** Il manque sans doute des versements : l'appli le signale en rouge dans
Répartition > Espèces, avec le montant manquant au minimum. Chez Trade Republic, importe l'export CSV
complet depuis l'ouverture du compte.

**Une ligne n'a pas de cours.** Vérifie son ticker Google dans l'onglet Titres du Sheet
(`EPA:MC`, `NASDAQ:AAPL`…).

**Qui voit mes données ?** Toi, et techniquement l'administrateur de l'appli (dont le robot lit ton
Sheet). Les autres utilisateurs ne voient rien de ton portefeuille.

**C'est un conseil en investissement ?** Non. Les calculs sont automatiques et simplifiés : ils aident à
réfléchir, ils ne décident pas à ta place.
