import hashlib
import html
from copy import deepcopy
from datetime import date, datetime
from io import BytesIO

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageOps

from modules.auth import init_db, register_user, authenticate_user
from modules.user_profile import get_user_profile, save_user_profile, save_user_avatar, remove_user_avatar
from modules.file_reader import extract_file_content
from modules.claim_extractor import extract_claims
from modules.verification import generate_search_links
from modules.web_reader import extract_article
from modules.evidence_analyzer import analyze_evidence
from modules.evidence_similarity import analyze_claim_evidence_similarity
from modules.image_forensics import analyze_image
from modules.source_credibility import analyze_source
from modules.claim_assessment import assess_claim
from modules.report_generator import generate_pdf_report, generate_investigation_pdf
from modules.cloud_store import (
    save_investigation, list_user_investigations,
    save_investigation_evidence, update_investigation_claims,
    analytics_for_user, delete_user_investigation, get_user_investigation,
    update_investigation_content,
    list_investigation_evidence, supabase_configured,
)
from modules.ai_features import assess_claim_with_context, ai_claim_review, chat_answer


def _prepare_profile_avatar(uploaded_file):
    """Validate and normalize a profile image before it is stored."""
    if uploaded_file is None:
        raise ValueError("Please choose a profile picture first.")

    raw_bytes = uploaded_file.getvalue()
    if not raw_bytes:
        raise ValueError("The selected image is empty.")
    if len(raw_bytes) > 5 * 1024 * 1024:
        raise ValueError("Profile picture must be 5 MB or smaller.")

    try:
        with Image.open(BytesIO(raw_bytes)) as source:
            image_format = (source.format or "").upper()
            if image_format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("Please upload a JPG, PNG or WEBP image.")
            source.verify()

        # Normalize uploads to JPEG so phone orientation, transparency and
        # browser-specific image encodings do not break later previews.
        with Image.open(BytesIO(raw_bytes)) as source:
            image = ImageOps.exif_transpose(source)
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

            if image.width * image.height > 30_000_000:
                raise ValueError("Image resolution is too large. Please choose an image under 30 megapixels.")

            image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="JPEG", quality=90, optimize=True)
            return output.getvalue()
    except Image.DecompressionBombError as error:
        raise ValueError("This image is too large to process safely. Please choose a smaller image.") from error
    except (OSError, SyntaxError) as error:
        raise ValueError("The selected file is not a valid image. Please choose a JPG, PNG or WEBP file.") from error




# -----------------------------------------------------------------------------
# PAGE CONFIGURATION
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="TruthLens AI | Content Investigation",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# -----------------------------------------------------------------------------
# DATABASE / AUTHENTICATION
# -----------------------------------------------------------------------------
init_db()

if "authenticated_user" not in st.session_state:
    st.session_state.authenticated_user = None


# -----------------------------------------------------------------------------
# SESSION STATE
# -----------------------------------------------------------------------------
DEFAULTS = {
    "history": [],
    "extracted_text": "",
    "current_file_hash": "",
    "current_filename": "",
    "claims": [],
    "selected_claims": [],
    "evidence": [],
    "forensic_result": None,
    "current_investigation_id": None,
    "chat_messages": [],
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = deepcopy(value)


def reset_investigation(new_text="", filename="", content_hash=""):
    """Clear data belonging to the previous investigation."""
    st.session_state.extracted_text = new_text
    st.session_state.current_filename = filename
    st.session_state.current_file_hash = content_hash
    st.session_state.claims = []
    st.session_state.selected_claims = []
    st.session_state.evidence = []
    st.session_state.forensic_result = None
    st.session_state.current_investigation_id = None

    # Clear the multiselect's stored value before it is recreated.
    st.session_state.pop("dashboard_claim_selection", None)
    st.session_state.pop("dashboard_extracted_text_editor", None)



def persist_current_investigation(title=None, text=None):
    """Persist the active investigation without interrupting the workflow."""
    account = st.session_state.get("authenticated_user") or {}
    content = st.session_state.get("extracted_text", "") if text is None else text
    if not account.get("id") or not content:
        return None
    username = account.get("username", "user")
    display_title = title or st.session_state.get("current_filename") or "Untitled investigation"
    try:
        saved_id = save_investigation(
            account["id"], username, display_title, content,
            source_name=display_title,
            claims=st.session_state.get("claims", []),
        )
        st.session_state.current_investigation_id = saved_id
        return saved_id
    except Exception as error:
        st.warning("Cloud/local history could not be saved: " + str(error))
        return None


def persist_claims():
    account = st.session_state.get("authenticated_user") or {}
    investigation_id = st.session_state.get("current_investigation_id")
    if account.get("id") and investigation_id:
        try:
            update_investigation_claims(
                account["id"], account.get("username", "user"),
                investigation_id, st.session_state.get("claims", []),
            )
        except Exception as error:
            st.warning("Could not update saved claims: " + str(error))


def sign_out():
    """Clear user-specific workspace state before signing out."""
    for key in DEFAULTS:
        st.session_state.pop(key, None)
    st.session_state.pop("dashboard_claim_selection", None)
    st.session_state.pop("dashboard_extracted_text_editor", None)
    st.session_state.pop("active_workspace_page", None)
    st.session_state.pop("workspace_page", None)
    st.session_state.pop("pending_workspace_page", None)
    st.session_state.pop("profile_avatar_upload_version", None)
    st.session_state.authenticated_user = None


# -----------------------------------------------------------------------------
# LOGIN / REGISTRATION
if st.session_state.authenticated_user is None:
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    .stApp{background:#f8f7ff;font-family:Inter,sans-serif}
    [data-testid="stHeader"]{background:transparent}
    .block-container{max-width:1500px;padding:2rem 3rem 3rem}
    .auth-brand{display:flex;align-items:center;gap:14px;margin:18px 0 62px}
    .auth-mark{width:58px;height:58px;border:5px solid #7138f4;border-radius:50%;display:grid;place-items:center;color:#7138f4;font-weight:800;font-size:22px;box-shadow:inset 0 0 0 4px #eee7ff}
    .auth-brand-name{font-size:27px;font-weight:800;letter-spacing:-1.2px;color:#11152b}
    .auth-sub{font-size:13px;color:#667085;margin-top:4px}
    .auth-heading{font-size:42px;font-weight:800;letter-spacing:-2px;color:#11152b;line-height:1.1;margin:0 0 12px}
    .auth-heading span,.auth-right h2 span{color:#7138f4}
    .auth-copy{color:#667085;font-size:16px;line-height:1.6;margin-bottom:26px}
    .auth-right{background:radial-gradient(circle at 100% 0%,#e3d7ff 0,transparent 30%),linear-gradient(145deg,#f8f5ff,#f0eaff);border-radius:24px;padding:clamp(32px,5vw,76px);min-height:700px}
    .auth-right h2{font-size:clamp(38px,4vw,58px);line-height:1.08;letter-spacing:-2px;color:#11152b!important;font-weight:800;margin:25px 0 18px}
    .auth-right h2 span{color:#7138f4!important}
    .auth-right p{font-size:18px;color:#4f5872!important;line-height:1.65}
    .auth-visual{margin:38px auto 28px;max-width:560px;border:1px solid #d9cdfb;background:#fff;border-radius:22px;padding:26px;box-shadow:0 24px 70px rgba(92,57,180,.13)}
    .visual-top{font-weight:800;font-size:19px;color:#171b32!important;border-bottom:1px solid #ece7f7;padding-bottom:15px}
    .visual-row{display:flex;gap:16px;align-items:center;padding:20px 0 16px}
    .visual-thumb{width:92px;height:78px;flex:0 0 92px;border-radius:12px;background:linear-gradient(135deg,#d8c5ff,#8c56f5);display:grid;place-items:center;color:white;font-size:30px}
    .visual-lines{flex:1;min-width:0}.visual-lines strong{display:block;color:#20243a;font-size:14px;margin-bottom:8px}.visual-lines span{display:block;color:#65708a;font-size:12px;line-height:1.5}.visual-lines i{display:block;height:8px;border-radius:8px;background:#e5e0f2;margin:8px 0}
    .visual-meta{display:flex;flex-wrap:wrap;gap:8px;margin:4px 0 14px}.visual-tag{font-size:11px;font-weight:700;padding:6px 9px;border-radius:7px;background:#f1ebff;color:#6330d9}
    .verified{display:inline-block;padding:9px 13px;border-radius:9px;background:#dcfce9;color:#087b45!important;font-weight:750;font-size:13px}
    .auth-features{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:28px}
    .auth-feature strong{display:block;color:#171b32!important;margin:8px 0 5px;font-size:14px}
    .auth-feature small{color:#4f5872!important;line-height:1.5;font-size:12px}
    .auth-icon{width:42px;height:42px;border-radius:12px;background:#e8ddff;color:#7138f4;display:grid;place-items:center;font-weight:800;font-size:18px}
    /* Explicit contrast for Streamlit widgets: do not rely on the host theme. */
    div[data-testid="stRadio"] label,div[data-testid="stRadio"] label p,
    div[data-testid="stCheckbox"] label,div[data-testid="stCheckbox"] label p,
    div[data-testid="stWidgetLabel"] p{color:#171b32!important;opacity:1!important;font-weight:600!important}
    div[data-testid="stRadio"] [role="radiogroup"]{gap:22px}
    div[data-testid="stRadio"] input,div[data-testid="stCheckbox"] input{accent-color:#7138f4!important}
    .stTextInput label{font-weight:700!important;color:#171b32!important;opacity:1!important}
    .stTextInput input{border:1px solid #d7dbea!important;border-radius:11px!important;min-height:48px!important;background:#fff!important;color:#171b32!important;-webkit-text-fill-color:#171b32!important}
    .stTextInput input::placeholder{color:#737b91!important;-webkit-text-fill-color:#737b91!important;opacity:1!important}
    .stTextInput [data-baseweb="input"]{background:#fff!important;border-radius:11px!important}
    div[data-testid="stForm"]{border:1px solid #e2dcf0!important;border-radius:16px!important;background:rgba(255,255,255,.72)!important;padding:18px!important}
    div[data-testid="stFormSubmitButton"] button{background:linear-gradient(100deg,#7138f4,#6330e8)!important;color:#fff!important;border:0!important;border-radius:11px!important;min-height:52px!important;font-weight:750!important;box-shadow:0 8px 18px rgba(99,48,232,.18)!important}
    div[data-testid="stFormSubmitButton"] button:hover{background:linear-gradient(100deg,#6028e8,#5120d0)!important;color:#fff!important}
    div[data-testid="stFormSubmitButton"] button p{color:#fff!important}
    div[data-testid="stTabs"] button{font-weight:650!important}
    @media(max-width:900px){.block-container{padding:1rem!important}.auth-right{display:none}.auth-brand{margin:12px 0 38px}}
    </style>
    """, unsafe_allow_html=True)
    left, right = st.columns([0.9, 1.1], gap="large")
    with left:
        st.markdown('<div class="auth-brand"><div class="auth-mark">TL</div><div><div class="auth-brand-name">TruthLens <span style="color:#7138f4">AI</span></div><div class="auth-sub">Content Investigation Platform</div></div></div><div class="auth-heading">Welcome <span style="color:#7138f4">Back</span></div><div class="auth-copy">Sign in to investigate, verify, and track content with TruthLens AI.</div>', unsafe_allow_html=True)
        auth_mode = st.radio("Account", ["Sign in", "Create account"], horizontal=True, label_visibility="collapsed", key="auth_mode")
        if auth_mode == "Sign in":
            with st.form("truthlens_login_form"):
                login_username = st.text_input("Username", key="login_username", placeholder="Enter your username")
                login_password = st.text_input("Password", type="password", key="login_password", placeholder="Enter your password")
                st.checkbox("Remember me", value=True)
                login_submitted = st.form_submit_button("Sign In  →", type="primary", use_container_width=True)
            if login_submitted:
                account = authenticate_user(login_username, login_password)
                if account:
                    st.session_state.authenticated_user = account
                    st.rerun()
                else:
                    st.error("Username or password is incorrect.")
        else:
            with st.form("truthlens_register_form"):
                new_username = st.text_input("Choose a username", key="register_username")
                new_password = st.text_input("Create password", type="password", key="register_password")
                confirm_password = st.text_input("Confirm password", type="password", key="register_confirm")
                register_submitted = st.form_submit_button("Create Account", type="primary", use_container_width=True)
            if register_submitted:
                if new_password != confirm_password:
                    st.error("Passwords do not match.")
                else:
                    success, message = register_user(new_username, new_password)
                    if success:
                        st.success(message + " You can now sign in.")
                    else:
                        st.error(message)
    with right:
        st.markdown("""
        <div class="auth-right">
          <h2>Discover the <span>Truth</span><br>Behind Every Story.</h2>
          <p>AI-powered content investigation to inspect claims, analyze source credibility, and organize reliable evidence.</p>
          <div class="auth-visual">
            <div class="visual-top">News Analysis</div>
            <div class="visual-row">
              <div class="visual-thumb">▧</div>
              <div class="visual-lines">
                <strong>Sample news article</strong>
                <span>Review the headline, claim and supporting source details.</span>
                <i></i><i style="width:76%"></i>
              </div>
            </div>
            <div class="visual-meta"><span class="visual-tag">Claim detected</span><span class="visual-tag">Source check</span></div>
            <span class="verified">✓ Evidence review ready</span>
          </div>
          <div class="auth-features"><div class="auth-feature"><div class="auth-icon">AI</div><strong>AI Detection</strong><small>Inspect content and image indicators.</small></div><div class="auth-feature"><div class="auth-icon">✓</div><strong>Source Analysis</strong><small>Review evidence and source details.</small></div><div class="auth-feature"><div class="auth-icon">▥</div><strong>History</strong><small>Keep track of your investigations.</small></div></div>
        </div>
        """, unsafe_allow_html=True)
    st.stop()


# UI STYLING — VERCEL-INSPIRED PROFESSIONAL THEME
# -----------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    :root {
        --background: #fafafa;
        --surface: #ffffff;
        --foreground: #111111;
        --muted: #737373;
        --border: #e5e5e5;
        --soft: #f5f5f5;
        --accent: #111111;
    }
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background: var(--background); color: var(--foreground); }
    [data-testid="stHeader"] { background: rgba(250,250,250,.94); }
    [data-testid="stSidebar"] { background: #17142b !important; border-right: 1px solid #2d2750 !important; }
    [data-testid="stSidebar"] > div:first-child { background: #17142b !important; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] *,
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"],
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] *,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] label p { color: #f4f0ff !important; opacity: 1 !important; }
    [data-testid="stSidebar"] hr { border-color: #393255 !important; }
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] { gap: 7px !important; }
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radio"] {
        color: #f4f0ff !important; background: transparent !important;
        border-radius: 9px !important; padding: 8px 10px !important; min-height: 38px !important;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radio"]:hover { background: #292344 !important; }
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radio"][aria-checked="true"] {
        background: #39266d !important; color: #ffffff !important;
        box-shadow: inset 3px 0 0 #a78bfa !important; font-weight: 700 !important;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radio"] > div:first-child {
        border: 2px solid #b9a7f5 !important; background: #211b39 !important;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radio"][aria-checked="true"] > div:first-child {
        border-color: #c4b5fd !important; background: #8b5cf6 !important;
    }
    [data-testid="stSidebar"] .stButton > button {
        background: #292344 !important; color: #ffffff !important;
        border: 1px solid #59468b !important; border-radius: 10px !important;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background: #39266d !important; border-color: #a78bfa !important;
    }
    .block-container { max-width: 1420px; padding-top: 2rem; padding-bottom: 4rem; }
    h1, h2, h3, h4 { color: #111111 !important; letter-spacing: -.045em !important; font-weight: 650 !important; }
    h1 { font-size: clamp(2rem, 3.2vw, 2.7rem) !important; }
    h2 { font-size: 1.65rem !important; }
    h3 { font-size: 1.2rem !important; }
    p, label, .stMarkdown { color: #262626; }
    .hero {
        padding: 30px 0 26px 0;
        border-bottom: 1px solid var(--border);
        margin-bottom: 28px;
        background: transparent;
    }
    .hero-kicker { color: #737373; font-size: .72rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
    .hero-title { color: #111111; font-size: clamp(2.15rem, 4vw, 3.25rem); font-weight: 750; letter-spacing: -.065em; line-height: 1.04; margin: 12px 0; }
    .hero-copy { color: #666666; font-size: 1rem; max-width: 720px; line-height: 1.65; }
    .section-label { color: #737373; font-size: .7rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; margin: 4px 0 8px; }
    div[data-testid="stMetric"] { background: #ffffff; border: 1px solid var(--border); padding: 16px 18px; border-radius: 10px; box-shadow: 0 1px 2px rgba(0,0,0,.025); }
    div[data-testid="stMetricLabel"] { color: #737373; font-size: .8rem; }
    div[data-testid="stMetricValue"] { color: #111111; font-weight: 650; }
    div[data-testid="stMetricDelta"] { font-size: .75rem; }
    .stButton > button, .stDownloadButton > button, .stLinkButton > a {
        border-radius: 7px; font-weight: 600; min-height: 2.55rem;
        border: 1px solid #d4d4d4; background: #ffffff; color: #171717;
        transition: background .15s ease, border-color .15s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover { border-color: #a3a3a3; background: #f5f5f5; color: #111111; }
    .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] { background: #111111; border: 1px solid #111111; color: #ffffff; }
    .stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover { background: #333333; border-color: #333333; color: #ffffff; }
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"], .stMultiSelect div[data-baseweb="select"] {
        background: #ffffff; border-color: #d4d4d4; border-radius: 7px; color: #171717;
    }
    div[data-testid="stExpander"], div[data-testid="stForm"] { border: 1px solid var(--border); border-radius: 9px; background: #ffffff; }
    div[data-testid="stTabs"] button { color: #525252; font-weight: 600; }
    div[data-testid="stTabs"] button[aria-selected="true"] { color: #111111; }
    [data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 8px; }
    hr { border-color: var(--border); }
    .footer-note { color: #8a8a8a; font-size: .78rem; text-align: center; padding-top: 24px; }
    .nav-brand { font-size: 1.05rem; font-weight: 750; letter-spacing: -.04em; color: #111111; }
    .nav-subtitle { color: #737373; font-size: .75rem; margin-top: 2px; }

    /* HIGH-CONTRAST OVERRIDES: keep all Streamlit content readable */
    [data-testid="stAppViewContainer"],
    [data-testid="stAppViewContainer"] .main,
    [data-testid="stAppViewContainer"] section.main,
    [data-testid="stAppViewContainer"] [data-testid="stVerticalBlock"] {
        color: #171717 !important;
    }
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stMarkdownContainer"] span,
    [data-testid="stCaptionContainer"],
    [data-testid="stWidgetLabel"] p,
    [data-testid="stFileUploader"] label,
    [data-testid="stTextArea"] label,
    [data-testid="stTextInput"] label {
        color: #262626 !important;
        opacity: 1 !important;
    }
    .hero-kicker, .hero-copy, .hero-title, .section-label {
        opacity: 1 !important;
        visibility: visible !important;
    }
    .hero-title { color: #111111 !important; }
    .hero-copy { color: #525252 !important; }
    .stTextInput input,
    .stTextArea textarea,
    [data-baseweb="input"] input,
    [data-baseweb="textarea"] textarea {
        background: #ffffff !important;
        color: #171717 !important;
        -webkit-text-fill-color: #171717 !important;
        caret-color: #171717 !important;
        opacity: 1 !important;
    }
    .stTextInput input::placeholder,
    .stTextArea textarea::placeholder,
    [data-baseweb="input"] input::placeholder,
    [data-baseweb="textarea"] textarea::placeholder {
        color: #737373 !important;
        -webkit-text-fill-color: #737373 !important;
        opacity: 1 !important;
    }
    [data-testid="stAlert"] {
        background: #f5f5f5 !important;
        border: 1px solid #d4d4d4 !important;
        color: #262626 !important;
    }
    [data-testid="stAlert"] * {
        color: #262626 !important;
        opacity: 1 !important;
    }
    .stButton > button[kind="primary"] *,
    .stFormSubmitButton > button[kind="primary"] * {
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
    }
    .stButton > button:disabled,
    .stButton > button:disabled * {
        color: #737373 !important;
        -webkit-text-fill-color: #737373 !important;
        opacity: 1 !important;
    }
    @media (max-width: 768px) {
        .block-container { padding: 1.15rem .9rem 2.5rem .9rem !important; }
        .hero { padding: 18px 0 20px; }
        .hero-title { font-size: 2.05rem; }
        .hero-copy { font-size: .92rem; }
        .stHorizontalBlock { flex-wrap: wrap !important; gap: .65rem !important; }
        .stHorizontalBlock > div { flex: 1 1 100% !important; min-width: 100% !important; }
        div[data-testid="stMetric"] { padding: 12px; }
        .stButton > button, .stDownloadButton > button, .stLinkButton > a { width: 100%; }
        div[data-testid="stTabs"] button { font-size: .82rem; padding-left: .35rem; padding-right: .35rem; }
    }


    /* ------------------------------------------------------------------
       TRUTHLENS VISUAL POLISH — restrained indigo / teal / slate palette
       High-contrast semantic surfaces for every Streamlit message type.
       ------------------------------------------------------------------ */
    :root {
        --tl-bg: #f7f8fc;
        --tl-surface: #ffffff;
        --tl-ink: #172033;
        --tl-muted: #64748b;
        --tl-border: #e2e8f0;
        --tl-indigo: #4f46e5;
        --tl-indigo-soft: #eef2ff;
        --tl-teal: #0f766e;
        --tl-teal-soft: #ecfdf5;
        --tl-amber: #92400e;
        --tl-amber-soft: #fffbeb;
        --tl-red: #9f1239;
        --tl-red-soft: #fff1f2;
    }

    .stApp { background: var(--tl-bg) !important; color: var(--tl-ink) !important; }
    [data-testid="stAppViewContainer"] { background: var(--tl-bg) !important; }
    [data-testid="stHeader"] { background: rgba(247,248,252,.96) !important; }
    [data-testid="stSidebar"] { background: #ffffff !important; border-right: 1px solid var(--tl-border) !important; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] * { color: #26324a !important; }
    [data-testid="stSidebar"] [data-testid="stRadio"] label { color: #26324a !important; }

    /* Make every heading readable, including markdown headings inside cards. */
    h1, h2, h3, h4, h5,
    [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3,
    [data-testid="stMarkdownContainer"] h4,
    [data-testid="stMarkdownContainer"] h5 {
        color: #172033 !important;
        -webkit-text-fill-color: #172033 !important;
        opacity: 1 !important;
        visibility: visible !important;
    }
    [data-testid="stMarkdownContainer"] h3 { font-size: 1.12rem !important; font-weight: 700 !important; letter-spacing: -.025em !important; }
    [data-testid="stMarkdownContainer"] strong, [data-testid="stMarkdownContainer"] b { color: #172033 !important; }
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stCaptionContainer"],
    [data-testid="stWidgetLabel"] p { color: #334155 !important; opacity: 1 !important; }

    /* Consistent cards and metrics. */
    div[data-testid="stMetric"] {
        background: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 12px !important;
        padding: 17px 19px !important;
        box-shadow: 0 2px 7px rgba(15,23,42,.035) !important;
    }
    div[data-testid="stMetricLabel"], div[data-testid="stMetricLabel"] * { color: #64748b !important; }
    div[data-testid="stMetricValue"], div[data-testid="stMetricValue"] * { color: #172033 !important; -webkit-text-fill-color: #172033 !important; font-weight: 700 !important; }
    div[data-testid="stVerticalBlockBorderWrapper"] { border-color: #dbe3ef !important; border-radius: 12px !important; }
    div[data-testid="stExpander"] { background: #ffffff !important; border: 1px solid #dbe3ef !important; border-radius: 10px !important; }
    div[data-testid="stExpander"] summary,
    div[data-testid="stExpander"] summary span,
    div[data-testid="stExpander"] summary p { color: #26324a !important; }

    /* Semantic alerts: blue info, green success, amber warning, rose error. */
    [data-testid="stAlert"],
    div[data-testid="stAlert"] > div,
    div[data-testid="stAlert"] [data-testid="stMarkdownContainer"] {
        background: #eff6ff !important;
        border-color: #bfdbfe !important;
        color: #1e3a8a !important;
        -webkit-text-fill-color: #1e3a8a !important;
        opacity: 1 !important;
    }
    [data-testid="stAlert"] p,
    [data-testid="stAlert"] span,
    [data-testid="stAlert"] div,
    [data-testid="stAlert"] li { color: #1e3a8a !important; -webkit-text-fill-color: #1e3a8a !important; opacity: 1 !important; }
    [data-testid="stAlert"] svg { color: #2563eb !important; fill: #2563eb !important; }
    [data-testid="stAlert"][kind="success"], [data-testid="stAlert"]:has(svg[ data-testid="stSuccessIcon"]) { background: #ecfdf5 !important; }
    [data-testid="stAlert"]:has(svg[aria-label*="Success"]) { background: #ecfdf5 !important; border-color: #a7f3d0 !important; }
    [data-testid="stAlert"]:has(svg[aria-label*="Warning"]) { background: #fffbeb !important; border-color: #fde68a !important; }
    [data-testid="stAlert"]:has(svg[aria-label*="Error"]) { background: #fff1f2 !important; border-color: #fecdd3 !important; }

    /* Form fields and tabs. */
    .stTextInput input, .stTextArea textarea,
    [data-baseweb="input"] input, [data-baseweb="textarea"] textarea {
        background: #ffffff !important;
        color: #172033 !important;
        -webkit-text-fill-color: #172033 !important;
        border-color: #cbd5e1 !important;
        caret-color: #172033 !important;
        opacity: 1 !important;
    }
    .stTextInput input::placeholder, .stTextArea textarea::placeholder,
    [data-baseweb="input"] input::placeholder, [data-baseweb="textarea"] textarea::placeholder {
        color: #94a3b8 !important; -webkit-text-fill-color: #94a3b8 !important; opacity: 1 !important;
    }
    div[data-testid="stTabs"] button { color: #64748b !important; }
    div[data-testid="stTabs"] button[aria-selected="true"] { color: var(--tl-indigo) !important; border-bottom-color: var(--tl-indigo) !important; }

    /* Buttons: indigo primary, quiet neutral secondary. */
    .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
        background: #4f46e5 !important; border: 1px solid #4f46e5 !important; color: #ffffff !important;
        border-radius: 8px !important; font-weight: 650 !important;
    }
    .stButton > button[kind="primary"] *, .stFormSubmitButton > button[kind="primary"] * { color: #ffffff !important; -webkit-text-fill-color: #ffffff !important; }
    .stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover { background: #4338ca !important; border-color: #4338ca !important; }
    .stButton > button:not([kind="primary"]), .stDownloadButton > button, .stLinkButton > a {
        background: #ffffff !important; color: #26324a !important; border: 1px solid #cbd5e1 !important; border-radius: 8px !important;
    }
    .stButton > button:not([kind="primary"]):hover, .stDownloadButton > button:hover, .stLinkButton > a:hover { background: #f1f5f9 !important; border-color: #94a3b8 !important; }

    .hero { border-bottom-color: #dbe3ef !important; }
    .hero-kicker, .section-label { color: #4f46e5 !important; }
    .hero-title { color: #172033 !important; -webkit-text-fill-color: #172033 !important; }
    .hero-copy { color: #64748b !important; }
    .footer-note { color: #94a3b8 !important; }
    [data-testid="stDataFrame"] { border: 1px solid #dbe3ef !important; border-radius: 10px !important; }
    hr { border-color: #e2e8f0 !important; }

    
    /* AQUA BLUE WORKSPACE THEME — authenticated app stylesheet */
    :root{color-scheme:light;--background:#eaf8fc;--surface:#fff;--foreground:#102b3a;--muted:#557181;--border:#ccebf3;--soft:#f3fbfd;--accent:#007f91}
    html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],[data-testid="stMainBlockContainer"],[data-testid="stAppViewContainer"] .main,section.main{background:#eaf8fc!important;color:#102b3a!important}
    [data-testid="stHeader"]{background:#eaf8fc!important}
    [data-testid="stSidebar"],[data-testid="stSidebar"]>div,[data-testid="stSidebar"]>div:first-child,[data-testid="stSidebar"] [data-testid="stSidebarContent"]{background:#006477!important;border-right:1px solid #008da3!important}
    [data-testid="stSidebar"] *{color:#effcff!important;opacity:1!important}
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:#b8edf4!important}
    [data-testid="stSidebar"] hr{border-color:#27899a!important}
    [data-testid="stSidebar"] [role="radiogroup"]{gap:7px!important}
    [data-testid="stSidebar"] [role="radio"]{color:#effcff!important;background:transparent!important;border-radius:9px!important}
    [data-testid="stSidebar"] [role="radio"]:hover{background:#087f91!important}
    [data-testid="stSidebar"] [role="radio"][aria-checked="true"]{background:#00aabd!important;color:#fff!important;box-shadow:inset 3px 0 0 #b8f7fb!important;font-weight:700!important}
    [data-testid="stSidebar"] [role="radio"]>div:first-child{border:2px solid #8bdce8!important;background:#064858!important}
    [data-testid="stSidebar"] [role="radio"][aria-checked="true"]>div:first-child{border-color:#b8f7fb!important;background:#00bfd2!important}
    [data-testid="stSidebar"] button{background:#008da3!important;color:#fff!important;border:1px solid #4bd5e2!important}
    h1,h2,h3,h4,h5,[data-testid="stMarkdownContainer"] h1,[data-testid="stMarkdownContainer"] h2,[data-testid="stMarkdownContainer"] h3{color:#102b3a!important;-webkit-text-fill-color:#102b3a!important}
    p,label,.stMarkdown,[data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] li,[data-testid="stWidgetLabel"] p,[data-testid="stCaptionContainer"]{color:#294b5a!important;opacity:1!important}
    .hero-kicker,.section-label{color:#008da3!important}.hero-title{color:#102b3a!important;-webkit-text-fill-color:#102b3a!important}.hero-copy{color:#557181!important}
    div[data-testid="stMetric"],div[data-testid="stVerticalBlockBorderWrapper"],div[data-testid="stForm"],div[data-testid="stExpander"]{background:#fff!important;border:1px solid #ccebf3!important;border-radius:12px!important;box-shadow:0 3px 12px rgba(0,103,125,.055)!important}
    div[data-testid="stMetricLabel"],div[data-testid="stMetricLabel"] *,div[data-testid="stMetricValue"],div[data-testid="stMetricValue"] *{color:#102b3a!important;-webkit-text-fill-color:#102b3a!important}
    div[data-testid="stMetricValue"],div[data-testid="stMetricValue"] *{font-size:1.35rem!important;line-height:1.2!important}
    .stTextInput input,.stTextArea textarea,.stNumberInput input,[data-baseweb="input"] input,[data-baseweb="textarea"] textarea,[data-baseweb="select"]>div{background:#fbfeff!important;color:#102b3a!important;-webkit-text-fill-color:#102b3a!important;border:1px solid #a9d7e3!important;caret-color:#102b3a!important;border-radius:8px!important}
    .stTextInput input::placeholder,.stTextArea textarea::placeholder,[data-baseweb="input"] input::placeholder,[data-baseweb="textarea"] textarea::placeholder{color:#7795a2!important;-webkit-text-fill-color:#7795a2!important;opacity:1!important}
    [data-testid="stDateInput"],[data-testid="stDateInput"]>div,[data-testid="stDateInput"] [data-baseweb="input"],[data-testid="stDateInput"] input,[data-testid="stDateInput"] button{background:#fbfeff!important;color:#102b3a!important;-webkit-text-fill-color:#102b3a!important;border-color:#a9d7e3!important}
    [data-testid="stDateInput"] svg{color:#007f91!important;fill:#007f91!important}
    .stButton>button,.stDownloadButton>button,.stLinkButton>a{background:#fff!important;color:#124252!important;border:1px solid #b8dce5!important;border-radius:8px!important}
    .stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"],div[data-testid="stFormSubmitButton"] button{background:#007f91!important;color:#fff!important;-webkit-text-fill-color:#fff!important;border:1px solid #007f91!important;border-radius:9px!important;font-weight:700!important}
    .stButton>button[kind="primary"] *, .stFormSubmitButton>button[kind="primary"] *,div[data-testid="stFormSubmitButton"] button *{color:#fff!important;-webkit-text-fill-color:#fff!important}
    .stButton>button[kind="primary"]:hover,.stFormSubmitButton>button[kind="primary"]:hover{background:#006b7b!important}
    [data-testid="stAlert"]{background:#e0f7fb!important;border:1px solid #a9e4ed!important}
    [data-testid="stAlert"] *{color:#075568!important;-webkit-text-fill-color:#075568!important}
    [data-testid="stFileUploader"] section{background:#f7fdff!important;border:1px dashed #82cbd9!important;border-radius:10px!important}
    [data-testid="stFileUploader"] *{color:#294b5a!important}
    [data-testid="stImage"] img{border-radius:50%!important;object-fit:cover!important;border:3px solid #bcecf3!important}
    .profile-avatar-fallback{background:linear-gradient(145deg,#b9f3f8,#65d9e6)!important;border:2px solid #48c6d5!important;color:#00566a!important}
    .profile-display-name{color:#102b3a!important}.profile-username{color:#557181!important}.profile-status{color:#00845a!important}
    hr{border-color:#ccebf3!important}
    [data-testid="stSidebarCollapsedControl"] button,button[aria-label="Open sidebar"],button[title="Open sidebar"]{width:42px!important;height:42px!important;min-width:42px!important;border-radius:50%!important;background:#00aabd!important;border:2px solid #b8edf4!important;box-shadow:0 3px 12px rgba(0,103,125,.22)!important;display:flex!important;align-items:center!important;justify-content:center!important;padding:0!important;overflow:hidden!important}
    [data-testid="stSidebarCollapsedControl"] button svg,button[aria-label="Open sidebar"] svg,button[title="Open sidebar"] svg{display:block!important;width:21px!important;height:21px!important;color:#fff!important;stroke:#fff!important;opacity:1!important}
    [data-testid="stSidebarCollapsedControl"] button:hover,button[aria-label="Open sidebar"]:hover,button[title="Open sidebar"]:hover{background:#007f91!important;transform:translateY(-1px)}

    .profile-display-name{font-size:1.15rem!important;font-weight:700!important;color:#102b3a!important}
    .profile-username{font-size:.9rem!important;color:#557181!important}
    .profile-status{font-size:.85rem!important;color:#00845a!important;font-weight:600!important}
</style>
    """,
    unsafe_allow_html=True,
)


active_theme = get_user_profile(st.session_state.authenticated_user["id"]).get("theme", "Light")
if active_theme == "Dark":
    st.markdown("""
    <style>
    :root{color-scheme:dark}
    html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],[data-testid="stMainBlockContainer"],[data-testid="stAppViewContainer"] .main,section.main{background:#101820!important;color:#edf4f7!important}
    [data-testid="stHeader"]{background:#101820!important}
    [data-testid="stSidebar"],[data-testid="stSidebar"]>div,[data-testid="stSidebar"]>div:first-child,[data-testid="stSidebar"] [data-testid="stSidebarContent"]{background:#07131b!important;border-color:#203642!important}
    [data-testid="stSidebar"] *{color:#e6f1f5!important}
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:#9db5c0!important}
    [data-testid="stSidebar"] [role="radio"]{background:transparent!important;color:#e6f1f5!important}
    [data-testid="stSidebar"] [role="radio"]:hover{background:#18313d!important}
    [data-testid="stSidebar"] [role="radio"][aria-checked="true"]{background:#07576a!important;color:#fff!important;box-shadow:inset 3px 0 0 #43d5e5!important}
    [data-testid="stSidebar"] [role="radio"] *,
    [data-testid="stSidebar"] [role="radio"] p,
    [data-testid="stSidebar"] [role="radio"] span,
    [data-testid="stSidebar"] [role="radio"] label{color:#e6f1f5!important;-webkit-text-fill-color:#e6f1f5!important;opacity:1!important}
    [data-testid="stSidebar"] [role="radio"][aria-checked="true"] *,
    [data-testid="stSidebar"] [role="radio"][aria-checked="true"] p,
    [data-testid="stSidebar"] [role="radio"][aria-checked="true"] span{color:#fff!important;-webkit-text-fill-color:#fff!important}
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] *,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] *,
    [data-testid="stSidebar"] p{color:#dce9ee!important;-webkit-text-fill-color:#dce9ee!important}
    [data-testid="stSidebar"] button{background:#07576a!important;color:#fff!important;border-color:#25889a!important}
    h1,h2,h3,h4,h5,[data-testid="stMarkdownContainer"] h1,[data-testid="stMarkdownContainer"] h2,[data-testid="stMarkdownContainer"] h3{color:#f2f7fa!important;-webkit-text-fill-color:#f2f7fa!important}
    p,label,.stMarkdown,[data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] li,[data-testid="stWidgetLabel"] p,[data-testid="stCaptionContainer"]{color:#c2d2d9!important}
    .hero-title,.profile-display-name{color:#f2f7fa!important;-webkit-text-fill-color:#f2f7fa!important}
    .hero-copy,.profile-username{color:#a8bdc7!important}
    .hero-kicker,.section-label{color:#54d4e3!important}
    div[data-testid="stMetric"],div[data-testid="stVerticalBlockBorderWrapper"],div[data-testid="stForm"],div[data-testid="stExpander"]{background:#172630!important;border:1px solid #2c4653!important;box-shadow:0 3px 12px rgba(0,0,0,.18)!important}
    [data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] *,
    [data-testid="stMain"] [data-testid="stMarkdownContainer"] *,
    [data-testid="stMain"] .stMarkdown strong,
    [data-testid="stMain"] .stMarkdown b{color:#dce8ed!important;-webkit-text-fill-color:#dce8ed!important}
    [data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] h1,
    [data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] h2,
    [data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] h3,
    [data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] h4{color:#f4f8fa!important;-webkit-text-fill-color:#f4f8fa!important}
    [data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]{background:#1b2b35!important;border-color:#344b57!important}
    div[data-testid="stMetricLabel"],div[data-testid="stMetricLabel"] *,div[data-testid="stMetricValue"],div[data-testid="stMetricValue"] *{color:#f0f6f8!important;-webkit-text-fill-color:#f0f6f8!important}
    .stTextInput input,.stTextArea textarea,.stNumberInput input,[data-baseweb="input"] input,[data-baseweb="textarea"] textarea,[data-baseweb="select"]>div,[data-testid="stDateInput"] input{background:#0d1b24!important;color:#f0f6f8!important;-webkit-text-fill-color:#f0f6f8!important;border:1px solid #385563!important;caret-color:#fff!important}
    [data-baseweb="select"]>div,
    [data-baseweb="select"] [role="combobox"],
    [data-baseweb="select"] [data-testid="stSelectboxVirtualDropdown"],
    [data-baseweb="popover"] [role="listbox"],
    [data-baseweb="popover"] [role="option"]{background:#1b303b!important;color:#edf5f8!important;-webkit-text-fill-color:#edf5f8!important}
    [data-baseweb="select"] svg{fill:#dce8ed!important;color:#dce8ed!important}
    [data-baseweb="popover"],[data-baseweb="menu"],[role="listbox"]{background:#1b303b!important;color:#edf5f8!important}
    [data-baseweb="popover"] *,[data-baseweb="menu"] *,[role="listbox"] *,[role="option"]{background-color:#1b303b!important;color:#edf5f8!important;-webkit-text-fill-color:#edf5f8!important}
    [role="option"]:hover,[aria-selected="true"]{background:#28505d!important;color:#fff!important;-webkit-text-fill-color:#fff!important}
    [data-testid="stSelectbox"] [data-baseweb="select"]>div{background:#1b303b!important;color:#edf5f8!important}
    .stTextInput input::placeholder,.stTextArea textarea::placeholder,[data-baseweb="input"] input::placeholder,[data-baseweb="textarea"] textarea::placeholder{color:#8da6b1!important;-webkit-text-fill-color:#8da6b1!important}
    [data-testid="stDateInput"],[data-testid="stDateInput"]>div,[data-testid="stDateInput"] [data-baseweb="input"],[data-testid="stDateInput"] button{background:#0d1b24!important;color:#f0f6f8!important;border-color:#385563!important}
    .stButton>button,.stDownloadButton>button,.stLinkButton>a{background:#20343f!important;color:#edf5f8!important;border:1px solid #405b68!important}
    .stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"],div[data-testid="stFormSubmitButton"] button{background:#00869a!important;color:#fff!important;border-color:#16a6b8!important}
    .stButton>button[kind="primary"] *, .stFormSubmitButton>button[kind="primary"] *,div[data-testid="stFormSubmitButton"] button *{color:#fff!important;-webkit-text-fill-color:#fff!important}
    [data-testid="stAlert"],
    [data-testid="stAlert"]>div,
    [data-testid="stAlert"] [data-testid="stMarkdownContainer"]{background:#1b303b!important;border:1px solid #345563!important;border-radius:10px!important;box-shadow:none!important}
    [data-testid="stAlert"] *,
    [data-testid="stAlert"] p,
    [data-testid="stAlert"] svg{color:#dcecf1!important;-webkit-text-fill-color:#dcecf1!important;fill:#dcecf1!important}
    [data-testid="stAlert"]{background:#1a2a34!important;background-color:#1a2a34!important;border:1px solid #344c58!important;border-radius:10px!important;box-shadow:none!important}
    [data-testid="stAlert"] *{background-color:transparent!important;color:#e0ebef!important;-webkit-text-fill-color:#e0ebef!important;opacity:1!important}
    [data-testid="stAlert"] svg{fill:#9bb9c4!important;color:#9bb9c4!important}
    [data-testid="stAlert"] a{color:#70dce8!important;-webkit-text-fill-color:#70dce8!important}
    [data-testid="stFileUploader"] section{background:#10232d!important;border:1px dashed #416a79!important}
    [data-testid="stFileUploader"] *{color:#d5e5ea!important}
    [data-testid="stImage"] img{border-color:#48c8d8!important}
    .profile-avatar-fallback{background:#16404c!important;border-color:#48c8d8!important;color:#e8fbff!important}
    .profile-status{color:#54dca0!important}
    hr{border-color:#2b4652!important}
    [data-testid="stSidebarCollapsedControl"] button,button[aria-label="Open sidebar"],button[title="Open sidebar"]{background:#08778a!important;border-color:#70dce7!important}
    /* Dark-mode info notices: override Streamlit's default pale-blue alert surface. */
    [data-testid="stMain"] [data-testid="stAlert"],
    [data-testid="stMain"] [data-testid="stAlert"]>div,
    [data-testid="stMain"] [data-testid="stAlert"] [data-testid="stMarkdownContainer"],
    [data-testid="stMain"] [role="alert"],
    [data-testid="stMain"] [role="alert"]>div{
        background:#1b303b!important;
        background-color:#1b303b!important;
        border:1px solid #345563!important;
        border-radius:10px!important;
        color:#e6f0f4!important;
        -webkit-text-fill-color:#e6f0f4!important;
        box-shadow:none!important;
        opacity:1!important;
    }
    [data-testid="stMain"] [data-testid="stAlert"] *,
    [data-testid="stMain"] [role="alert"] *,
    [data-testid="stMain"] [data-testid="stAlert"] p,
    [data-testid="stMain"] [role="alert"] p{
        background:transparent!important;
        background-color:transparent!important;
        color:#e6f0f4!important;
        -webkit-text-fill-color:#e6f0f4!important;
        opacity:1!important;
    }
    [data-testid="stMain"] [data-testid="stAlert"] svg,
    [data-testid="stMain"] [role="alert"] svg{
        color:#79cbd8!important;
        fill:#79cbd8!important;
    }
    /* Sign-out is a secondary action, but must remain readable in dark mode. */
    [data-testid="stSidebar"] div[data-testid="stButton"]>button,
    [data-testid="stSidebar"] .stButton>button,
    [data-testid="stSidebar"] button[kind="secondary"]{
        background:#17323e!important;
        background-color:#17323e!important;
        color:#f1f7fa!important;
        -webkit-text-fill-color:#f1f7fa!important;
        border:1px solid #3c6878!important;
        opacity:1!important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"]>button *,
    [data-testid="stSidebar"] .stButton>button *,
    [data-testid="stSidebar"] button[kind="secondary"] *{
        color:#f1f7fa!important;
        -webkit-text-fill-color:#f1f7fa!important;
        opacity:1!important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"]>button:hover{
        background:#214653!important;
        border-color:#56bdcc!important;
    }
    </style>
    """, unsafe_allow_html=True)


st.markdown("""<style>
    /* AttendEase-inspired sidebar structure; keep TruthLens aqua-blue palette */
    .tl-sidebar-brand{display:flex;align-items:center;gap:11px;padding:12px 7px 25px}
    .tl-sidebar-mark{width:42px;height:42px;flex:0 0 42px;display:grid;place-items:center;border-radius:12px;background:#00aabd;color:#fff!important;font-size:18px;font-weight:800}
    .tl-sidebar-name{font-size:1.05rem;font-weight:800;letter-spacing:-.035em;color:#effcff!important}
    .tl-sidebar-tag{font-size:.68rem;color:#b8edf4!important;margin-top:3px}
    .tl-sidebar-section{font-size:.65rem;font-weight:800;letter-spacing:.14em;color:#a8e5ed!important;margin:12px 0 12px;padding:0 10px}
    .tl-sidebar-profile{border-top:1px solid #27899a;margin-top:24px;padding:17px 6px 4px;display:flex;align-items:center;gap:10px}
    .tl-sidebar-avatar{width:36px;height:36px;flex:0 0 36px;border-radius:50%;display:grid;place-items:center;background:#00aabd;color:#fff!important;font-size:14px;font-weight:800}
    .tl-sidebar-user{font-size:.82rem;font-weight:750;color:#effcff!important;line-height:1.3;overflow-wrap:anywhere}
    .tl-sidebar-role{font-size:.68rem;color:#b8edf4!important;margin-top:3px}
    [data-testid="stSidebar"] [data-testid="stButton"] button[key="sidebar_profile_button"],
    [data-testid="stSidebar"] div[data-testid="stButton"]:has(button[kind="secondary"]) button{
        background:rgba(0,40,52,.18)!important;border:1px solid #27899a!important;
        color:#effcff!important;text-align:left!important;justify-content:flex-start!important;
        min-height:38px!important;padding:5px 10px!important;font-weight:750!important;
    }
    [data-testid="stSidebar"] [data-testid="stButton"] button[key="sidebar_profile_button"] *{color:#effcff!important}
    /* Sidebar navigation uses real buttons, not radio controls. */
    [data-testid="stSidebar"] [class*="st-key-nav-item-"]{margin:0 0 6px!important}
    [data-testid="stSidebar"] [class*="st-key-nav-item-"] [data-testid="stButton"]{width:100%!important}
    [data-testid="stSidebar"] [class*="st-key-nav-item-"] [data-testid="stButton"]>button{
        width:100%!important;min-height:47px!important;
        display:flex!important;align-items:center!important;justify-content:flex-start!important;
        padding:0 14px!important;border-radius:12px!important;
        border:1px solid rgba(126,211,222,.14)!important;
        background:rgba(0,42,54,.20)!important;
        color:#e7fbff!important;-webkit-text-fill-color:#e7fbff!important;
        font-size:.91rem!important;font-weight:650!important;text-align:left!important;
        box-shadow:none!important;transition:background .18s ease,border-color .18s ease,transform .18s ease!important;
    }
    [data-testid="stSidebar"] [class*="st-key-nav-item-"] [data-testid="stButton"]>button p,
    [data-testid="stSidebar"] [class*="st-key-nav-item-"] [data-testid="stButton"]>button span{
        color:inherit!important;-webkit-text-fill:inherit!important;font-weight:inherit!important;
    }
    [data-testid="stSidebar"] [class*="st-key-nav-item-"] [data-testid="stButton"]>button:hover{
        background:#087f91!important;border-color:#38b7c5!important;
        color:#fff!important;-webkit-text-fill:#fff!important;transform:translateX(2px)!important;
    }
    [data-testid="stSidebar"] [class*="st-key-nav-item-"] [data-testid="stButton"]>button[kind="primary"]{
        background:linear-gradient(105deg,#00aabd 0%,#078da2 100%)!important;
        border-color:#72e1e8!important;color:#fff!important;-webkit-text-fill:#fff!important;
        font-weight:750!important;box-shadow:0 5px 14px rgba(0,30,44,.18),inset 3px 0 0 #b9f7fb!important;
    }
    [data-testid="stSidebar"] [class*="st-key-nav-item-"] [data-testid="stButton"]>button:focus-visible{
        outline:2px solid #b8f7fb!important;outline-offset:2px!important;
    }
    @media(max-width:700px){
        [data-testid="stSidebar"] [class*="st-key-nav-item-"] [data-testid="stButton"]>button{
            min-height:44px!important;font-size:.88rem!important;
        }
    }
</style>""", unsafe_allow_html=True)

# SIDEBAR NAVIGATION
# -----------------------------------------------------------------------------
def _navigate_to_workspace_page(page_name):
    """Change the active workspace page from a sidebar navigation button."""
    st.session_state["active_workspace_page"] = page_name


# Apply navigation requests before the sidebar buttons are created.
# Persisting the destination keeps the current page stable across Streamlit reruns.
pending_page = st.session_state.pop("pending_workspace_page", None)
if pending_page:
    st.session_state["active_workspace_page"] = pending_page

if "active_workspace_page" not in st.session_state:
    st.session_state["active_workspace_page"] = "Overview"

page_icons = {
    "Overview": "⌂  Overview",
    "Investigate": "⌕  Investigate",
    "Claim Verification": "✓  Claim Verification",
    "Source Checker": "◎  Source Checker",
    "Evidence Review": "▤  Evidence Review",
    "Reports": "▧  Reports",
    "History": "◷  History",
    "AI Assistant": "✦  AI Assistant",
    "Analytics": "▥  Analytics",
    "Settings": "⚙  Settings",
    "About": "ⓘ  About",
}
with st.sidebar:
    st.markdown(
        '<div class="tl-sidebar-brand"><div class="tl-sidebar-mark">TL</div>'
        '<div><div class="tl-sidebar-name">TruthLens AI</div>'
        '<div class="tl-sidebar-tag">Content investigation workspace</div></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="tl-sidebar-section">MAIN MENU</div>', unsafe_allow_html=True)
    for menu_item, menu_label in page_icons.items():
        menu_slug = menu_item.lower().replace(" ", "-")
        with st.container(key=f"nav-item-{menu_slug}"):
            st.button(
                menu_label,
                key=f"nav-button-{menu_slug}",
                type=(
                    "primary"
                    if st.session_state.get("active_workspace_page", "Overview") == menu_item
                    else "secondary"
                ),
                use_container_width=True,
                on_click=_navigate_to_workspace_page,
                args=(menu_item,),
            )
    page = st.session_state.get("active_workspace_page", "Overview")
    username = st.session_state.authenticated_user.get("username", "User")
    initials = html.escape((username[:1] or "U").upper())
    st.markdown(
        '<div class="tl-sidebar-profile"><div class="tl-sidebar-avatar">' + initials + '</div>',
        unsafe_allow_html=True,
    )
    if st.button(f"{username}  ·  Profile", key="sidebar_profile_button", use_container_width=True):
        st.session_state["pending_workspace_page"] = "Profile"
        st.rerun()
    st.markdown(
        '<div class="tl-sidebar-role" style="padding-left:52px;margin-top:-9px">TruthLens AI User</div>',
        unsafe_allow_html=True,
    )
    if st.button("↪  Sign out", use_container_width=True):
        sign_out()
        st.rerun()


# -----------------------------------------------------------------------------
# EVIDENCE WORKSPACE
# -----------------------------------------------------------------------------
def render_evidence_for_claim(claim, index):
    """Show search links and collect manually reviewed evidence."""
    with st.expander(
        f"Evidence workspace · Claim {index}", expanded=(index == 1)
    ):
        st.markdown("**Selected claim**")
        st.write(claim)

        links = generate_search_links(claim)
        if links:
            columns = st.columns(4)
            labels = [
                "Google Search",
                "Google News",
                "Fact Check Search",
                "Official Sources",
            ]
            for column, label in zip(columns, labels):
                column.link_button(
                    label, links[label], use_container_width=True
                )

        st.markdown("#### Add evidence manually")
        with st.form(key=f"manual_evidence_{index}"):
            title = st.text_input("Source / article title")
            source_url = st.text_input(
                "Source URL", placeholder="https://..."
            )
            excerpt = st.text_area(
                "Relevant paragraph or evidence", height=110
            )
            relation = st.selectbox(
                "Relationship to claim",
                ["Supports", "Contradicts", "Context only", "Unclear"],
            )
            submitted = st.form_submit_button(
                "Save evidence", use_container_width=True
            )

        if submitted:
            if not source_url.strip() or not excerpt.strip():
                st.error("Source URL and evidence paragraph are required.")
            else:
                evidence_item = {
                    "claim": claim,
                    "title": title.strip() or "Untitled source",
                    "url": source_url.strip(),
                    "excerpt": excerpt.strip(),
                    "relation": relation,
                    "date": datetime.now().strftime("%d-%m-%Y %I:%M %p"),
                }
                st.session_state.evidence.append(evidence_item)
                account = st.session_state.get("authenticated_user") or {}
                investigation_id = st.session_state.get("current_investigation_id")
                if account.get("id") and investigation_id:
                    try:
                        save_investigation_evidence(
                            account["id"], account.get("username", "user"),
                            investigation_id, evidence_item,
                        )
                    except Exception as error:
                        st.warning("Evidence saved in this session, but persistence failed: " + str(error))
                st.success("Evidence saved.")
                st.rerun()

        saved = [
            item for item in st.session_state.evidence
            if item.get("claim") == claim
        ]
        st.markdown(f"**Saved evidence: {len(saved)}**")

        for item in saved:
            with st.container(border=True):
                st.markdown(
                    f"**{item.get('title') or 'Untitled source'}** · "
                    f"{item.get('relation', 'Unclear')}"
                )
                st.write(item.get("excerpt", ""))

                source_url = item.get("url", "")
                if source_url:
                    source_result = analyze_source(source_url)

                    if source_result.get("valid_url"):
                        first, second = st.columns(2)
                        first.metric(
                            "Domain category", source_result.get("category", "Unknown")
                        )
                        second.metric(
                            "Connection",
                            "HTTPS" if source_result.get("https") else "Not HTTPS",
                        )
                        st.caption(f"Domain: {source_result.get('domain', 'Unknown')}")
                        st.caption("Technical checks: " + source_result.get("indicator_level", "Not assessed"))
                        for warning in source_result.get("risk_indicators", []):
                            st.warning(warning)

                        with st.expander("Source indicators and limitations"):
                            for indicator in source_result.get("indicators", []):
                                st.write(f"• {indicator}")
                            limitations = source_result.get("limitations", [])
                            if isinstance(limitations, str):
                                limitations = [limitations]
                            for limitation in limitations:
                                st.caption(limitation)
                    else:
                        st.warning(
                            "This source URL could not be validated by the basic URL checker."
                        )

                    st.markdown(f"[Open source]({source_url})")


# -----------------------------------------------------------------------------
# CLAIM VERIFICATION DASHBOARD
# -----------------------------------------------------------------------------
def render_verification_dashboard():
    selected_claims = st.session_state.selected_claims

    if not selected_claims:
        st.info(
            "Identify claims from your extracted text to see the verification dashboard."
        )
        return

    st.markdown(
        '<div class="section-label">Evidence review</div>',
        unsafe_allow_html=True,
    )
    st.header("Claim verification overview")

    for number, claim in enumerate(selected_claims, start=1):
        result = analyze_evidence(claim, st.session_state.evidence)
        similarity_results = analyze_claim_evidence_similarity(
            claim, st.session_state.evidence
        )
        assessment = assess_claim(claim, st.session_state.evidence)

        with st.container(border=True):
            st.markdown(f"### Claim {number}")
            st.write(claim)
            st.markdown(f"**Preliminary evidence status:** {result['status']}")

            columns = st.columns(4)
            for column, label in zip(
                columns, ["Supports", "Contradicts", "Context only", "Unclear"]
            ):
                column.metric(label, result["counts"][label])

            st.caption(f"Total sources collected: {result['total']}")
            st.markdown("#### Evidence-based assessment summary")
            st.write(f"**Combined assessment:** {assessment['status']}")

            summary_columns = st.columns(3)
            summary_columns[0].metric(
                "Unique domains", assessment["unique_domains"]
            )
            summary_columns[1].metric(
                "Supporting", assessment["counts"]["Supports"]
            )
            summary_columns[2].metric(
                "Contradicting", assessment["counts"]["Contradicts"]
            )

            if assessment["domains"]:
                st.caption("Domains: " + ", ".join(assessment["domains"]))

            if assessment["source_categories"]:
                category_summary = ", ".join(
                    f"{category}: {count}"
                    for category, count in assessment["source_categories"].items()
                )
                st.caption("Source categories: " + category_summary)

            smart_assessment = assess_claim_with_context(claim, st.session_state.evidence)
            with st.expander("AI-assisted evidence assessment", expanded=False):
                st.markdown(f"**Assessment:** {smart_assessment['conclusion']}")
                st.write(smart_assessment["explanation"])
                st.caption("This is an evidence summary, not an independent true/false verdict.")
                for source_row in smart_assessment["sources"]:
                    st.markdown(f"**{source_row['title']}** · {source_row['relation']}")
                    st.caption(f"{source_row['domain']} · {source_row['source_category']} · Text overlap: {source_row['text_overlap']}%")
            limitations = assessment.get("limitations", "")
            if limitations:
                st.info(limitations)

            with st.expander("Lexical similarity details"):
                if similarity_results:
                    for item in similarity_results:
                        st.markdown(
                            f"**{item['title']}** — {item['score']}% · {item['label']}"
                        )
                        st.caption(
                            f"Relationship selected by user: {item['relation']}"
                        )
                        if item["common_words"]:
                            st.write(
                                "Common words: " + ", ".join(item["common_words"])
                            )
                        if item["url"]:
                            st.markdown(f"[Open source]({item['url']})")
                else:
                    st.info("No saved evidence available for similarity analysis.")

            report_data = {
                "claim": claim,
                "status": assessment["status"],
                "counts": result["counts"],
                "sources": result["sources"],
                "unique_domains": assessment["unique_domains"],
                "domains": assessment["domains"],
            }

            try:
                pdf_bytes = generate_pdf_report(report_data)
                st.download_button(
                    "Download this claim's PDF report",
                    data=pdf_bytes,
                    file_name=f"truthlens_claim_{number}_report.pdf",
                    mime="application/pdf",
                    key=f"download_claim_pdf_{number}",
                    use_container_width=True,
                )
            except Exception as error:
                st.error(f"Could not generate PDF report: {error}")

    st.warning(
        "These are evidence-management and text-overlap indicators, "
        "not an independently verified true/false verdict."
    )


# -----------------------------------------------------------------------------
# OVERVIEW
# -----------------------------------------------------------------------------
if page == "Overview":
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">TRUTHLENS AI / WORKSPACE</div>
            <div class="hero-title">Clarity starts with<br>checking the evidence.</div>
            <div class="hero-copy">A structured workspace to inspect documents, extract factual claims, collect source material and review evidence relationships.</div>
        </div>
        """, unsafe_allow_html=True,
    )
    stats = st.columns(4)
    stats[0].metric("Current source", st.session_state.current_filename or "No source")
    stats[1].metric("Characters extracted", f"{len(st.session_state.extracted_text):,}")
    stats[2].metric("Candidate claims", len(st.session_state.claims))
    stats[3].metric("Evidence records", len(st.session_state.evidence))
    st.subheader("Workspace")
    left, right = st.columns([1.35, 1])
    with left:
        with st.container(border=True):
            st.markdown("**Start an investigation**")
            st.write("Upload a document, paste a news story or provide a public article URL.")
            st.caption("Supported inputs include PDF, DOCX, TXT, images, PPTX and XLSX.")
            if st.button("Open investigation", type="primary", use_container_width=True):
                # Update navigation through a separate pending key. The radio
                # widget owns workspace_page after it has been instantiated.
                st.session_state["pending_workspace_page"] = "Investigate"
                st.rerun()
    with right:
        with st.container(border=True):
            st.markdown("**Investigation workflow**")
            st.markdown("""1. Add a source
2. Extract and review text
3. Identify candidate claims
4. Collect evidence
5. Review the evidence summary""")
    st.subheader("Current investigation")
    if st.session_state.extracted_text:
        st.write(f"**Source:** {st.session_state.current_filename or 'Untitled source'}")
        st.caption(f"{len(st.session_state.extracted_text):,} characters available for review.")
    else:
        st.info("No active investigation. Start by adding a source.")
    st.caption("TruthLens AI provides research indicators. It does not independently establish whether a claim is true or false.")

# -----------------------------------------------------------------------------
# INVESTIGATE — ORIGINAL WORKFLOW AND BACKEND FUNCTIONS PRESERVED
# -----------------------------------------------------------------------------
elif page == "Investigate":
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">Content intelligence workspace</div>
            <div class="hero-title">Investigate content.<br>Follow the evidence.</div>
            <div class="hero-copy">
                Add a PDF, image, document, plain text or webpage link. Read the content,
                find important claims and check sources — all on this page.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metric_columns = st.columns(4)
    metric_columns[0].metric(
        "Current file", st.session_state.current_filename or "Not uploaded"
    )
    metric_columns[1].metric(
        "Extracted characters", f"{len(st.session_state.extracted_text):,}"
    )
    metric_columns[2].metric("Possible claims", len(st.session_state.claims))
    metric_columns[3].metric("Saved evidence", len(st.session_state.evidence))

    st.markdown(
        "<div class='section-label'>Step 01 · Add something to check</div>",
        unsafe_allow_html=True,
    )
    st.header("Choose how you want to add content")
    st.caption("Upload a file, paste text, or add a public webpage link.")

    file_tab, text_tab, link_tab = st.tabs(
        ["📁 Upload file", "✍️ Paste text", "🔗 Website link"]
    )

    with file_tab:
        st.caption(
            "PDF, DOCX, TXT, JPG, JPEG, PNG, WEBP, PPTX and XLSX are supported."
        )
        uploaded_file = st.file_uploader(
            "Choose a document or image",
            type=["pdf", "docx", "txt", "jpg", "jpeg", "png", "webp", "pptx", "xlsx"],
            key="main_dashboard_upload",
        )

    with text_tab:
        pasted_text = st.text_area(
            "Paste the text you want to check",
            placeholder="Paste a news story, message, social media post or any text here...",
            height=170,
            key="direct_text_input",
        )
        if st.button(
            "Use this text", key="use_pasted_text", type="primary",
            use_container_width=True
        ):
            if pasted_text.strip():
                text_value = pasted_text.strip()
                text_hash = hashlib.sha256(text_value.encode("utf-8")).hexdigest()
                reset_investigation(text_value, "Pasted text", text_hash)
                persist_current_investigation("Pasted text", text_value)
                st.success("Text added. You can now review it and find claims below.")
                st.rerun()
            else:
                st.warning("Please paste some text first.")

    with link_tab:
        webpage_url = st.text_input(
            "Paste a public webpage link",
            placeholder="https://example.com/news-story",
            key="direct_webpage_url",
        )
        st.caption(
            "Public pages work best. Login pages, paywalls and some dynamic websites may not load."
        )
        if st.button(
            "Get text from this link", key="use_webpage_link", type="primary",
            use_container_width=True
        ):
            if not webpage_url.strip():
                st.warning("Please enter a webpage link first.")
            else:
                with st.spinner("Trying to read the webpage..."):
                    try:
                        article_data = extract_article(webpage_url.strip())
                        page_text = article_data.get("text", "").strip()
                        if page_text:
                            title = article_data.get("title") or webpage_url.strip()
                            page_hash = hashlib.sha256(page_text.encode("utf-8")).hexdigest()
                            reset_investigation(page_text, title, page_hash)
                            persist_current_investigation(title, page_text)
                            st.success("Webpage text added. Review it below.")
                            st.rerun()
                        else:
                            st.warning("No readable text was found on this webpage.")
                    except Exception as error:
                        st.error(f"Could not read this webpage: {error}")

    # Uploaded file processing
    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        extension = uploaded_file.name.rsplit(".", 1)[-1].lower()

        if st.session_state.current_file_hash != file_hash:
            reset_investigation(
                filename=uploaded_file.name,
                content_hash=file_hash,
            )

        info_columns = st.columns([2, 1, 1])
        info_columns[0].success(f"Selected: {uploaded_file.name}")
        info_columns[1].metric("File type", extension.upper())
        info_columns[2].metric("File size", f"{len(file_bytes) / 1024:.1f} KB")

        is_image = extension in {"jpg", "jpeg", "png", "webp"}

        if is_image:
            with st.expander("Preview uploaded image", expanded=True):
                try:
                    with Image.open(BytesIO(file_bytes)) as preview:
                        st.image(preview, use_container_width=True)
                except Exception as error:
                    st.error(f"Could not preview image: {error}")

            st.markdown(
                "<div class='section-label'>Image investigation</div>",
                unsafe_allow_html=True,
            )
            st.subheader("Image forensics")

            if st.button(
                "Run image analysis", type="primary",
                key="dashboard_image_analysis"
            ):
                with st.spinner(
                    "Running metadata, image indicators and model analysis..."
                ):
                    st.session_state.forensic_result = analyze_image(file_bytes)

            forensic = st.session_state.forensic_result
            if forensic:
                if forensic.get("success"):
                    metadata = forensic["metadata"]
                    quality = forensic["quality"]
                    columns = st.columns(4)
                    columns[0].metric(
                        "Dimensions",
                        f"{metadata['width']} × {metadata['height']}"
                    )
                    columns[1].metric("Format", metadata["format"])
                    columns[2].metric("Edge mean", quality["edge_mean"])
                    columns[3].metric("Edge variance", quality["edge_variance"])

                    with st.expander("View EXIF metadata"):
                        if metadata["exif"]:
                            st.json(metadata["exif"])
                        else:
                            st.info("No EXIF metadata found.")

                    ai_result = forensic.get("ai_detection", {})
                    st.markdown("#### TruthLens AI model analysis")
                    if ai_result.get("available"):
                        st.write(
                            f"**TruthLens AI model output:** {ai_result.get('prediction', 'Unavailable')}"
                        )
                        score_columns = st.columns(2)
                        score_columns[0].metric(
                            "AI-generated likelihood", f"{ai_result.get('ai_score', 0)}%"
                        )
                        score_columns[1].metric(
                            "Human-created likelihood", f"{ai_result.get('human_score', 0)}%"
                        )
                        st.caption(f"Detection engine: {ai_result.get('engine', ai_result.get('model', 'Not specified'))}")
                        st.info(
                            ai_result.get("warning", "Model output is an indicator, not proof of image origin.")
                        )
                    else:
                        st.info(
                            "AI classifier unavailable: "
                            + ai_result.get("error", "No details supplied")
                        )

                    if forensic.get("ela_available"):
                        with st.expander("View Error Level Analysis (ELA)"):
                            st.image(
                                forensic["ela_image"], use_container_width=True
                            )

                    for warning in forensic.get("warnings", []):
                        st.caption(f"• {warning}")
                else:
                    st.error(
                        "Image analysis failed: "
                        + forensic.get("error", "Unknown error")
                    )

        st.markdown(
            "<div class='section-label'>Step 02 · Read the content</div>",
            unsafe_allow_html=True,
        )
        st.subheader("Text extraction")
        st.caption(
            "This reads text from documents and uses OCR for scanned pages and images."
        )

        if st.button(
            "Extract text from file", type="primary",
            key="dashboard_extract_text"
        ):
            with st.spinner("Reading file content..."):
                extracted = extract_file_content(uploaded_file)

            if extracted.startswith("ERROR:"):
                st.error(extracted)
            elif not extracted.strip():
                st.warning("No readable text was found in this file.")
            else:
                st.session_state.extracted_text = extracted
                st.session_state.claims = []
                st.session_state.selected_claims = []
                st.session_state.evidence = []
                st.session_state.pop("dashboard_claim_selection", None)
                st.session_state.history.append({
                    "filename": uploaded_file.name,
                    "date": datetime.now().strftime("%d-%m-%Y %I:%M %p"),
                    "characters": len(extracted),
                    "text": extracted,
                })
                persist_current_investigation(uploaded_file.name, extracted)
                st.success("Text extraction completed.")

    # Extracted text review and claim investigation
    if st.session_state.extracted_text:
        st.markdown(
            "<div class='section-label'>Step 02 · Check the text</div>",
            unsafe_allow_html=True,
        )
        st.subheader("Review the text")
        st.caption("Correct any reading mistakes before finding claims.")

        edited_text = st.text_area(
            "You can correct OCR mistakes before claim extraction.",
            value=st.session_state.extracted_text,
            height=210,
            key="dashboard_extracted_text_editor",
        )

        if edited_text != st.session_state.extracted_text:
            st.session_state.extracted_text = edited_text
            st.session_state.claims = []
            st.session_state.selected_claims = []
            st.session_state.evidence = []
            st.session_state.pop("dashboard_claim_selection", None)
            account = st.session_state.get("authenticated_user") or {}
            investigation_id = st.session_state.get("current_investigation_id")
            if account.get("id") and investigation_id:
                try:
                    update_investigation_content(
                        account["id"], account.get("username", "user"),
                        investigation_id,
                        st.session_state.get("current_filename") or "Edited investigation",
                        edited_text,
                    )
                except Exception as error:
                    st.warning("Edited text could not be saved to history: " + str(error))

        download_columns = st.columns(2)
        download_columns[0].download_button(
            "Download extracted TXT",
            edited_text,
            file_name="truthlens_extracted_text.txt",
            mime="text/plain",
            use_container_width=True,
        )
        csv_data = pd.DataFrame(
            {"Extracted Text": [edited_text]}
        ).to_csv(index=False).encode("utf-8-sig")
        download_columns[1].download_button(
            "Download extracted CSV",
            csv_data,
            file_name="truthlens_extracted_text.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.markdown(
            "<div class='section-label'>Step 03 · Find important statements</div>",
            unsafe_allow_html=True,
        )
        st.subheader("Find possible claims")
        st.caption(
            "The tool suggests possible claims; it does not decide whether they are true."
        )

        if st.button(
            "Identify possible news claims", type="primary",
            key="dashboard_extract_claims"
        ):
            with st.spinner("Finding candidate factual statements..."):
                extracted_claims = extract_claims(
                    st.session_state.extracted_text
                )

            normalized_claims = []
            seen_claims = set()
            for item in extracted_claims:
                claim_text = (
                    item.get("claim", "")
                    if isinstance(item, dict)
                    else str(item)
                ).strip()
                if claim_text and claim_text not in seen_claims:
                    normalized_claims.append({"claim": claim_text})
                    seen_claims.add(claim_text)

            st.session_state.claims = normalized_claims
            persist_claims()
            st.session_state.selected_claims = [
                item["claim"] for item in normalized_claims
            ]
            st.session_state.evidence = []
            st.session_state.pop("dashboard_claim_selection", None)

        if st.session_state.claims:
            options = [item["claim"] for item in st.session_state.claims]
            selected = st.multiselect(
                "Choose claims to investigate",
                options=options,
                default=[
                    claim for claim in st.session_state.selected_claims
                    if claim in options
                ],
                key="dashboard_claim_selection",
            )
            st.session_state.selected_claims = selected
            st.caption(
                "Select the statements you want to check. "
                "These suggestions are not automatically verified."
            )

            for index, claim in enumerate(selected, start=1):
                render_evidence_for_claim(claim, index)

            if st.session_state.evidence:
                report_lines = []
                for number, item in enumerate(
                    st.session_state.evidence, start=1
                ):
                    report_lines.extend([
                        f"EVIDENCE {number}",
                        f"Claim: {item.get('claim', '')}",
                        f"Source: {item.get('title', '')}",
                        f"URL: {item.get('url', '')}",
                        f"Assessment: {item.get('relation', '')}",
                        f"Date: {item.get('date', '')}",
                        f"Evidence: {item.get('excerpt', '')}",
                        "-" * 55,
                    ])

                st.download_button(
                    "Download evidence report",
                    "\n".join(report_lines),
                    file_name="truthlens_evidence_report.txt",
                    mime="text/plain",
                )
        else:
            st.info("Click ‘Identify possible news claims’ to continue.")
    else:
        st.info(
            "Start above: upload a file, paste text, or enter a public webpage link. "
            "Then follow the steps shown here."
        )


# -----------------------------------------------------------------------------
# AI CLAIM VERIFICATION
# -----------------------------------------------------------------------------
elif page == "Claim Verification":
    st.markdown('<div class="section-label">EVIDENCE-BASED REVIEW</div>', unsafe_allow_html=True)
    st.title("AI Claim Verification")
    st.caption("Review the evidence collected for each selected claim. The assessment is explainable and does not produce an unsupported true/false verdict.")
    if not st.session_state.selected_claims:
        st.info("No claims selected. Go to Investigate, extract candidate claims and select the statements you want to review.")
    else:
        for number, claim in enumerate(st.session_state.selected_claims, start=1):
            result = assess_claim_with_context(claim, st.session_state.evidence)
            with st.container(border=True):
                st.markdown(f"### Claim {number}")
                st.write(claim)
                st.subheader(result["conclusion"])
                st.write(result["explanation"])
                if st.button("Run AI review", key=f"ai_claim_review_{number}", type="primary"):
                    with st.spinner("Reviewing the collected evidence..."):
                        model_review = ai_claim_review(claim, st.session_state.evidence)
                    st.session_state[f"claim_review_result_{number}"] = model_review
                model_review = st.session_state.get(f"claim_review_result_{number}")
                if model_review:
                    st.markdown("**" + model_review["mode"] + "**")
                    st.write(model_review["answer"])
                cols = st.columns(4)
                for col, label in zip(cols, ["Supports", "Contradicts", "Context only", "Unclear"]):
                    col.metric(label, result["counts"][label])
                if result["sources"]:
                    st.markdown("**Reviewed evidence sources**")
                    for source in result["sources"]:
                        st.markdown(f"**{source['title']}** · {source['relation']}")
                        st.caption(f"{source['domain']} · {source['source_category']} · Text overlap: {source['text_overlap']}%")
                else:
                    st.warning("No evidence has been collected for this claim yet.")
                for note in result["limitations"]:
                    st.caption("• " + note)

        st.divider()
        render_verification_dashboard()


# -----------------------------------------------------------------------------
# SOURCE CREDIBILITY CHECKER
# -----------------------------------------------------------------------------
elif page == "Source Checker":
    st.markdown('<div class="section-label">SOURCE INSPECTION</div>', unsafe_allow_html=True)
    st.title("Source Credibility Checker")
    st.caption("Inspect technical URL and domain indicators. This is not a verified publisher reputation service.")
    with st.form("source_checker_form"):
        source_url_input = st.text_input("Website or article URL", placeholder="https://example.com/news/article")
        check_source = st.form_submit_button("Check source", type="primary")
    if check_source:
        source_result = analyze_source(source_url_input)
        if source_result.get("valid_url"):
            st.subheader(source_result.get("domain", "Unknown domain"))
            first, second = st.columns(2)
            first.metric("Domain category", source_result.get("category", "Unknown"))
            second.metric("Technical indicator level", source_result.get("indicator_level", "Not assessed"))
            st.write("**Connection:** " + ("HTTPS" if source_result.get("https") else "HTTP"))
            for item in source_result.get("indicators", []):
                st.write("• " + item)
            if source_result.get("risk_indicators"):
                st.markdown("**Checks to perform**")
                for item in source_result["risk_indicators"]:
                    st.warning(item)
            else:
                st.success("No additional URL-level warning was detected by these basic checks.")
            with st.expander("Limitations"):
                for item in source_result.get("limitations", []):
                    st.caption(item)
        else:
            st.error(source_result.get("note", "This URL could not be checked."))
    st.info("A government-style domain, known publisher domain or HTTPS connection does not guarantee that a particular article is accurate.")


# -----------------------------------------------------------------------------
# EVIDENCE REVIEW
# -----------------------------------------------------------------------------
elif page == "Evidence Review":
    st.markdown('<div class="section-label">Research workspace</div>', unsafe_allow_html=True)
    st.title("Evidence review")
    st.caption("Review saved source material and the relationship assigned to each selected claim.")
    if st.session_state.evidence:
        for index, item in enumerate(st.session_state.evidence, start=1):
            with st.container(border=True):
                st.markdown(f"**{index}. {item.get('title') or 'Untitled source'}**")
                st.caption(f"Relationship: {item.get('relation', 'Unclear')} · Added: {item.get('date', 'Date unavailable')}")
                st.write(item.get('claim', ''))
                st.write(item.get('excerpt', ''))
                if item.get('url'):
                    st.markdown(f"[Open source]({item['url']})")
    else:
        st.info("No evidence has been saved yet. Open Investigate, identify claims and add source evidence.")

# -----------------------------------------------------------------------------
# REPORTS
# -----------------------------------------------------------------------------
elif page == "Reports":
    st.markdown('<div class="section-label">Export and documentation</div>', unsafe_allow_html=True)
    st.title("Investigation reports")
    st.caption("Generate downloadable summaries from the evidence currently saved in this session.")
    if not st.session_state.selected_claims:
        st.info("No claims selected yet. Complete the claim and evidence workflow first.")
    else:
        full_report_data = {
            "title": st.session_state.get("current_filename") or "Current investigation",
            "source_name": st.session_state.get("current_filename") or "Current source",
            "claims": st.session_state.selected_claims,
            "evidence": st.session_state.evidence,
        }
        try:
            full_pdf = generate_investigation_pdf(full_report_data)
            st.download_button(
                "Download complete investigation PDF",
                data=full_pdf,
                file_name="truthlens_complete_investigation.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
        except Exception as error:
            st.error("Could not generate complete investigation PDF: " + str(error))
        for number, claim in enumerate(st.session_state.selected_claims, start=1):
            # Build the PDF from the evidence records themselves so the exported
            # report cannot silently omit a saved item due to minor text spacing.
            def _claim_key(value):
                return " ".join(str(value or "").split()).casefold()

            claim_evidence = [
                item for item in st.session_state.evidence
                if isinstance(item, dict)
                and _claim_key(item.get("claim")) == _claim_key(claim)
            ]
            report_counts = {
                "Supports": 0, "Contradicts": 0,
                "Context only": 0, "Unclear": 0,
            }
            for item in claim_evidence:
                relation = item.get("relation", "Unclear")
                report_counts[relation if relation in report_counts else "Unclear"] += 1

            result = analyze_evidence(claim, claim_evidence)
            assessment = assess_claim(claim, claim_evidence)
            with st.container(border=True):
                st.markdown(f"**Claim {number}**")
                st.write(claim)
                st.caption(f"Evidence status: {assessment.get('status', result.get('status', 'Not assessed'))}")
                report_data = {
                    "claim": claim,
                    "status": assessment.get("status", result.get("status", "Not assessed")),
                    "counts": report_counts,
                    "sources": claim_evidence,
                    "unique_domains": assessment.get("unique_domains", 0),
                    "domains": assessment.get("domains", []),
                }
                try:
                    pdf_bytes = generate_pdf_report(report_data)
                    st.download_button(
                        f"Download claim {number} PDF", data=pdf_bytes,
                        file_name=f"truthlens_claim_{number}_report.pdf",
                        mime="application/pdf", key=f"reports_page_pdf_{number}",
                    )
                except Exception as error:
                    st.error(f"Could not generate PDF report: {error}")
        if st.session_state.evidence:
            lines = []
            for number, item in enumerate(st.session_state.evidence, start=1):
                lines.extend([f"EVIDENCE {number}", f"Claim: {item.get('claim', '')}", f"Source: {item.get('title', '')}", f"URL: {item.get('url', '')}", f"Relationship: {item.get('relation', '')}", f"Date: {item.get('date', '')}", f"Evidence: {item.get('excerpt', '')}", "-" * 50])
            st.download_button("Download complete evidence report (TXT)", "\n".join(lines), file_name="truthlens_evidence_report.txt", mime="text/plain", type="primary")

# -----------------------------------------------------------------------------
# HISTORY
# -----------------------------------------------------------------------------
elif page == "History":
    st.markdown('<div class="section-label">Past investigations</div>', unsafe_allow_html=True)
    st.title("Investigation history")
    account = st.session_state.authenticated_user
    username = account.get("username", "user")
    try:
        saved_history = list_user_investigations(account["id"], username)
    except Exception as error:
        saved_history = []
        st.error("Could not load saved history: " + str(error))

    if saved_history:
        history_rows = []
        for item in saved_history:
            body = item.get("extracted_text", item.get("text", "")) or ""
            history_rows.append({
                "Investigation": item.get("title", "Untitled"),
                "Date": item.get("created_at", "Date unavailable"),
                "Characters": len(body),
                "Claims": len(item.get("claims") or []),
            })
        st.dataframe(pd.DataFrame(history_rows), use_container_width=True, hide_index=True)
        for index, item in enumerate(saved_history):
            title = item.get("title", "Untitled investigation")
            created = item.get("created_at", "Date unavailable")
            with st.expander(f"{title} · {created}"):
                saved_text = item.get("extracted_text", item.get("text", "")) or ""
                st.caption(f"{len(saved_text):,} characters")
                st.text_area("Extracted content", saved_text, height=180, key=f"saved_history_{index}")
                saved_claims = item.get("claims") or []
                if saved_claims:
                    st.markdown("**Saved candidate claims**")
                    for claim_item in saved_claims:
                        st.write(claim_item.get("claim", "") if isinstance(claim_item, dict) else str(claim_item))
                if st.button("Open this investigation", key=f"open_history_{index}", type="primary"):
                    restored = get_user_investigation(account["id"], username, item.get("id"))
                    if restored:
                        st.session_state.extracted_text = restored.get("extracted_text", restored.get("text", "")) or ""
                        st.session_state.current_filename = restored.get("source_name") or restored.get("title", "Restored investigation")
                        st.session_state.current_investigation_id = restored.get("id")
                        st.session_state.claims = restored.get("claims") or []
                        st.session_state.selected_claims = [
                            row.get("claim", "") if isinstance(row, dict) else str(row)
                            for row in st.session_state.claims
                        ]
                        st.session_state.evidence = list_investigation_evidence(
                            account["id"], username, restored.get("id")
                        )
                        st.session_state["pending_workspace_page"] = "Investigate"
                        st.rerun()
                    else:
                        st.warning("This investigation could not be opened.")
                if st.button("Delete this investigation", key=f"delete_history_{index}"):
                    if delete_user_investigation(account["id"], username, item.get("id")):
                        st.success("Investigation deleted.")
                        st.rerun()
                    else:
                        st.warning("This investigation could not be deleted.")
    else:
        st.info("No saved investigations yet. Add and extract content in Investigate to build your history.")
    if not supabase_configured():
        st.caption("History is using the existing SQLite database on this deployment. Configure Supabase to make it durable across hosting restarts.")


# -----------------------------------------------------------------------------
# AI ASSISTANT
# -----------------------------------------------------------------------------
elif page == "AI Assistant":
    st.markdown(
        """
        <style>
        .tl-ai-hero {
            padding: 1.35rem 1.55rem;
            border-radius: 22px;
            background: linear-gradient(120deg, #063f50 0%, #087f91 58%, #12a7b0 100%);
            color: #ffffff;
            margin: .25rem 0 1.1rem 0;
            box-shadow: 0 12px 28px rgba(5, 76, 91, .16);
        }
        .tl-ai-kicker {
            color: #a9edf0;
            font-size: .72rem;
            font-weight: 800;
            letter-spacing: .15em;
            text-transform: uppercase;
            margin-bottom: .45rem;
        }
        .tl-ai-hero h1 {
            color: #ffffff !important;
            font-size: 2rem !important;
            margin: 0 0 .35rem 0 !important;
            line-height: 1.15;
        }
        .tl-ai-hero p {
            color: #e1f7f8 !important;
            margin: 0 !important;
            font-size: .98rem;
        }
        .tl-ai-status {
            display: inline-flex;
            align-items: center;
            gap: .45rem;
            border: 1px solid rgba(8, 132, 145, .18);
            background: #f0fbfc;
            color: #17616d;
            border-radius: 999px;
            padding: .35rem .75rem;
            font-size: .78rem;
            font-weight: 650;
            margin: .1rem 0 .85rem 0;
        }
        .tl-ai-dot {
            width: .48rem;
            height: .48rem;
            border-radius: 50%;
            background: #16a47a;
            display: inline-block;
            box-shadow: 0 0 0 3px rgba(22,164,122,.12);
        }
        [data-testid="stChatMessage"] {
            background: #ffffff;
            border: 1px solid #dcebf0;
            border-radius: 18px;
            padding: .9rem 1rem;
            margin: .65rem 0;
            box-shadow: 0 5px 16px rgba(17, 65, 82, .045);
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p {
            line-height: 1.65;
        }
        [data-testid="stChatInput"] {
            border-radius: 18px !important;
            border: 1px solid #b8dce3 !important;
            box-shadow: 0 8px 24px rgba(13, 92, 109, .08) !important;
            background: #ffffff !important;
        }
        [data-testid="stChatInput"] textarea {
            font-size: .98rem !important;
        }
        div.stButton > button[kind="secondary"] {
            border-radius: 13px;
            border-color: #c8e4e9;
            background: #ffffff;
            color: #175467;
            min-height: 2.8rem;
            font-weight: 600;
        }
        div.stButton > button[kind="secondary"]:hover {
            border-color: #0799a8;
            color: #057b89;
            background: #f1fbfc;
        }
        .tl-ai-welcome {
            border: 1px solid #d6eaf0;
            background: linear-gradient(135deg, #ffffff 0%, #f1fafc 100%);
            border-radius: 18px;
            padding: 1.05rem 1.2rem;
            margin: .5rem 0 1rem 0;
        }
        .tl-ai-welcome strong { color: #123b4b; }
        .tl-ai-welcome span { color: #527080; font-size: .9rem; }
        </style>
        <div class="tl-ai-hero">
          <div class="tl-ai-kicker">TRUTHLENS AI · RESEARCH WORKSPACE</div>
          <h1>Ask better questions. Examine the evidence.</h1>
          <p>Your investigation-aware assistant for claims, sources and evidence review.</p>
        </div>
        <div class="tl-ai-status"><span class="tl-ai-dot"></span> Assistant ready · Evidence-aware responses</div>
        """,
        unsafe_allow_html=True,
    )

    if supabase_configured():
        st.caption("Cloud persistence is configured. Open-ended model responses are optional and require HF_TOKEN.")
    else:
        st.caption("Local assistant mode · No paid API required. Optional model responses can be enabled with HF_TOKEN.")

    context_parts = []
    if st.session_state.get("extracted_text"):
        context_parts.append("Current source: " + st.session_state.get("current_filename", "Untitled"))
    if st.session_state.get("selected_claims"):
        context_parts.append("Selected claims: " + " | ".join(st.session_state.selected_claims[:8]))
    if st.session_state.get("evidence"):
        evidence_summary = []
        for item in st.session_state.evidence[:8]:
            if isinstance(item, dict):
                evidence_summary.append(
                    f"{item.get('title', 'Untitled source')} — {item.get('relation', 'Unclear')}"
                )
        context_parts.append("Saved evidence: " + "; ".join(evidence_summary))
    chat_context = "\\n".join(context_parts)

    if not st.session_state.chat_messages:
        st.markdown(
            '<div class="tl-ai-welcome"><strong>Welcome to your research assistant</strong><br>'
            '<span>Ask a question below, or start with one of these suggested prompts.</span></div>',
            unsafe_allow_html=True,
        )
        prompt_cols = st.columns(3, gap="small")
        quick_prompts = [
            "How do I verify a claim?",
            "How can I assess source credibility?",
            "What makes evidence contradictory?",
        ]
        quick_question = None
        for idx, prompt in enumerate(quick_prompts):
            if prompt_cols[idx].button(prompt, key=f"truthlens_quick_prompt_{idx}", use_container_width=True):
                quick_question = prompt
    else:
        quick_question = None

    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    typed_question = st.chat_input("Ask TruthLens AI about claims, sources or this investigation...")
    question = quick_question or typed_question
    if question:
        st.session_state.chat_messages.append({"role": "user", "content": question})
        answer = chat_answer(question, chat_context)
        st.session_state.chat_messages.append({"role": "assistant", "content": answer})
        st.rerun()

    if st.session_state.chat_messages:
        clear_col, note_col = st.columns([1, 4])
        with clear_col:
            if st.button("Clear conversation", key="clear_truthlens_chat", use_container_width=True):
                st.session_state.chat_messages = []
                st.rerun()
        with note_col:
            st.caption("TruthLens AI can make mistakes. Verify important findings against original sources.")


# -----------------------------------------------------------------------------
# ANALYTICS DASHBOARD
# -----------------------------------------------------------------------------
elif page == "Analytics":
    st.markdown('<div class="section-label">WORKSPACE INSIGHTS</div>', unsafe_allow_html=True)
    st.title("Analytics")
    st.caption("A focused view of your saved investigations and research activity.")

    account = st.session_state.authenticated_user
    try:
        stats = analytics_for_user(account["id"], account.get("username", "user"))
        history_rows = stats.get("recent", []) or []
        total_investigations = int(stats.get("investigations", 0) or 0)
        total_claims = int(stats.get("claims", 0) or 0)
        total_evidence = int(stats.get("evidence", 0) or 0)

        st.markdown("#### Workspace overview")
        metric_cols = st.columns(4)
        metric_cols[0].metric("Investigations", total_investigations)
        metric_cols[1].metric("Candidate claims", total_claims)
        metric_cols[2].metric("Evidence records", total_evidence)
        metric_cols[3].metric(
            "Avg. claims / investigation",
            f"{total_claims / total_investigations:.1f}" if total_investigations else "—",
        )

        st.divider()
        if history_rows:
            visible_history = history_rows[:30]
            selection_key = "analytics_selected_investigation_indexes"
            if selection_key not in st.session_state:
                st.session_state[selection_key] = []
            selected_rows = [
                int(index) for index in st.session_state[selection_key]
                if isinstance(index, int) and 0 <= index < len(visible_history)
            ]
            st.session_state[selection_key] = selected_rows

            st.markdown("#### Recent investigations")
            st.caption("Showing up to 30 recent investigations. Tap cards to compare one or more files; the chart expands vertically as needed.")

            # Touch-friendly selectable cards: no dataframe selection checkboxes.
            for row_start in range(0, len(visible_history), 2):
                card_cols = st.columns(2, gap="medium")
                for offset, card_col in enumerate(card_cols):
                    index = row_start + offset
                    if index >= len(visible_history):
                        continue
                    item = visible_history[index]
                    title = str(item.get("title") or "Untitled investigation")
                    display_title = title if len(title) <= 34 else title[:31] + "..."
                    claim_count = len(item.get("claims") or [])
                    created = str(item.get("created_at") or "Date unavailable")
                    is_selected = index in selected_rows
                    with card_col:
                        button_label = ("✓  " if is_selected else "＋  ") + display_title
                        if st.button(
                            button_label,
                            key=f"analytics_toggle_investigation_{index}",
                            type="primary" if is_selected else "secondary",
                            use_container_width=True,
                            help="Tap to add or remove this investigation from the comparison.",
                        ):
                            updated = list(st.session_state[selection_key])
                            if index in updated:
                                updated.remove(index)
                            else:
                                updated.append(index)
                            st.session_state[selection_key] = sorted(updated)
                            st.rerun()
                        st.caption(f"{created}  ·  {claim_count} claims")

            selected_rows = list(st.session_state[selection_key])
            selected_set = set(selected_rows)
            action_cols = st.columns([1, 1, 3])
            if action_cols[0].button("Show all", use_container_width=True, key="analytics_clear_selection"):
                st.session_state[selection_key] = []
                st.rerun()
            if selected_rows:
                action_cols[1].caption(f"{len(selected_rows)} selected")

            if selected_rows:
                selected_item = visible_history[selected_rows[0]]
                open_label = "Open selected" if len(selected_rows) == 1 else "Open first selected"
                if st.button(open_label, type="primary", use_container_width=True, key="analytics_open_selected"):
                    restored = get_user_investigation(
                        account["id"], account.get("username", "user"), selected_item.get("id")
                    )
                    if restored:
                        st.session_state.extracted_text = restored.get("extracted_text", restored.get("text", "")) or ""
                        st.session_state.current_filename = restored.get("source_name") or restored.get("title", "Restored investigation")
                        st.session_state.current_investigation_id = restored.get("id")
                        st.session_state.claims = restored.get("claims") or []
                        st.session_state.selected_claims = [
                            row.get("claim", "") if isinstance(row, dict) else str(row)
                            for row in st.session_state.claims
                        ]
                        st.session_state.evidence = list_investigation_evidence(
                            account["id"], account.get("username", "user"), restored.get("id")
                        )
                        st.session_state["pending_workspace_page"] = "Investigate"
                        st.rerun()
                    else:
                        st.error("This investigation could not be opened. Please try again from History.")
                if len(selected_rows) > 1:
                    st.caption("The first selected investigation will open. Select only one file to open a specific investigation.")

            st.divider()
            st.markdown("#### Claims by investigation")
            import altair as alt

            chart_rows = []
            for index, item in enumerate(visible_history):
                title = str(item.get("title") or "Untitled investigation")
                created = str(item.get("created_at") or "")
                chart_label = f"{index + 1:02d} · {title}"
                if created:
                    chart_label += f" · {created[:16]}"
                chart_rows.append({
                    "Investigation": chart_label,
                    "Claims": len(item.get("claims") or []),
                    "Selected": index in selected_set,
                })
            chart_df = pd.DataFrame(chart_rows)
            chart = alt.Chart(chart_df).mark_bar(
                cornerRadiusEnd=5,
                height=24,
            ).encode(
                y=alt.Y(
                    "Investigation:N",
                    sort="-x",
                    title=None,
                    axis=alt.Axis(labelLimit=230, labelFontSize=11, labelPadding=8, ticks=False, domain=False),
                ),
                x=alt.X(
                    "Claims:Q",
                    title="Candidate claims",
                    scale=alt.Scale(domainMin=0, nice=True, zero=True),
                    axis=alt.Axis(format="d", tickMinStep=1, grid=True),
                ),
                color=alt.condition(
                    alt.datum.Selected,
                    alt.value("#0799A8"),
                    alt.value("#8AA9C2"),
                ),
                tooltip=[
                    alt.Tooltip("Investigation:N", title="Investigation"),
                    alt.Tooltip("Claims:Q", title="Candidate claims"),
                    alt.Tooltip("Selected:N", title="Selected"),
                ],
            ).properties(
                height=max(220, min(1040, 34 * len(chart_rows))),
                padding={"left": 8, "right": 20, "top": 12, "bottom": 16},
            )
            st.altair_chart(chart, use_container_width=True)
            if selected_rows:
                st.caption("Highlighted bars match the investigations selected above. All recent investigations remain visible.")
            else:
                st.caption("Showing all recent investigations. Tap cards above to highlight files for comparison.")
        else:
            st.info("No saved investigations yet. Start an investigation to build your activity history.")

        st.divider()
        with st.expander("Storage details"):
            storage_name = stats.get("storage", "Unknown")
            if supabase_configured():
                st.success("Connected storage: " + str(storage_name))
                st.caption("Account-level investigation and evidence totals are loaded from the configured cloud database.")
            else:
                st.warning(
                    "Current storage: Local SQLite. On Streamlit hosting, local files may not survive every "
                    "restart or redeployment. Configure Supabase using supabase/schema.sql and Streamlit Secrets "
                    "for more reliable cross-session storage."
                )
    except Exception as error:
        st.error("Analytics could not be loaded. Please try again; if the issue continues, share the app logs.")
        st.caption(str(error))


# -----------------------------------------------------------------------------
# PROFILE
# -----------------------------------------------------------------------------
elif page == "Profile":
    profile = get_user_profile(st.session_state.authenticated_user["id"])
    username = st.session_state.authenticated_user["username"]
    st.markdown('<div class="section-label">MY ACCOUNT / PROFILE</div>', unsafe_allow_html=True)
    st.title("Profile")
    st.caption("Manage your personal details and account information.")
    if st.button("← Back to Overview", key="profile_back_to_overview"):
        st.session_state["active_workspace_page"] = "Overview"
        st.rerun()

    full_name = " ".join(
        part for part in (
            profile.get("first_name", ""),
            profile.get("middle_name", ""),
            profile.get("last_name", ""),
        ) if part
    ).strip() or username

    with st.container(border=True):
        st.markdown(
            f'<div class="profile-display-name">{html.escape(full_name)}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="profile-username">@{html.escape(username)}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="profile-status">● Account active</div>',
            unsafe_allow_html=True,
        )
        st.divider()

        st.markdown("""
        <style>
        .profile-photo-title{font-size:1.25rem;font-weight:750;color:#102b3a;margin:2px 0 14px}
        .profile-photo-note{font-size:.82rem;color:#678092;margin-top:5px}
        [data-testid="stImage"] img{border-radius:50%;border:4px solid #b9eaf0;object-fit:cover}
        </style>
        """, unsafe_allow_html=True)
        st.markdown('<div class="profile-photo-title">Profile photo</div>', unsafe_allow_html=True)
        photo_col, upload_col = st.columns([1, 3], vertical_alignment="center")
        with photo_col:
            if profile.get("avatar"):
                current_photo = Image.open(BytesIO(profile["avatar"])).convert("RGB")
                current_photo = ImageOps.fit(current_photo, (240, 240), method=Image.Resampling.LANCZOS)
                st.image(current_photo, width=150)
            else:
                initials = "".join(part[0] for part in full_name.split()[:2]).upper()
                st.markdown(
                    f'<div class="profile-avatar-fallback">{html.escape(initials or "TL")}</div>',
                    unsafe_allow_html=True,
                )
        if "profile_avatar_upload_version" not in st.session_state:
            st.session_state["profile_avatar_upload_version"] = 0
        avatar_upload_key = (
            f"profile_avatar_upload_{st.session_state['profile_avatar_upload_version']}"
        )

        with upload_col:
            avatar_file = st.file_uploader(
                "Upload a new profile photo",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=False,
                key=avatar_upload_key,
                help="JPG, PNG or WEBP · Maximum 5 MB.",
            )
            avatar_bytes = None
            if avatar_file is not None:
                try:
                    avatar_bytes = _prepare_profile_avatar(avatar_file)
                    with Image.open(BytesIO(avatar_bytes)) as preview_source:
                        preview_image = ImageOps.fit(
                            preview_source.convert("RGB"),
                            (240, 240),
                            method=Image.Resampling.LANCZOS,
                        )
                    st.caption("Preview · This is how your profile photo will appear")
                    st.image(preview_image, width=150)

                    if st.button(
                        "Save profile photo",
                        key="save_profile_photo",
                        type="primary",
                        use_container_width=True,
                    ):
                        save_user_avatar(
                            st.session_state.authenticated_user["id"],
                            avatar_bytes,
                        )
                        st.session_state["profile_avatar_upload_version"] += 1
                        st.success("Profile photo saved successfully.")
                        st.rerun()
                except (ValueError, OSError) as error:
                    st.error(str(error))
            else:
                st.markdown(
                    '<div class="profile-photo-note">Choose an image to preview it, then click '
                    'Save profile photo. Your current photo stays active until the new one is saved.</div>',
                    unsafe_allow_html=True,
                )

            if profile.get("avatar") and st.button("Remove photo", key="remove_profile_photo"):
                remove_user_avatar(st.session_state.authenticated_user["id"])
                st.session_state["profile_avatar_upload_version"] += 1
                st.success("Profile photo removed.")
                st.rerun()

        st.divider()

        st.markdown("""
        <style>
        .profile-form-heading{font-size:1.35rem;font-weight:750;color:#102b3a;margin:4px 0 18px}
        div[data-testid="stForm"] label,div[data-testid="stForm"] label p{font-size:.92rem!important;font-weight:700!important;color:#536779!important}
        div[data-testid="stForm"] input,div[data-testid="stForm"] textarea,
        div[data-testid="stForm"] [data-baseweb="select"]>div{
            min-height:52px!important;border-radius:13px!important;
            border:1.5px solid #d7e2ea!important;background:#fff!important;
            padding-left:14px!important;color:#17384a!important;
        }
        div[data-testid="stForm"] textarea{min-height:105px!important;padding-top:12px!important}
        div[data-testid="stForm"] [data-testid="stDateInput"] input{min-height:52px!important}
        div[data-testid="stForm"] [data-testid="stFormSubmitButton"] button{
            min-height:50px!important;border-radius:11px!important;font-weight:750!important
        }
        @media(max-width:700px){div[data-testid="stForm"] .stHorizontalBlock{flex-wrap:wrap!important}}
        </style>
        """, unsafe_allow_html=True)

        with st.form("profile_form", clear_on_submit=False):
            st.markdown('<div class="profile-form-heading">Personal information</div>', unsafe_allow_html=True)
            name_left, name_right = st.columns(2, gap="large")
            with name_left:
                first_name = st.text_input("First name", value=profile.get("first_name", ""), placeholder="Enter first name")
            with name_right:
                middle_name = st.text_input("Middle name", value=profile.get("middle_name", ""), placeholder="Enter middle name (optional)")

            detail_left, detail_right = st.columns(2, gap="large")
            with detail_left:
                last_name = st.text_input("Last name", value=profile.get("last_name", ""), placeholder="Enter last name")
            with detail_right:
                email = st.text_input("Email address", value=profile.get("email", ""), placeholder="you@example.com")

            today = date.today()
            dob_value = None
            if profile.get("date_of_birth"):
                try:
                    candidate_dob = date.fromisoformat(profile["date_of_birth"])
                    if date(1970, 1, 1) <= candidate_dob <= today:
                        dob_value = candidate_dob
                except ValueError:
                    dob_value = None

            contact_left, contact_right = st.columns(2, gap="large")
            with contact_left:
                phone = st.text_input("Phone number", value=profile.get("phone", ""), placeholder="+91 98765 43210")
            with contact_right:
                st.markdown("**Date of birth**")
                dob_day_options = [None] + list(range(1, 32))
                dob_month_options = [None] + list(range(1, 13))
                # Explicit year options ensure every year from 1970 onward is selectable.
                dob_year_options = [None] + list(range(1970, today.year + 1))

                dob_day_col, dob_month_col, dob_year_col = st.columns(
                    [0.85, 1.35, 1.0], gap="small"
                )
                with dob_day_col:
                    dob_day = st.selectbox(
                        "Day",
                        options=dob_day_options,
                        index=dob_day_options.index(dob_value.day) if dob_value else 0,
                        format_func=lambda value: "DD" if value is None else f"{value:02d}",
                        key="profile_dob_day",
                    )
                with dob_month_col:
                    dob_month = st.selectbox(
                        "Month",
                        options=dob_month_options,
                        index=dob_month_options.index(dob_value.month) if dob_value else 0,
                        format_func=lambda value: "MM" if value is None else date(2000, value, 1).strftime("%B"),
                        key="profile_dob_month",
                    )
                with dob_year_col:
                    dob_year = st.selectbox(
                        "Year",
                        options=dob_year_options,
                        index=dob_year_options.index(dob_value.year) if dob_value else 0,
                        format_func=lambda value: "YYYY" if value is None else str(value),
                        key="profile_dob_year",
                    )

                dob_parts_selected = [
                    dob_day is not None,
                    dob_month is not None,
                    dob_year is not None,
                ]
                dob = None
                dob_is_invalid = False
                if all(dob_parts_selected):
                    try:
                        dob = date(dob_year, dob_month, dob_day)
                    except ValueError:
                        dob_is_invalid = True
                        st.error("Please select a valid date of birth.")

            bio = st.text_area("About you", value=profile.get("bio", ""), height=105, placeholder="A short introduction (optional)")
            save_profile = st.form_submit_button("Save changes", type="primary", use_container_width=True)

        if save_profile:
            try:
                if any(dob_parts_selected) and not all(dob_parts_selected):
                    raise ValueError("Please select day, month and year, or leave all three blank.")
                if dob_is_invalid:
                    raise ValueError("Please select a valid date of birth.")
                save_user_profile(
                    st.session_state.authenticated_user["id"],
                    " ".join(part for part in (first_name, middle_name, last_name) if part),
                    email,
                    bio,
                    theme=profile.get("theme", "Light"),
                    compact=bool(profile.get("compact", False)),
                    email_updates=bool(profile.get("email_updates", True)),
                    investigation_updates=bool(profile.get("investigation_updates", False)),
                    first_name=first_name,
                    middle_name=middle_name,
                    last_name=last_name,
                    phone=phone,
                    date_of_birth=dob.isoformat() if dob else "",
                )
                st.success("Your profile has been updated.")
                st.rerun()
            except (ValueError, OSError) as error:
                st.error(str(error))

    st.markdown("#### Account information")
    info1, info2 = st.columns(2)
    info1.metric("Username", username)
    info2.metric("Account ID", str(st.session_state.authenticated_user["id"]))
    st.caption("Your login username cannot be changed from this page. Your password is never displayed.")

# SETTINGS
# -----------------------------------------------------------------------------
elif page == "Settings":
    profile = get_user_profile(st.session_state.authenticated_user["id"])
    st.markdown('<div class="section-label">MY ACCOUNT / PREFERENCES</div>', unsafe_allow_html=True)
    st.title("Settings")
    st.caption("Control your workspace experience and account preferences.")
    with st.container(border=True):
        st.subheader("Appearance")
        theme = st.selectbox("Workspace theme", ["Light", "Dark"], index=0 if profile.get("theme","Light")=="Light" else 1)
        compact = st.toggle("Compact layout", value=bool(profile.get("compact", False)))
    with st.container(border=True):
        st.subheader("Notifications")
        email_updates = st.toggle("Product and account updates", value=bool(profile.get("email_updates", True)))
        investigation_updates = st.toggle("Investigation reminders", value=bool(profile.get("investigation_updates", False)))
    with st.container(border=True):
        st.subheader("Security & access")
        st.info("Passwords are protected using PBKDF2-HMAC-SHA256. Never share your password.")
        st.write("Signed in as **"+st.session_state.authenticated_user["username"]+"**")
    if st.button("Save settings", type="primary"):
        save_user_profile(st.session_state.authenticated_user["id"], profile.get("display_name",""), profile.get("email",""), profile.get("bio",""), theme=theme, compact=compact, email_updates=email_updates, investigation_updates=investigation_updates)
        st.success("Settings saved.")
        st.rerun()


# -----------------------------------------------------------------------------
# ABOUT PROJECT
# -----------------------------------------------------------------------------
elif page == "About":
    st.markdown(
        '<div class="section-label">Project information</div>',
        unsafe_allow_html=True,
    )
    st.title("About TruthLens AI")
    st.markdown(
        """
        TruthLens AI is a student-built digital content investigation prototype.
        It combines document extraction, OCR, candidate claim extraction, evidence
        collection, lexical overlap analysis and basic image-forensics indicators.

        **Current capabilities**
        - Multi-format document and image upload
        - Hindi/English OCR through the existing extraction module
        - Editable extracted text and candidate claim extraction
        - Search links and manual evidence collection
        - Evidence relationship summaries and lexical similarity
        - Basic source domain category and HTTPS indicators
        - Image metadata, edge indicators, ELA and an experimental image classifier

        **Important limitations**
        - Candidate claims are not automatically verified.
        - Evidence relationships are selected by the user.
        - Lexical similarity measures word overlap, not meaning or truth.
        - Domain categories and HTTPS are basic indicators, not source trust scores.
        - Image classifiers and ELA can produce false positives and false negatives.
        - No result should be treated as a definitive authenticity verdict.
        """
    )


st.markdown(
    '<div class="footer-note">TruthLens AI · Research workspace · Evidence requires independent human review</div>',
    unsafe_allow_html=True,
)
