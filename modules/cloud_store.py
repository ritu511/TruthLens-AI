"""Optional Supabase persistence with a safe local SQLite fallback.

Supabase credentials are read only from Streamlit secrets or environment variables.
Never put a service-role key in source control.
"""
import os
from datetime import datetime, timezone

import requests
import streamlit as st

from modules.database import (
    save_analysis, list_analyses, get_analysis, delete_analysis,
    save_evidence, get_evidence,
)


def _setting(name, default=""):
    try:
        value = st.secrets.get(name, default)
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(name, default)


def supabase_configured():
    return bool(_setting("SUPABASE_URL") and _setting("SUPABASE_SERVICE_ROLE_KEY"))


def _request(method, path, *, params=None, payload=None):
    base = _setting("SUPABASE_URL").rstrip("/")
    key = _setting("SUPABASE_SERVICE_ROLE_KEY")
    if not base or not key:
        raise RuntimeError("Supabase is not configured.")
    response = requests.request(
        method,
        f"{base}/rest/v1/{path.lstrip('/')}",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        params=params,
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    if response.status_code == 204 or not response.content:
        return []
    return response.json()


def save_investigation(user_id, username, title, text, source_name="", claims=None):
    claims = claims if isinstance(claims, list) else []
    if supabase_configured():
        rows = _request("POST", "investigations", payload={
            "user_key": str(username).lower(),
            "title": str(title or "Untitled investigation")[:240],
            "source_name": str(source_name or "")[:240],
            "extracted_text": str(text or ""),
            "claims": claims,
        })
        return rows[0]["id"] if rows else None
    return save_analysis(user_id, title or "Untitled investigation", text)


def list_user_investigations(user_id, username):
    if supabase_configured():
        return _request(
            "GET", "investigations",
            params={
                "select": "id,title,source_name,created_at,extracted_text,claims",
                "user_key": f"eq.{str(username).lower()}",
                "order": "created_at.desc",
                "limit": "200",
            },
        )
    return list_analyses(user_id)


def get_user_investigation(user_id, username, investigation_id):
    if supabase_configured():
        rows = _request(
            "GET", "investigations",
            params={
                "select": "*",
                "id": f"eq.{investigation_id}",
                "user_key": f"eq.{str(username).lower()}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None
    try:
        return get_analysis(user_id, int(investigation_id))
    except (TypeError, ValueError):
        return None


def delete_user_investigation(user_id, username, investigation_id):
    if supabase_configured():
        _request(
            "DELETE", "investigations",
            params={
                "id": f"eq.{investigation_id}",
                "user_key": f"eq.{str(username).lower()}",
            },
        )
        return True
    try:
        return delete_analysis(user_id, int(investigation_id))
    except (TypeError, ValueError):
        return False


def save_investigation_evidence(user_id, username, investigation_id, item):
    if supabase_configured():
        _request("POST", "evidence", payload={
            "investigation_id": str(investigation_id),
            "user_key": str(username).lower(),
            "claim": str(item.get("claim", "")),
            "title": str(item.get("title", "Untitled source")),
            "url": str(item.get("url", "")),
            "excerpt": str(item.get("excerpt", "")),
            "relation": str(item.get("relation", "Unclear")),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return True
    try:
        save_evidence(
            int(investigation_id), item.get("claim", ""),
            item.get("title", "Untitled source"), item.get("url", ""),
            item.get("excerpt", ""), item.get("relation", "Unclear"),
            user_id,
        )
        return True
    except (TypeError, ValueError):
        return False


def list_investigation_evidence(user_id, username, investigation_id):
    if supabase_configured():
        return _request(
            "GET", "evidence",
            params={
                "select": "*",
                "investigation_id": f"eq.{investigation_id}",
                "user_key": f"eq.{str(username).lower()}",
                "order": "created_at.desc",
                "limit": "500",
            },
        )
    try:
        return get_evidence(int(investigation_id), user_id)
    except (TypeError, ValueError):
        return []


def analytics_for_user(user_id, username):
    records = list_user_investigations(user_id, username)
    total = len(records)
    claims = sum(len(row.get("claims") or []) for row in records)
    if supabase_configured():
        evidence_rows = _request(
            "GET", "evidence",
            params={
                "select": "id",
                "user_key": f"eq.{str(username).lower()}",
                "limit": "10000",
            },
        )
        evidence_count = len(evidence_rows)
    else:
        evidence_count = sum(
            len(get_evidence(row.get("id"), user_id))
            for row in records if row.get("id") is not None
        )
    return {
        "investigations": total,
        "claims": claims,
        "evidence": evidence_count,
        "recent": records[:10],
        "storage": "Supabase" if supabase_configured() else "Local SQLite",
    }


def update_investigation_claims(user_id, username, investigation_id, claims):
    claims = claims if isinstance(claims, list) else []
    if supabase_configured():
        _request(
            "PATCH", "investigations",
            params={
                "id": f"eq.{investigation_id}",
                "user_key": f"eq.{str(username).lower()}",
            },
            payload={"claims": claims},
        )
        return True
    # The legacy SQLite schema stores extracted text but has no claims column.
    # The app keeps claims in the active session; cloud storage persists them.
    return False
