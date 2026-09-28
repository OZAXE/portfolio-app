# Gérer les utilisateurs de l'appli (propriétaire)

Chaque utilisateur a son code d'accès et son propre Google Sheet (une copie du modèle). Tu n'as
rien à faire pour ajouter quelqu'un : chacun crée son compte depuis l'appli.

## Inviter quelqu'un

Envoie-lui le lien de l'appli (https://portfolio-front-8t6m.onrender.com) et le guide
[tutoriel-amis.md](tutoriel-amis.md). Il copie le Sheet modèle, le partage avec le compte de service,
puis crée son compte dans **Réglages > Pas encore de compte ?** (un code à coller dans son Sheet
prouve qu'il en est le propriétaire).

Préviens-le qu'en partageant son Sheet avec le compte de service, **tu as techniquement accès à
ses données** : l'appli l'affiche aussi avant l'inscription.

## Où sont les comptes

- **Les utilisateurs** : onglet « Utilisateurs » de ton Sheet (nom, empreinte du code d'accès,
  identifiant de son Sheet, date). Le code lui-même n'est jamais enregistré.
- **Toi** : seul compte administrateur, déclaré sur Render dans la variable `USERS_JSON`.
  Les amis ajoutés à la main dans `USERS_JSON` avant l'inscription libre y sont recopiés au
  démarrage de l'API, avec leur code actuel, et traités comme les autres.

## Supprimer un compte

Efface sa ligne dans l'onglet « Utilisateurs » : son code ne marche plus au bout d'une minute.
S'il figure aussi dans `USERS_JSON`, retire-l'en également (sinon sa ligne est recréée au prochain
démarrage). Il peut de son côté retirer le partage de son Sheet avec le compte de service.

## Code perdu

Il refait l'inscription avec le même Sheet : un nouveau code remplace l'ancien. Rien à faire de ton côté.

## Réglages sur Render (service portfolio-app > Environment)

| Variable | Rôle |
|---|---|
| `USERS_JSON` | Ton compte administrateur (voir ci-dessous). |
| `SIGNUP_OPEN` | `0` ferme les inscriptions (ouvertes par défaut). |
| `MAX_SIGNUPS` | Nombre maximum de comptes (50 par défaut : limite du serveur gratuit et du quota Google). |
| `PUBLIC_BRIEFS_FOLDER` | Identifiant du dossier « Briefs publics », lu par les utilisateurs (facultatif si un ami de `USERS_JSON` l'a déjà). |
| `REGISTRY_SHEET_ID` | Sheet où ranger les onglets Utilisateurs et Frais ETF (par défaut : le tien). |

`USERS_JSON` tient sur une ligne. Ta ligne doit toujours y figurer, sinon tu perds l'accès :

```json
[{"name": "<ton prénom>", "token": "<ton code d'accès>", "sheet_id": "<identifiant de ton Sheet>", "admin": true, "briefs_folder": "<identifiant de ton dossier Briefs>"}]
```

L'identifiant d'un Sheet est la partie de son lien entre `/d/` et `/edit` ; celui d'un dossier Drive,
la fin de son lien après `/folders/`. **Ne les écris jamais dans le repo** : il est public.
Garde le secret GitHub `APP_ACCESS_TOKEN` identique à ton code (il sert aux tâches de la nuit).
Pour générer un code solide :

```bash
python -c "import secrets; print(secrets.token_urlsafe(18))"
```

## Ce que voient les utilisateurs

- Leur portefeuille, leurs opérations, leur allocation cible, leurs comptes et banques, leur
  watchlist et leurs alertes, à partir de leur propre Sheet.
- Le screener, les super investisseurs et les comptes annuels, communs à tous.
- Les briefs publics (dossier « Briefs publics »), jamais tes briefs perso.
- Leur relevé quotidien, leurs notifications de la nuit et leur plus-value de la semaine, sur le sujet
  ntfy choisi dans Réglages > Notifications.

## Le Sheet modèle (une seule fois)

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

## Les briefs publics (une seule fois, facultatif)

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
