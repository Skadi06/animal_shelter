"""Database connection and initial shelter data setup.

This module keeps database-specific setup separate from Flask route handlers.
It uses PostgreSQL when DATABASE_URL or POSTGRES_URL is configured, and a
local SQLite file for development.
"""

from pathlib import Path
import os
import sqlite3
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Environment variables are settings supplied outside the Python source code.
# Vercel/Supabase may use POSTGRES_URL; other setups may use DATABASE_URL.
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
# SQLite stores its local development database beside this Python file.
DB_PATH = Path(__file__).resolve().parent / "shelter.db"


class Database:
    """Give the rest of the app one consistent way to talk to either database.

    The website uses Supabase PostgreSQL when a connection URL is configured.
    On a computer without that setting, it uses a local SQLite file instead.
    """
    def __init__(self):
        """Open a connection and make database rows easy to read by column name.

        Supabase's URL may include options for another database driver, so only
        options Psycopg understands are kept. ``prepare_threshold=None`` avoids
        prepared statements, which the Supabase transaction pooler does not use.
        SQLite enables foreign keys to keep local behavior close to PostgreSQL.
        """
        # A configured URL means we are connecting to the hosted PostgreSQL DB.
        if DATABASE_URL:
            import psycopg
            from psycopg.rows import dict_row
            # The Supabase/Vercel integration can append a hint for Vercel's
            # JavaScript driver; libpq/Psycopg rejects unknown URI options.
            parts = urlsplit(DATABASE_URL)
            psycopg_options = {
                "sslmode", "sslcert", "sslkey", "sslrootcert", "connect_timeout",
                "application_name", "channel_binding", "gssencmode", "keepalives",
                "keepalives_idle", "keepalives_interval", "keepalives_count",
                "target_session_attrs", "load_balance_hosts", "hostaddr",
            }
            # Remove URL options Psycopg cannot understand before connecting.
            query = urlencode([
                (key, value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
                if key.lower() in psycopg_options
            ])
            postgres_url = urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
            self.connection = psycopg.connect(
                postgres_url,
                row_factory=dict_row,
                prepare_threshold=None,  # Supabase transaction pooler does not support prepared statements.
            )
            self.postgres = True
        else:
            # No hosted URL: create/use the local SQLite file instead.
            self.connection = sqlite3.connect(DB_PATH)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.postgres = False

    def __enter__(self):
        """Return this connection wrapper when Python enters a ``with db()`` block.

        This lets routes write ``with db() as conn`` and know the connection
        will be finalized when the indented block finishes.
        """
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Commit a successful block, roll back a failed one, and close the DB.

        Python calls this automatically after a ``with`` block. The original
        exception details are passed to the database driver so it can decide
        whether the transaction should commit or roll back. The connection is
        closed in ``finally`` even if finishing the transaction raises an error.
        """
        try:
            return self.connection.__exit__(exc_type, exc_value, traceback)
        finally:
            self.connection.close()

    def execute(self, sql, values=()):
        """Run one SQL command with values supplied separately from the command.

        Routes use ``?`` placeholders so the same query works with SQLite.
        When PostgreSQL is active, this method changes those placeholders to
        Psycopg's ``%s`` format. The favorites insert also gets PostgreSQL's
        equivalent of SQLite's ``INSERT OR IGNORE`` behavior.
        """
        if self.postgres:
            # Existing routes use SQLite-style question marks. Convert them
            # here so the same route code can run against PostgreSQL.
            sql = sql.replace("INSERT OR IGNORE INTO favorites", "INSERT INTO favorites")
            sql = sql.replace("VALUES(?,?)", "VALUES(%s,%s) ON CONFLICT (user_id, animal_id) DO NOTHING") if "INSERT INTO favorites" in sql else sql
            sql = sql.replace("?", "%s")
        return self.connection.execute(sql, values)

    def executemany(self, sql, values):
        """Run the same insert/update once for every row in ``values``.

        This is used for starter records: ``values`` is a list of animals or
        volunteer opportunities, and each tuple supplies one row's values.
        """
        for row in values:
            self.execute(sql, row)


def db():
    """Create a fresh database connection wrapper for one route operation."""
    return Database()


def init_db():
    """Create the tables the shelter website needs and add example content.

    This can run more than once: ``IF NOT EXISTS`` leaves existing tables as
    they are, sample animals are added only if missing, and opportunities are
    added only when their table is empty. That means a restart does not replace
    animal information entered by staff.
    """
    # Keep table definitions shared across local SQLite and hosted PostgreSQL;
    # only their auto-increment and timestamp default syntax differ.
    id_type = "SERIAL" if DATABASE_URL else "INTEGER"
    time_default = "CURRENT_TIMESTAMP::text" if DATABASE_URL else "CURRENT_TIMESTAMP"
    with db() as conn:
        # Each table stores one kind of information: accounts, animals, saved
        # animal links, adoption/volunteer applications, opportunities, or messages.
        schema = f"""
        CREATE TABLE IF NOT EXISTS users (
            id {id_type} PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user', name TEXT DEFAULT '', phone TEXT DEFAULT '',
            address TEXT DEFAULT '', experience TEXT DEFAULT '', pets TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS animals (
            id {id_type} PRIMARY KEY, name TEXT NOT NULL, species TEXT DEFAULT 'Dog', breed TEXT DEFAULT '',
            age TEXT DEFAULT '', gender TEXT DEFAULT '', size TEXT DEFAULT '', description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Available', photo TEXT DEFAULT '', vaccinated TEXT DEFAULT '',
            spayed_neutered TEXT DEFAULT '', dietary_needs TEXT DEFAULT '', behavior TEXT DEFAULT '', special_care TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            animal_id INTEGER NOT NULL REFERENCES animals(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, animal_id)
        );
        CREATE TABLE IF NOT EXISTS adoptions (
            id {id_type} PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), animal_id INTEGER NOT NULL REFERENCES animals(id),
            name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT DEFAULT '', housing TEXT DEFAULT '',
            other_pets TEXT DEFAULT '', experience TEXT DEFAULT '', status TEXT DEFAULT 'Submitted', created_at TEXT DEFAULT {time_default}
        );
        CREATE TABLE IF NOT EXISTS volunteer_applications (
            id {id_type} PRIMARY KEY, user_id INTEGER REFERENCES users(id), name TEXT NOT NULL, email TEXT NOT NULL,
            phone TEXT DEFAULT '', interests TEXT DEFAULT '', availability TEXT DEFAULT '', experience TEXT DEFAULT '',
            status TEXT DEFAULT 'Submitted', created_at TEXT DEFAULT {time_default}
        );
        CREATE TABLE IF NOT EXISTS opportunities (
            id {id_type} PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '', schedule TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS messages (
            id {id_type} PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            name TEXT NOT NULL, email TEXT NOT NULL, animal_id INTEGER,
            message TEXT NOT NULL, reply TEXT DEFAULT '', created_at TEXT DEFAULT {time_default}
        );
        """
        # The schema string contains multiple CREATE TABLE commands. Split it
        # at each semicolon and send each non-empty command to the database.
        for statement in schema.split(";"):
            if statement.strip():
                conn.execute(statement)
        # Adoption applications enter staff review as soon as they are sent.
        # Upgrade older records that still use the former Submitted status.
        conn.execute("UPDATE adoptions SET status='In Review' WHERE status='Submitted'")
        conn.execute(
            """UPDATE animals SET status='Pending'
               WHERE status='Available' AND id IN (
                   SELECT animal_id FROM adoptions WHERE status='In Review'
               )"""
        )
        # Upgrade databases created before account-linked questions and the
        # regular-user role were introduced.
        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()} if not DATABASE_URL else {row["column_name"] for row in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users'").fetchall()}
        message_columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()} if not DATABASE_URL else {row["column_name"] for row in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name='messages'").fetchall()}
        if "role" in user_columns:
            conn.execute("UPDATE users SET role='user' WHERE role='volunteer'")
        if "user_id" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
        if "reply" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN reply TEXT DEFAULT ''")
        # Add the first four demo records only when there are no animals yet.
        count = conn.execute("SELECT COUNT(*) AS total FROM animals").fetchone()
        if count["total"] == 0:
            # Add demo listings only to a new database, so staff data is never
            # overwritten when a Vercel function starts again.
            # Every tuple follows the same order as the column list: name,
            # species, breed, age, gender, size, description, status, photo,
            # vaccination, spay/neuter, diet, behavior, and special care.
            conn.executemany("""INSERT INTO animals
              (name,species,breed,age,gender,size,description,status,photo,vaccinated,spayed_neutered,dietary_needs,behavior,special_care)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", [
                (
                    "Charlie", "Dog", "Golden Retriever", "2 years", "Male", "Large",
                    "A friendly, playful companion who loves long walks and meeting people.",
                    "Available", "https://images.unsplash.com/photo-1552053831-71594a27632d?w=800",
                    "Up to date", "Yes", "Standard adult diet",
                    "Friendly and energetic", "Daily exercise",
                ),
                (
                    "Bella", "Dog", "Mixed Breed", "8 months", "Female", "Medium",
                    "A curious puppy who is learning quickly and enjoys gentle play.",
                    "Available", "https://images.unsplash.com/photo-1543466835-00a7907e9de1?w=800",
                    "Up to date", "Scheduled", "Puppy food",
                    "Still in training", "Needs puppy socialization",
                ),
                (
                    "Max", "Dog", "Rescue Dog", "3 years", "Male", "Medium",
                    "A calm, affectionate dog ready for a patient forever family.",
                    "Pending", "https://images.unsplash.com/photo-1517849845537-4d257902454a?w=800",
                    "Up to date", "Yes", "Sensitive stomach; vet-approved food",
                    "Gentle and relaxed", "Slow introductions to new dogs",
                ),
                (
                    "Mittens", "Cat", "Domestic Shorthair", "1 year", "Female", "Small",
                    "A sweet indoor cat who likes sunny windows and quiet company.",
                    "Available", "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=800",
                    "Up to date", "Yes", "Standard cat diet",
                    "Litter trained", "Indoor home preferred",
                ),
            ])
        # Add sample dogs by name so existing databases receive these once too.
        # These three extra dogs are inserted by name, even into a database
        # that already had animals before this sample data was introduced.
        sample_dogs = [
            (
                "Daisy", "Dog", "Beagle Mix", "4 years", "Female", "Small",
                "Daisy is a cheerful trail buddy who loves sniffing around the yard and curling up after a walk.",
                "Available", "https://images.unsplash.com/photo-1548199973-03cce0bbc87b?w=800",
                "Up to date", "Yes", "Standard adult diet",
                "Social and curious", "Daily walks and a secure yard",
            ),
            (
                "Cooper", "Dog", "Labrador Retriever Mix", "1 year", "Male", "Large",
                "Cooper is an affectionate young dog who enjoys fetch, learning tricks, and spending time with people.",
                "Available", "https://images.unsplash.com/photo-1518717758536-85ae29035b6d?w=800",
                "Up to date", "Yes", "Standard adult diet",
                "Playful and eager to learn", "Needs regular exercise and training",
            ),
            (
                "Luna", "Dog", "Terrier Mix", "6 months", "Female", "Small",
                "Luna is a gentle puppy who is building confidence and would enjoy a patient home with time for training.",
                "Available", "https://images.unsplash.com/photo-1552053831-71594a27632d?w=800",
                "In progress", "Scheduled", "Puppy food",
                "Shy at first, warms up with treats", "Puppy socialization and basic training",
            ),
        ]
        for dog in sample_dogs:
            if not conn.execute("SELECT id FROM animals WHERE name=?", (dog[0],)).fetchone():
                conn.execute("""INSERT INTO animals
                  (name,species,breed,age,gender,size,description,status,photo,vaccinated,spayed_neutered,dietary_needs,behavior,special_care)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", dog)
        # Only seed volunteer roles on an empty table, so saved edits are kept.
        if conn.execute("SELECT COUNT(*) AS total FROM opportunities").fetchone()["total"] == 0:
            conn.executemany("INSERT INTO opportunities (title,description,schedule) VALUES (?,?,?)", [
                ("Animal Care Helper", "Help with feeding, enrichment, and keeping animal spaces tidy.", "Weekdays, 8–11 AM or 3–6 PM"),
                ("Adoption Event Support", "Welcome visitors and introduce them to animals at community events.", "Saturday events, 10 AM–2 PM"),
                ("Foster a Friend", "Provide a temporary home for an animal while they wait for adoption.", "Flexible, coordinated with shelter staff")
            ])




