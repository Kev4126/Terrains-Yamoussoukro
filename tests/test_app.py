"""Tests automatiques de l'application (stdlib unittest, rien à installer).

Lancer :   python -m unittest discover -s tests -v

Les tests utilisent une base TEMPORAIRE : le vrai fichier terrains.db n'est jamais touché.
"""
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from io import StringIO
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

# Avant d'importer l'application : on lui indique une base et une clé temporaires.
DOSSIER_TEST = tempfile.mkdtemp(prefix="terrains_tests_")
os.environ["TERRAINS_DB"] = os.path.join(DOSSIER_TEST, "test.db")
os.environ["TERRAINS_CLE"] = os.path.join(DOSSIER_TEST, "secret.key")
os.environ["TERRAINS_UPLOADS"] = os.path.join(DOSSIER_TEST, "uploads")

import app as application  # noqa: E402
import reparer  # noqa: E402

MOT_DE_PASSE_TEST = "motdepasse123"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 100


def tearDownModule():
    shutil.rmtree(DOSSIER_TEST, ignore_errors=True)


class BaseTest(unittest.TestCase):
    """Chaque test repart d'une base neuve, remplie avec les données initiales."""

    def setUp(self):
        if os.path.exists(application.DB_PATH):
            os.remove(application.DB_PATH)
        application.init_db()
        shutil.rmtree(application.UPLOAD_DIR, ignore_errors=True)
        self.client = application.app.test_client()

    # --- aides ---
    def jeton(self, client=None, url="/connexion"):
        page = (client or self.client).get(url).get_data(as_text=True)
        return re.search(r'name="csrf" value="([^"]+)"', page).group(1)

    def connecter(self, email="admin@terrains.test", mot_de_passe=MOT_DE_PASSE_TEST, client=None):
        client = client or self.client
        return client.post("/connexion", data={
            "csrf": self.jeton(client), "email": email, "mot_de_passe": mot_de_passe})

    def inscrire(self, client=None, **champs):
        client = client or self.client
        donnees = {"csrf": self.jeton(client, "/inscription"), "role": "notaire",
                   "nom": "Étude Kouassi", "email": "kouassi@exemple.ci",
                   "telephone": "07 12 34 56 78", "mot_de_passe": "SuperMotDePasse1",
                   "confirmation": "SuperMotDePasse1"}
        donnees.update(champs)
        return client.post("/inscription", data=donnees)

    def sql(self, requete, params=()):
        base = sqlite3.connect(application.DB_PATH)
        try:
            resultat = base.execute(requete, params).fetchall()
            base.commit()
            return resultat
        finally:
            base.close()

    def nb_cartes(self, url):
        return self.client.get(url).get_data(as_text=True).count('class="carte"')


# ------------------------------------------------------------------ annonces

class TestListeEtFiche(BaseTest):

    def test_liste_affiche_les_six_terrains_publies(self):
        reponse = self.client.get("/")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(self.nb_cartes("/"), 6)

    def test_annonce_en_attente_invisible_dans_la_liste(self):
        self.assertNotIn("Lot en attente", self.client.get("/").get_data(as_text=True))

    def test_publier_une_annonce_la_fait_apparaitre(self):
        self.sql("UPDATE terrain SET statut = 'publie' WHERE id = 7")
        self.assertEqual(self.nb_cartes("/"), 7)

    def test_fiche_contient_whatsapp_appel_et_badge(self):
        page = self.client.get("/terrain/1").get_data(as_text=True)
        self.assertIn("https://wa.me/2250700000001?text=", page)
        self.assertIn("tel:+2250700000001", page)
        self.assertIn("Vendeur vérifié", page)
        self.assertIn("Propriétaire", page)

    def test_fiche_vendeur_non_verifie_sans_badge(self):
        page = self.client.get("/terrain/4").get_data(as_text=True)
        self.assertNotIn("Vendeur vérifié", page)

    def test_fiche_avec_photo(self):
        self.sql("INSERT INTO photo (url, id_terrain) VALUES ('/static/test.jpg', 1)")
        self.assertIn("/static/test.jpg", self.client.get("/terrain/1").get_data(as_text=True))

    def test_fiche_en_attente_ou_inexistante_donne_404(self):
        self.assertEqual(self.client.get("/terrain/7").status_code, 404)
        self.assertEqual(self.client.get("/terrain/9999").status_code, 404)
        self.assertIn("Terrain introuvable", self.client.get("/terrain/9999").get_data(as_text=True))

    def test_liste_vide_message(self):
        self.sql("UPDATE terrain SET statut = 'vendu'")
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("Aucun terrain n'est publié", page)

    def test_formats_prix_et_superficie(self):
        self.assertEqual(application.fcfa(18000000), "18\u202f000\u202f000 FCFA")
        self.assertEqual(application.m2(600), "600 m²")


class TestFiltres(BaseTest):

    def test_filtre_quartier(self):
        self.assertEqual(self.nb_cartes("/?quartier=1"), 2)

    def test_filtre_titre_foncier(self):
        self.assertEqual(self.nb_cartes("/?titre=1"), 3)

    def test_filtre_type_de_terrain(self):
        self.assertEqual(self.nb_cartes("/?type=1"), 4)

    def test_filtre_prix_maximum(self):
        self.assertEqual(self.nb_cartes("/?prix_max=20000000"), 3)

    def test_filtre_superficie_minimum(self):
        self.assertEqual(self.nb_cartes("/?superficie_min=1000"), 3)

    def test_filtres_combines(self):
        self.assertEqual(self.nb_cartes("/?quartier=1&prix_max=20000000"), 1)

    def test_aucun_resultat(self):
        page = self.client.get("/?prix_max=1").get_data(as_text=True)
        self.assertIn("Aucun terrain ne correspond", page)

    def test_valeurs_invalides_ignorees(self):
        self.assertEqual(self.nb_cartes("/?quartier=abc&prix_max=x'; DROP TABLE terrain;--"), 6)
        self.assertEqual(len(self.sql("SELECT id FROM terrain")), 7)   # la table existe toujours

    def test_tri_prix_croissant_et_decroissant(self):
        croissant = self.client.get("/?tri=prix_asc").get_data(as_text=True)
        self.assertLess(croissant.index("6\u202f500\u202f000"), croissant.index("35\u202f000\u202f000"))
        decroissant = self.client.get("/?tri=prix_desc").get_data(as_text=True)
        self.assertLess(decroissant.index("35\u202f000\u202f000"), decroissant.index("6\u202f500\u202f000"))

    def test_tri_inconnu_remplace_par_tri_par_defaut(self):
        page = self.client.get("/?tri=DROP").get_data(as_text=True)
        self.assertIn('value="recent" selected', page)

    def test_filtre_choisi_reste_selectionne(self):
        page = self.client.get("/?quartier=1").get_data(as_text=True)
        self.assertIn("correspondent à vos critères", page)
        self.assertIn('value="1" selected', page)


# ------------------------------------------------------------------ comptes

class TestTelephone(unittest.TestCase):

    def test_numero_ivoirien_a_dix_chiffres(self):
        self.assertEqual(application.normaliser_telephone("07 12 34 56 78"), "2250712345678")

    def test_numero_avec_indicatif_225(self):
        self.assertEqual(application.normaliser_telephone("225 07 12 34 56 78"), "2250712345678")

    def test_numero_etranger_avec_plus_ou_00(self):
        self.assertEqual(application.normaliser_telephone("+33 6 12 34 56 78"), "33612345678")
        self.assertEqual(application.normaliser_telephone("0033612345678"), "33612345678")

    def test_numeros_invalides(self):
        for brut in ("12345", "abc", "", "+12", "0712"):
            self.assertIsNone(application.normaliser_telephone(brut), brut)


class TestInscription(BaseTest):

    def test_inscription_valide_connecte_et_enregistre_un_hash(self):
        reponse = self.inscrire()
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(self.client.get("/mon-compte").status_code, 200)
        nom, role, verifie, tel, hash_mdp = self.sql(
            "SELECT nom, role, verifie, telephone_whatsapp, mot_de_passe_hash "
            "FROM utilisateur WHERE email = 'kouassi@exemple.ci'")[0]
        self.assertEqual((role, verifie, tel), ("notaire", 0, "2250712345678"))
        self.assertNotIn("SuperMotDePasse1", hash_mdp)
        self.assertTrue(hash_mdp.startswith("pbkdf2:sha256"))

    def test_page_inscription_s_affiche(self):
        self.assertEqual(self.client.get("/inscription").status_code, 200)

    def test_refus_des_champs_invalides(self):
        cas = {
            "email déjà pris": {"email": "ADMIN@terrains.test"},
            "email invalide": {"email": "pasunemail"},
            "mot de passe trop court": {"mot_de_passe": "abc", "confirmation": "abc"},
            "mot de passe = email": {"email": "dupont@exemple.ci",
                                      "mot_de_passe": "dupont@exemple.ci",
                                      "confirmation": "dupont@exemple.ci"},
            "confirmation différente": {"confirmation": "autre chose 123"},
            "téléphone invalide": {"telephone": "12345"},
            "nom trop court": {"nom": "A"},
            "rôle administrateur interdit": {"role": "administrateur"},
        }
        for nom_du_cas, champs in cas.items():
            with self.subTest(nom_du_cas):
                reponse = self.inscrire(client=application.app.test_client(), **champs)
                self.assertEqual(reponse.status_code, 200)
                self.assertIn('role="alert"', reponse.get_data(as_text=True))
        self.assertEqual(len(self.sql("SELECT id FROM utilisateur")), 4)   # aucun compte créé

    def test_inscription_deja_connecte_redirige(self):
        self.connecter()
        self.assertEqual(self.client.get("/inscription").status_code, 302)

    def test_course_sur_email_unique(self):
        """Si l'email est pris entre la vérification et l'insertion, on affiche une erreur propre."""
        vrai_execute = sqlite3.Connection.execute

        class FauxCurseur:
            def fetchone(self):
                return None

        class FausseConnexion:
            def __init__(self, vraie):
                self.vraie = vraie

            def execute(self, requete, params=()):
                if requete.startswith("SELECT 1 FROM utilisateur"):
                    return FauxCurseur()               # fait croire que l'email est libre
                return self.vraie.execute(requete, params)

            def commit(self):
                self.vraie.commit()

        vraie_get_db = application.get_db
        with mock.patch.object(application, "get_db", lambda: FausseConnexion(vraie_get_db())):
            reponse = self.inscrire(email="admin@terrains.test")
        self.assertIn("Un compte existe déjà", reponse.get_data(as_text=True))


class TestConnexion(BaseTest):

    def test_connexion_des_comptes_de_test(self):
        for email in ("admin@terrains.test", "proprietaire1@terrains.test", "notaire@terrains.test"):
            with self.subTest(email):
                client = application.app.test_client()
                reponse = self.connecter(email, client=client)
                self.assertEqual(reponse.status_code, 302)
                self.assertEqual(client.get("/mon-compte").status_code, 200)

    def test_email_insensible_a_la_casse(self):
        self.assertEqual(self.connecter("ADMIN@Terrains.TEST").status_code, 302)

    def test_mauvais_mot_de_passe_et_email_inconnu_meme_message(self):
        for email in ("admin@terrains.test", "inconnu@terrains.test"):
            with self.subTest(email):
                client = application.app.test_client()
                page = self.connecter(email, "faux", client=client).get_data(as_text=True)
                self.assertIn("Email ou mot de passe incorrect.", page)
                self.assertEqual(client.get("/mon-compte").status_code, 302)

    def test_page_connexion_s_affiche(self):
        self.assertEqual(self.client.get("/connexion").status_code, 200)

    def test_deja_connecte_redirige(self):
        self.connecter()
        self.assertEqual(self.client.get("/connexion").status_code, 302)

    def test_deconnexion_par_post_uniquement(self):
        self.connecter()
        self.assertEqual(self.client.get("/deconnexion").status_code, 405)
        reponse = self.client.post("/deconnexion", data={"csrf": self.jeton(url="/mon-compte")})
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(self.client.get("/mon-compte").status_code, 302)


class TestProtection(BaseTest):

    def test_mon_compte_protege(self):
        reponse = self.client.get("/mon-compte")
        self.assertEqual(reponse.status_code, 302)
        self.assertIn("/connexion", reponse.headers["Location"])

    def test_mon_compte_affiche_les_infos_de_l_administrateur(self):
        self.connecter()
        page = self.client.get("/mon-compte").get_data(as_text=True)
        self.assertIn("admin@terrains.test", page)
        self.assertIn("Compte vérifié", page)

    def test_mon_compte_non_verifie(self):
        self.connecter("proprietaire2@terrains.test")
        page = self.client.get("/mon-compte").get_data(as_text=True)
        self.assertIn("pas encore été vérifié", page)

    def test_session_d_un_compte_supprime_est_videe(self):
        with self.client.session_transaction() as session:
            session["user_id"] = 9999
        self.assertEqual(self.client.get("/mon-compte").status_code, 302)

    def test_get_db_reutilise_la_meme_connexion_dans_une_requete(self):
        with application.app.test_request_context():
            premiere = application.get_db()
            deuxieme = application.get_db()
            self.assertIs(premiere, deuxieme)

    def test_connecte_voit_son_nom_dans_l_entete(self):
        self.connecter("notaire@terrains.test")
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("Étude Notariale Test", page)
        self.assertIn("Se déconnecter", page)
        self.assertNotIn("Créer un compte", page)

    def test_visiteur_voit_connexion_et_inscription_dans_l_entete(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("Connexion", page)
        self.assertIn("Créer un compte", page)

    def test_csrf_refuse_formulaire_sans_jeton(self):
        reponse = self.client.post("/connexion", data={"email": "a@b.co", "mot_de_passe": "x"})
        self.assertEqual(reponse.status_code, 400)
        self.assertIn("Formulaire expiré", reponse.get_data(as_text=True))

    def test_csrf_refuse_jeton_vide_faux_ou_non_ascii(self):
        self.client.get("/connexion")
        for faux in ("", "faux", "é€"):
            with self.subTest(faux):
                reponse = self.client.post("/connexion", data={
                    "csrf": faux, "email": "a@b.co", "mot_de_passe": "x"})
                self.assertEqual(reponse.status_code, 400)

    def test_cle_secrete_creee_puis_reutilisee(self):
        chemin = os.path.join(DOSSIER_TEST, "cle_test.key")
        with mock.patch.object(application, "CLE_PATH", chemin):
            premiere = application.charger_cle_secrete()
            deuxieme = application.charger_cle_secrete()
        self.assertEqual(len(premiere), 32)
        self.assertEqual(premiere, deuxieme)

    def test_init_db_ne_remplace_pas_une_base_existante(self):
        self.sql("UPDATE terrain SET titre = 'Modifié' WHERE id = 1")
        application.init_db()
        self.assertEqual(self.sql("SELECT titre FROM terrain WHERE id = 1")[0][0], "Modifié")


# ------------------------------------------------------------------ profils

class TestProfil(BaseTest):

    def test_profil_d_un_proprietaire_verifie_avec_ses_terrains(self):
        page = self.client.get("/profil/2").get_data(as_text=True)
        self.assertIn("Propriétaire Test 1", page)
        self.assertIn("Compte vérifié", page)
        self.assertIn("Terrains publiés (4)", page)
        self.assertIn("https://wa.me/2250700000001?text=", page)
        self.assertIn("visites sur rendez-vous", page)
        self.assertEqual(self.nb_cartes("/profil/2"), 4)

    def test_profil_n_affiche_pas_les_annonces_en_attente(self):
        # le propriétaire 3 a 3 annonces dont 1 en attente : seules 2 sont publiques
        self.assertEqual(self.nb_cartes("/profil/3"), 2)
        self.assertNotIn("Lot en attente", self.client.get("/profil/3").get_data(as_text=True))

    def test_profil_non_verifie_sans_badge_et_sans_presentation(self):
        page = self.client.get("/profil/3").get_data(as_text=True)
        self.assertNotIn("Compte vérifié", page)
        self.assertIn("pas encore rédigé de présentation", page)

    def test_profil_d_un_notaire_sans_terrain(self):
        page = self.client.get("/profil/4").get_data(as_text=True)
        self.assertIn("Notaire", page)
        self.assertIn("Terrains publiés (0)", page)
        self.assertIn("Aucun terrain publié pour le moment.", page)

    def test_profil_administrateur_ou_inexistant_donne_404(self):
        self.assertEqual(self.client.get("/profil/1").status_code, 404)
        self.assertEqual(self.client.get("/profil/9999").status_code, 404)

    def test_la_fiche_d_un_terrain_mene_au_profil_du_vendeur(self):
        self.assertIn('href="/profil/2"', self.client.get("/terrain/1").get_data(as_text=True))

    def test_presentation_html_est_neutralisee(self):
        self.sql("UPDATE utilisateur SET presentation = ? WHERE id = 2",
                 ("<script>alert(1)</script>",))
        page = self.client.get("/profil/2").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)


class TestModifierProfil(BaseTest):

    def donnees(self, **champs):
        base = {"csrf": self.jeton(url="/mon-compte/modifier"), "nom": "Nouveau Nom",
                "telephone": "05 11 22 33 44", "presentation": "Ma présentation."}
        base.update(champs)
        return base

    def test_page_protegee(self):
        reponse = self.client.get("/mon-compte/modifier")
        self.assertEqual(reponse.status_code, 302)
        self.assertIn("/connexion", reponse.headers["Location"])

    def test_formulaire_prerempli_avec_les_infos_actuelles(self):
        self.connecter("proprietaire1@terrains.test")
        page = self.client.get("/mon-compte/modifier").get_data(as_text=True)
        self.assertIn('value="Propriétaire Test 1"', page)
        self.assertIn('value="+2250700000001"', page)
        self.assertIn("visites sur rendez-vous", page)

    def test_formulaire_sans_presentation(self):
        self.connecter("proprietaire2@terrains.test")
        self.assertEqual(self.client.get("/mon-compte/modifier").status_code, 200)

    def test_modification_valide(self):
        self.connecter("proprietaire2@terrains.test")
        reponse = self.client.post("/mon-compte/modifier", data=self.donnees())
        self.assertEqual(reponse.status_code, 302)
        nom, tel, presentation = self.sql(
            "SELECT nom, telephone_whatsapp, presentation FROM utilisateur WHERE id = 3")[0]
        self.assertEqual((nom, tel, presentation), ("Nouveau Nom", "2250511223344", "Ma présentation."))
        page = self.client.get("/mon-compte").get_data(as_text=True)
        self.assertIn("Votre profil est mis à jour.", page)
        self.assertIn("Nouveau Nom", self.client.get("/profil/3").get_data(as_text=True))

    def test_presentation_vide_est_enregistree_comme_absente(self):
        self.connecter("proprietaire1@terrains.test")
        self.client.post("/mon-compte/modifier", data=self.donnees(presentation=""))
        self.assertIsNone(self.sql("SELECT presentation FROM utilisateur WHERE id = 2")[0][0])

    def test_numero_etranger_deja_enregistre_peut_etre_reenvoye(self):
        self.sql("UPDATE utilisateur SET telephone_whatsapp = '33612345678' WHERE id = 2")
        self.connecter("proprietaire1@terrains.test")
        page = self.client.get("/mon-compte/modifier").get_data(as_text=True)
        self.assertIn('value="+33612345678"', page)
        reponse = self.client.post("/mon-compte/modifier", data=self.donnees(telephone="+33612345678"))
        self.assertEqual(reponse.status_code, 302)

    def test_refus_des_champs_invalides(self):
        self.connecter("proprietaire1@terrains.test")
        cas = {
            "nom trop court": {"nom": "A"},
            "téléphone invalide": {"telephone": "12345"},
            "présentation trop longue": {"presentation": "x" * 601},
        }
        for nom_du_cas, champs in cas.items():
            with self.subTest(nom_du_cas):
                reponse = self.client.post("/mon-compte/modifier", data=self.donnees(**champs))
                self.assertEqual(reponse.status_code, 200)
                self.assertIn('role="alert"', reponse.get_data(as_text=True))
        self.assertEqual(self.sql("SELECT nom FROM utilisateur WHERE id = 2")[0][0], "Propriétaire Test 1")

    def test_modification_sans_jeton_refusee(self):
        self.connecter("proprietaire1@terrains.test")
        reponse = self.client.post("/mon-compte/modifier", data={"nom": "Pirate"})
        self.assertEqual(reponse.status_code, 400)

    def test_liens_de_la_page_mon_compte(self):
        self.connecter("notaire@terrains.test")
        page = self.client.get("/mon-compte").get_data(as_text=True)
        self.assertIn("Modifier mon profil", page)
        self.assertIn('href="/profil/4"', page)
        client_admin = application.app.test_client()
        self.connecter("admin@terrains.test", client=client_admin)
        page_admin = client_admin.get("/mon-compte").get_data(as_text=True)
        self.assertIn("Modifier mon profil", page_admin)
        self.assertNotIn("Voir ma page publique", page_admin)


# ------------------------------------------------------------------ publication

class TestAides(unittest.TestCase):

    def test_lire_entier(self):
        self.assertEqual(application.lire_entier("18 000 000"), 18000000)
        self.assertEqual(application.lire_entier("18\u202f000\u202f000"), 18000000)
        self.assertEqual(application.lire_entier("600"), 600)
        for faux in ("", "abc", "12,5", "-3", "1.5"):
            self.assertIsNone(application.lire_entier(faux), faux)

    def test_type_image_reconnu_par_le_contenu(self):
        self.assertEqual(application.type_image(JPEG), "jpg")
        self.assertEqual(application.type_image(PNG), "png")
        self.assertEqual(application.type_image(WEBP), "webp")
        self.assertIsNone(application.type_image(b"RIFF0000AVI " + b"0" * 20))
        self.assertIsNone(application.type_image(b"<?php echo 1; ?>"))
        self.assertIsNone(application.type_image(b""))


class TestPublier(BaseTest):

    def donnees(self, **champs):
        base = {"csrf": self.jeton(url="/publier"), "titre": "Terrain de test",
                "quartier": "1", "superficie": "600", "prix": "18 000 000",
                "titre_foncier": "1", "type": "1", "description": "Un beau terrain."}
        base.update(champs)
        return base

    def publier(self, **champs):
        return self.client.post("/publier", data=self.donnees(**champs),
                                content_type="multipart/form-data")

    def nb_terrains(self):
        return len(self.sql("SELECT id FROM terrain"))

    def test_page_protegee(self):
        reponse = self.client.get("/publier")
        self.assertEqual(reponse.status_code, 302)
        self.assertIn("/connexion", reponse.headers["Location"])

    def test_administrateur_n_a_pas_acces(self):
        self.connecter("admin@terrains.test")
        reponse = self.client.get("/publier")
        self.assertEqual(reponse.status_code, 403)
        self.assertIn("Accès refusé", reponse.get_data(as_text=True))

    def test_formulaire_affiche_les_listes(self):
        self.connecter("proprietaire1@terrains.test")
        page = self.client.get("/publier").get_data(as_text=True)
        for texte in ("Millionnaire", "ACD (Arrêté de Concession Définitive)", "Résidentiel", "Envoyer pour validation"):
            self.assertIn(texte, page)

    def test_publication_valide_reste_en_attente(self):
        self.connecter("proprietaire1@terrains.test")
        avant = self.nb_terrains()
        reponse = self.publier()
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(self.nb_terrains(), avant + 1)
        titre, prix, superficie, statut, vendeur, description = self.sql(
            "SELECT titre, prix, superficie, statut, id_vendeur, description "
            "FROM terrain ORDER BY id DESC LIMIT 1")[0]
        self.assertEqual((titre, prix, superficie, statut, vendeur),
                         ("Terrain de test", 18000000, 600, "en_attente", 2))
        self.assertEqual(description, "Un beau terrain.")
        page = self.client.get("/mes-annonces").get_data(as_text=True)
        self.assertIn("Votre annonce est enregistrée", page)
        self.assertIn("En attente de validation", page)
        self.assertEqual(self.nb_cartes("/"), 6)                    # invisible tant que non validée

    def test_description_vide_enregistree_comme_absente(self):
        self.connecter("notaire@terrains.test")
        self.publier(description="")
        self.assertIsNone(self.sql("SELECT description FROM terrain ORDER BY id DESC LIMIT 1")[0][0])

    def test_annonce_validee_apparait_dans_la_liste(self):
        self.connecter("proprietaire1@terrains.test")
        self.publier()
        self.sql("UPDATE terrain SET statut = 'publie' WHERE titre = 'Terrain de test'")
        self.assertEqual(self.nb_cartes("/"), 7)

    def test_refus_des_champs_invalides(self):
        self.connecter("proprietaire1@terrains.test")
        cas = {
            "titre trop court": {"titre": "abc"},
            "titre trop long": {"titre": "x" * 101},
            "description trop longue": {"description": "x" * 1001},
            "superficie non numérique": {"superficie": "abc"},
            "superficie nulle": {"superficie": "0"},
            "superficie trop grande": {"superficie": "10000001"},
            "prix non numérique": {"prix": "beaucoup"},
            "prix nul": {"prix": "0"},
            "prix trop grand": {"prix": "100000000001"},
            "quartier inexistant": {"quartier": "999"},
            "titre foncier inexistant": {"titre_foncier": "999"},
            "type inexistant": {"type": "999"},
            "quartier vide": {"quartier": ""},
        }
        avant = self.nb_terrains()
        for nom_du_cas, champs in cas.items():
            with self.subTest(nom_du_cas):
                reponse = self.publier(**champs)
                self.assertEqual(reponse.status_code, 200)
                self.assertIn('role="alert"', reponse.get_data(as_text=True))
        self.assertEqual(self.nb_terrains(), avant)

    def test_valeurs_saisies_conservees_apres_une_erreur(self):
        self.connecter("proprietaire1@terrains.test")
        page = self.publier(titre="abc", superficie="750").get_data(as_text=True)
        self.assertIn('value="750"', page)
        self.assertIn('value="abc"', page)
        self.assertIn('value="1" selected', page)

    def test_limite_d_annonces_en_attente(self):
        self.connecter("proprietaire1@terrains.test")
        for _ in range(10):
            self.sql("INSERT INTO terrain (titre, superficie, prix, id_quartier, id_type_titre, "
                     "id_type_terrain, id_vendeur) VALUES ('Attente', 100, 100, 1, 1, 1, 2)")
        avant = self.nb_terrains()
        page = self.publier().get_data(as_text=True)
        self.assertIn("10 annonces en attente", page)
        self.assertEqual(self.nb_terrains(), avant)

    def test_sans_jeton_refuse(self):
        self.connecter("proprietaire1@terrains.test")
        reponse = self.client.post("/publier", data={"titre": "Pirate"})
        self.assertEqual(reponse.status_code, 400)

    def test_envoi_trop_volumineux(self):
        self.connecter("proprietaire1@terrains.test")
        donnees = self.donnees()
        donnees["photos"] = (io.BytesIO(JPEG + b"0" * (15 * 1024 * 1024)), "enorme.jpg")
        reponse = self.client.post("/publier", data=donnees, content_type="multipart/form-data")
        self.assertEqual(reponse.status_code, 413)
        self.assertIn("Envoi trop volumineux", reponse.get_data(as_text=True))


class TestPhotos(BaseTest):

    def envoyer(self, fichiers, **champs):
        donnees = {"csrf": self.jeton(url="/publier"), "titre": "Terrain avec photos",
                   "quartier": "1", "superficie": "500", "prix": "9000000",
                   "titre_foncier": "1", "type": "1"}
        donnees.update(champs)
        donnees["photos"] = [(io.BytesIO(contenu), nom) for contenu, nom in fichiers]
        return self.client.post("/publier", data=donnees, content_type="multipart/form-data")

    def nb_photos(self):
        return len(self.sql("SELECT id FROM photo"))

    def test_trois_photos_enregistrees_et_servies(self):
        self.connecter("proprietaire1@terrains.test")
        reponse = self.envoyer([(JPEG, "a.jpg"), (PNG, "b.png"), (WEBP, "c.webp")])
        self.assertEqual(reponse.status_code, 302)
        urls = [ligne[0] for ligne in self.sql("SELECT url FROM photo ORDER BY id")]
        self.assertEqual(len(urls), 3)
        self.assertEqual([u.rsplit(".", 1)[1] for u in urls], ["jpg", "png", "webp"])
        for url in urls:
            self.assertRegex(url, r"^/photos/[0-9a-f]{32}\.(jpg|png|webp)$")
            with self.client.get(url) as fichier:
                self.assertEqual(fichier.status_code, 200)
                self.assertEqual(fichier.headers["X-Content-Type-Options"], "nosniff")
        with self.client.get(urls[0]) as fichier:
            self.assertEqual(fichier.data, JPEG)

    def test_le_nom_du_fichier_envoye_n_est_jamais_utilise(self):
        self.connecter("proprietaire1@terrains.test")
        self.envoyer([(JPEG, "../../etc/passwd.jpg")])
        url = self.sql("SELECT url FROM photo")[0][0]
        self.assertNotIn("passwd", url)
        self.assertNotIn("..", url)

    def test_photos_visibles_sur_la_fiche_la_liste_et_le_profil(self):
        self.connecter("proprietaire1@terrains.test")
        self.envoyer([(JPEG, "a.jpg"), (PNG, "b.png")])
        self.sql("UPDATE terrain SET statut = 'publie' WHERE titre = 'Terrain avec photos'")
        premiere, deuxieme = [l[0] for l in self.sql("SELECT url FROM photo ORDER BY id")]
        id_terrain = self.sql("SELECT id FROM terrain WHERE titre = 'Terrain avec photos'")[0][0]
        fiche = self.client.get(f"/terrain/{id_terrain}").get_data(as_text=True)
        self.assertIn(f'class="photo-principale" src="{premiere}"', fiche)
        self.assertIn(deuxieme, fiche)
        self.assertIn(f'class="carte-photo" src="{premiere}"', self.client.get("/").get_data(as_text=True))
        self.assertIn(premiere, self.client.get("/profil/2").get_data(as_text=True))

    def test_fiche_avec_une_seule_photo_sans_miniatures(self):
        self.connecter("proprietaire1@terrains.test")
        self.envoyer([(JPEG, "a.jpg")])
        self.sql("UPDATE terrain SET statut = 'publie' WHERE titre = 'Terrain avec photos'")
        id_terrain = self.sql("SELECT id FROM terrain WHERE titre = 'Terrain avec photos'")[0][0]
        self.assertNotIn("miniatures", self.client.get(f"/terrain/{id_terrain}").get_data(as_text=True))

    def test_refus_des_mauvaises_photos(self):
        self.connecter("proprietaire1@terrains.test")
        avant = len(self.sql("SELECT id FROM terrain"))
        cas = {
            "fichier non image déguisé en jpg": [(b"<?php echo 1; ?>", "virus.jpg")],
            "photo trop lourde": [(JPEG + b"0" * (3 * 1024 * 1024), "grosse.jpg")],
            "trop de photos": [(JPEG, f"{i}.jpg") for i in range(5)],
        }
        for nom_du_cas, fichiers in cas.items():
            with self.subTest(nom_du_cas):
                reponse = self.envoyer(fichiers)
                self.assertEqual(reponse.status_code, 200)
                self.assertIn('role="alert"', reponse.get_data(as_text=True))
        self.assertEqual(len(self.sql("SELECT id FROM terrain")), avant)
        self.assertEqual(self.nb_photos(), 0)

    def test_champ_photo_vide_est_ignore(self):
        self.connecter("proprietaire1@terrains.test")
        reponse = self.envoyer([(b"", "")])
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(self.nb_photos(), 0)

    def test_adresses_de_photos_invalides(self):
        self.assertEqual(self.client.get("/photos/mauvais-nom.jpg").status_code, 404)
        self.assertEqual(self.client.get("/photos/..%2Fapp.py").status_code, 404)
        self.assertEqual(self.client.get("/photos/" + "a" * 32 + ".jpg").status_code, 404)


class TestMesAnnonces(BaseTest):

    def test_page_protegee(self):
        self.assertEqual(self.client.get("/mes-annonces").status_code, 302)

    def test_affiche_les_annonces_avec_leur_statut(self):
        self.connecter("proprietaire2@terrains.test")           # 3 annonces : 2 publiées, 1 en attente
        page = self.client.get("/mes-annonces").get_data(as_text=True)
        self.assertEqual(page.count("Publiée"), 2)
        self.assertEqual(page.count("En attente de validation"), 1)
        self.assertIn('href="/terrain/4"', page)
        self.assertNotIn('href="/terrain/7"', page)             # pas de lien tant que non publiée
        self.assertIn("Publier un terrain", page)

    def test_aucune_annonce(self):
        self.connecter("notaire@terrains.test")
        self.assertIn("pas encore d'annonce", self.client.get("/mes-annonces").get_data(as_text=True))

    def test_administrateur_sans_bouton_publier(self):
        self.connecter("admin@terrains.test")
        page = self.client.get("/mes-annonces").get_data(as_text=True)
        self.assertIn("pas encore d'annonce", page)
        self.assertNotIn("Publier un terrain", page)

    def test_lien_publier_dans_l_entete_selon_le_profil(self):
        self.assertNotIn("Publier un terrain", self.client.get("/").get_data(as_text=True))
        self.connecter("notaire@terrains.test")
        self.assertIn("Publier un terrain", self.client.get("/").get_data(as_text=True))
        autre = application.app.test_client()
        self.connecter("admin@terrains.test", client=autre)
        self.assertNotIn("Publier un terrain", autre.get("/").get_data(as_text=True))

    def test_en_tetes_de_securite(self):
        entetes = self.client.get("/").headers
        self.assertEqual(entetes["X-Content-Type-Options"], "nosniff")
        self.assertEqual(entetes["X-Frame-Options"], "DENY")


# ------------------------------------------------------------------ administration

class TestAdmin(BaseTest):

    def poster(self, url):
        return self.client.post(url, data={"csrf": self.jeton(url="/admin")})

    def statut(self, id_terrain):
        return self.sql("SELECT statut FROM terrain WHERE id = ?", (id_terrain,))[0][0]

    def test_acces_visiteur_proprietaire_et_administrateur(self):
        reponse = self.client.get("/admin")
        self.assertEqual(reponse.status_code, 302)
        self.assertIn("/connexion", reponse.headers["Location"])
        self.connecter("proprietaire1@terrains.test")
        self.assertEqual(self.client.get("/admin").status_code, 403)
        autre = application.app.test_client()
        self.connecter("admin@terrains.test", client=autre)
        self.assertEqual(autre.get("/admin").status_code, 200)

    def test_tableau_de_bord(self):
        self.connecter("admin@terrains.test")
        page = self.client.get("/admin").get_data(as_text=True)
        self.assertIn("Annonces en attente (1)", page)
        self.assertIn("Lot en attente de validation", page)
        self.assertIn("Comptes à vérifier (1)", page)
        self.assertIn("Propriétaire Test 2", page)
        self.assertIn("En attente de validation", page)           # libellé de la statistique

    def test_annonce_avec_photo_affichee_dans_l_administration(self):
        self.sql("INSERT INTO photo (url, id_terrain) VALUES ('/photos/test.jpg', 7)")
        self.connecter("admin@terrains.test")
        page = self.client.get("/admin").get_data(as_text=True)
        self.assertIn('src="/photos/test.jpg"', page)
        self.assertIn("1 photo", page)

    def test_valider_publie_l_annonce(self):
        self.connecter("admin@terrains.test")
        self.assertEqual(self.poster("/admin/annonces/7/valider").status_code, 302)
        self.assertEqual(self.statut(7), "publie")
        self.assertIn("Annonce publiée.", self.client.get("/admin").get_data(as_text=True))
        self.assertEqual(self.nb_cartes("/"), 7)

    def test_refuser_masque_l_annonce(self):
        self.connecter("admin@terrains.test")
        self.poster("/admin/annonces/7/refuser")
        self.assertEqual(self.statut(7), "refuse")
        self.assertIn("Annonce refusée.", self.client.get("/admin").get_data(as_text=True))
        self.assertEqual(self.nb_cartes("/"), 6)

    def test_annonce_deja_traitee_ou_inexistante_inchangee(self):
        self.connecter("admin@terrains.test")
        self.poster("/admin/annonces/1/refuser")                    # l'annonce 1 est déjà publiée
        self.assertEqual(self.statut(1), "publie")
        self.assertIn("plus en attente", self.client.get("/admin").get_data(as_text=True))
        self.poster("/admin/annonces/9999/valider")
        self.assertEqual(len(self.sql("SELECT id FROM terrain")), 7)

    def test_action_inconnue_et_methode_get(self):
        self.connecter("admin@terrains.test")
        self.assertEqual(self.poster("/admin/annonces/7/supprimer").status_code, 404)
        self.assertEqual(self.statut(7), "en_attente")
        self.assertEqual(self.client.get("/admin/annonces/7/valider").status_code, 405)

    def test_un_non_administrateur_ne_peut_rien_decider(self):
        self.connecter("proprietaire1@terrains.test")
        jeton = self.jeton(url="/mon-compte")
        reponse = self.client.post("/admin/annonces/7/valider", data={"csrf": jeton})
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(self.statut(7), "en_attente")
        reponse = self.client.post("/admin/comptes/3/verifier", data={"csrf": jeton})
        self.assertEqual(reponse.status_code, 403)

    def test_decision_sans_jeton_refusee(self):
        self.connecter("admin@terrains.test")
        reponse = self.client.post("/admin/annonces/7/valider", data={})
        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(self.statut(7), "en_attente")

    def test_verifier_un_compte(self):
        self.connecter("admin@terrains.test")
        self.poster("/admin/comptes/3/verifier")
        self.assertEqual(self.sql("SELECT verifie FROM utilisateur WHERE id = 3")[0][0], 1)
        self.assertIn("Compte marqué comme vérifié.", self.client.get("/admin").get_data(as_text=True))
        self.assertIn("Compte vérifié", self.client.get("/profil/3").get_data(as_text=True))

    def test_verifier_un_compte_inutile_ou_inexistant(self):
        self.connecter("admin@terrains.test")
        self.poster("/admin/comptes/2/verifier")                    # déjà vérifié
        self.assertIn("pas besoin d", self.client.get("/admin").get_data(as_text=True))
        self.poster("/admin/comptes/1/verifier")                    # l'administrateur lui-même
        self.poster("/admin/comptes/9999/verifier")
        self.assertEqual(self.sql("SELECT verifie FROM utilisateur WHERE id = 1")[0][0], 1)

    def test_listes_vides(self):
        self.sql("UPDATE terrain SET statut = 'publie' WHERE id = 7")
        self.sql("UPDATE utilisateur SET verifie = 1")
        self.connecter("admin@terrains.test")
        page = self.client.get("/admin").get_data(as_text=True)
        self.assertIn("Aucune annonce en attente.", page)
        self.assertIn("Aucun compte à vérifier.", page)

    def test_liens_vers_l_administration_selon_le_profil(self):
        self.assertNotIn("Administration", self.client.get("/").get_data(as_text=True))
        self.connecter("admin@terrains.test")
        self.assertIn("Administration", self.client.get("/").get_data(as_text=True))
        self.assertIn("Espace administrateur", self.client.get("/mon-compte").get_data(as_text=True))
        autre = application.app.test_client()
        self.connecter("notaire@terrains.test", client=autre)
        self.assertNotIn("Administration", autre.get("/").get_data(as_text=True))
        self.assertNotIn("Espace administrateur", autre.get("/mon-compte").get_data(as_text=True))


# ------------------------------------------------------------------ reparer.py

class TestReparer(unittest.TestCase):

    def setUp(self):
        self.dossier = tempfile.mkdtemp(dir=DOSSIER_TEST)
        for fichier in ("schema.sql", "donnees_initiales.sql"):
            shutil.copy(os.path.join(RACINE, fichier), self.dossier)
        self.base = os.path.join(self.dossier, "terrains.db")
        patchs = [mock.patch.object(reparer, "BASE", self.dossier),
                  mock.patch.object(reparer, "DB", self.base)]
        for p in patchs:
            p.start()
            self.addCleanup(p.stop)

    def nb(self, statut):
        base = sqlite3.connect(self.base)
        try:
            return base.execute("SELECT COUNT(*) FROM terrain WHERE statut = ?", (statut,)).fetchone()[0]
        finally:
            base.close()

    def lancer(self, *args):
        with mock.patch("sys.stdout", new=StringIO()) as sortie:
            reparer.principal(list(args))
        return sortie.getvalue()

    def test_reinitialiser_cree_la_base(self):
        self.assertIn("6 annonces publiées", self.lancer())
        self.assertEqual((self.nb("publie"), self.nb("en_attente")), (6, 1))

    def test_reinitialiser_remplace_une_base_abimee(self):
        with open(self.base, "w") as f:
            f.write("n'importe quoi")
        self.lancer()
        self.assertEqual(self.nb("publie"), 6)

    def test_publier_puis_remettre_en_attente(self):
        self.lancer()
        self.assertIn("statut = publie", self.lancer("publier", "7"))
        self.assertEqual(self.nb("publie"), 7)
        self.assertIn("statut = en_attente", self.lancer("attente", "7"))
        self.assertEqual(self.nb("publie"), 6)

    def test_annonce_inexistante(self):
        self.lancer()
        self.assertIn("Aucune annonce n°99", self.lancer("publier", "99"))

    def test_arguments_invalides_affichent_l_aide(self):
        self.assertIn("Répare ou pilote", self.lancer("n'importe", "quoi"))

    def test_commentaire_sans_tirets_est_repare(self):
        chemin = os.path.join(self.dossier, "schema.sql")
        with open(chemin, encoding="utf-8") as f:
            lignes = f.read().split("\n")
        lignes[0] = lignes[0].replace("-- ", "", 1)
        with open(chemin, "w", encoding="utf-8") as f:
            f.write("\n".join(lignes))
        reparer.corriger_commentaires(chemin)
        with open(chemin, encoding="utf-8") as f:
            self.assertTrue(f.readline().startswith("-- "))

    def test_base_verrouillee_arrete_proprement(self):
        self.lancer()
        with mock.patch.object(reparer.os, "remove", side_effect=PermissionError), \
             mock.patch("sys.stdout", new=StringIO()) as sortie:
            with self.assertRaises(SystemExit):
                reparer.reinitialiser()
        self.assertIn("Impossible de supprimer", sortie.getvalue())

    def test_changer_statut_sur_base_sans_tables(self):
        sqlite3.connect(self.base).close()                 # fichier de base vide
        with mock.patch("sys.stdout", new=StringIO()) as sortie:
            with self.assertRaises(SystemExit):
                reparer.changer_statut("publie", 7)
        self.assertIn("Erreur", sortie.getvalue())


if __name__ == "__main__":
    unittest.main()
