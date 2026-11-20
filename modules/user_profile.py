"""Persistent user profile and preference storage for TruthLens AI."""
from modules.auth import _connect


def get_user_profile(user_id):
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                bio TEXT NOT NULL DEFAULT '',
                theme TEXT NOT NULL DEFAULT 'Light',
                compact INTEGER NOT NULL DEFAULT 0,
                email_updates INTEGER NOT NULL DEFAULT 1,
                investigation_updates INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        row = conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO user_profiles(user_id) VALUES (?)", (user_id,))
            row = conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row)


def save_user_profile(user_id, display_name, email, bio, theme="Light",
                      compact=False, email_updates=True, investigation_updates=False):
    display_name = (display_name or "").strip()[:80]
    email = (email or "").strip()[:160]
    bio = (bio or "").strip()[:500]
    if email and ("@" not in email or "." not in email.rsplit("@", 1)[-1]):
        raise ValueError("Please enter a valid email address.")
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                bio TEXT NOT NULL DEFAULT '',
                theme TEXT NOT NULL DEFAULT 'Light',
                compact INTEGER NOT NULL DEFAULT 0,
                email_updates INTEGER NOT NULL DEFAULT 1,
                investigation_updates INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            INSERT INTO user_profiles(user_id, display_name, email, bio, theme, compact,
                                       email_updates, investigation_updates)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name=excluded.display_name, email=excluded.email, bio=excluded.bio,
                theme=excluded.theme, compact=excluded.compact,
                email_updates=excluded.email_updates,
                investigation_updates=excluded.investigation_updates
        """, (user_id, display_name, email, bio, theme, int(compact),
              int(email_updates), int(investigation_updates)))
