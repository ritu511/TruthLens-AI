"""Persistent user profile and preference storage for TruthLens AI."""
from modules.auth import _connect


def _ensure_profile_table(conn):
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
            first_name TEXT NOT NULL DEFAULT '',
            middle_name TEXT NOT NULL DEFAULT '',
            last_name TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            date_of_birth TEXT NOT NULL DEFAULT '',
            avatar BLOB,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(user_profiles)")}
    migrations = {
        "first_name": "TEXT NOT NULL DEFAULT ''",
        "middle_name": "TEXT NOT NULL DEFAULT ''",
        "last_name": "TEXT NOT NULL DEFAULT ''",
        "phone": "TEXT NOT NULL DEFAULT ''",
        "date_of_birth": "TEXT NOT NULL DEFAULT ''",
        "avatar": "BLOB",
    }
    for column, definition in migrations.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE user_profiles ADD COLUMN {column} {definition}")


def get_user_profile(user_id):
    with _connect() as conn:
        _ensure_profile_table(conn)
        row = conn.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            conn.execute("INSERT INTO user_profiles(user_id) VALUES (?)", (user_id,))
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
        return dict(row)


def save_user_profile(
    user_id, display_name, email, bio, theme="Light", compact=False,
    email_updates=True, investigation_updates=False, first_name="",
    middle_name="", last_name="", phone="", date_of_birth="", avatar=None
):
    legacy_display_name = (display_name or "").strip()[:180]
    first_name = (first_name or "").strip()[:60]
    middle_name = (middle_name or "").strip()[:60]
    last_name = (last_name or "").strip()[:60]
    display_name = " ".join(part for part in (first_name, middle_name, last_name) if part)
    if not display_name:
        display_name = legacy_display_name
    email = (email or "").strip()[:160]
    bio = (bio or "").strip()[:500]
    phone = (phone or "").strip()[:25]
    date_of_birth = (date_of_birth or "").strip()[:10]

    if email and ("@" not in email or "." not in email.rsplit("@", 1)[-1]):
        raise ValueError("Please enter a valid email address.")
    if phone and not phone.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "").isdigit():
        raise ValueError("Please enter a valid phone number.")
    if date_of_birth:
        from datetime import date
        parsed_dob = date.fromisoformat(date_of_birth)
        if parsed_dob > date.today():
            raise ValueError("Date of birth cannot be in the future.")

    with _connect() as conn:
        _ensure_profile_table(conn)
        conn.execute("""
            INSERT INTO user_profiles(
                user_id, display_name, email, bio, theme, compact,
                email_updates, investigation_updates, first_name, middle_name,
                last_name, phone, date_of_birth, avatar
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    COALESCE(?, (SELECT avatar FROM user_profiles WHERE user_id = ?)))
            ON CONFLICT(user_id) DO UPDATE SET
                display_name=excluded.display_name,
                email=excluded.email,
                bio=excluded.bio,
                theme=excluded.theme,
                compact=excluded.compact,
                email_updates=excluded.email_updates,
                investigation_updates=excluded.investigation_updates,
                first_name=excluded.first_name,
                middle_name=excluded.middle_name,
                last_name=excluded.last_name,
                phone=excluded.phone,
                date_of_birth=excluded.date_of_birth,
                avatar=COALESCE(excluded.avatar, user_profiles.avatar)
        """, (
            user_id, display_name, email, bio, theme, int(compact),
            int(email_updates), int(investigation_updates), first_name,
            middle_name, last_name, phone, date_of_birth, avatar, user_id
        ))
