# Utiliser Portfolio Insights : guide pour les amis

Portfolio Insights suit ton portefeuille d'actions (PEA, CTO) à partir d'un Google Sheet qui t'appartient,
et l'analyse : valeur intrinsèque, score qualité, dividendes, comparaison à un indice, alertes.
L'installation prend environ 10 minutes, sans rien installer sur ton ordinateur. C'est gratuit.

## Ce qu'il faut savoir avant de commencer

- **Tes données restent dans ton Google Sheet.** L'appli le lit et y ajoute les opérations que tu saisis.
- Pour que l'appli puisse lire ton Sheet, tu le partages avec un « compte de service » (un robot Google)
  géré par l'administrateur de l'appli. **Il a donc techniquement accès à ton Sheet** :
  ne le fais que si tu lui fais confiance.
- L'appli n'est pas un conseil en investissement : les calculs sont automatiques et simplifiés.

## Étape 1 : copier le Sheet modèle (2 min)

1. Ouvre le **Sheet modèle** :
   https://docs.google.com/spreadsheets/d/1Cw44TPxJkpfoXUKkg4eDuDeoHIIvI-UJmzkXi2MYeZU/edit
2. Menu **Fichier > Créer une copie**, nomme-la par exemple « Mon portefeuille », puis **Créer une copie**.
   C'est ta copie qui compte désormais, garde son lien. Laisse-la en accès restreint (ne la partage
   pas « à tous les utilisateurs disposant du lien »).

## Étape 2 : partager ton Sheet avec l'appli (1 min)

1. Sur ton téléphone, ouvre https://portfolio-front-8t6m.onrender.com
   (la première ouverture peut prendre jusqu'à une minute : le serveur gratuit se réveille),
   onglet **Réglages > Pas encore de compte ?** : l'adresse du robot de l'appli y est affichée
   (elle se termine par `.iam.gserviceaccount.com`).
2. Dans ta copie, bouton **Partager** en haut à droite : ajoute cette adresse, rôle **Éditeur**,
   décoche « Envoyer une notification » (le robot ne lit pas ses mails), puis **Partager**.

## Étape 3 : créer ton compte (2 min)

1. Dans l'appli, **Réglages > Pas encore de compte ?** : colle le lien de ta copie, **Vérifier mon Sheet**.
2. L'appli affiche un code (`PI-…`) : dans ton Sheet, onglet **Réglages**, colle-le dans la case à droite
   de `code_inscription`. C'est la preuve que ce Sheet est bien à toi.
3. Indique ton prénom ou un pseudo, puis **Créer mon compte**. Ton **code d'accès personnel** s'affiche
   et reste enregistré sur ce téléphone : note-le pour tes autres appareils (Réglages > Code d'accès).
   Code perdu ? Refais ces étapes avec le même Sheet, tu en recevras un nouveau.
4. Installe l'appli sur l'écran d'accueil :
   - Android (Chrome) : menu ⋮ > **Ajouter à l'écran d'accueil** ;
   - iPhone (Safari) : bouton Partager > **Sur l'écran d'accueil**.

## Étape 4 : tes comptes et tes banques (3 min)

Dans l'appli, **Réglages > Mes comptes et courtiers** :

1. **Comptes** : un compte par enveloppe et par banque, par exemple « PEA Boursorama »,
   « CTO Trade Republic », « PEA Fortuneo ». L'enveloppe est `PEA` ou `CTO`. Remplace les deux comptes
   d'exemple, puis **Enregistrer les comptes**.
2. **Frais de chaque banque** : une grille par banque et par type d'ordre (`Ordre`, ou
   `Plan d'investissement` pour les achats programmés). Frais d'un ordre = le plus grand entre le
   *minimum* et *fixe + pourcentage × montant*, plus les frais de change pour un titre en devise.
   Recopie-les depuis la grille tarifaire de ta banque : ils servent à pré-remplir les frais, que tu
   peux toujours corriger au moment de la saisie. Puis **Enregistrer les frais**.

## Étape 5 : saisir tes positions

Le plus rapide : onglet **Portefeuille**, bouton **Importer un relevé**. Choisis le compte, puis :
- **Trade Republic** : l'export CSV des transactions, sur toute la période depuis l'ouverture du compte ;
- **Boursorama** : les avis d'opéré PDF (Espace client > Documents), tous d'un coup.

L'appli affiche les opérations trouvées avant d'écrire quoi que ce soit : décoche ce que tu ne veux pas,
complète un ticker s'il manque, puis valide. Les opérations déjà présentes dans le Sheet sont repérées
et décochées.

Pour une autre banque, bouton **+ Nouvelle opération**, une ligne par achat déjà fait :
compte, date, ticker au format Yahoo (`MC.PA` pour LVMH, `AAPL` pour Apple, `SAP.DE` pour SAP…),
quantité, prix, frais.

L'onglet **Positions** du Sheet se calcule tout seul (quantité, PRU frais inclus, valeur, plus-value).

## Étape 6 (facultatif) : ton allocation cible

Onglet **Portefeuille**, section **Allocation cible** : **Définir mes cibles**. Crée tes poches
(ex : « ETF Monde » 60 %, « Actions » 40 %, total 100 %), choisis la poche de chaque ligne, puis
**Enregistrer**. L'appli compare ta répartition réelle à ces cibles et te dit où placer tes prochains
versements.

## Étape 7 (facultatif) : les notifications

Chaque nuit, l'appli peut t'envoyer tes alertes (forte baisse d'une position, action surveillée qui
passe sous sa valeur intrinsèque, alertes de prix), et chaque vendredi soir ta plus-value de la
semaine (sans compter l'argent versé entre-temps) :

1. Installe l'appli gratuite **ntfy** (Play Store ou App Store).
2. Dans Portfolio Insights, **Réglages > Notifications** : **Générer un sujet**, puis **Enregistrer**.
3. Dans ntfy, bouton **+**, colle ce sujet et abonne-toi. **Envoyer un test** pour vérifier.

Garde ce sujet pour toi : quiconque le connaît peut lire tes notifications.
Pour une alerte de prix : ouvre la fiche d'une action, bouton **🔔 Alerte de prix**.

## Et ensuite ?

Pour découvrir tout ce que fait l'appli (allocation, dividendes, screener, alertes…), lis le
[guide d'utilisation](guide-utilisation.md), aussi accessible depuis **Réglages > Aide**.

## Bon à savoir

- **L'historique se remplit tout seul** : chaque nuit après un jour de bourse, une ligne est ajoutée à
  l'onglet **Historique** de ton Sheet, et la courbe d'évolution avance.
- **Mode discret** : touche l'œil à côté de « Valeur des placements » pour flouter les montants
  (les pourcentages restent visibles), pratique pour montrer l'appli.
- **Hors ligne** : l'appli s'ouvre sans réseau et affiche tes dernières valeurs connues.

## En cas de souci

| Message | Solution |
|---|---|
| « code d'accès requis » | Saisis ou recolle ton code dans Réglages. |
| « L'appli n'a pas accès à ce Sheet » | Refais l'étape 2 : partage en Éditeur avec l'adresse du robot. |
| « Code de vérification absent ou incorrect » | Colle le code `PI-…` dans l'onglet Réglages de ton Sheet, à droite de `code_inscription`, sans espace. |
| « Le compte de service doit être Éditeur du Google Sheet » | Refais l'étape 2 avec le rôle Éditeur. |
| « Compte inconnu » à la saisie | Ajoute le compte dans Réglages > Mes comptes et courtiers. |
| Une position sans cours dans le Sheet | Vérifie son ticker Google dans l'onglet Titres (ex. `EPA:MC`, `NASDAQ:AAPL`). |
| Ligne en double chaque samedi dans Historique | Supprime l'ancien script : Sheet > Extensions > Apps Script > Déclencheurs, supprime `releveHebdo`. |
