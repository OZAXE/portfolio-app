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

Le plus simple : une fois ton compte créé (étape 4), dans l'appli, **Réglages > Mes comptes et courtiers**.
Tu peux y ajouter n'importe quelle banque. Sinon, directement dans ta copie :

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

1. Sur ton téléphone, ouvre https://portfolio-front-8t6m.onrender.com
   (la première ouverture peut prendre jusqu'à une minute : le serveur gratuit se réveille),
   onglet **Réglages > Pas encore de compte ?** : l'adresse du robot de l'appli y est affichée
   (elle se termine par `.iam.gserviceaccount.com`).
2. Dans ta copie, bouton **Partager** en haut à droite : ajoute cette adresse, rôle **Éditeur**,
   décoche « Envoyer une notification » (le robot ne lit pas ses mails), puis **Partager**.

## Étape 4 : créer ton compte (2 min)

1. Dans l'appli, **Réglages > Pas encore de compte ?** : colle le lien de ta copie, **Vérifier mon Sheet**.
2. L'appli affiche un code (`PI-…`) : dans ton Sheet, onglet **Réglages**, colle-le dans la case à droite
   de `code_inscription`. C'est la preuve que ce Sheet est bien à toi.
3. Indique ton prénom ou un pseudo, puis **Créer mon compte**. Ton **code d'accès personnel** s'affiche
   et reste enregistré sur ce téléphone : note-le pour tes autres appareils. Code perdu ? Refais ces
   étapes avec le même Sheet, tu en recevras un nouveau.
4. Installe l'appli sur l'écran d'accueil :
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

## Étape 6 : l'historique

Rien à faire : chaque nuit après un jour de bourse, l'appli ajoute une ligne à l'onglet **Historique**
de ton Sheet, et la courbe d'évolution se remplit toute seule.

Si tu avais installé l'ancien script Apps Script du relevé hebdomadaire, supprime-le : dans ton Sheet,
**Extensions > Apps Script**, icône d'horloge **Déclencheurs** à gauche, supprime le déclencheur `releveHebdo`.

Pour montrer l'appli sans dévoiler ton capital, touche l'œil à côté de « Valeur des placements » :
les montants sont floutés, les pourcentages restent visibles.

## Étape 7 (facultatif) : les notifications

Chaque nuit, l'appli peut t'envoyer tes alertes (forte baisse d'une position, action surveillée qui
passe sous sa valeur intrinsèque, alertes de prix) :

1. Installe l'appli gratuite **ntfy** (Play Store ou App Store).
2. Dans Portfolio Insights, **Réglages > Notifications** : **Générer un sujet**, puis **Enregistrer**.
3. Dans ntfy, bouton **+**, colle ce sujet et abonne-toi. **Envoyer un test** pour vérifier.

Pour une alerte de prix : ouvre la fiche d'une action, bouton **🔔 Alerte de prix**.

Chaque vendredi soir (dans la nuit), tu reçois aussi ta plus-value de la semaine, sans compter
l'argent versé entre-temps.

## En cas de souci

| Message | Solution |
|---|---|
| « code d'accès requis » | Saisis ou recolle ton code dans Réglages. |
| « L'appli n'a pas accès à ce Sheet » | Refais l'étape 3 : partage en Éditeur avec l'adresse du robot. |
| « Code de vérification absent ou incorrect » | Colle le code `PI-…` dans l'onglet Réglages de ton Sheet, à droite de `code_inscription`, sans espace. |
| « Le compte de service doit être Éditeur du Google Sheet » | Refais l'étape 3 avec le rôle Éditeur. |
| « Compte inconnu » à la saisie | Ajoute le compte dans l'onglet Comptes. |
| Une position sans cours dans le Sheet | Vérifie son ticker Google dans l'onglet Titres (ex. `EPA:MC`, `NASDAQ:AAPL`). |

## Allocation cible (facultatif)

Dans l'onglet Portefeuille, section **Allocation cible** : **Définir mes cibles**. Crée tes poches
(ex : « ETF Monde » 60 %, « Actions » 40 %), choisis la poche de chaque ligne, puis **Enregistrer**.
L'appli compare ta répartition réelle à ces cibles et te dit où placer tes prochains versements.
