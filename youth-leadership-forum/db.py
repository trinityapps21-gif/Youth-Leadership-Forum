"""Database layer.

Uses Turso (libSQL) when TURSO_DATABASE_URL is set, otherwise a local SQLite
file so the app can be run and tested without any keys.
Every query goes through query()/one()/execute()/insert() so the rest of the
app never touches a driver directly.
"""
import sqlite3

from flask import current_app, g

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'member',
        status TEXT NOT NULL DEFAULT 'pending',
        organization TEXT DEFAULT '',
        signup_note TEXT DEFAULT '',
        bio TEXT DEFAULT '',
        avatar TEXT DEFAULT '',
        status_reason TEXT DEFAULT '',
        suspended_until TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        last_seen TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        content TEXT DEFAULT '',
        image TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        is_removed INTEGER DEFAULT 0,
        removed_reason TEXT DEFAULT '',
        removed_by INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS likes (
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (post_id, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL DEFAULT 'direct',
        name TEXT DEFAULT '',
        description TEXT DEFAULT '',
        avatar TEXT DEFAULT '',
        created_by INTEGER,
        direct_key TEXT UNIQUE,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS conversation_members (
        conversation_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        role TEXT DEFAULT 'member',
        last_read_id INTEGER DEFAULT 0,
        joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (conversation_id, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS blocks (
        blocker_id INTEGER NOT NULL,
        blocked_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (blocker_id, blocked_id)
    )""",
    """CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_id INTEGER NOT NULL,
        target_type TEXT NOT NULL,
        target_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        status TEXT DEFAULT 'open',
        resolved_by INTEGER,
        resolved_at TEXT,
        resolution TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        admin_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        seen INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS admin_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        target_type TEXT,
        target_id INTEGER,
        reason TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS password_resets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        new_hash TEXT NOT NULL,
        note TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',
        reason TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        resolved_by INTEGER,
        resolved_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_resets_status ON password_resets(status, user_id)",
    "CREATE INDEX IF NOT EXISTS idx_posts_user ON posts(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_members_user ON conversation_members(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)",
    "CREATE INDEX IF NOT EXISTS idx_warnings_user ON warnings(user_id, seen)",
]


def _connect():
    cfg = current_app.config
    if cfg["TURSO_DATABASE_URL"]:
        if cfg["TURSO_DRIVER"] == "libsql":
            import libsql
            return libsql.connect(database=cfg["TURSO_DATABASE_URL"], auth_token=cfg["TURSO_AUTH_TOKEN"])
        from turso_http import Connection
        return Connection(cfg["TURSO_DATABASE_URL"], cfg["TURSO_AUTH_TOKEN"], timeout=cfg["TURSO_TIMEOUT"])
    return sqlite3.connect(cfg["LOCAL_DB_PATH"])


def get_db():
    if "db" not in g:
        g.db = _connect()
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def query(sql, params=()):
    """Run a SELECT and return a list of dicts."""
    cur = get_db().execute(sql, tuple(params))
    if not cur.description:
        return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=()):
    """Run a write statement and commit."""
    conn = get_db()
    conn.execute(sql, tuple(params))
    conn.commit()


def insert(sql, params=()):
    """Run an INSERT (without RETURNING) and return the new row id."""
    conn = get_db()
    cur = conn.execute(sql + " RETURNING id", tuple(params))
    row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def init_db(app):
    """Create tables and the first admin account if needed."""
    from werkzeug.security import generate_password_hash
    with app.app_context():
        conn = get_db()
        if hasattr(conn, "batch"):
            conn.batch(SCHEMA)  # one round trip instead of one per table
        else:
            for stmt in SCHEMA:
                conn.execute(stmt)
        conn.commit()
        cfg = app.config
        has_admin = one("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
        if not has_admin and cfg["ADMIN_EMAIL"] and cfg["ADMIN_PASSWORD"]:
            execute(
                "INSERT INTO users (name, email, password_hash, role, status) VALUES (?,?,?,?,?)",
                (cfg["ADMIN_NAME"], cfg["ADMIN_EMAIL"], generate_password_hash(cfg["ADMIN_PASSWORD"]), "admin", "active"),
            )
            app.logger.info("Created first admin account: %s", cfg["ADMIN_EMAIL"])
        elif not has_admin:
            app.logger.warning("No admin exists. Set ADMIN_EMAIL and ADMIN_PASSWORD in .env and restart.")
        close_db()
