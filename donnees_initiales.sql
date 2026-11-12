-- Chargement initial : données de référence + annonces de TEST.
-- Les numéros ci-dessous sont fictifs : remplacez-les pour tester le bouton WhatsApp.

PRAGMA foreign_keys = ON;

-- Tables de référence (chargées une fois pour toutes)
INSERT INTO ville (nom) VALUES ('Yamoussoukro');

INSERT INTO quartier (nom, id_ville) VALUES
    ('Millionnaire', 1),
    ('Kokrenou', 1),
    ('Assabou', 1),
    ('N''Zuessy', 1);

INSERT INTO type_titre (libelle) VALUES
    ('ACD (Arrêté de Concession Définitive)'),
    ('Lettre d''attribution'),
    ('Attestation villageoise'),
    ('Arrêté de concession provisoire');

INSERT INTO type_terrain (libelle) VALUES
    ('Résidentiel'),
    ('Commercial'),
    ('Agricole');

-- Comptes de test (mot de passe de tous les comptes : motdepasse123).
-- À SUPPRIMER avant toute vraie mise en ligne. Seul le hash est stocké, jamais le mot de passe.
INSERT INTO utilisateur (nom, email, mot_de_passe_hash, telephone_whatsapp, presentation, role, verifie) VALUES
    ('Administrateur', 'admin@terrains.test', 'pbkdf2:sha256:1000000$4khsE6rr9eOT6H3A$64839db5983cc76fbf394eed1949c1d126115a4c9fa672642e4b3dcc65944c83', '2250700000000', NULL, 'administrateur', 1),
    ('Propriétaire Test 1', 'proprietaire1@terrains.test', 'pbkdf2:sha256:1000000$hmmJeqv3l9CXj9ul$405e2611be87ee52e30315db4cbae47b7d2ee8f9710023e7af5fce039fcf495e', '2250700000001', 'Propriétaire à Yamoussoukro. Terrains avec titre foncier, visites sur rendez-vous.
Profil de test pour la démonstration.', 'proprietaire', 1),
    ('Propriétaire Test 2', 'proprietaire2@terrains.test', 'pbkdf2:sha256:1000000$wyVwpjXQy90lL0GX$204c50b0703b72fcf82df33310668b1dd4801b911460cd2ffb1f9897015489d7', '2250700000002', NULL, 'proprietaire', 0),
    ('Étude Notariale Test', 'notaire@terrains.test', 'pbkdf2:sha256:1000000$rYQZni6RW03jSlSU$c2ba022af63d526878cb648cd5eb9bcc40ff742e520e7a14036a54c290f5748e', '2250700000003', 'Étude notariale à Yamoussoukro : vérification des titres fonciers et rédaction des actes de vente.
Profil de test pour la démonstration.', 'notaire', 1);

-- Annonces de test (id_quartier, id_type_titre, id_type_terrain, id_vendeur)
INSERT INTO terrain (titre, description, superficie, prix, statut, id_quartier, id_type_titre, id_type_terrain, id_vendeur) VALUES
    ('Lot de 600 m² bien situé',
     'Terrain plat, accès facile par route bitumée. Annonce de test pour la démonstration.',
     600, 18000000, 'publie', 1, 1, 1, 2),
    ('Terrain d''angle proche d''un grand axe',
     'Idéal pour un commerce ou un petit immeuble. Annonce de test pour la démonstration.',
     450, 25000000, 'publie', 2, 2, 2, 2),
    ('Grand terrain résidentiel',
     'Grande parcelle pouvant accueillir une villa avec jardin. Annonce de test pour la démonstration.',
     1200, 30000000, 'publie', 3, 1, 1, 2),
    ('Lot calme en zone résidentielle',
     'Quartier tranquille, à proximité des écoles. Annonce de test pour la démonstration.',
     500, 6500000, 'publie', 4, 3, 1, 3),
    ('Parcelle de 2 hectares',
     'Terrain agricole, sol adapté à la culture vivrière. Annonce de test pour la démonstration.',
     20000, 8000000, 'publie', 4, 4, 3, 3),
    ('Deux lots mitoyens',
     'Deux lots côte à côte vendus ensemble. Annonce de test pour la démonstration.',
     1200, 35000000, 'publie', 1, 1, 1, 2),
    ('Lot en attente de validation',
     'Cette annonce n''apparaît pas sur le site tant que l''administrateur ne l''a pas validée.',
     400, 9000000, 'en_attente', 2, 2, 1, 3);
