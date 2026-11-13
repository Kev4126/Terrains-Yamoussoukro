"""Plateforme de vente de terrains à Yamoussoukro : Sprint 3 (administration, modification des annonces).

Ce que fait cette version :
  - liste des terrains publiés avec filtres, fiche d'un terrain, contact WhatsApp
  - inscription et connexion des propriétaires et notaires
  - page « Mon compte » (réservée aux utilisateurs connectés) et modification du profil
  - page profil publique d'un propriétaire ou d'un notaire, avec ses terrains
  - publication d'un terrain avec photos (statut « en attente » jusqu'à validation) et suivi des annonces
  - espace administrateur : valider ou refuser les annonces, vérifier les comptes
  - modification, vente et suppression d'une annonce par son propriétaire

Lancer :  python app.py   puis ouvrir http://127.0.0.1:5000
"""
import functools
import os
import re
import secrets
import sqlite3
from urllib.parse import quote

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("TERRAINS_DB", os.path.join(BASE_DIR, "terrains.db"))
CLE_PATH = os.environ.get("TERRAINS_CLE", os.path.join(BASE_DIR, "secret.key"))
METHODE_HASH = "pbkdf2:sha256"
UPLOAD_DIR = os.environ.get("TERRAINS_UPLOADS", os.path.join(BASE_DIR, "uploads"))

# Règles de publication d'un terrain
PHOTOS_MAX = 4
PHOTO_TAILLE_MAX = 3 * 1024 * 1024          # 3 Mo par photo
SUPERFICIE_MAX = 10_000_000                 # m²
PRIX_MAX = 100_000_000_000                  # FCFA
DESCRIPTION_MAX = 1000
MAX_EN_ATTENTE = 10                         # annonces en attente de validation par utilisateur
STATUTS = {"en_attente": "En attente de validation", "publie": "Publiée",
           "refuse": "Refusée", "vendu": "Vendue"}

app = Flask(__name__)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"   # le cookie de connexion n'est pas envoyé depuis d'autres sites
app.config["SESSION_COOKIE_HTTPONLY"] = True    # inaccessible au JavaScript
app.config["MAX_CONTENT_LENGTH"] = 14 * 1024 * 1024   # taille maximale d'un envoi (4 photos + formulaire)


def charger_cle_secrete():
    """La clé qui signe les sessions est créée au premier lancement et jamais publiée (.gitignore)."""
    if not os.path.exists(CLE_PATH):
        with open(CLE_PATH, "wb") as f:
            f.write(secrets.token_bytes(32))
    with open(CLE_PATH, "rb") as f:
        return f.read()


app.secret_key = charger_cle_secrete()


# ---------- Base de données ----------

def init_db():
    """Crée terrains.db à partir de schema.sql et donnees_initiales.sql si elle n'existe pas."""
    if os.path.exists(DB_PATH):
        return
    conn = sqlite3.connect(DB_PATH)
    for fichier in ("schema.sql", "donnees_initiales.sql"):
        with open(os.path.join(BASE_DIR, fichier), encoding="utf-8") as f:
            conn.executescript(f.read())
    conn.commit()
    conn.close()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_erreur):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------- Comptes : session, protection des pages, CSRF ----------

def utilisateur_courant():
    """Retourne l'utilisateur connecté (ligne de la base) ou None."""
    if "utilisateur" not in g:
        g.utilisateur = None
        if "user_id" in session:
            g.utilisateur = get_db().execute(
                "SELECT id, nom, email, telephone_whatsapp, presentation, role, verifie, date_inscription "
                "FROM utilisateur WHERE id = ?", (session["user_id"],)
            ).fetchone()
            if g.utilisateur is None:      # compte supprimé : on vide la session
                session.clear()
    return g.utilisateur


def connexion_requise(vue):
    """Décorateur : redirige vers la page de connexion si personne n'est connecté."""
    @functools.wraps(vue)
    def enveloppe(*args, **kwargs):
        if utilisateur_courant() is None:
            flash("Connectez-vous pour accéder à cette page.", "info")
            return redirect(url_for("connexion"))
        return vue(*args, **kwargs)
    return enveloppe


def admin_requis(vue):
    """Décorateur : réservé à l'administrateur (connexion d'abord, puis contrôle du rôle)."""
    @connexion_requise
    @functools.wraps(vue)
    def enveloppe(*args, **kwargs):
        if utilisateur_courant()["role"] != "administrateur":
            abort(403)
        return vue(*args, **kwargs)
    return enveloppe


def csrf_token():
    """Jeton secret placé dans chaque formulaire : empêche un autre site de soumettre un formulaire à votre place."""
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@app.before_request
def verifier_csrf():
    if request.method == "POST":
        attendu = session.get("csrf", "")
        envoye = request.form.get("csrf", "")
        # Le jeton attendu doit exister : sinon deux textes vides seraient « identiques ».
        if not attendu or not secrets.compare_digest(attendu.encode(), envoye.encode()):
            abort(400)


@app.context_processor
def variables_communes():
    return {"utilisateur_courant": utilisateur_courant(), "csrf_token": csrf_token}


# ---------- Validation des champs ----------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NOM_PHOTO_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")
ROLES_INSCRIPTION = {"proprietaire": "Propriétaire", "notaire": "Notaire"}
PRESENTATION_MAX = 600
DUMMY_HASH = generate_password_hash("mot de passe factice", method=METHODE_HASH)


def normaliser_telephone(brut):
    """'07 00 00 00 00' -> '2250700000000'. Un numéro étranger doit commencer par + ou 00."""
    texte = re.sub(r"[\s.\-()]", "", brut)
    international = texte.startswith("+") or texte.startswith("00")
    texte = texte.lstrip("+")
    if texte.startswith("00"):
        texte = texte[2:]
    if not texte.isdigit():
        return None
    if international:
        return texte if 8 <= len(texte) <= 15 else None
    if len(texte) == 10:                      # numéro ivoirien à 10 chiffres
        return "225" + texte
    if texte.startswith("225") and len(texte) == 13:
        return texte
    return None


# ---------- Affichage des nombres ----------

@app.template_filter("fcfa")
def fcfa(valeur):
    """18000000 -> '18 000 000 FCFA'"""
    return f"{int(valeur):,}".replace(",", "\u202f") + " FCFA"


@app.template_filter("m2")
def m2(valeur):
    return f"{int(valeur):,}".replace(",", "\u202f") + " m²"


# ---------- Pages : annonces ----------

REQUETE_TERRAIN = """
    SELECT t.id, t.titre, t.description, t.superficie, t.prix, t.date_creation,
           (SELECT url FROM photo WHERE id_terrain = t.id ORDER BY id LIMIT 1) AS photo_url,
           q.nom  AS quartier,
           v.nom  AS ville,
           tt.libelle AS titre_foncier,
           ty.libelle AS type_terrain,
           u.id   AS id_vendeur,
           u.nom  AS vendeur,
           u.role AS vendeur_role,
           u.telephone_whatsapp AS telephone,
           u.verifie AS vendeur_verifie
    FROM terrain t
    JOIN quartier     q  ON q.id  = t.id_quartier
    JOIN ville        v  ON v.id  = q.id_ville
    JOIN type_titre   tt ON tt.id = t.id_type_titre
    JOIN type_terrain ty ON ty.id = t.id_type_terrain
    JOIN utilisateur  u  ON u.id  = t.id_vendeur
    WHERE t.statut = 'publie'
"""

# Tris autorisés (liste blanche : on n'insère jamais du texte venant de l'utilisateur dans le SQL)
TRIS = {
    "recent": ("Plus récents", "t.date_creation DESC, t.id DESC"),
    "prix_asc": ("Prix croissant", "t.prix ASC"),
    "prix_desc": ("Prix décroissant", "t.prix DESC"),
    "superficie_desc": ("Superficie décroissante", "t.superficie DESC"),
}


@app.route("/")
def liste():
    db = get_db()
    f = {
        cle: request.args.get(cle, "").strip()
        for cle in ("quartier", "titre", "type", "prix_max", "superficie_min", "tri")
    }
    conditions, params = [], []
    if f["quartier"].isdigit():
        conditions.append("t.id_quartier = ?")
        params.append(int(f["quartier"]))
    if f["titre"].isdigit():
        conditions.append("t.id_type_titre = ?")
        params.append(int(f["titre"]))
    if f["type"].isdigit():
        conditions.append("t.id_type_terrain = ?")
        params.append(int(f["type"]))
    if f["prix_max"].isdigit():
        conditions.append("t.prix <= ?")
        params.append(int(f["prix_max"]))
    if f["superficie_min"].isdigit():
        conditions.append("t.superficie >= ?")
        params.append(int(f["superficie_min"]))

    tri = f["tri"] if f["tri"] in TRIS else "recent"
    requete = REQUETE_TERRAIN
    if conditions:
        requete += " AND " + " AND ".join(conditions)
    requete += " ORDER BY " + TRIS[tri][1]
    terrains = db.execute(requete, params).fetchall()

    return render_template(
        "index.html",
        terrains=terrains,
        f=f,
        tri=tri,
        tris=TRIS,
        filtres_actifs=bool(conditions),
        quartiers=db.execute("SELECT id, nom FROM quartier ORDER BY nom").fetchall(),
        titres=db.execute("SELECT id, libelle FROM type_titre ORDER BY id").fetchall(),
        types=db.execute("SELECT id, libelle FROM type_terrain ORDER BY id").fetchall(),
    )


@app.route("/terrain/<int:terrain_id>")
def fiche(terrain_id):
    db = get_db()
    terrain = db.execute(REQUETE_TERRAIN + " AND t.id = ?", (terrain_id,)).fetchone()
    if terrain is None:
        abort(404)  # inexistant, ou pas encore publié
    photos = db.execute(
        "SELECT url FROM photo WHERE id_terrain = ? ORDER BY id", (terrain_id,)
    ).fetchall()
    message = (
        f"Bonjour, je suis intéressé par le terrain « {terrain['titre']} » "
        f"({terrain['quartier']}) vu sur Terrains Yamoussoukro."
    )
    whatsapp_url = f"https://wa.me/{terrain['telephone']}?text={quote(message)}"
    return render_template(
        "terrain.html", terrain=terrain, photos=photos, whatsapp_url=whatsapp_url
    )


# ---------- Pages : comptes ----------

@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    if utilisateur_courant():
        return redirect(url_for("mon_compte"))
    valeurs = {"nom": "", "email": "", "telephone": "", "role": "proprietaire"}
    erreurs = []
    if request.method == "POST":
        valeurs = {cle: request.form.get(cle, "").strip() for cle in valeurs}
        mot_de_passe = request.form.get("mot_de_passe", "")
        confirmation = request.form.get("confirmation", "")
        email = valeurs["email"].lower()
        telephone = normaliser_telephone(valeurs["telephone"])

        if not 2 <= len(valeurs["nom"]) <= 80:
            erreurs.append("Le nom doit contenir entre 2 et 80 caractères.")
        if not EMAIL_RE.match(email) or len(email) > 120:
            erreurs.append("L'adresse email n'est pas valide.")
        if telephone is None:
            erreurs.append("Le numéro WhatsApp n'est pas valide (exemple : 07 00 00 00 00, "
                           "ou +33... pour un numéro étranger).")
        if valeurs["role"] not in ROLES_INSCRIPTION:
            erreurs.append("Choisissez si vous êtes propriétaire ou notaire.")
        if not 8 <= len(mot_de_passe) <= 128:
            erreurs.append("Le mot de passe doit contenir au moins 8 caractères.")
        elif mot_de_passe.lower() == email:
            erreurs.append("Le mot de passe ne doit pas être votre adresse email.")
        if mot_de_passe != confirmation:
            erreurs.append("Les deux mots de passe ne sont pas identiques.")

        db = get_db()
        if not erreurs and db.execute(
            "SELECT 1 FROM utilisateur WHERE email = ?", (email,)
        ).fetchone():
            erreurs.append("Un compte existe déjà avec cette adresse email.")

        if not erreurs:
            try:
                curseur = db.execute(
                    "INSERT INTO utilisateur (nom, email, mot_de_passe_hash, telephone_whatsapp, role) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (valeurs["nom"], email,
                     generate_password_hash(mot_de_passe, method=METHODE_HASH),
                     telephone, valeurs["role"]),
                )
                db.commit()
            except sqlite3.IntegrityError:
                erreurs.append("Un compte existe déjà avec cette adresse email.")
            else:
                session.clear()                       # nouvelle session = pas de session héritée
                session["user_id"] = curseur.lastrowid
                flash("Votre compte est créé. Bienvenue !", "succes")
                return redirect(url_for("mon_compte"))
    return render_template("inscription.html", valeurs=valeurs, erreurs=erreurs,
                           roles=ROLES_INSCRIPTION)


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if utilisateur_courant():
        return redirect(url_for("mon_compte"))
    email = ""
    erreur = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        mot_de_passe = request.form.get("mot_de_passe", "")
        ligne = get_db().execute(
            "SELECT id, mot_de_passe_hash FROM utilisateur WHERE email = ?", (email,)
        ).fetchone()
        # On vérifie toujours un hash, même si l'email n'existe pas :
        # la réponse prend le même temps et ne révèle pas quels emails sont inscrits.
        hash_a_tester = ligne["mot_de_passe_hash"] if ligne else DUMMY_HASH
        if check_password_hash(hash_a_tester, mot_de_passe) and ligne:
            session.clear()
            session["user_id"] = ligne["id"]
            flash("Vous êtes connecté.", "succes")
            return redirect(url_for("mon_compte"))
        erreur = "Email ou mot de passe incorrect."   # même message dans les deux cas
    return render_template("connexion.html", email=email, erreur=erreur)


@app.route("/deconnexion", methods=["POST"])
def deconnexion():
    session.clear()
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for("liste"))


@app.route("/mon-compte")
@connexion_requise
def mon_compte():
    return render_template("mon_compte.html", roles=ROLES_INSCRIPTION)


@app.route("/mon-compte/modifier", methods=["GET", "POST"])
@connexion_requise
def modifier_profil():
    utilisateur = utilisateur_courant()
    # Le numéro est affiché avec « + » pour être relu correctement (y compris un numéro étranger).
    valeurs = {"nom": utilisateur["nom"],
               "telephone": "+" + utilisateur["telephone_whatsapp"],
               "presentation": utilisateur["presentation"] or ""}
    erreurs = []
    if request.method == "POST":
        valeurs = {cle: request.form.get(cle, "").strip() for cle in valeurs}
        telephone = normaliser_telephone(valeurs["telephone"])
        if not 2 <= len(valeurs["nom"]) <= 80:
            erreurs.append("Le nom doit contenir entre 2 et 80 caractères.")
        if telephone is None:
            erreurs.append("Le numéro WhatsApp n'est pas valide (exemple : 07 00 00 00 00, "
                           "ou +33... pour un numéro étranger).")
        if len(valeurs["presentation"]) > PRESENTATION_MAX:
            erreurs.append(f"La présentation ne doit pas dépasser {PRESENTATION_MAX} caractères.")
        if not erreurs:
            db = get_db()
            db.execute(
                "UPDATE utilisateur SET nom = ?, telephone_whatsapp = ?, presentation = ? WHERE id = ?",
                (valeurs["nom"], telephone, valeurs["presentation"] or None, utilisateur["id"]),
            )
            db.commit()
            flash("Votre profil est mis à jour.", "succes")
            return redirect(url_for("mon_compte"))
    return render_template("modifier_profil.html", valeurs=valeurs, erreurs=erreurs,
                           presentation_max=PRESENTATION_MAX)


@app.route("/profil/<int:utilisateur_id>")
def profil(utilisateur_id):
    """Page publique d'un propriétaire ou d'un notaire : présentation et terrains publiés."""
    db = get_db()
    membre = db.execute(
        "SELECT id, nom, role, verifie, presentation, telephone_whatsapp, date_inscription "
        "FROM utilisateur WHERE id = ? AND role IN ('proprietaire', 'notaire')",
        (utilisateur_id,),
    ).fetchone()
    if membre is None:
        abort(404)
    terrains = db.execute(
        REQUETE_TERRAIN + " AND u.id = ? ORDER BY t.date_creation DESC, t.id DESC",
        (utilisateur_id,),
    ).fetchall()
    message = "Bonjour, je vous contacte depuis Terrains Yamoussoukro."
    whatsapp_url = f"https://wa.me/{membre['telephone_whatsapp']}?text={quote(message)}"
    return render_template("profil.html", membre=membre, terrains=terrains,
                           whatsapp_url=whatsapp_url, roles=ROLES_INSCRIPTION)


def lire_entier(texte):
    """'18 000 000' -> 18000000. Retourne None si ce n'est pas un nombre entier positif."""
    nettoye = re.sub(r"[\s\u202f\u00a0]", "", texte)
    return int(nettoye) if nettoye.isdigit() else None


def type_image(octets):
    """Reconnaît JPG, PNG et WebP d'après le CONTENU du fichier (pas d'après son nom)."""
    if octets.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if octets.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if octets[:4] == b"RIFF" and octets[8:12] == b"WEBP":
        return "webp"
    return None


CHAMPS_ANNONCE = ("titre", "description", "superficie", "prix", "quartier", "titre_foncier", "type")


def listes_formulaire(db):
    """Les trois listes de choix du formulaire : quartiers, titres fonciers, types de terrain."""
    return (db.execute("SELECT id, nom FROM quartier ORDER BY nom").fetchall(),
            db.execute("SELECT id, libelle FROM type_titre ORDER BY id").fetchall(),
            db.execute("SELECT id, libelle FROM type_terrain ORDER BY id").fetchall())


def lire_formulaire_annonce(quartiers, titres, types, photos_gardees=0):
    """Lit et contrôle le formulaire d'une annonce (publication ou modification).

    Retourne (valeurs, erreurs, superficie, prix, photos) ; `photos` contient les
    nouvelles photos valides sous la forme (octets, extension)."""
    valeurs = {cle: request.form.get(cle, "").strip() for cle in CHAMPS_ANNONCE}
    superficie = lire_entier(valeurs["superficie"])
    prix = lire_entier(valeurs["prix"])
    erreurs = []

    if not 5 <= len(valeurs["titre"]) <= 100:
        erreurs.append("Le titre doit contenir entre 5 et 100 caractères.")
    if len(valeurs["description"]) > DESCRIPTION_MAX:
        erreurs.append(f"La description ne doit pas dépasser {DESCRIPTION_MAX} caractères.")
    if superficie is None or not 1 <= superficie <= SUPERFICIE_MAX:
        erreurs.append("La superficie doit être un nombre entier de m² (au moins 1).")
    if prix is None or not 1 <= prix <= PRIX_MAX:
        erreurs.append("Le prix doit être un nombre entier de FCFA (au moins 1).")
    if valeurs["quartier"] not in {str(q["id"]) for q in quartiers}:
        erreurs.append("Choisissez un quartier dans la liste.")
    if valeurs["titre_foncier"] not in {str(t["id"]) for t in titres}:
        erreurs.append("Choisissez un type de titre foncier dans la liste.")
    if valeurs["type"] not in {str(t["id"]) for t in types}:
        erreurs.append("Choisissez un type de terrain dans la liste.")

    photos = []
    fichiers = [f for f in request.files.getlist("photos") if f and f.filename]
    if len(fichiers) + photos_gardees > PHOTOS_MAX:
        erreurs.append(f"Une annonce peut avoir {PHOTOS_MAX} photos au maximum.")
    else:
        for fichier in fichiers:
            octets = fichier.read(PHOTO_TAILLE_MAX + 1)
            extension = type_image(octets)
            if len(octets) > PHOTO_TAILLE_MAX:
                erreurs.append(f"La photo « {fichier.filename} » dépasse 3 Mo.")
            elif extension is None:
                erreurs.append(f"« {fichier.filename} » n'est pas une image JPG, PNG ou WebP.")
            else:
                photos.append((octets, extension))
    return valeurs, erreurs, superficie, prix, photos


def enregistrer_photos(db, id_terrain, photos):
    """Écrit les fichiers dans uploads/ (nom aléatoire) et les relie à l'annonce."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    for octets, extension in photos:
        nom_fichier = f"{secrets.token_hex(16)}.{extension}"   # jamais le nom donné par l'utilisateur
        with open(os.path.join(UPLOAD_DIR, nom_fichier), "wb") as f:
            f.write(octets)
        db.execute("INSERT INTO photo (url, id_terrain) VALUES (?, ?)",
                   (f"/photos/{nom_fichier}", id_terrain))


def supprimer_fichier_photo(url):
    """Efface le fichier d'une photo (seulement s'il porte un nom géré par le site)."""
    nom = url.rsplit("/", 1)[-1]
    if NOM_PHOTO_RE.match(nom):
        try:
            os.remove(os.path.join(UPLOAD_DIR, nom))
        except FileNotFoundError:
            pass


def nb_en_attente(db, id_vendeur):
    return db.execute("SELECT COUNT(*) FROM terrain WHERE id_vendeur = ? AND statut = 'en_attente'",
                      (id_vendeur,)).fetchone()[0]


def message_limite():
    return (f"Vous avez déjà {MAX_EN_ATTENTE} annonces en attente de validation. "
            "Attendez qu'elles soient traitées avant d'en publier d'autres.")


@app.route("/publier", methods=["GET", "POST"])
@connexion_requise
def publier():
    utilisateur = utilisateur_courant()
    if utilisateur["role"] not in ROLES_INSCRIPTION:
        abort(403)                     # l'administrateur ne publie pas de terrain
    db = get_db()
    quartiers, titres, types = listes_formulaire(db)
    valeurs = {cle: "" for cle in CHAMPS_ANNONCE}
    erreurs = []
    if request.method == "POST":
        valeurs, erreurs, superficie, prix, photos = lire_formulaire_annonce(quartiers, titres, types)
        if nb_en_attente(db, utilisateur["id"]) >= MAX_EN_ATTENTE:
            erreurs.append(message_limite())
        if not erreurs:
            curseur = db.execute(
                "INSERT INTO terrain (titre, description, superficie, prix, "
                "id_quartier, id_type_titre, id_type_terrain, id_vendeur) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (valeurs["titre"], valeurs["description"] or None, superficie, prix,
                 int(valeurs["quartier"]), int(valeurs["titre_foncier"]), int(valeurs["type"]),
                 utilisateur["id"]),
            )                                          # le statut par défaut est « en_attente »
            enregistrer_photos(db, curseur.lastrowid, photos)
            db.commit()
            flash("Votre annonce est enregistrée. Elle sera visible après validation "
                  "par l'administrateur.", "succes")
            return redirect(url_for("mes_annonces"))
    return render_template("publier.html", valeurs=valeurs, erreurs=erreurs,
                           quartiers=quartiers, titres=titres, types=types,
                           photos_max=PHOTOS_MAX, description_max=DESCRIPTION_MAX,
                           titre_page="Publier un terrain",
                           introduction="Votre annonce est vérifiée par l'administrateur avant d'apparaître "
                                        "sur le site. Seuls des terrains à Yamoussoukro peuvent être publiés.",
                           action=url_for("publier"), libelle_bouton="Envoyer pour validation",
                           photos_existantes=[])


@app.route("/mes-annonces")
@connexion_requise
def mes_annonces():
    annonces = get_db().execute(
        "SELECT t.id, t.titre, t.prix, t.superficie, t.statut, t.date_creation, q.nom AS quartier "
        "FROM terrain t JOIN quartier q ON q.id = t.id_quartier "
        "WHERE t.id_vendeur = ? ORDER BY t.id DESC",
        (utilisateur_courant()["id"],),
    ).fetchall()
    return render_template("mes_annonces.html", annonces=annonces, statuts=STATUTS,
                           roles=ROLES_INSCRIPTION)


def annonce_du_vendeur(terrain_id):
    """L'annonce demandée, si elle appartient à l'utilisateur connecté. Sinon : 404."""
    annonce = get_db().execute(
        "SELECT * FROM terrain WHERE id = ? AND id_vendeur = ?",
        (terrain_id, utilisateur_courant()["id"])).fetchone()
    if annonce is None:
        abort(404)
    return annonce


@app.route("/annonces/<int:terrain_id>/modifier", methods=["GET", "POST"])
@connexion_requise
def modifier_annonce(terrain_id):
    annonce = annonce_du_vendeur(terrain_id)
    if annonce["statut"] == "vendu":
        flash("Une annonce vendue ne peut plus être modifiée.", "info")
        return redirect(url_for("mes_annonces"))
    db = get_db()
    quartiers, titres, types = listes_formulaire(db)
    photos = db.execute("SELECT id, url FROM photo WHERE id_terrain = ? ORDER BY id",
                        (terrain_id,)).fetchall()
    valeurs = {"titre": annonce["titre"], "description": annonce["description"] or "",
               "superficie": str(annonce["superficie"]), "prix": str(annonce["prix"]),
               "quartier": str(annonce["id_quartier"]),
               "titre_foncier": str(annonce["id_type_titre"]),
               "type": str(annonce["id_type_terrain"])}
    erreurs = []
    if request.method == "POST":
        # Seules les photos de CETTE annonce peuvent être supprimées : on ignore tout autre numéro.
        a_supprimer = set(request.form.getlist("supprimer_photo")) & {str(p["id"]) for p in photos}
        valeurs, erreurs, superficie, prix, nouvelles = lire_formulaire_annonce(
            quartiers, titres, types, photos_gardees=len(photos) - len(a_supprimer))
        if annonce["statut"] != "en_attente" and nb_en_attente(db, annonce["id_vendeur"]) >= MAX_EN_ATTENTE:
            erreurs.append(message_limite())      # elle va repasser « en attente »
        if not erreurs:
            db.execute(
                "UPDATE terrain SET titre = ?, description = ?, superficie = ?, prix = ?, "
                "id_quartier = ?, id_type_titre = ?, id_type_terrain = ?, statut = 'en_attente' "
                "WHERE id = ?",
                (valeurs["titre"], valeurs["description"] or None, superficie, prix,
                 int(valeurs["quartier"]), int(valeurs["titre_foncier"]), int(valeurs["type"]),
                 terrain_id))
            urls_supprimees = [p["url"] for p in photos if str(p["id"]) in a_supprimer]
            for id_photo in a_supprimer:
                db.execute("DELETE FROM photo WHERE id = ?", (int(id_photo),))
            enregistrer_photos(db, terrain_id, nouvelles)
            db.commit()
            for url in urls_supprimees:
                supprimer_fichier_photo(url)
            flash("Annonce modifiée. Elle sera de nouveau vérifiée par l'administrateur "
                  "avant d'être visible.", "succes")
            return redirect(url_for("mes_annonces"))
    return render_template("publier.html", valeurs=valeurs, erreurs=erreurs,
                           quartiers=quartiers, titres=titres, types=types,
                           photos_max=PHOTOS_MAX, description_max=DESCRIPTION_MAX,
                           titre_page="Modifier mon annonce",
                           introduction="Après modification, l'annonce repasse en validation "
                                        "et n'est plus visible tant que l'administrateur ne l'a pas approuvée.",
                           action=url_for("modifier_annonce", terrain_id=terrain_id),
                           libelle_bouton="Enregistrer les modifications", photos_existantes=photos)


@app.route("/annonces/<int:terrain_id>/vendue", methods=["POST"])
@connexion_requise
def marquer_vendue(terrain_id):
    annonce = annonce_du_vendeur(terrain_id)
    if annonce["statut"] != "publie":
        flash("Seule une annonce publiée peut être marquée comme vendue.", "info")
    else:
        db = get_db()
        db.execute("UPDATE terrain SET statut = 'vendu' WHERE id = ?", (terrain_id,))
        db.commit()
        flash("Annonce marquée comme vendue. Elle n'est plus visible sur le site.", "succes")
    return redirect(url_for("mes_annonces"))


@app.route("/annonces/<int:terrain_id>/supprimer", methods=["GET", "POST"])
@connexion_requise
def supprimer_annonce(terrain_id):
    annonce = annonce_du_vendeur(terrain_id)
    if request.method == "POST":
        db = get_db()
        urls = [ligne["url"] for ligne in
                db.execute("SELECT url FROM photo WHERE id_terrain = ?", (terrain_id,))]
        db.execute("DELETE FROM terrain WHERE id = ?", (terrain_id,))   # ses photos partent en cascade
        db.commit()
        for url in urls:
            supprimer_fichier_photo(url)
        flash("Annonce supprimée définitivement.", "succes")
        return redirect(url_for("mes_annonces"))
    return render_template("supprimer_annonce.html", annonce=annonce)


@app.route("/photos/<nom_fichier>")
def photo(nom_fichier):
    if not NOM_PHOTO_RE.match(nom_fichier):
        abort(404)
    return send_from_directory(UPLOAD_DIR, nom_fichier)


ANNONCES_EN_ATTENTE = """
    SELECT t.id, t.titre, t.description, t.superficie, t.prix, t.date_creation,
           (SELECT url FROM photo WHERE id_terrain = t.id ORDER BY id LIMIT 1) AS photo_url,
           (SELECT COUNT(*) FROM photo WHERE id_terrain = t.id) AS nb_photos,
           q.nom  AS quartier,
           tt.libelle AS titre_foncier,
           ty.libelle AS type_terrain,
           u.id   AS id_vendeur,
           u.nom  AS vendeur,
           u.role AS vendeur_role,
           u.verifie AS vendeur_verifie
    FROM terrain t
    JOIN quartier     q  ON q.id  = t.id_quartier
    JOIN type_titre   tt ON tt.id = t.id_type_titre
    JOIN type_terrain ty ON ty.id = t.id_type_terrain
    JOIN utilisateur  u  ON u.id  = t.id_vendeur
    WHERE t.statut = 'en_attente'
    ORDER BY t.id
"""


@app.route("/admin")
@admin_requis
def admin():
    """Tableau de bord de l'administrateur : annonces à valider et comptes à vérifier."""
    db = get_db()
    nombres = {ligne["statut"]: ligne["nb"] for ligne in db.execute(
        "SELECT statut, COUNT(*) AS nb FROM terrain GROUP BY statut")}
    comptes = db.execute(
        "SELECT id, nom, email, role, date_inscription FROM utilisateur "
        "WHERE verifie = 0 AND role IN ('proprietaire', 'notaire') ORDER BY id").fetchall()
    return render_template("admin.html", annonces=db.execute(ANNONCES_EN_ATTENTE).fetchall(),
                           comptes=comptes, nombres=nombres, statuts=STATUTS,
                           roles=ROLES_INSCRIPTION)


@app.route("/admin/annonces/<int:terrain_id>/<action>", methods=["POST"])
@admin_requis
def admin_decider(terrain_id, action):
    nouveaux_statuts = {"valider": "publie", "refuser": "refuse"}
    if action not in nouveaux_statuts:
        abort(404)
    db = get_db()
    # « AND statut = 'en_attente' » : on ne change pas une annonce déjà traitée
    curseur = db.execute(
        "UPDATE terrain SET statut = ? WHERE id = ? AND statut = 'en_attente'",
        (nouveaux_statuts[action], terrain_id))
    db.commit()
    if curseur.rowcount:
        flash("Annonce publiée." if action == "valider" else "Annonce refusée.", "succes")
    else:
        flash("Cette annonce n'est plus en attente.", "info")
    return redirect(url_for("admin"))


@app.route("/admin/comptes/<int:utilisateur_id>/verifier", methods=["POST"])
@admin_requis
def admin_verifier(utilisateur_id):
    db = get_db()
    curseur = db.execute(
        "UPDATE utilisateur SET verifie = 1 WHERE id = ? AND verifie = 0 "
        "AND role IN ('proprietaire', 'notaire')", (utilisateur_id,))
    db.commit()
    if curseur.rowcount:
        flash("Compte marqué comme vérifié.", "succes")
    else:
        flash("Ce compte n'a pas besoin d'être vérifié.", "info")
    return redirect(url_for("admin"))


# ---------- Erreurs ----------

@app.errorhandler(404)
def introuvable(_erreur):
    return render_template("404.html"), 404


@app.after_request
def entetes_de_securite(reponse):
    reponse.headers["X-Content-Type-Options"] = "nosniff"   # le navigateur ne devine pas le type d'un fichier
    reponse.headers["X-Frame-Options"] = "DENY"             # le site ne peut pas être affiché dans le cadre d'un autre
    return reponse


@app.errorhandler(403)
def acces_refuse(_erreur):
    return render_template(
        "erreur.html", titre="Accès refusé",
        message="Votre profil ne permet pas d'accéder à cette page.",
    ), 403


@app.errorhandler(413)
def envoi_trop_gros(_erreur):
    return render_template(
        "erreur.html", titre="Envoi trop volumineux",
        message="Les fichiers envoyés sont trop lourds (14 Mo au total, 3 Mo par photo).",
    ), 413


@app.errorhandler(400)
def requete_invalide(_erreur):
    return render_template(
        "erreur.html", titre="Formulaire expiré",
        message="Cette page a expiré ou la demande est invalide. Rechargez la page et recommencez.",
    ), 400


init_db()

if __name__ == "__main__":  # pragma: no cover
    app.run(debug=True)
