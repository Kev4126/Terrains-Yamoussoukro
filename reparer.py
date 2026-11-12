"""Répare ou pilote la base terrains.db.

À placer dans le dossier du projet (à côté de app.py).

  python reparer.py              recrée la base proprement (6 annonces publiées, 1 en attente)
  python reparer.py publier 7    passe l'annonce n°7 au statut « publie »
  python reparer.py attente 7    remet l'annonce n°7 au statut « en_attente »
"""
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "terrains.db")
FICHIERS_SQL = ("schema.sql", "donnees_initiales.sql")
MOTS_SQL = ("CREATE", "INSERT", "PRAGMA", "DROP", "UPDATE", "ALTER")


def corriger_commentaires(chemin):
    """Remet « -- » devant les lignes de commentaire du début de fichier qui l'ont perdu."""
    with open(chemin, encoding="utf-8") as f:
        lignes = f.read().split("\n")
    debut = True
    for i, ligne in enumerate(lignes):
        s = ligne.strip()
        if s.upper().startswith(MOTS_SQL):
            debut = False
        elif debut and s and not s.startswith("--"):
            lignes[i] = "-- " + ligne
    with open(chemin, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lignes))


def reinitialiser():
    for nom in FICHIERS_SQL:
        corriger_commentaires(os.path.join(BASE, nom))
    if os.path.exists(DB):
        try:
            os.remove(DB)
        except PermissionError:
            print("Impossible de supprimer terrains.db.")
            print("Fermez DB Browser et arrêtez le serveur (Ctrl + C), puis relancez.")
            sys.exit(1)
    conn = sqlite3.connect(DB)
    for nom in FICHIERS_SQL:
        with open(os.path.join(BASE, nom), encoding="utf-8") as f:
            conn.executescript(f.read())
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM terrain WHERE statut = 'publie'").fetchone()[0]
    conn.close()
    print(f"Base recréée. {n} annonces publiées. Relancez : python app.py")


def changer_statut(statut, id_terrain):
    conn = sqlite3.connect(DB)
    try:
        cur = conn.execute("UPDATE terrain SET statut = ? WHERE id = ?", (statut, id_terrain))
        conn.commit()
    except sqlite3.OperationalError as e:
        print("Erreur :", e, "(fermez DB Browser s'il est ouvert)")
        sys.exit(1)
    finally:
        conn.close()
    if cur.rowcount == 0:
        print(f"Aucune annonce n°{id_terrain}.")
    else:
        print(f"Annonce n°{id_terrain} : statut = {statut}. Rechargez le site avec F5.")


def principal(args):
    if not args:
        reinitialiser()
    elif len(args) == 2 and args[0] in ("publier", "attente") and args[1].isdigit():
        changer_statut("publie" if args[0] == "publier" else "en_attente", int(args[1]))
    else:
        print(__doc__)


if __name__ == "__main__":  # pragma: no cover
    principal(sys.argv[1:])
