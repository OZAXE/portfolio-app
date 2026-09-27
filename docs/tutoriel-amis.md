# Utiliser Portfolio Insights : guide pour les amis

Portfolio Insights suit ton portefeuille d'actions (PEA, CTO) à partir d'un Google Sheet qui t'appartient,
et l'analyse : valeur intrinsèque, score qualité, dividendes, comparaison à un indice, alertes.
L'installation prend environ 10 minutes, sans rien installer sur ton ordinateur.

## Ce qu'il faut savoir avant de commencer

- **Tes données restent dans ton Google Sheet.** L'appli le lit et y ajoute les opérations que tu saisis.
- Pour que l'appli puisse lire ton Sheet, tu le partages avec un « compte de service » (un robot Google)
  géré par la personne qui t'a invité. **Cette personne a donc techniquement accès à ton Sheet** :
  ne le fais que si tu lui fais confiance.
- L'appli n'est pas un conseil en investissement : les calculs sont automatiques et simplifiés.

## Étape 1 : copier le Sheet modèle (2 min)

1. Ouvre le **Sheet modèle** :
   https://docs.google.com/spreadsheets/d/1Cw44TPxJkpfoXUKkg4eDuDeoHIIvI-UJmzkXi2MYeZU/edit
2. Menu **Fichier > Créer une copie**, nomme-la par exemple « Mon portefeuille », puis **Créer une copie**.
   C'est ta copie qui compte désormais, garde son lien.

## Étape 2 : décrire tes comptes et tes frais (3 min)

Dans ta copie :

1. Onglet **Comptes** : une ligne par compte-titres (les deux lignes présentes sont des exemples,
   remplace-les par les tiens). Exemple :

   | Compte | Enveloppe | Courtier |
   |---|---|---|
   | PEA Boursorama | PEA | Boursorama |
   | PEA Trade Republic | PEA | Trade Republic |
   | CTO Trade Republic | CTO | Trade Republic |

   L'enveloppe doit être `PEA` ou `CTO`. Le courtier doit être écrit exactement comme dans l'onglet
   **Frais** : c'est lui qui détermine les frais proposés (un PEA et un CTO Trade Republic ont le même barème).
2. Onglet **Frais** : le barème de chaque courtier, par type d'ordre (`Ordre` ou `Plan d'investissement`,
   pour les achats programmés comme les plans Trade Republic).
   Frais d'un ordre = le plus grand entre le *minimum* et *fixe + pourcentage × montant*.
   Vérifie les valeurs sur la grille tarifaire de ton courtier : elles servent à pré-remplir les frais,
   que tu peux toujours corriger au moment de la saisie.

## Étape 3 : partager ton Sheet avec l'appli (1 min)

1. Bouton **Partager** en haut à droite de ta copie.
2. Ajoute l'adresse du compte de service qu'on t'a donnée (elle se termine par `.iam.gserviceaccount.com`),
   rôle **Éditeur**, décoche « Envoyer une notification » (le robot ne lit pas ses mails), puis **Partager**.
3. Envoie le **lien de ta copie** à la personne qui t'a invité. Elle te renverra ton **code d'accès personnel**.

## Étape 4 : ouvrir l'appli (2 min)

1. Sur ton téléphone, ouvre https://portfolio-front-8t6m.onrender.com
   (la première ouverture peut prendre jusqu'à une minute : le serveur gratuit se réveille).
2. Onglet **Réglages > Code d'accès** : colle ton code, **Enregistrer**.
3. Installe-la sur l'écran d'accueil :
   - Android (Chrome) : menu ⋮ > **Ajouter à l'écran d'accueil** ;
   - iPhone (Safari) : bouton Partager > **Sur l'écran d'accueil**.

## Étape 5 : saisir tes positions

Le plus rapide : onglet **Portefeuille**, bouton **Importer un relevé**. Choisis le compte, puis :
- **Trade Republic** : l'export CSV des transactions, sur toute la période depuis l'ouverture du compte ;
- **Boursorama** : les avis d'opéré PDF (Espace client > Documents), tous d'un coup.

L'appli affiche les opérations trouvées avant d'écrire quoi que ce soit : décoche ce que tu ne veux pas,
complète un ticker s'il manque, puis valide. Les opérations déjà présentes dans le Sheet sont repérées
et décochées.

Sinon, bouton **+ Nouvelle opération**, une ligne par achat déjà fait :
compte, date, ticker au format Yahoo (`MC.PA` pour LVMH, `AAPL` pour Apple, `SAP.DE` pour SAP…),
quantité, prix, frais. Tu peux aussi remplir directement l'onglet **Opérations** du Sheet en recopiant
une ligne existante.

L'onglet **Positions** du Sheet se calcule tout seul (quantité, PRU frais inclus, valeur, plus-value).

## Étape 6 (facultatif) : l'historique hebdomadaire

Pour que la courbe d'évolution se remplisse toute seule chaque samedi :

1. Dans ton Sheet : **Extensions > Apps Script**.
2. Remplace le contenu par celui du fichier
   [`sheet-template/historique.gs`](../sheet-template/historique.gs), puis enregistre.
3. En haut, choisis la fonction **`installerDeclencheur`** et clique sur **Exécuter**, puis accepte les
   autorisations (Paramètres avancés > Accéder au projet).

## Étape 7 (facultatif) : les notifications

Chaque nuit, l'appli peut t'envoyer tes alertes (forte baisse d'une position, action surveillée qui
passe sous sa valeur intrinsèque, alertes de prix) :

1. Installe l'appli gratuite **ntfy** (Play Store ou App Store).
2. Dans Portfolio Insights, **Réglages > Notifications** : **Générer un sujet**, puis **Enregistrer**.
3. Dans ntfy, bouton **+**, colle ce sujet et abonne-toi. **Envoyer un test** pour vérifier.

Pour une alerte de prix : ouvre la fiche d'une action, bouton **🔔 Alerte de prix**.

## En cas de souci

| Message | Solution |
|---|---|
| « code d'accès requis » | Saisis ou recolle ton code dans Réglages. |
| « Le compte de service doit être Éditeur du Google Sheet » | Refais l'étape 3 avec le rôle Éditeur. |
| « Compte inconnu » à la saisie | Ajoute le compte dans l'onglet Comptes. |
| Une position sans cours dans le Sheet | Vérifie son ticker Google dans l'onglet Titres (ex. `EPA:MC`, `NASDAQ:AAPL`). |
