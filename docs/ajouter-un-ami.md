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

## 2. Préparer les briefs publics (une seule fois, facultatif)

Tes briefs parlent de ton portefeuille (titre, chapeau, « Mes positions », tags, PRU…) : les amis
ne doivent pas y avoir accès. À la place, ils lisent une version publique, rédigée à part.

1. Crée un dossier Drive « Briefs publics » et partage-le en **Lecteur** avec le compte de service.
   Les amis n'ont pas besoin d'y avoir accès : c'est l'appli qui le lit pour eux.
   L'identifiant du dossier est la fin de son lien, après `/folders/`.
2. Ajoute à la tâche Cowork hebdo la consigne suivante :
   > Après avoir déposé le brief habituel dans le dossier Briefs, rédige une **version publique** du
   > même brief et dépose-la dans le dossier Drive « Briefs publics », avec le même nom de fichier
   > (AAAA-MM-JJ.html) et la même mise en page (DA_de_reference.html). Cette version ne doit contenir
   > **aucune information sur mon portefeuille** : pas de section « Mes positions », pas de montants,
   > de PRU, de plus-values ni de performances, et aucune mention de mes titres comme étant les miens.
   > Titre, chapeau, tags et exemples de l'Apprentissage doivent être rédigés de façon générale
   > (« les marchés », « un investisseur »), pas au « tu ». Garde l'actu éco, les graphiques de marché,
   > l'Apprentissage, l'agenda et le jeu. Relis la version publique avant de la déposer pour vérifier
   > qu'aucun chiffre ni nom de titre venant du portefeuille n'y reste.
3. Relis le premier brief public avant de l'ouvrir aux amis : rien dans le code ne vérifie qu'il est
   anonyme. Les anciens briefs n'ont pas de version publique.

## 3. Pour chaque ami

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
     {"name": "Paul", "token": "<code de Paul>", "sheet_id": "<ID du Sheet de Paul>", "briefs_folder": "<ID du dossier Briefs publics>"}
   ]
   ```
   `briefs_folder` indique le dossier Drive dont l'utilisateur voit les briefs dans l'appli : ton
   dossier Briefs sur ta ligne, le dossier « Briefs publics » sur celle des amis. **Ne mets jamais
   ton dossier Briefs sur la ligne d'un ami.** Sans `briefs_folder`, l'onglet Briefs reste vide.
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
- Les briefs publics si leur ligne a `"briefs_folder"` vers le dossier « Briefs publics », jamais tes briefs perso.
- Les notifications nocturnes ne concernent pour l'instant que le propriétaire.
