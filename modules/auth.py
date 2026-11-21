
import sqlite3
import os
import hashlib
import hmac
import secrets
from pathlib import Path


DB_PATH = Path(
    os.getenv("TRUTHLENS_DB", "truthlens.db")
).expanduser().resolve()


def _connect():
    """Create a database connection."""

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30
    )

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def init_db():
    """Create required database tables."""

    with _connect() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS investigations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # Forward-compatible schema migration for persisted candidate claims.
        investigation_columns = {
            row["name"] for row in conn.execute(
                "PRAGMA table_info(investigations)"
            ).fetchall()
        }
        if "claims_json" not in investigation_columns:
            conn.execute(
                "ALTER TABLE investigations ADD COLUMN claims_json TEXT NOT NULL DEFAULT '[]'"
            )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS evidence(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                investigation_id INTEGER NOT NULL,
                claim TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT,
                excerpt TEXT NOT NULL,
                relation TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(investigation_id)
                REFERENCES investigations(id)
            )
        """)


def _hash_password(password, salt):
    """Secure password hashing using PBKDF2-HMAC-SHA256."""

    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        310000
    )


def register_user(username, password):
    """Register a new user account."""

    if not isinstance(username, str):
        return False, "Invalid username."

    if not isinstance(password, str):
        return False, "Invalid password."

    username = username.strip()

    if not 3 <= len(username) <= 40:
        return False, "Username must be 3–40 characters."

    if not username.replace("_", "").replace("-", "").isalnum():
        return False, "Use letters, numbers, underscore or hyphen only."

    if not 8 <= len(password) <= 128:
        return False, "Password must contain 8–128 characters."

    username = username.lower()

    salt = secrets.token_bytes(16)
    password_hash = _hash_password(password, salt)

    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO users(username, salt, password_hash)
                VALUES (?, ?, ?)
                """,
                (username, salt, password_hash)
            )

        return True, "Account created successfully. Please sign in."

    except sqlite3.IntegrityError:
        return False, "That username is already taken."

    except sqlite3.Error:
        return False, "Database error. Please try again."


def authenticate_user(username, password):
    """Authenticate an existing user."""

    if not isinstance(username, str) or not isinstance(password, str):
        return None

    username = username.strip().lower()

    if not username or not password or len(password) > 128:
        return None

    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,)
            ).fetchone()

        if row is None:
            return None

        candidate = _hash_password(
            password,
            row["salt"]
        )

        if hmac.compare_digest(
            candidate,
            row["password_hash"]
        ):
            return {
                "id": row["id"],
                "username": row["username"]
            }

        return None

    except sqlite3.Error:
        return None
