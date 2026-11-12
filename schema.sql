-- Schéma de la base (MCD version 1) : une table par entité du cahier des charges.
-- Chaque table sert de bloc extensible : on pourra ajouter des colonnes plus tard
-- (GPS, vidéo, mot de passe, etc.) sans casser les annonces existantes.

PRAGMA foreign_keys = ON;

CREATE TABLE ville (
    id  INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL UNIQUE
);

CREATE TABLE quartier (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    nom      TEXT NOT NULL,
    id_ville INTEGER NOT NULL REFERENCES ville(id),
    UNIQUE (nom, id_ville)
);

CREATE TABLE type_titre (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    libelle TEXT NOT NULL UNIQUE
);

CREATE TABLE type_terrain (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    libelle TEXT NOT NULL UNIQUE
);

CREATE TABLE utilisateur (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    nom                TEXT NOT NULL,                      -- nom affiché (personne, étude notariale...)
    email              TEXT NOT NULL UNIQUE COLLATE NOCASE, -- sert d'identifiant de connexion
    mot_de_passe_hash  TEXT NOT NULL,                      -- jamais le mot de passe lui-même
    telephone_whatsapp TEXT NOT NULL,                      -- format international sans le + (ex. 2250700000000)
    presentation       TEXT,                               -- texte de la page profil (Sprint 2, jour 3)
    role               TEXT NOT NULL CHECK (role IN ('administrateur', 'proprietaire', 'notaire')),
    verifie            INTEGER NOT NULL DEFAULT 0 CHECK (verifie IN (0, 1)),
    date_inscription   TEXT NOT NULL DEFAULT (date('now'))
);

CREATE TABLE terrain (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    titre           TEXT NOT NULL,
    description     TEXT,
    superficie      INTEGER NOT NULL CHECK (superficie > 0),   -- en m²
    prix            INTEGER NOT NULL CHECK (prix >= 0),        -- en FCFA
    statut          TEXT NOT NULL DEFAULT 'en_attente'
                    CHECK (statut IN ('en_attente', 'publie', 'refuse', 'vendu')),
    date_creation   TEXT NOT NULL DEFAULT (date('now')),
    id_quartier     INTEGER NOT NULL REFERENCES quartier(id),
    id_type_titre   INTEGER NOT NULL REFERENCES type_titre(id),
    id_type_terrain INTEGER NOT NULL REFERENCES type_terrain(id),
    id_vendeur      INTEGER NOT NULL REFERENCES utilisateur(id)
);

CREATE TABLE photo (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT NOT NULL,
    id_terrain INTEGER NOT NULL REFERENCES terrain(id) ON DELETE CASCADE
);
