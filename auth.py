import streamlit as st
import os
import hashlib
import hmac
import json
import datetime
import logging
import secrets as _secrets

_log = logging.getLogger("vls_auth")

ADMIN_USERNAME = "admin"
USERS_FILE = "users.json"
PASSKEYS_FILE = "passkeys.json"
SESSION_TOKENS_FILE = "session_tokens.json"
_COOKIE_NAME = "vls_session"
_COOKIE_MANAGER_KEY = "vls_cookie_mgr_v1"

# ─────────────────────────────────────────────
# DATABASE HELPER  (falls back to JSON if DB unavailable)
# ─────────────────────────────────────────────
def _db_available():
    return bool(os.environ.get("DATABASE_URL", ""))

def _get_conn():
    import db as _db
    return _db.get_conn()

# ─────────────────────────────────────────────
# ADMIN PASSWORD
# ─────────────────────────────────────────────
def get_admin_password():
    pw = os.getenv("ADMIN_PASSWORD")
    if pw:
        return pw
    try:
        return st.secrets["ADMIN_PASSWORD"]
    except Exception:
        return None

# ─────────────────────────────────────────────
# PASSWORD HASHING
# ─────────────────────────────────────────────
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ─────────────────────────────────────────────
# USER MANAGEMENT  — PostgreSQL-backed
# ─────────────────────────────────────────────

def _row_to_user(row):
    """Convert a DB row tuple (username, password_hash, role, tags, joined,
    passkey_used, email, email_updates) to the dict format the rest of the
    app expects."""
    username, pw_hash, role, tags, joined, passkey_used, email, email_updates = row
    return {
        "password_hash": pw_hash,
        "role": role,
        "tags": tags if isinstance(tags, list) else json.loads(tags or "[]"),
        "joined": joined,
        "passkey_used": passkey_used,
        "email": email,
        "email_updates": bool(email_updates),
    }


def load_users():
    if not _db_available():
        return _load_users_json()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT username, password_hash, role, tags, joined, passkey_used, email, email_updates
            FROM users
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {row[0]: _row_to_user(row) for row in rows}
    except Exception as exc:
        _log.error(f"load_users DB error: {exc}")
        return _load_users_json()


def _load_users_json():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def email_exists(email: str) -> bool:
    """Return True if any existing user already has this email address."""
    needle = email.strip().lower()
    if not needle:
        return False
    users = load_users()
    for data in users.values():
        if data.get("email", "").strip().lower() == needle:
            return True
    return False


def _email_to_username(email: str):
    """Return the username for a given email, or None if not found."""
    needle = email.strip().lower()
    if not needle:
        return None
    users = load_users()
    for uname, data in users.items():
        if data.get("email", "").strip().lower() == needle:
            return uname
    return None


def save_users(users):
    """Bulk-upsert — kept for compatibility.  Direct per-user functions
    are preferred for individual operations."""
    if not _db_available():
        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=2)
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        for uname, data in users.items():
            cur.execute("""
                INSERT INTO users (username, password_hash, role, tags, joined, passkey_used, email, email_updates)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (username) DO UPDATE SET
                    password_hash = EXCLUDED.password_hash,
                    role          = EXCLUDED.role,
                    tags          = EXCLUDED.tags,
                    joined        = EXCLUDED.joined,
                    passkey_used  = EXCLUDED.passkey_used,
                    email         = EXCLUDED.email,
                    email_updates = EXCLUDED.email_updates
            """, (
                uname,
                data.get("password_hash", ""),
                data.get("role", "member"),
                json.dumps(data.get("tags", [])),
                data.get("joined", ""),
                data.get("passkey_used", ""),
                data.get("email", ""),
                bool(data.get("email_updates", False)),
            ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        _log.error(f"save_users DB error: {exc}")


def add_user(username, password, tags=None, passkey_used=None, email="", email_updates=False):
    """Returns True on success, False on failure."""
    uname = username.lower().strip()
    if not _db_available():
        try:
            users = _load_users_json()
            users[uname] = {
                "password_hash": hash_password(password),
                "role": "member",
                "tags": tags or [],
                "joined": datetime.date.today().isoformat(),
                "passkey_used": passkey_used or "",
                "email": email.strip().lower(),
                "email_updates": email_updates,
            }
            with open(USERS_FILE, "w") as f:
                json.dump(users, f, indent=2)
            return True
        except Exception as exc:
            _log.error(f"add_user JSON error: {exc}")
            return False
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (username, password_hash, role, tags, joined, passkey_used, email, email_updates)
            VALUES (%s, %s, 'member', %s, %s, %s, %s, %s)
            ON CONFLICT (username) DO NOTHING
        """, (
            uname,
            hash_password(password),
            json.dumps(tags or []),
            datetime.date.today().isoformat(),
            passkey_used or "",
            email.strip().lower(),
            bool(email_updates),
        ))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as exc:
        _log.error(f"add_user DB error: {exc}")
        return False


def remove_user(username):
    uname = username.lower().strip()
    if not _db_available():
        users = _load_users_json()
        users.pop(uname, None)
        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=2)
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE username = %s", (uname,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        _log.error(f"remove_user DB error: {exc}")


def update_user_tags(username, tags):
    uname = username.lower().strip()
    if not _db_available():
        users = _load_users_json()
        if uname in users:
            users[uname]["tags"] = tags
            with open(USERS_FILE, "w") as f:
                json.dump(users, f, indent=2)
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE users SET tags = %s WHERE username = %s",
                    (json.dumps(tags), uname))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        _log.error(f"update_user_tags DB error: {exc}")


def update_user(username, fields: dict):
    """Update arbitrary fields on a user record."""
    uname = username.lower().strip()
    if not _db_available():
        users = _load_users_json()
        if uname in users:
            for k, v in fields.items():
                users[uname][k] = v
            with open(USERS_FILE, "w") as f:
                json.dump(users, f, indent=2)
        return
    if not fields:
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        allowed = {"password_hash", "role", "tags", "joined", "passkey_used", "email", "email_updates"}
        set_parts = []
        values = []
        for k, v in fields.items():
            if k not in allowed:
                continue
            set_parts.append(f"{k} = %s")
            values.append(json.dumps(v) if k == "tags" else v)
        if set_parts:
            values.append(uname)
            cur.execute(f"UPDATE users SET {', '.join(set_parts)} WHERE username = %s", values)
            conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        _log.error(f"update_user DB error: {exc}")


def get_all_users():
    return load_users()


def check_password(identifier, password):
    """Returns (valid: bool, role: str).  role is 'admin' | 'dfs' | 'member'.
    identifier may be a username OR an email address."""
    raw = identifier.strip()
    uname = raw.lower()

    # Resolve email → username if identifier looks like an email
    if "@" in raw:
        resolved = _email_to_username(raw)
        if resolved:
            uname = resolved
        else:
            return False, "member"

    admin_pw = get_admin_password()
    if uname == ADMIN_USERNAME and admin_pw:
        if hmac.compare_digest(password, admin_pw):
            return True, "admin"
        return False, "member"
    users = load_users()
    if uname in users:
        stored_hash = users[uname].get("password_hash", "")
        if hmac.compare_digest(hash_password(password), stored_hash):
            role = users[uname].get("role", "member")
            return True, role
    return False, "member"


def resolve_identifier_to_username(identifier: str) -> str:
    """Return the canonical username for a username or email identifier."""
    raw = identifier.strip()
    if "@" in raw:
        resolved = _email_to_username(raw)
        return resolved or raw.lower()
    return raw.lower()

# ─────────────────────────────────────────────
# PASSKEY MANAGEMENT  — PostgreSQL-backed
# ─────────────────────────────────────────────

def _row_to_passkey(row):
    code, uses_remaining, max_uses, tag, created, used_by = row
    return {
        "uses_remaining": uses_remaining,
        "max_uses": max_uses,
        "tag": tag,
        "created": created,
        "used_by": used_by if isinstance(used_by, list) else json.loads(used_by or "[]"),
    }


def load_passkeys():
    if not _db_available():
        return _load_passkeys_json()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT code, uses_remaining, max_uses, tag, created, used_by FROM passkeys")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {row[0]: _row_to_passkey(row) for row in rows}
    except Exception as exc:
        _log.error(f"load_passkeys DB error: {exc}")
        return _load_passkeys_json()


def _load_passkeys_json():
    if not os.path.exists(PASSKEYS_FILE):
        return {}
    try:
        with open(PASSKEYS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_passkeys(passkeys):
    """Bulk-upsert — kept for compatibility."""
    if not _db_available():
        with open(PASSKEYS_FILE, "w") as f:
            json.dump(passkeys, f, indent=2)
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        for code, data in passkeys.items():
            cur.execute("""
                INSERT INTO passkeys (code, uses_remaining, max_uses, tag, created, used_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    uses_remaining = EXCLUDED.uses_remaining,
                    max_uses       = EXCLUDED.max_uses,
                    tag            = EXCLUDED.tag,
                    created        = EXCLUDED.created,
                    used_by        = EXCLUDED.used_by
            """, (
                code,
                data.get("uses_remaining", 0),
                data.get("max_uses", 0),
                data.get("tag", ""),
                data.get("created", ""),
                json.dumps(data.get("used_by", [])),
            ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        _log.error(f"save_passkeys DB error: {exc}")


def create_passkey(code, max_uses, tag):
    code = code.upper().strip()
    if not _db_available():
        passkeys = _load_passkeys_json()
        passkeys[code] = {
            "uses_remaining": max_uses,
            "max_uses": max_uses,
            "tag": tag.lower().strip(),
            "created": datetime.date.today().isoformat(),
            "used_by": [],
        }
        with open(PASSKEYS_FILE, "w") as f:
            json.dump(passkeys, f, indent=2)
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO passkeys (code, uses_remaining, max_uses, tag, created, used_by)
            VALUES (%s, %s, %s, %s, %s, '[]')
            ON CONFLICT (code) DO UPDATE SET
                uses_remaining = EXCLUDED.uses_remaining,
                max_uses       = EXCLUDED.max_uses,
                tag            = EXCLUDED.tag,
                created        = EXCLUDED.created
        """, (
            code,
            max_uses,
            max_uses,
            tag.lower().strip(),
            datetime.date.today().isoformat(),
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        _log.error(f"create_passkey DB error: {exc}")


def delete_passkey(code):
    code = code.upper().strip()
    if not _db_available():
        passkeys = _load_passkeys_json()
        passkeys.pop(code, None)
        with open(PASSKEYS_FILE, "w") as f:
            json.dump(passkeys, f, indent=2)
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM passkeys WHERE code = %s", (code,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        _log.error(f"delete_passkey DB error: {exc}")


def validate_passkey(code):
    """Returns (valid: bool, tag: str, error_msg: str)"""
    code = code.upper().strip()
    if not code:
        return False, "", "Please enter a passkey."
    if not _db_available():
        passkeys = _load_passkeys_json()
        if code not in passkeys:
            return False, "", "Invalid passkey. Please check the code and try again."
        pk = passkeys[code]
        if pk["uses_remaining"] <= 0:
            return False, "", "This passkey has reached its maximum uses."
        return True, pk.get("tag", ""), ""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT uses_remaining, tag FROM passkeys WHERE code = %s", (code,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None:
            return False, "", "Invalid passkey. Please check the code and try again."
        uses_remaining, tag = row
        if uses_remaining <= 0:
            return False, "", "This passkey has reached its maximum uses."
        return True, tag or "", ""
    except Exception as exc:
        _log.error(f"validate_passkey DB error: {exc}")
        return False, "", "Error checking passkey. Please try again."


def consume_passkey(code, username):
    code = code.upper().strip()
    if not _db_available():
        passkeys = _load_passkeys_json()
        if code in passkeys:
            passkeys[code]["uses_remaining"] = max(0, passkeys[code]["uses_remaining"] - 1)
            if username not in passkeys[code]["used_by"]:
                passkeys[code]["used_by"].append(username)
            with open(PASSKEYS_FILE, "w") as f:
                json.dump(passkeys, f, indent=2)
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE passkeys
            SET uses_remaining = GREATEST(0, uses_remaining - 1),
                used_by = CASE
                    WHEN used_by @> %s::jsonb THEN used_by
                    ELSE used_by || %s::jsonb
                END
            WHERE code = %s
        """, (
            json.dumps([username]),
            json.dumps([username]),
            code,
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        _log.error(f"consume_passkey DB error: {exc}")

# ─────────────────────────────────────────────
# SESSION TOKEN MANAGEMENT  (Remember Me)
# ─────────────────────────────────────────────

def _load_session_tokens_json() -> dict:
    if not os.path.exists(SESSION_TOKENS_FILE):
        return {}
    try:
        with open(SESSION_TOKENS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def generate_session_token() -> str:
    return _secrets.token_hex(32)


def store_session_token(token: str, username: str) -> None:
    expires = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat()
    if not _db_available():
        tokens = _load_session_tokens_json()
        tokens[token] = {"username": username, "expires_at": expires}
        try:
            with open(SESSION_TOKENS_FILE, "w") as f:
                json.dump(tokens, f, indent=2)
        except Exception as exc:
            _log.error(f"store_session_token JSON error: {exc}")
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO session_tokens (token, username, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (token) DO UPDATE SET expires_at = EXCLUDED.expires_at
        """, (token, username, expires))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        _log.error(f"store_session_token DB error: {exc}")


def validate_session_token(token: str):
    """Return username if token is valid + unexpired, else None."""
    if not token:
        return None
    now = datetime.datetime.utcnow().isoformat()
    if not _db_available():
        tokens = _load_session_tokens_json()
        entry = tokens.get(token)
        if entry and now < entry.get("expires_at", ""):
            return entry.get("username")
        return None
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT username, expires_at FROM session_tokens WHERE token = %s", (token,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None:
            return None
        username, expires_at = row
        if now < expires_at:
            return username
        return None
    except Exception as exc:
        _log.error(f"validate_session_token DB error: {exc}")
        return None


def delete_session_token(token: str) -> None:
    if not token:
        return
    if not _db_available():
        tokens = _load_session_tokens_json()
        tokens.pop(token, None)
        try:
            with open(SESSION_TOKENS_FILE, "w") as f:
                json.dump(tokens, f, indent=2)
        except Exception:
            pass
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM session_tokens WHERE token = %s", (token,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        _log.error(f"delete_session_token DB error: {exc}")


def _get_cookie_manager():
    """Return a CookieManager instance, or None if unavailable."""
    try:
        import extra_streamlit_components as stx
        return stx.CookieManager(key=_COOKIE_MANAGER_KEY)
    except Exception:
        return None


def check_remember_me() -> bool:
    """Try to auto-authenticate from a Remember Me browser cookie.
    Call this once per page load, before the is_logged_in() check.

    The CookieManager (extra-streamlit-components) renders an iframe that
    delivers cookie values asynchronously. On the very first render the value
    may not be available yet, in which case we leave _rm_done unset so that
    the next Streamlit rerun (triggered naturally by the component) will try
    again.  We only set _rm_done=True once we have received a definitive
    answer (token found+valid, token found+invalid, or cookie absent).
    """
    if st.session_state.get("authenticated"):
        return False
    if st.session_state.get("_rm_done"):
        return False
    try:
        cm = _get_cookie_manager()
        if cm is None:
            st.session_state._rm_done = True
            return False
        token = cm.get(_COOKIE_NAME)
        if token is None:
            # Cookie manager may not have loaded yet — leave _rm_done unset
            # so the next rerun triggered by the component can try again.
            # But only retry once (guard with _rm_retried flag).
            if st.session_state.get("_rm_retried"):
                st.session_state._rm_done = True
            else:
                st.session_state._rm_retried = True
            return False
        # We have a definitive value — mark done regardless of outcome
        st.session_state._rm_done = True
        if not token:
            return False
        username = validate_session_token(token)
        if not username:
            try:
                cm.delete(_COOKIE_NAME)
            except Exception:
                pass
            return False
        users = load_users()
        if username not in users:
            return False
        role = users[username].get("role", "member")
        st.session_state.authenticated = True
        st.session_state.user_role = role
        st.session_state.is_admin = (role == "admin")
        st.session_state.username = username
        st.session_state._session_token = token
        _log.info(f"Auto-authenticated '{username}' via Remember Me cookie")
        return True
    except Exception as exc:
        _log.debug(f"check_remember_me: {exc}")
        st.session_state._rm_done = True
        return False


def _set_remember_me_cookie(token: str) -> None:
    """Write the session token cookie in the browser (30-day expiry)."""
    try:
        cm = _get_cookie_manager()
        if cm is None:
            return
        expires = datetime.datetime.now() + datetime.timedelta(days=30)
        cm.set(_COOKIE_NAME, token, expires_at=expires)
    except Exception as exc:
        _log.debug(f"_set_remember_me_cookie: {exc}")


def _clear_remember_me_cookie() -> None:
    """Delete the session cookie from the browser."""
    try:
        cm = _get_cookie_manager()
        if cm is None:
            return
        cm.delete(_COOKIE_NAME)
    except Exception as exc:
        _log.debug(f"_clear_remember_me_cookie: {exc}")


# ─────────────────────────────────────────────
# SESSION HELPERS
# ─────────────────────────────────────────────
def is_logged_in():
    return st.session_state.get("authenticated", False)

def is_admin():
    return st.session_state.get("user_role", "member") == "admin"

def is_dfs():
    """True for both 'admin' and 'dfs' roles — grants DFS Optimizer access."""
    return st.session_state.get("user_role", "member") in ("admin", "dfs")

def get_username():
    return st.session_state.get("username", "")

def logout():
    token = st.session_state.get("_session_token")
    if token:
        delete_session_token(token)
    _clear_remember_me_cookie()
    for key in ["authenticated", "is_admin", "user_role", "username", "_session_token",
                "_rm_done", "_rm_retried"]:
        st.session_state.pop(key, None)

# ─────────────────────────────────────────────
# LOGIN / SIGNUP PAGE
# ─────────────────────────────────────────────
def render_login_page():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background: linear-gradient(135deg, #0a0a0f 0%, #0f0a1a 40%, #0a0f0a 100%); min-height: 100vh; }
    [data-testid="stAppViewContainer"] { background: transparent; }

    .stTextInput > div > div > input {
        background: rgba(255,255,255,0.05) !important;
        border: 1px solid rgba(212,175,55,0.25) !important;
        border-radius: 8px !important;
        color: #ffffff !important;
        padding: 12px 16px !important;
        font-size: 14px !important;
    }
    .stTextInput > div > div > input:focus {
        border-color: rgba(212,175,55,0.6) !important;
        box-shadow: 0 0 0 2px rgba(212,175,55,0.1) !important;
    }
    .stTextInput > label {
        color: rgba(255,255,255,0.55) !important;
        font-size: 11px !important;
        font-weight: 600 !important;
        letter-spacing: 1.2px !important;
        text-transform: uppercase !important;
    }
    div[data-testid="stForm"] .stButton > button {
        width: 100% !important;
        background: linear-gradient(135deg, #D4AF37 0%, #9B59B6 100%) !important;
        color: #000000 !important;
        font-weight: 700 !important;
        font-size: 14px !important;
        letter-spacing: 1.5px !important;
        text-transform: uppercase !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 14px !important;
        margin-top: 8px !important;
        box-shadow: 0 4px 20px rgba(212,175,55,0.25) !important;
    }
    div[data-testid="stForm"] .stButton > button:hover {
        opacity: 0.9 !important;
        box-shadow: 0 6px 30px rgba(212,175,55,0.4) !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        background: rgba(255,255,255,0.03) !important;
        border-radius: 10px !important;
        border: 1px solid rgba(212,175,55,0.1) !important;
        padding: 4px !important;
        margin-bottom: 20px !important;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 7px !important;
        color: rgba(255,255,255,0.5) !important;
        font-size: 13px !important;
        font-weight: 600 !important;
        padding: 8px 16px !important;
        border-bottom: none !important;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, rgba(212,175,55,0.15), rgba(155,89,182,0.15)) !important;
        color: #D4AF37 !important;
        border-bottom: none !important;
    }
    #MainMenu, footer, header { visibility: hidden; }
    [data-testid="stToolbar"] { display: none; }

    /* ── Client-side loading overlay ── */
    @keyframes vls-progress {
        0%   { width: 0%; }
        60%  { width: 75%; }
        100% { width: 100%; }
    }
    @keyframes vls-pulse {
        0%, 100% { opacity: 0.4; }
        50%       { opacity: 1; }
    }
    @keyframes vls-fadein {
        from { opacity: 0; }
        to   { opacity: 1; }
    }
    #vls-login-overlay {
        display: none;
        position: fixed; inset: 0;
        background: #080810;
        z-index: 99999;
        align-items: center; justify-content: center;
        animation: vls-fadein 0.2s ease forwards;
    }
    #vls-login-overlay.active { display: flex; }
    .vls-ov-inner { text-align: center; width: 320px; }
    .vls-ov-logo {
        font-size: 38px; font-weight: 900;
        background: linear-gradient(135deg, #D4AF37, #9B59B6);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        letter-spacing: 1px; margin-bottom: 6px;
    }
    .vls-ov-sub {
        font-size: 11px; letter-spacing: 3.5px; text-transform: uppercase;
        color: rgba(255,255,255,0.25); margin-bottom: 36px;
    }
    .vls-ov-track {
        height: 3px; background: rgba(255,255,255,0.07);
        border-radius: 99px; overflow: hidden; margin-bottom: 18px;
    }
    .vls-ov-fill {
        height: 100%;
        background: linear-gradient(90deg, #D4AF37, #9B59B6);
        border-radius: 99px;
        animation: vls-progress 2.5s cubic-bezier(0.4,0,0.2,1) forwards;
    }
    .vls-ov-status {
        font-size: 12px; color: rgba(255,255,255,0.35);
        letter-spacing: 0.5px;
        animation: vls-pulse 1.4s ease-in-out infinite;
    }
    </style>

    <!-- Fullscreen overlay — shown client-side on button click -->
    <div id="vls-login-overlay">
        <div class="vls-ov-inner">
            <div class="vls-ov-logo">VLS 3000</div>
            <div class="vls-ov-sub">The Syndicate Suite</div>
            <div class="vls-ov-track"><div class="vls-ov-fill"></div></div>
            <div class="vls-ov-status">Initializing models&hellip;</div>
        </div>
    </div>

    <script>
    (function() {
        var _obs;
        function attachOverlay() {
            // Stop the observer loop the moment we leave the login page
            if (!document.getElementById('vls-login-overlay')) {
                if (_obs) { _obs.disconnect(); }
                return;
            }
            var btns = document.querySelectorAll('[data-testid="stFormSubmitButton"] button');
            if (!btns.length) {
                setTimeout(attachOverlay, 150);
                return;
            }
            btns.forEach(function(btn) {
                if (btn._vlsOverlayBound) return;
                // Only attach to the login submit button, not the signup button
                var label = (btn.textContent || btn.innerText || '').trim().toUpperCase();
                if (label !== 'ACCESS THE SUITE') return;
                btn._vlsOverlayBound = true;
                btn.addEventListener('click', function() {
                    var ov = document.getElementById('vls-login-overlay');
                    if (ov) {
                        ov.classList.add('active');
                        setTimeout(function() { ov.classList.remove('active'); }, 2500);
                    }
                });
            });
        }
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', attachOverlay);
        } else {
            attachOverlay();
        }
        _obs = new MutationObserver(attachOverlay);
        _obs.observe(document.body, { childList: true, subtree: true });
    })();
    </script>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<div style='text-align:center;margin-bottom:4px'><img src='/app/static/vls_logo.png' style='width:80px;height:80px;border-radius:50%;object-fit:cover;'></div>", unsafe_allow_html=True)
        st.markdown("<div style='text-align:center;font-size:32px;font-weight:900;background:linear-gradient(135deg,#D4AF37,#9B59B6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px'>VLS 3000</div>", unsafe_allow_html=True)
        st.markdown("<div style='text-align:center;color:rgba(255,255,255,0.3);font-size:11px;letter-spacing:3px;text-transform:uppercase;margin-bottom:24px'>The Syndicate Suite</div>", unsafe_allow_html=True)

        tab_login, tab_signup = st.tabs(["🔑  Sign In", "🎟️  Create Account"])

        # ── SIGN IN TAB ──
        with tab_login:
            with st.form("login_form"):
                identifier = st.text_input("Username or Email", placeholder="Enter username or email")
                password = st.text_input("Password", type="password", placeholder="Enter password")
                remember_me = st.checkbox("Remember me for 30 days")
                submitted = st.form_submit_button("Access the Suite")
                if submitted:
                    if not identifier or not password:
                        st.error("Please enter your username (or email) and password.")
                    else:
                        valid, role = check_password(identifier, password)
                        if valid:
                            resolved_uname = resolve_identifier_to_username(identifier)
                            st.session_state.authenticated = True
                            st.session_state.user_role = role
                            st.session_state.is_admin = (role == "admin")
                            st.session_state.username = resolved_uname
                            st.session_state.show_loading = True
                            if remember_me:
                                token = generate_session_token()
                                store_session_token(token, resolved_uname)
                                st.session_state._session_token = token
                                _set_remember_me_cookie(token)
                            st.rerun()
                        else:
                            st.error("Invalid credentials. Access denied.")

        # ── CREATE ACCOUNT TAB ──
        with tab_signup:
            st.markdown("<div style='color:rgba(255,255,255,0.45);font-size:12px;margin-bottom:12px'>Enter your passkey to create a member account.</div>", unsafe_allow_html=True)
            with st.form("signup_form"):
                new_user = st.text_input("Choose a Username", placeholder="e.g. johndoe")
                new_email = st.text_input("Email Address", placeholder="e.g. johndoe@email.com")
                new_pass = st.text_input("Choose a Password", type="password", placeholder="Min. 6 characters")
                confirm_pass = st.text_input("Confirm Password", type="password", placeholder="Repeat password")
                passkey_input = st.text_input("Passkey", placeholder="4–6 digit/letter code", max_chars=6)
                email_opt_in = st.checkbox("📬 Email me about important updates, promotions, and launch news (optional)")
                signup_submitted = st.form_submit_button("Create My Account")

                if signup_submitted:
                    uname = new_user.lower().strip()
                    code = passkey_input.upper().strip()
                    err = None

                    if not uname or not new_email or not new_pass or not confirm_pass or not code:
                        err = "All fields are required (email is needed for your account)."
                    elif len(uname) < 3:
                        err = "Username must be at least 3 characters."
                    elif uname == ADMIN_USERNAME:
                        err = "That username is reserved."
                    elif "@" not in new_email or "." not in new_email:
                        err = "Please enter a valid email address."
                    elif len(new_pass) < 6:
                        err = "Password must be at least 6 characters."
                    elif new_pass != confirm_pass:
                        err = "Passwords do not match."
                    else:
                        users = load_users()
                        if uname in users:
                            err = "Username already taken. Please choose another."
                        elif email_exists(new_email):
                            err = "An account already exists with that email address. Try signing in instead."

                    if err:
                        st.error(err)
                    else:
                        valid_pk, tag, pk_err = validate_passkey(code)
                        if not valid_pk:
                            st.error(pk_err)
                        else:
                            tags = [tag] if tag else []
                            ok = add_user(uname, new_pass, tags=tags, passkey_used=code,
                                          email=new_email, email_updates=email_opt_in)
                            if ok:
                                consume_passkey(code, uname)
                                st.session_state.authenticated = True
                                st.session_state.user_role = "member"
                                st.session_state.is_admin = False
                                st.session_state.username = uname
                                st.session_state.show_loading = True
                                st.session_state._rm_done = True
                                st.rerun()
                            else:
                                st.error("Account creation failed — please try again or contact support.")

        st.markdown("<div style='text-align:center;color:rgba(255,255,255,0.15);font-size:11px;margin-top:24px;letter-spacing:1px'>VLS 3000 · Version 0.19.0 · Members Only</div>", unsafe_allow_html=True)
