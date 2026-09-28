# Guide d'utilisation de Portfolio Insights

Ce guide explique comment se servir de l'appli au quotidien. Pour l'installer et créer ton compte,
suis d'abord le [guide d'installation](tutoriel-amis.md).

L'appli a quatre onglets en bas de l'écran : **Portefeuille**, **Marché**, **Briefs** et **Réglages**.

> Astuce : les mots soulignés en pointillés (PRU, PER, marge de sécurité…) s'expliquent quand tu
> les touches. Tous sont aussi dans **Réglages > Lexique des indicateurs**.

---

## 1. Suivre mon portefeuille

### Ce que montre le haut de la page

- **Valeur des placements** : ce que valent aujourd'hui toutes tes lignes (PEA + CTO).
- La ligne verte ou rouge en dessous : ta **plus-value latente**, c'est-à-dire ce que tu gagnerais
  (ou perdrais) en vendant tout maintenant, en euros et en %, par rapport à l'argent investi.
- **Rendement annualisé** (ou **rendement réel** la première année) : ta performance réelle, qui tient
  compte de la date de chaque versement. C'est le bon chiffre pour te comparer à un livret ou à un indice.
- **Gain total** : plus-value + dividendes touchés + gains des ventes déjà faites.
- Une case par enveloppe (**PEA**, **CTO**) avec sa valeur et sa performance.

Les valeurs viennent de ton Google Sheet, qui suit les cours de bourse (avec environ 20 minutes de retard).

### Cacher les montants (mode discret)

Touche l'**œil** en haut à droite de « Valeur des placements » : tous les montants en euros et les
quantités sont floutés, les pourcentages restent visibles. Pratique pour montrer l'appli à quelqu'un.
Touche à nouveau l'œil pour tout réafficher. Le réglage est mémorisé sur ton téléphone.

### La courbe d'évolution

- **Valeur** : l'évolution de ton patrimoine en euros (total, PEA, CTO).
- **Performance** : la même chose en %, ce qui neutralise tes versements.
- **Comparer au MSCI World / S&P 500 / CAC 40** : l'appli rejoue ton historique comme si chaque euro
  avait été placé le même jour dans un ETF de l'indice. Si ta courbe est au-dessus, tes choix battent
  l'indice ; en dessous, un simple ETF aurait fait mieux.

Un point est ajouté chaque nuit après un jour de bourse : la courbe se remplit toute seule.
Quand tu importes un relevé ou saisis une opération passée, la courbe est aussi **reconstituée**
depuis la date de l'opération, jour par jour, avec les cours de clôture de chaque jour. Le bouton
**Reconstituer l'historique depuis mes opérations** recalcule toute la courbe depuis ton premier achat.

### Le détail d'une ligne

Dans **Positions**, touche une ligne pour la déplier :
- ce que tu as investi, ton gain total et ton rendement sur cette ligne ;
- la **valeur intrinsèque** estimée, la **marge de sécurité** et le **score qualité** sur 20 (voir la partie 4) ;
- le bouton **📈 Graphique des achats** : le cours depuis ton premier achat, avec chaque achat, chaque
  vente et ton **PRU** (prix de revient moyen). Tu vois d'un coup d'œil si tu as acheté haut ou bas.

---

## 2. Enregistrer mes opérations

### Un achat, une vente ou un dividende

Onglet **Portefeuille**, bouton **+ Nouvelle opération** :

1. Choisis le **type** (Achat, Vente, Dividende), la **date** et le **compte**.
2. Tape le **titre** au format Yahoo : `MC.PA` pour LVMH, `AI.PA` pour Air Liquide, `AAPL` pour Apple,
   `SAP.DE` pour SAP, `BTC-EUR` pour le Bitcoin, `ETH-EUR` pour l'Ethereum. La liste propose les titres
   que tu as déjà. Une crypto se range dans ton CTO ; elle n'a ni valeur intrinsèque ni score.
3. Indique la **quantité** et le **prix unitaire**. Pour un titre en dollars, choisis la devise :
   le taux de change se remplit tout seul.
4. Les **frais** et **taxes** (dont la taxe sur les transactions financières de 0,4 % sur les grandes
   entreprises françaises) sont proposés d'après la grille de ta banque. Les champs en pointillés sont
   calculés : corrige-les si ton relevé indique autre chose.
5. **Enregistrer dans le Sheet**. Le portefeuille se met à jour.

Pour un **dividende** : mets le montant brut, et en taxes la retenue ou le prélèvement indiqué sur ton relevé.

### Importer un relevé de ta banque

Bouton **Importer un relevé**, choisis le compte puis le ou les fichiers :
- **Trade Republic** : relevé de compte PDF (Profil > Documents) ou export CSV des transactions, depuis
  l'ouverture du compte. Le relevé PDF contient le CTO et le PEA : chaque opération est rangée dans le
  compte de la bonne enveloppe. Il ne donne qu'un montant par ligne : les frais sont comptés 1 € par
  ordre (0 € pour un plan d'investissement) et les dividendes sont enregistrés nets de la retenue à la
  source. Les cryptos (Bitcoin, Ethereum…) sont importées ; les attributions d'actions gratuites ne le
  sont pas : saisis les actions reçues en **Achat** au prix de 0 € ;
- **Boursorama** : avis d'opéré PDF (Espace client > Documents), tous d'un coup.

Touche **Analyser** : l'appli liste les opérations trouvées **sans rien écrire**. Les opérations déjà
enregistrées sont repérées et décochées. Décoche ce que tu ne veux pas, complète un ticker manquant
s'il est encadré en rouge, puis valide. Pour les autres banques, utilise **+ Nouvelle opération**.

### Supprimer des opérations en double

Si une opération apparaît deux fois (fichier importé deux fois, opération déjà saisie à la main…) :
**Importer un relevé** puis **Rechercher les doublons dans mes opérations**. L'appli liste les
opérations en double (même titre ou même montant, dates à quelques jours près) et coche la copie à
supprimer, de préférence celle qui vient d'un import. Vérifie la liste : deux ordres identiques le même
jour peuvent être réels, décoche-les alors. **Supprimer** retire les lignes de l'onglet Opérations et
recalcule la courbe.

### Ajouter une banque ou corriger des frais

**Réglages > Mes comptes et courtiers** : ajoute un compte (ex : « PEA Fortuneo », enveloppe PEA),
puis la grille de frais de la banque, recopiée depuis sa grille tarifaire. Un compte qui a déjà des
opérations ne peut être ni supprimé ni renommé.

---

## 3. Piloter mes investissements

### Où placer mon prochain versement ? (allocation cible)

Section **Allocation cible** :

1. **Définir mes cibles** (ou **Modifier mes cibles**) : crée des **poches**, par exemple
   « ETF Monde » 60 %, « Actions France » 20 %, « Actions US » 20 % (le total doit faire 100 %).
2. Choisis la poche de chaque ligne, puis **Enregistrer**.
3. Le tableau compare ta répartition **actuelle** à ta **cible** et affiche l'**écart** en euros.
4. Tape le montant que tu vas investir dans « Je vais investir … € » : l'appli te dit combien mettre
   dans chaque poche pour te rapprocher de tes cibles, sans rien vendre.

### Ma répartition

Section **Répartition** : ton portefeuille par **secteur**, **zone** géographique, **devise** ou **poche**.
Coche **Voir à travers les ETF** pour compter le contenu réel de tes ETF (un ETF S&P 500 compte alors
comme 500 entreprises américaines). **Exposition par entreprise** montre tes plus grosses entreprises,
en direct et via tes ETF : utile pour repérer si tu es trop exposé à Apple ou Nvidia sans le savoir.

### Mes dividendes à venir

Section **Dividendes à venir** : les dividendes attendus sur 12 mois, mois par mois (touche une barre
pour le détail), le revenu annuel estimé en brut et en net d'impôt. L'estimation suppose que chaque
entreprise versera comme l'an dernier. Les ETF capitalisants ne versent rien : c'est normal.

### Frais et plafond du PEA

Section **Plafond PEA et frais** :
- **Plafond du PEA** : ce que tu as versé sur 150 000 € autorisés, et ce qu'il te reste ;
- **frais payés par année** : courtage, taxes sur les transactions, impôts sur les dividendes ;
- **frais courants des ETF** : ce que tes ETF te coûtent chaque année (en % et en euros).

### Mes plus-values réalisées et l'impôt

Section **Plus-values réalisées et dividendes** : par année et par enveloppe, les gains de tes ventes
et les dividendes touchés. Pour le CTO, l'appli estime l'impôt (flat tax de 30 %, 31,4 % à partir de
2026). Sur le PEA, rien n'est imposé tant que tu ne retires pas d'argent. C'est une estimation : ta
déclaration fait foi.

### Épargne et patrimoine

Si tu as rempli l'onglet **Livret** du Sheet (livret A, LDDS…), la section **Épargne et patrimoine**
additionne tes livrets et tes placements.

---

## 4. Trouver et analyser des actions (onglet Marché)

### Le screener

Près de 2 000 actions (grands indices américains, européens et asiatiques) analysées chaque nuit. Tu peux :
- **rechercher** une action par nom ou ticker ;
- **filtrer** par région, secteur, ou avec les boutons : **DCF fiable**, **Score ≥ 14**,
  **Mes positions**, **Super investisseurs**, **Ma watchlist**, **Dividende en hausse 5 ans** ;
- **trier** par marge de sécurité, score qualité, PER, capitalisation ou rendement du dividende.

Une action absente du screener ? Tape son ticker Yahoo puis **Analyser « … » en direct**.

### Lire la fiche d'une action

Touche une action pour l'ouvrir. Les repères essentiels :
- **Score qualité (sur 20)** : rentabilité, marges, dette et régularité, comparées aux entreprises
  du même secteur. Au-dessus de 14, c'est une entreprise solide.
- **Valeur intrinsèque** : ce que vaut l'action d'après les cash-flows futurs estimés (méthode DCF).
- **Marge de sécurité** : l'écart entre cette valeur et le cours. Positive, l'action paraît sous-évaluée ;
  négative, elle paraît chère. Ne te fie qu'aux DCF marqués **fiables** : les autres sont indicatifs.
- **PER** : le prix payé pour 1 € de bénéfice. Plus il est bas, moins l'action est chère, à comparer
  avec les entreprises du même secteur.
- **Dividende** : rendement, historique sur 12 ans, années de hausse consécutives.
- **Historique du screener** et **Comptes annuels** : l'évolution du cours, de la valeur intrinsèque,
  du chiffre d'affaires et des bénéfices sur plusieurs années.

Aucun indicateur ne suffit seul : une action peu chère l'est parfois pour une bonne raison.

### Surveiller une action (watchlist)

Dans la fiche, **☆ Surveiller** l'ajoute à ta watchlist (section **Actions surveillées** du
Portefeuille, et filtre **Ma watchlist** du screener). Tu seras alerté si elle passe sous sa valeur
intrinsèque. Touche **★ Surveillée** pour la retirer.

### Les super investisseurs

**Marché > Super investisseurs** : ce qu'achètent et vendent 27 grands gérants (Warren Buffett,
Bill Ackman…), d'après leurs déclarations trimestrielles aux États-Unis. Ces déclarations ont jusqu'à
45 jours de retard : c'est une source d'idées, pas un signal d'achat.

---

## 5. Alertes et notifications

### Les alertes automatiques

Section **Alertes** du Portefeuille : chaque jour, l'appli signale sur tes positions et ta watchlist
une forte baisse, une action qui passe sous sa valeur intrinsèque, un score qualité en baisse, un
dividende réduit ou un super investisseur qui achète ou vend.

### Les alertes de prix

Dans la fiche d'une action, **🔔 Alerte de prix** : choisis « passe sous » ou « dépasse » un prix, avec
une note si tu veux (« renforcer sous 150 € »). Elles sont listées dans **Mes alertes de prix**, où tu
peux les supprimer ou les réactiver après déclenchement. Le prix est vérifié chaque nuit sur le cours
de clôture.

### Recevoir les notifications sur ton téléphone

Configure-les dans **Réglages > Notifications** (voir le guide d'installation). Tu reçois alors chaque
nuit tes alertes, et chaque vendredi soir ta **plus-value de la semaine** (l'argent versé pendant la
semaine n'est pas compté).

---

## 6. Briefs

L'onglet **Briefs** propose chaque semaine un point sur les marchés : actualité économique, graphiques,
un sujet pour apprendre et l'agenda de la semaine.

---

## 7. Réglages

- **Apparence** : le thème (**Auto** suit le mode clair ou sombre du téléphone, **Sombre**, **Clair**,
  **Noir** pour les écrans OLED), la couleur des boutons et onglets, la taille du texte et l'icône de
  l'appli. Les gains restent en vert et les pertes en rouge quelle que soit la couleur. Pour voir la
  nouvelle icône sur l'écran d'accueil, supprime l'appli de l'écran d'accueil puis ajoute-la à nouveau.
- **Code d'accès** : à saisir une fois par appareil. Perdu ? Refais l'inscription avec le même Sheet.
- **Mes comptes et courtiers** : tes comptes et les grilles de frais de tes banques.
- **Hypothèses du DCF** : pour les curieux, remplace les hypothèses automatiques (croissance,
  taux d'actualisation) par les tiennes ; toutes les valeurs intrinsèques sont recalculées.
- **Notifications** : ton sujet ntfy.
- **Lexique des indicateurs** : la définition de chaque terme, avec des repères chiffrés.

---

## Questions fréquentes

**L'appli met du temps à s'ouvrir.** Le serveur gratuit s'endort après 15 minutes sans visite et met
30 secondes à une minute à se réveiller. Pendant ce temps, l'appli affiche tes dernières valeurs connues
(« Valeurs du … · mise à jour… »).

**Ça marche sans réseau ?** Oui en lecture : l'appli s'ouvre et affiche tes dernières valeurs et le
screener de la veille. Il faut du réseau pour enregistrer une opération.

**Je modifie mon Sheet à la main : l'appli le voit ?** Oui : valeurs, positions et opérations en moins
d'une minute. La comparaison à un indice et les dividendes à venir, plus longs à calculer, sont
recalculés dans la journée (ou tout de suite si tu enregistres l'opération depuis l'appli).

**Une ligne n'a pas de cours.** Vérifie son ticker Google dans l'onglet Titres du Sheet
(`EPA:MC`, `NASDAQ:AAPL`…).

**Qui voit mes données ?** Toi, et techniquement l'administrateur de l'appli (dont le robot lit ton
Sheet). Les autres utilisateurs ne voient rien de ton portefeuille.

**C'est un conseil en investissement ?** Non. Les calculs sont automatiques et simplifiés : ils aident
à réfléchir, ils ne décident pas à ta place.
