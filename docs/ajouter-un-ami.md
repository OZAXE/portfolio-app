# Ajouter un ami à l'appli (propriétaire)

Chaque utilisateur a son code d'accès et son Google Sheet. Les codes et les Sheets sont déclarés
dans la variable `USERS_JSON` du service backend sur Render.

## 1. Préparer le Sheet modèle (une seule fois)

Déjà fait : https://docs.google.com/spreadsheets/d/1Cw44TPxJkpfoXUKkg4eDuDeoHIIvI-UJmzkXi2MYeZU/edit
(à refaire seulement si le modèle change).

1. Crée un Google Sheet vide nommé « Portfolio Insights — Modèle » et partage-le en **Éditeur**
   avec le compte de service.
2. Construis-y les onglets du modèle :
   ```bash
   gh workflow run admin.yml -f target=<ID du Sheet modèle> -f migrate_from=
   ```
3. Supprime l'onglet vide « Feuille 1 » s'il est resté, puis **Partager > Accès général :
   Tous les utilisateurs disposant du lien, Lecteur**. C'est ce lien que tu envoies à tes amis :
   ils en feront une copie (Fichier > Créer une copie), sans pouvoir modifier le modèle.

## 2. Pour chaque ami

1. Envoie-lui le lien du Sheet modèle, l'adresse du compte de service et le
   [tutoriel](tutoriel-amis.md).
2. Il te renvoie le lien de **sa copie**, partagée en Éditeur avec le compte de service.
   L'identifiant du Sheet est la partie entre `/d/` et `/edit` du lien.
3. Génère-lui un code d'accès :
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(18))"
   ```
4. Sur Render > service **portfolio-app** > **Environment**, mets à jour `USERS_JSON`
   (une seule ligne de JSON), puis **Save, rebuild and deploy** :
   ```json
   [
     {"name": "Enzo", "token": "<ton code actuel>", "sheet_id": "1d9wtW41Ncerh6O0mmYC5YpADIkNQCI0GNUp9Xo-OZT4", "admin": true, "briefs_folder": "1hlL6XgoWhVdlNLzUKmy2s-C0Ipo1Uw52"},
     {"name": "Paul", "token": "<code de Paul>", "sheet_id": "<ID du Sheet de Paul>"}
   ]
   ```
   Dès que `USERS_JSON` existe, `APP_ACCESS_TOKEN` n'est plus lu par l'API : **ta propre ligne
   doit y figurer**, avec ton code actuel, sinon tu perds l'accès. Garde aussi le secret GitHub
   `APP_ACCESS_TOKEN` identique à ton code (il sert au calcul nocturne des alertes).
5. Envoie-lui son code par un canal privé.

## Retirer un ami

Supprime sa ligne de `USERS_JSON` et redéploie : son code ne fonctionne plus immédiatement.
Il peut aussi retirer le partage de son Sheet avec le compte de service.

## Ce que voient les amis

- Leur portefeuille, leur watchlist et leurs alertes dans l'appli, à partir de leur propre Sheet.
- Le screener, les super investisseurs et les comptes annuels, communs à tous.
- Pas de briefs hebdo, sauf si tu ajoutes `"briefs_folder"` à leur ligne (dossier Drive partagé avec le compte de service).
- Les notifications nocturnes ne concernent pour l'instant que le propriétaire.
