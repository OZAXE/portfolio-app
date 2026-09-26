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

1. Ouvre le lien du **Sheet modèle** qu'on t'a envoyé.
2. Menu **Fichier > Créer une copie**, nomme-la par exemple « Mon portefeuille », puis **Créer une copie**.
   C'est ta copie qui compte désormais, garde son lien.

## Étape 2 : décrire tes comptes et tes frais (3 min)

Dans ta copie :

1. Onglet **Comptes** : une ligne par compte-titres. Exemple :

   | Compte | Enveloppe | Courtier |
   |---|---|---|
   | PEA Boursorama | PEA | Boursorama |
   | CTO Trade Republic | CTO | Trade Republic |

   L'enveloppe doit être `PEA` ou `CTO`.
2. Onglet **Frais** : le barème de chaque courtier, par type d'ordre (`Ordre` ou `Plan d'investissement`).
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

Dans l'onglet **Portefeuille**, bouton **+ Nouvelle opération**, une ligne par achat déjà fait :
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

## En cas de souci

| Message | Solution |
|---|---|
| « code d'accès requis » | Saisis ou recolle ton code dans Réglages. |
| « Le compte de service doit être Éditeur du Google Sheet » | Refais l'étape 3 avec le rôle Éditeur. |
| « Compte inconnu » à la saisie | Ajoute le compte dans l'onglet Comptes. |
| Une position sans cours dans le Sheet | Vérifie son ticker Google dans l'onglet Titres (ex. `EPA:MC`, `NASDAQ:AAPL`). |
