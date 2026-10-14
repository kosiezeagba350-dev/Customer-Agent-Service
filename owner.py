"""Owner dashboard API: signup, login, email verification, password reset, usage, bookings, business info, billing."""
import json
import math
import os
import re
import secrets
import sqlite3
import time
from datetime import date, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

import auth
import billing
import db
from email_utils import send_email
from usage import access_state
from util import client_ip, rate_limit

router = APIRouter(prefix="/owner")
ORIGIN_RE = re.compile(r"^https?://[^/\s]+$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _base(request: Request) -> str:
    return (os.getenv("PUBLIC_BASE_URL") or str(request.base_url)).rstrip("/")


def _set_session(response: Response, request: Request, biz_id: str):
    response.set_cookie(
        auth.COOKIE, auth.make_token(biz_id), httponly=True, samesite="lax",
        secure=os.getenv("COOKIE_SECURE", "1") == "1", max_age=auth.MAX_AGE, path="/",
    )


def current_biz(request: Request):
    r = auth.read_token(request.cookies.get(auth.COOKIE, ""), "session")
    biz = db.get_business(r[0]) if r else None
    if not biz:
        raise HTTPException(401, "Not signed in")
    return biz


@router.get("/config")
def config():
    return {
        "signup_enabled": os.getenv("SIGNUP_ENABLED", "1") == "1",
        "terms_url": os.getenv("TERMS_URL", ""),
        "privacy_url": os.getenv("PRIVACY_URL", ""),
    }


# ---------- Signup, email verification, password reset ----------
def _verification_email(request: Request, biz: dict, email: str):
    token = auth.make_token(biz["id"], "verify", 3 * 86400)
    link = f"{_base(request)}/owner/verify?token={token}"
    send_email(
        email, "Confirm your email",
        f"Hi,\n\nConfirm your email to turn on the assistant for {biz['name']}:\n{link}\n\n"
        "This link expires in 3 days. If you didn't sign up, you can ignore this email.",
    )


def _new_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "business"
    while True:
        biz_id = f"{slug}-{secrets.token_hex(2)}"
        if not db.get_business(biz_id):
            return biz_id


class SignupIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=80)
    email: str = Field(max_length=200)
    password: str = Field(min_length=10, max_length=200)
    website: str | None = Field(None, max_length=200)
    accepted_terms: bool = False


@router.post("/signup")
def signup(body: SignupIn, request: Request, response: Response, tasks: BackgroundTasks):
    if os.getenv("SIGNUP_ENABLED", "1") != "1":
        raise HTTPException(403, "Sign-up is closed right now. Please contact us.")
    rate_limit(f"signup:{client_ip(request)}", 5, 3600)
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    if not body.accepted_terms:
        raise HTTPException(400, "Please accept the terms to continue.")
    if db.get_by_email(email):
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    origins = []
    if body.website and body.website.strip():
        w = body.website.strip().rstrip("/")
        w = w if w.startswith(("http://", "https://")) else "https://" + w
        if ORIGIN_RE.match(w):
            origins = [w]
    biz_id = _new_id(body.business_name)
    db.upsert_business({
        "id": biz_id, "name": body.business_name.strip(), "allowed_origins": origins,
        "knowledge": {
            "description": "", "location": "", "contact": {"phone": "", "email": email},
            "hours": {"start": 9, "end": 17, "days": "Monday to Friday"}, "services": [], "faqs": [],
        },
    })
    try:
        db.set_owner(biz_id, email, auth.hash_password(body.password))
    except sqlite3.IntegrityError:
        db.q("DELETE FROM businesses WHERE id=?", (biz_id,), commit=True)
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    db.set_verified(biz_id, 0)
    db.set_terms_accepted(biz_id)
    tasks.add_task(_verification_email, request, {"id": biz_id, "name": body.business_name.strip()}, email)
    _set_session(response, request, biz_id)
    return {"ok": True}


@router.get("/verify")
def verify(token: str):
    r = auth.read_token(token, "verify")
    if r and db.get_business(r[0]):
        db.set_verified(r[0], 1)
        return RedirectResponse("/dashboard/?verified=1")
    return RedirectResponse("/dashboard/?verified=0")


@router.post("/resend-verification")
def resend_verification(request: Request, tasks: BackgroundTasks, biz=Depends(current_biz)):
    rate_limit(f"resend:{biz['id']}", 3, 3600)
    if biz.get("email_verified") != 0:
        return {"ok": True}
    tasks.add_task(_verification_email, request, biz, biz["owner_email"])
    return {"ok": True}


class ForgotIn(BaseModel):
    email: str = Field(max_length=200)


@router.post("/forgot")
def forgot(body: ForgotIn, request: Request, tasks: BackgroundTasks):
    """Always answers the same way, so nobody can use it to find out who has an account."""
    rate_limit(f"forgot:{client_ip(request)}", 5, 3600)
    biz = db.get_by_email(body.email)
    if biz and biz.get("password_hash"):
        token = auth.make_token(biz["id"], "reset", 3600, auth.fingerprint(biz["password_hash"]))
        link = f"{_base(request)}/dashboard/?reset={token}"
        tasks.add_task(
            send_email, biz["owner_email"], "Reset your password",
            f"Hi,\n\nUse this link to choose a new password for {biz['name']}:\n{link}\n\n"
            "It works once and expires in 1 hour. If you didn't ask for this, ignore this email.",
        )
    return {"ok": True}


class ResetIn(BaseModel):
    token: str = Field(max_length=600)
    new_password: str = Field(min_length=10, max_length=200)


@router.post("/reset")
def reset(body: ResetIn, request: Request):
    rate_limit(f"reset:{client_ip(request)}", 10, 3600)
    r = auth.read_token(body.token, "reset")
    biz = db.get_business(r[0]) if r else None
    if not biz or not secrets.compare_digest(r[1], auth.fingerprint(biz.get("password_hash"))):
        raise HTTPException(400, "This link has expired or was already used. Request a new one.")
    db.set_password(biz["id"], auth.hash_password(body.new_password))
    db.set_verified(biz["id"], 1)  # they just proved they control the inbox
    return {"ok": True}


# ---------- Login ----------
class LoginIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    rate_limit(f"login:{client_ip(request)}", 10, 60)
    biz = db.get_by_email(body.email)
    if not biz or not biz.get("password_hash") or not auth.check_password(body.password, biz["password_hash"]):
        raise HTTPException(401, "Wrong email or password")
    _set_session(response, request, biz["id"])
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


# ---------- Dashboard data ----------
def _resets() -> str:
    t = datetime.now(timezone.utc)
    d = date(t.year + 1, 1, 1) if t.month == 12 else date(t.year, t.month + 1, 1)
    return f"{d.strftime('%b')} {d.day}"


@router.get("/me")
def me(biz=Depends(current_biz)):
    plan = biz.get("plan") or "trial"
    status = biz.get("status") or "trial"
    days_left = None
    if status == "trial":
        end = (biz.get("created_at") or 0) + billing.TRIAL_DAYS * 86400
        days_left = max(0, math.ceil((end - time.time()) / 86400))
    k = biz["knowledge"]
    return {
        "id": biz["id"], "name": biz["name"], "email": biz.get("owner_email"), "knowledge": k,
        "allowed_origins": biz["allowed_origins"], "human_phone": biz.get("human_phone"),
        "twilio_number": biz.get("twilio_number"), "whatsapp_number": biz.get("whatsapp_number"),
        "plan": plan, "plan_label": billing.PLANS.get(plan, billing.PLANS["trial"])["label"],
        "status": status, "access": access_state(biz), "trial_days_left": days_left,
        "email_verified": biz.get("email_verified") != 0,
        "onboarding": not (k.get("description") or "").strip() and not k.get("services"),
        "used": db.get_usage(biz["id"])["messages"], "limit": billing.limit_for(biz), "resets": _resets(),
        "has_billing_account": bool(biz.get("stripe_customer_id")),
        "stripe_enabled": billing.stripe_ready(),
        "plans": [{"key": key, "label": v["label"], "messages": v["messages"], "price_usd": v["price_usd"]}
                  for key, v in billing.PLANS.items() if key != "trial"],
    }


class ProfileIn(BaseModel):
    knowledge: dict
    allowed_origins: list[str] = []
    human_phone: str | None = None


@router.put("/knowledge")
def save_profile(body: ProfileIn, biz=Depends(current_biz)):
    k = body.knowledge
    if len(json.dumps(k)) > 20000:
        raise HTTPException(400, "That's too much text. Please shorten it.")
    hours = k.get("hours") or {}
    try:
        start, end = int(hours.get("start", 9)), int(hours.get("end", 17))
    except (TypeError, ValueError):
        raise HTTPException(400, "Opening and closing hours must be numbers.")
    if not 0 <= start < end <= 24:
        raise HTTPException(400, "Opening hour must be before closing hour (0 to 24).")
    k["hours"] = {**hours, "start": start, "end": end}
    origins = []
    for o in body.allowed_origins:
        o = o.strip().rstrip("/")
        if o and not ORIGIN_RE.match(o):
            raise HTTPException(400, f"'{o}' should look like https://yourbusiness.com")
        if o:
            origins.append(o)
    db.update_profile(biz["id"], k, origins, body.human_phone)
    return {"ok": True}


@router.get("/bookings")
def bookings(biz=Depends(current_biz)):
    rows = db.q(
        "SELECT id, name, contact, service, date, hour FROM bookings WHERE business_id=? AND date>=? "
        "ORDER BY date, hour", (biz["id"], date.today().isoformat()))
    return {"bookings": [dict(r) for r in rows]}


@router.delete("/bookings/{booking_id}")
def cancel_booking(booking_id: int, biz=Depends(current_biz)):
    db.q("DELETE FROM bookings WHERE id=? AND business_id=?", (booking_id, biz["id"]), commit=True)
    return {"ok": True}


class PasswordIn(BaseModel):
    old_password: str = Field(max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


@router.post("/password")
def change_password(body: PasswordIn, request: Request, biz=Depends(current_biz)):
    rate_limit(f"pw:{client_ip(request)}", 10, 60)
    if not auth.check_password(body.old_password, biz.get("password_hash") or ""):
        raise HTTPException(400, "Current password is wrong")
    db.set_password(biz["id"], auth.hash_password(body.new_password))
    return {"ok": True}


# ---------- Billing ----------
class PlanIn(BaseModel):
    plan: str


@router.post("/billing/checkout")
def checkout(body: PlanIn, biz=Depends(current_biz)):
    if not billing.stripe_ready():
        raise HTTPException(503, "Billing isn't set up yet. Contact support.")
    try:
        if biz.get("stripe_subscription_id") and (biz.get("status") in ("active", "past_due")):
            return {"url": billing.portal_url(biz)}  # change plans in the Stripe portal
        return {"url": billing.checkout_url(biz, body.plan)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/billing/portal")
def portal(biz=Depends(current_biz)):
    if not billing.stripe_ready():
        raise HTTPException(503, "Billing isn't set up yet. Contact support.")
    try:
        return {"url": billing.portal_url(biz)}
    except ValueError as e:
        raise HTTPException(400, str(e))
