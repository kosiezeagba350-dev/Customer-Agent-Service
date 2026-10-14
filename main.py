import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import Gather, VoiceResponse

import auth
import billing
import db
import owner
from usage import guarded_reply
from util import client_ip, rate_limit

load_dotenv()
app = FastAPI(title="Customer Agent (multi-business)")
# CORS is open so the widget can load anywhere; each business's allowed_origins is enforced in /chat.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(owner.router)

XML = "application/xml"
BASE = Path(__file__).parent


def _file(*candidates):
    """Works whether files sit in dashboard/ and widget/ folders or all together in one flat folder."""
    for c in candidates:
        p = BASE / c
        if p.is_file():
            return p
    raise HTTPException(404, "Not found")


@app.get("/dashboard")
def dashboard_redirect():
    return RedirectResponse("/dashboard/")


@app.get("/dashboard/")
def dashboard():
    return FileResponse(_file("dashboard/index.html", "index.html"), media_type="text/html")


@app.get("/widget/widget.js")
def widget_js():
    return FileResponse(_file("widget/widget.js", "widget.js"), media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=300"})


def need_admin(key: str | None):
    expected = os.getenv("ADMIN_KEY")
    if not expected:
        raise HTTPException(503, "Admin disabled: set ADMIN_KEY")
    if not key or not secrets.compare_digest(key, expected):
        raise HTTPException(401, "Bad admin key")


async def verify_twilio(request: Request):
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not token:
        return  # set TWILIO_AUTH_TOKEN in production
    form = await request.form()
    url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/") + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    if not RequestValidator(token).validate(url, dict(form), request.headers.get("X-Twilio-Signature", "")):
        raise HTTPException(403, "Invalid Twilio signature")


# ---------- Admin: onboard and manage businesses ----------
class BusinessIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]{2,40}$")
    name: str = Field(max_length=120)
    knowledge: dict
    allowed_origins: list[str] = []
    twilio_number: str | None = None
    whatsapp_number: str | None = None
    human_phone: str | None = None


@app.put("/admin/businesses")
def admin_upsert(b: BusinessIn, x_admin_key: str | None = Header(None)):
    need_admin(x_admin_key)
    db.upsert_business(b.model_dump())
    return {"ok": True, "id": b.id}


@app.get("/admin/businesses")
def admin_list(x_admin_key: str | None = Header(None)):
    need_admin(x_admin_key)
    return {"businesses": db.list_businesses()}


@app.get("/admin/businesses/{biz_id}/bookings")
def admin_bookings(biz_id: str, x_admin_key: str | None = Header(None)):
    need_admin(x_admin_key)
    rows = db.q("SELECT name, contact, service, date, hour FROM bookings WHERE business_id=? ORDER BY date, hour", (biz_id,))
    return {"bookings": [dict(r) for r in rows]}


class OwnerIn(BaseModel):
    email: str = Field(max_length=200)


@app.post("/admin/businesses/{biz_id}/owner")
def admin_set_owner(biz_id: str, body: OwnerIn, x_admin_key: str | None = Header(None)):
    """Creates or replaces the owner login. Returns a temporary password once."""
    need_admin(x_admin_key)
    if not db.get_business(biz_id):
        raise HTTPException(404, "Unknown business")
    pw = auth.temp_password()
    try:
        db.set_owner(biz_id, body.email, auth.hash_password(pw))
    except Exception:
        raise HTTPException(409, "That email is already used by another business")
    db.set_verified(biz_id, 1)
    return {"email": body.email.strip().lower(), "temporary_password": pw}


@app.post("/admin/businesses/{biz_id}/reset-password")
def admin_reset_password(biz_id: str, x_admin_key: str | None = Header(None)):
    need_admin(x_admin_key)
    if not db.get_business(biz_id):
        raise HTTPException(404, "Unknown business")
    pw = auth.temp_password()
    db.set_password(biz_id, auth.hash_password(pw))
    return {"temporary_password": pw}


class BillingPatch(BaseModel):
    plan: str | None = None
    status: str | None = None  # trial, active, past_due, canceled
    limit_override: int | None = None  # extra headroom for one customer; null clears it


@app.patch("/admin/businesses/{biz_id}/billing")
def admin_billing(biz_id: str, body: BillingPatch, x_admin_key: str | None = Header(None)):
    need_admin(x_admin_key)
    if not db.get_business(biz_id):
        raise HTTPException(404, "Unknown business")
    fields = body.model_dump(exclude_unset=True)
    if fields.get("plan") and fields["plan"] not in billing.PLANS:
        raise HTTPException(400, "Unknown plan")
    if fields.get("status") and fields["status"] not in {"trial", "active", "past_due", "canceled"}:
        raise HTTPException(400, "Unknown status")
    db.update_billing(biz_id, fields)
    return {"ok": True}


@app.get("/admin/usage")
def admin_usage(month: str | None = None, x_admin_key: str | None = Header(None)):
    """Per-business usage and estimated AI cost. Check the per-million-token prices in .env against current pricing."""
    need_admin(x_admin_key)
    cin, cout = float(os.getenv("COST_IN_PER_M", "3")), float(os.getenv("COST_OUT_PER_M", "15"))
    usage = db.all_usage(month)
    out = []
    for biz_id in db.list_businesses():
        b = db.get_business(biz_id)
        u = usage.get(biz_id, {"messages": 0, "input_tokens": 0, "output_tokens": 0})
        out.append({
            "id": biz_id, "plan": b.get("plan"), "status": b.get("status"),
            "messages": u["messages"], "limit": billing.limit_for(b),
            "input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"],
            "est_ai_cost_usd": round(u["input_tokens"] / 1e6 * cin + u["output_tokens"] / 1e6 * cout, 4),
        })
    return {"month": month or db.month_key(), "businesses": out}


# ---------- Stripe ----------
@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    if not billing.stripe_ready() or not os.getenv("STRIPE_WEBHOOK_SECRET"):
        raise HTTPException(503, "Stripe not configured")
    try:
        billing.handle_webhook(await request.body(), request.headers.get("stripe-signature", ""))
    except Exception:
        raise HTTPException(400, "Invalid webhook")
    return {"ok": True}


# ---------- Website chat ----------
class ChatIn(BaseModel):
    business_id: str = Field(max_length=60)
    session_id: str = Field(max_length=100)
    message: str = Field(max_length=1000)


@app.post("/chat")
async def chat(body: ChatIn, request: Request):
    biz = db.get_business(body.business_id)
    if not biz:
        raise HTTPException(404, "Unknown business")
    origin = request.headers.get("origin")
    if biz["allowed_origins"] and origin and origin not in biz["allowed_origins"]:
        raise HTTPException(403, "This site is not allowed to use this assistant")
    rate_limit(f"{biz['id']}:{client_ip(request)}")
    text, handoff = await run_in_threadpool(guarded_reply, biz, body.session_id, body.message, "chat")
    return {"reply": text, "handoff": handoff}


# ---------- WhatsApp (Twilio) ----------
@app.post("/whatsapp")
async def whatsapp(request: Request):
    await verify_twilio(request)
    form = await request.form()
    biz = db.find_by_number("whatsapp_number", form.get("To", ""))
    r = MessagingResponse()
    if not biz:
        r.message("This number is not in service.")
    else:
        text, _ = await run_in_threadpool(guarded_reply, biz, form.get("From", ""), form.get("Body", ""), "chat")
        r.message(text)
    return Response(str(r), media_type=XML)


# ---------- Phone (Twilio) ----------
def _gather(vr: VoiceResponse, biz_id: str, prompt: str):
    g = Gather(input="speech", action=f"/voice/respond?b={biz_id}", method="POST",
               speechTimeout="auto", language="en-US")
    g.say(prompt)
    vr.append(g)
    vr.say("I didn't hear anything. Goodbye.")
    return vr


@app.post("/voice/incoming")
async def voice_incoming(request: Request):
    await verify_twilio(request)
    form = await request.form()
    biz = db.find_by_number("twilio_number", form.get("To", ""))
    vr = VoiceResponse()
    if not biz:
        vr.say("Sorry, this number is not in service.")
        vr.hangup()
    else:
        _gather(vr, biz["id"],
                f"Thanks for calling {biz['name']}. You're speaking with an AI assistant. How can I help?")
    return Response(str(vr), media_type=XML)


@app.post("/voice/respond")
async def voice_respond(request: Request):
    await verify_twilio(request)
    form = await request.form()
    biz = db.get_business(request.query_params.get("b"))
    vr = VoiceResponse()
    if not biz:
        vr.hangup()
        return Response(str(vr), media_type=XML)
    speech = form.get("SpeechResult", "")
    if not speech:
        _gather(vr, biz["id"], "Sorry, could you say that again?")
        return Response(str(vr), media_type=XML)
    text, handoff = await run_in_threadpool(guarded_reply, biz, form.get("CallSid", ""), speech, "voice")
    if handoff and biz.get("human_phone"):
        vr.say(text)
        vr.say("Connecting you to a team member now.")
        vr.dial(biz["human_phone"])
    else:
        _gather(vr, biz["id"], text)
    return Response(str(vr), media_type=XML)


@app.get("/health")
def health():
    return {"ok": True}
