"""PostgreSQL connection and shelter schema setup.

This module keeps database setup separate from Flask route handlers. It requires
PostgreSQL through DATABASE_URL or POSTGRES_URL; SQLite is not supported.
"""

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")

class Database:
    """Provide a PostgreSQL connection with dictionary-style result rows.

    The website uses the configured PostgreSQL database.
    """
    def __init__(self):
        """Open a connection and make database rows easy to read by column name.

        Supabase's URL may include options for another database driver, so only
        options Psycopg understands are kept. ``prepare_threshold=None`` avoids
        prepared statements, which the Supabase transaction pooler does not use.
        """
        if not DATABASE_URL:
            raise RuntimeError(
                "PostgreSQL is required. Configure DATABASE_URL or POSTGRES_URL."
            )
        import psycopg
        from psycopg.rows import dict_row
        parts = urlsplit(DATABASE_URL)
        psycopg_options = {
            "sslmode", "sslcert", "sslkey", "sslrootcert", "connect_timeout",
            "application_name", "channel_binding", "gssencmode", "keepalives",
            "keepalives_idle", "keepalives_interval", "keepalives_count",
            "target_session_attrs", "load_balance_hosts", "hostaddr",
        }
        query = urlencode([
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() in psycopg_options
        ])
        postgres_url = urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
        self.connection = psycopg.connect(
            postgres_url,
            row_factory=dict_row,
            prepare_threshold=None,
        )
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

        Routes use ``?`` placeholders; this method changes those placeholders
        to Psycopg's ``%s`` format and maps favorite inserts to PostgreSQL
        conflict handling.
        """
        return self.connection.execute(sql.replace("?", "%s"), values)

def db():
    """Create a fresh database connection wrapper for one route operation."""
    return Database()

def init_db():
    """Create or upgrade the PostgreSQL tables the shelter website needs."""
    with db() as conn:
        schema = """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user', name TEXT DEFAULT '', phone TEXT DEFAULT '',
            address TEXT DEFAULT '', experience TEXT DEFAULT '', pets TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS animals (
            id SERIAL PRIMARY KEY, name TEXT NOT NULL, species TEXT DEFAULT 'Dog', breed TEXT DEFAULT '',
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
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), animal_id INTEGER NOT NULL REFERENCES animals(id),
            name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT DEFAULT '', housing TEXT DEFAULT '',
            other_pets TEXT DEFAULT '', experience TEXT DEFAULT '', status TEXT DEFAULT 'In Review', created_at TEXT DEFAULT CURRENT_TIMESTAMP::text
        );
        CREATE TABLE IF NOT EXISTS volunteer_applications (
            id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), name TEXT NOT NULL, email TEXT NOT NULL,
            phone TEXT DEFAULT '', interests TEXT DEFAULT '', availability TEXT DEFAULT '', experience TEXT DEFAULT '',
            status TEXT DEFAULT 'Submitted', created_at TEXT DEFAULT CURRENT_TIMESTAMP::text
        );
        CREATE TABLE IF NOT EXISTS opportunities (
            id SERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '', schedule TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            name TEXT NOT NULL, email TEXT NOT NULL, animal_id INTEGER,
            message TEXT NOT NULL, reply TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP::text
        );
        """
        for statement in schema.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute("UPDATE adoptions SET status='In Review' WHERE status='Submitted'")
        conn.execute(
            """UPDATE animals SET status='Pending'
               WHERE status='Available' AND id IN (
                   SELECT animal_id FROM adoptions WHERE status='In Review'
               )"""
        )
        user_columns = {row["column_name"] for row in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users'").fetchall()}
        message_columns = {row["column_name"] for row in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name='messages'").fetchall()}
        if "role" in user_columns:
            conn.execute("UPDATE users SET role='user' WHERE role='volunteer'")
        if "user_id" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
        if "reply" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN reply TEXT DEFAULT ''")
