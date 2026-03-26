import os
import json
import logging

import psycopg2
import psycopg2.extras

_log = logging.getLogger("vls_db")

_DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_conn():
    if not _DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(_DATABASE_URL)


def init_db():
    if not _DATABASE_URL:
        _log.warning("DATABASE_URL not set — falling back to JSON file storage")
        return

    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username      TEXT    PRIMARY KEY,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL DEFAULT 'member',
                tags          JSONB   NOT NULL DEFAULT '[]',
                joined        TEXT    NOT NULL DEFAULT '',
                passkey_used  TEXT    NOT NULL DEFAULT '',
                email         TEXT    NOT NULL DEFAULT '',
                email_updates BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS passkeys (
                code           TEXT    PRIMARY KEY,
                uses_remaining INT     NOT NULL,
                max_uses       INT     NOT NULL,
                tag            TEXT    NOT NULL DEFAULT '',
                created        TEXT    NOT NULL DEFAULT '',
                used_by        JSONB   NOT NULL DEFAULT '[]'
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS session_tokens (
                token      TEXT    PRIMARY KEY,
                username   TEXT    NOT NULL,
                expires_at TEXT    NOT NULL
            )
        """)

        conn.commit()

        _migrate_users(cur, conn)
        _migrate_passkeys(cur, conn)

        cur.close()
        conn.close()
        _log.info("Database initialised successfully")
    except Exception as exc:
        _log.error(f"init_db failed: {exc}")


def _migrate_users(cur, conn):
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] > 0:
        return

    json_path = "users.json"
    if not os.path.exists(json_path):
        return

    try:
        with open(json_path) as f:
            users = json.load(f)

        count = 0
        for uname, data in users.items():
            cur.execute("""
                INSERT INTO users (username, password_hash, role, tags, joined, passkey_used, email, email_updates)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (username) DO NOTHING
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
            count += 1

        conn.commit()
        _log.info(f"Migrated {count} users from users.json")
    except Exception as exc:
        _log.error(f"User migration failed: {exc}")


def _migrate_passkeys(cur, conn):
    cur.execute("SELECT COUNT(*) FROM passkeys")
    if cur.fetchone()[0] > 0:
        return

    json_path = "passkeys.json"
    if not os.path.exists(json_path):
        return

    try:
        with open(json_path) as f:
            passkeys = json.load(f)

        count = 0
        for code, data in passkeys.items():
            cur.execute("""
                INSERT INTO passkeys (code, uses_remaining, max_uses, tag, created, used_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (code) DO NOTHING
            """, (
                code,
                data.get("uses_remaining", 0),
                data.get("max_uses", 0),
                data.get("tag", ""),
                data.get("created", ""),
                json.dumps(data.get("used_by", [])),
            ))
            count += 1

        conn.commit()
        _log.info(f"Migrated {count} passkeys from passkeys.json")
    except Exception as exc:
        _log.error(f"Passkey migration failed: {exc}")
