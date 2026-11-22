# Notifications à heure fixe (cron-job.org)

## Pourquoi

Les notifications (brief, récap du samedi, alertes) partent du workflow `notifications.yml`. Planifié par GitHub à
8 h 07 et 18 h 07, il démarrait en réalité vers 17 h et vers minuit (6 à 9 h de retard mesurés en novembre 2026) :
GitHub ne garantit pas l'heure de ses tâches planifiées, surtout sur un petit dépôt.

cron-job.org (gratuit, déjà utilisé pour réveiller le serveur Render) appelle donc l'API de GitHub à l'heure dite pour
lancer le workflow. Avantage en plus : il suit le fuseau Europe/Paris, donc pas de décalage d'une heure l'été.
Les horaires planifiés de GitHub restent en secours : un passage de secours ne fait rien si cron-job.org a déjà lancé le
même passage dans les 14 heures.

## 1. Créer un jeton GitHub limité au dépôt

1. GitHub > photo de profil > Settings > Developer settings > Personal access tokens > **Fine-grained tokens** >
   Generate new token.
2. Nom : `cron-job notifications`. Expiration : 1 an (noter de le renouveler).
3. Repository access : **Only select repositories** > `portfolio-app`.
4. Permissions > Repository permissions > **Actions : Read and write**. Rien d'autre (Metadata en lecture est ajouté
   d'office).
5. Generate token, copier le jeton (`github_pat_...`) : il ne s'affiche qu'une fois.

Ce jeton ne permet que de lancer / annuler des workflows de ce dépôt : il ne lit ni ne modifie le code.

## 2. Créer les deux tâches sur cron-job.org

Créer une tâche « Notifications matin » puis une « Notifications soir », identiques sauf l'heure et le passage :

| Champ | Matin | Soir |
|---|---|---|
| URL | `https://api.github.com/repos/OZAXE/portfolio-app/actions/workflows/notifications.yml/dispatches` | idem |
| Planification | tous les jours, 8 h 07 | tous les jours, 18 h 07 |
| Fuseau horaire (réglages du compte ou de la tâche) | Europe/Paris | Europe/Paris |

Onglet **Avancé** de chaque tâche :

- Méthode : **POST**
- En-têtes :
  - `Authorization` : `Bearer github_pat_...` (le jeton de l'étape 1)
  - `Accept` : `application/vnd.github+json`
  - `Content-Type` : `application/json`
- Corps de la requête :
  - matin : `{"ref": "main", "inputs": {"passage": "matin"}}`
  - soir : `{"ref": "main", "inputs": {"passage": "soir"}}`

Bouton **Tester l'exécution** : GitHub répond `204 No Content` quand c'est bon. Le lancement apparaît alors dans l'onglet
Actions du dépôt sous le nom « Notifications (matin, déclenché) ». Un 401 / 403 = jeton faux ou sans la permission
Actions ; un 422 = corps de la requête mal recopié.

Activer « Me prévenir si la tâche échoue » dans cron-job.org.

## 3. Vérifier

Le lendemain, onglet Actions > Notifications : un lancement « déclenché » vers 8 h 07, et le lancement « secours » de
GitHub, plus tard, qui s'arrête à l'étape « Déjà envoyé ? » sans rien envoyer.
