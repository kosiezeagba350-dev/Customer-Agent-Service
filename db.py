"""SQLite storage for many businesses. Swap for Postgres when you outgrow it."""
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
# On Render, set DB_PATH to a persistent disk, e.g. /var/data/agent.db
DB_PATH = Path(os.getenv("DB_PATH") or Path(__file__).parent / "agent.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
NUMBER_FIELDS = {"twilio_number", "whatsapp_number"}
BILLING_FIELDS = {"plan", "status", "stripe_customer_id", "stripe_subscription_id", "limit_override"}
NEW_COLS = {
    "owner_email": "TEXT",
    "password_hash": "TEXT",
    "plan": "TEXT DEFAULT 'trial'",
    "status": "TEXT DEFAULT 'trial'",
    "stripe_customer_id": "TEXT",
    "stripe_subscription_id": "TEXT",
    "limit_override": "INTEGER",
    "created_at": "INTEGER",
    "email_verified": "INTEGER DEFAULT 1",
    "terms_accepted_at": "INTEGER",
}
_ready = False


def _conn():
    global _ready
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute(
        "CREATE TABLE IF NOT EXISTS businesses (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "knowledge TEXT NOT NULL, allowed_origins TEXT NOT NULL DEFAULT '[]', "
        "twilio_number TEXT, whatsapp_number TEXT, human_phone TEXT)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY, business_id TEXT NOT NULL, "
        "name TEXT, contact TEXT, service TEXT, date TEXT NOT NULL, hour INTEGER NOT NULL, "
        "UNIQUE(business_id, date, hour))"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS usage (business_id TEXT NOT NULL, month TEXT NOT NULL, "
        "messages INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER NOT NULL DEFAULT 0, "
        "output_tokens INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (business_id, month))"
    )
    if not _ready:
        have = {r["name"] for r in c.execute("PRAGMA table_info(businesses)")}
        for col, typ in NEW_COLS.items():
            if col not in have:
                c.execute(f"ALTER TABLE businesses ADD COLUMN {col} {typ}")
        c.execute("UPDATE businesses SET created_at=? WHERE created_at IS NULL", (int(time.time()),))
        c.execute("UPDATE businesses SET plan='trial' WHERE plan IS NULL")
        c.execute("UPDATE businesses SET status='trial' WHERE status IS NULL")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_owner_email ON businesses(owner_email)")
        c.commit()
        _ready = True
    return c


def q(sql, args=(), commit=False):
    c = _conn()
    try:
        rows = c.execute(sql, args).fetchall()
        if commit:
            c.commit()
        return rows
    finally:
        c.close()


def norm_number(n):
    if not n:
        return None
    n = n.replace("whatsapp:", "")
    return re.sub(r"[^\d+]", "", n) or None


def month_key():
    return time.strftime("%Y-%m", time.gmtime())


def _biz(row):
    if not row:
        return None
    d = dict(row)
    d["knowledge"] = json.loads(d["knowledge"])
    d["allowed_origins"] = json.loads(d["allowed_origins"])
    return d


# ---------- businesses ----------
def upsert_business(b):
    q(
        "INSERT INTO businesses (id, name, knowledge, allowed_origins, twilio_number, whatsapp_number, "
        "human_phone, created_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
        "knowledge=excluded.knowledge, allowed_origins=excluded.allowed_origins, "
        "twilio_number=excluded.twilio_number, whatsapp_number=excluded.whatsapp_number, "
        "human_phone=excluded.human_phone",
        (
            b["id"], b["name"], json.dumps(b["knowledge"]), json.dumps(b.get("allowed_origins", [])),
            norm_number(b.get("twilio_number")), norm_number(b.get("whatsapp_number")),
            norm_number(b.get("human_phone")), int(time.time()),
        ),
        commit=True,
    )


def update_profile(biz_id, knowledge, allowed_origins, human_phone):
    q(
        "UPDATE businesses SET knowledge=?, allowed_origins=?, human_phone=? WHERE id=?",
        (json.dumps(knowledge), json.dumps(allowed_origins), norm_number(human_phone), biz_id),
        commit=True,
    )


def get_business(biz_id):
    rows = q("SELECT * FROM businesses WHERE id=?", (biz_id or "",))
    return _biz(rows[0]) if rows else None


def get_by_email(email):
    rows = q("SELECT * FROM businesses WHERE owner_email=?", ((email or "").strip().lower(),))
    return _biz(rows[0]) if rows else None


def find_by_number(field, number):
    if field not in NUMBER_FIELDS or not norm_number(number):
        return None
    rows = q(f"SELECT * FROM businesses WHERE {field}=?", (norm_number(number),))
    return _biz(rows[0]) if rows else None


def find_by_stripe(field, value):
    if field not in {"stripe_customer_id", "stripe_subscription_id"} or not value:
        return None
    rows = q(f"SELECT * FROM businesses WHERE {field}=?", (value,))
    return _biz(rows[0]) if rows else None


def list_businesses():
    return [r["id"] for r in q("SELECT id FROM businesses ORDER BY id")]


# ---------- owner login ----------
def set_owner(biz_id, email, password_hash):
    q("UPDATE businesses SET owner_email=?, password_hash=? WHERE id=?",
      (email.strip().lower(), password_hash, biz_id), commit=True)


def set_verified(biz_id, flag):
    q("UPDATE businesses SET email_verified=? WHERE id=?", (1 if flag else 0, biz_id), commit=True)


def set_terms_accepted(biz_id):
    q("UPDATE businesses SET terms_accepted_at=? WHERE id=?", (int(time.time()), biz_id), commit=True)


def set_password(biz_id, password_hash):
    q("UPDATE businesses SET password_hash=? WHERE id=?", (password_hash, biz_id), commit=True)


# ---------- billing ----------
def update_billing(biz_id, fields: dict):
    fields = {k: v for k, v in fields.items() if k in BILLING_FIELDS}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    q(f"UPDATE businesses SET {sets} WHERE id=?", (*fields.values(), biz_id), commit=True)


# ---------- usage ----------
def add_usage(biz_id, messages=0, input_tokens=0, output_tokens=0):
    q(
        "INSERT INTO usage (business_id, month, messages, input_tokens, output_tokens) VALUES (?,?,?,?,?) "
        "ON CONFLICT(business_id, month) DO UPDATE SET messages=messages+excluded.messages, "
        "input_tokens=input_tokens+excluded.input_tokens, output_tokens=output_tokens+excluded.output_tokens",
        (biz_id, month_key(), messages, input_tokens, output_tokens),
        commit=True,
    )


def get_usage(biz_id, month=None):
    rows = q("SELECT messages, input_tokens, output_tokens FROM usage WHERE business_id=? AND month=?",
             (biz_id, month or month_key()))
    return dict(rows[0]) if rows else {"messages": 0, "input_tokens": 0, "output_tokens": 0}


def all_usage(month=None):
    rows = q("SELECT business_id, messages, input_tokens, output_tokens FROM usage WHERE month=?",
             (month or month_key(),))
    return {r["business_id"]: dict(r) for r in rows}
