"""Gatekeeper: enforces plan status and monthly message limits before the AI is called."""
import time

import db
from agent import reply
from billing import TRIAL_DAYS, limit_for


def access_state(biz) -> str:
    status = biz.get("status") or "trial"
    if biz.get("email_verified") == 0:
        return "unverified"
    if status == "canceled":
        return "canceled"
    if status == "trial" and time.time() > (biz.get("created_at") or 0) + TRIAL_DAYS * 86400:
        return "trial_expired"
    if db.get_usage(biz["id"])["messages"] >= limit_for(biz):
        return "limit"
    return "ok"  # past_due keeps working for now (grace period)


def guarded_reply(biz, session_id, text, channel="chat"):
    if access_state(biz) != "ok":
        phone = biz.get("human_phone") or biz["knowledge"].get("contact", {}).get("phone", "")
        msg = "Sorry, our assistant is unavailable right now. "
        msg += f"Please call us at {phone}." if phone else "Please contact us directly."
        return msg, True
    db.add_usage(biz["id"], messages=1)
    return reply(biz, session_id, text, channel)
