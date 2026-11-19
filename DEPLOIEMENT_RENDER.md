# Déploiement Render

1. Envoyez ce dossier vers votre dépôt GitHub.
2. Dans Render, créez un **Web Service** depuis ce dépôt. Le fichier `render.yaml` configure la commande de démarrage.
3. Ajoutez un disque persistant Render monté sur `/var/data`.
4. Dans **Environment**, définissez :

   - `TERRAINS_DB=/var/data/terrains.db`
   - `TERRAINS_UPLOADS=/var/data/uploads`
   - `TERRAINS_CLE=/var/data/secret.key`

Le disque est indispensable : sans lui, les comptes, annonces et photos seraient perdus lors d’un redéploiement.
