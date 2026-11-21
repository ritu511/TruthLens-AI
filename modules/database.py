
from contextlib import contextmanager

from modules.auth import _connect


VALID_RELATIONS = {
    "Supports",
    "Contradicts",
    "Context only",
    "Unclear"
}


@contextmanager
def _db():
    """Safely manage database transactions and close connections."""

    conn = _connect()

    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def save_analysis(user_id, title, text):
    """Save an investigation for a specific user."""

    if not user_id:
        raise ValueError("Valid user ID is required.")

    if not isinstance(title, str) or not title.strip():
        raise ValueError("A valid investigation title is required.")

    if not isinstance(text, str) or not text.strip():
        raise ValueError("Investigation text is required.")

    with _db() as conn:
        cur = conn.execute(
            """
            INSERT INTO investigations(user_id, title, text)
            VALUES (?, ?, ?)
            """,
            (user_id, title.strip(), text)
        )

        return cur.lastrowid


def list_analyses(user_id):
    """List investigations belonging to one user."""

    if not user_id:
        return []

    with _db() as conn:
        rows = conn.execute(
            """
            SELECT id, title, text, created_at, claims_json
            FROM investigations
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,)
        ).fetchall()

    return [dict(row) for row in rows]


def get_analysis(user_id, analysis_id):
    """Get an investigation only if it belongs to the user."""

    if not user_id or not analysis_id:
        return None

    with _db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM investigations
            WHERE id = ? AND user_id = ?
            """,
            (analysis_id, user_id)
        ).fetchone()

    return dict(row) if row else None


def delete_analysis(user_id, analysis_id):
    """Delete an investigation only if it belongs to the user."""

    if not user_id or not analysis_id:
        return False

    with _db() as conn:

        owned = conn.execute(
            """
            SELECT id
            FROM investigations
            WHERE id = ? AND user_id = ?
            """,
            (analysis_id, user_id)
        ).fetchone()

        if not owned:
            return False

        conn.execute(
            "DELETE FROM evidence WHERE investigation_id = ?",
            (analysis_id,)
        )

        conn.execute(
            """
            DELETE FROM investigations
            WHERE id = ? AND user_id = ?
            """,
            (analysis_id, user_id)
        )

    return True


def save_evidence(
    analysis_id,
    claim,
    title,
    url,
    excerpt,
    relation,
    user_id
):
    """Save evidence after verifying investigation ownership."""

    if not user_id or not analysis_id:
        raise ValueError("Valid user and investigation IDs are required.")

    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("A valid claim is required.")

    if not isinstance(excerpt, str) or not excerpt.strip():
        raise ValueError("Evidence text is required.")

    if relation not in VALID_RELATIONS:
        raise ValueError("Invalid evidence relationship.")

    if not isinstance(title, str):
        title = "Untitled Source"

    if not isinstance(url, str):
        url = ""

    with _db() as conn:

        owned = conn.execute(
            """
            SELECT id
            FROM investigations
            WHERE id = ? AND user_id = ?
            """,
            (analysis_id, user_id)
        ).fetchone()

        if not owned:
            raise ValueError("Investigation not found or access denied.")

        cur = conn.execute(
            """
            INSERT INTO evidence(
                investigation_id,
                claim,
                title,
                url,
                excerpt,
                relation
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                claim.strip(),
                title.strip() or "Untitled Source",
                url.strip(),
                excerpt.strip(),
                relation
            )
        )

        return cur.lastrowid


def get_evidence(analysis_id, user_id, claim=None):
    """Retrieve evidence after verifying investigation ownership."""

    if not user_id or not analysis_id:
        return []

    with _db() as conn:

        owned = conn.execute(
            """
            SELECT id
            FROM investigations
            WHERE id = ? AND user_id = ?
            """,
            (analysis_id, user_id)
        ).fetchone()

        if not owned:
            return []

        query = """
            SELECT *
            FROM evidence
            WHERE investigation_id = ?
        """

        args = [analysis_id]

        if claim is not None:
            query += " AND claim = ?"
            args.append(claim)

        query += " ORDER BY id DESC"

        rows = conn.execute(query, args).fetchall()

    return [dict(row) for row in rows]


def delete_evidence(evidence_id, user_id):
    """Delete evidence only if it belongs to the specified user."""

    if not evidence_id or not user_id:
        return False

    with _db() as conn:

        cur = conn.execute(
            """
            DELETE FROM evidence
            WHERE id = ?
            AND investigation_id IN (
                SELECT id
                FROM investigations
                WHERE user_id = ?
            )
            """,
            (evidence_id, user_id)
        )

        return cur.rowcount > 0
