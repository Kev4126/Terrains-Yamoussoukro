# Lancer l'application (Sprint 2)

1. Installer Python 3 (https://www.python.org), puis ouvrir un terminal dans ce dossier.
2. Créer un environnement et installer Flask :

       python -m venv venv
       venv\Scripts\activate          (Windows)   |   source venv/bin/activate   (Mac/Linux)
       pip install -r requirements.txt

3. Lancer :

       python app.py

4. Ouvrir http://127.0.0.1:5000 dans le navigateur.

Au premier lancement, `terrains.db` est créée automatiquement à partir de
`schema.sql` et `donnees_initiales.sql`, et une clé secrète `secret.key` est générée.
Pour repartir de zéro (par exemple après un changement de schéma) :
arrêter le serveur, fermer DB Browser, puis `python reparer.py`.

## Photos
Les photos envoyées avec une annonce sont enregistrées dans le dossier `uploads/`
(créé automatiquement, exclu de GitHub). Pour publier une annonce en attente avant
que l'espace administrateur existe : `python reparer.py publier 8` (8 = numéro de l'annonce),
ou changer la colonne `statut` en `publie` dans DB Browser.

## Comptes de test
Mot de passe de tous les comptes : `motdepasse123`

| Email | Profil |
|---|---|
| admin@terrains.test | Administrateur |
| proprietaire1@terrains.test | Propriétaire (vérifié) |
| proprietaire2@terrains.test | Propriétaire (non vérifié) |
| notaire@terrains.test | Notaire (vérifié) |

Ces comptes servent aux démonstrations : à supprimer avant toute vraie mise en ligne.

## Voir la base en direct
Ouvrir `terrains.db` avec DB Browser for SQLite, onglet « Parcourir les données ».
Dans la table `utilisateur`, la colonne `mot_de_passe_hash` contient un texte illisible :
c'est normal, le mot de passe n'est jamais stocké en clair.

## Tests et couverture du code (objectif : au moins 70 %)
Les tests sont dans `tests/test_app.py`. Ils utilisent une base temporaire :
`terrains.db` n'est jamais modifiée.

    python -m unittest discover -s tests -v          (lance les tests, rien à installer)

Pour mesurer le pourcentage de code contrôlé :

    pip install -r requirements-dev.txt
    coverage run -m unittest discover -s tests
    coverage report        (tableau avec le % par fichier ; échoue sous 70 %, réglage dans .coveragerc)
    coverage html          (ouvrir htmlcov\index.html : vert = testé, rouge = non testé)
