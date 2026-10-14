import sqlite3
from datetime import date

import db

TOOLS = [
    {
        "name": "check_availability",
        "description": "List open hourly slots for a date (YYYY-MM-DD).",
        "input_schema": {
            "type": "object",
            "properties": {"date": {"type": "string"}},
            "required": ["date"],
        },
    },
    {
        "name": "book_appointment",
        "description": "Book a slot. Only call after the customer confirms name, contact, service, date and hour.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "contact": {"type": "string", "description": "Phone or email"},
                "service": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "hour": {"type": "integer", "description": "24-hour clock, e.g. 14"},
            },
            "required": ["name", "contact", "service", "date", "hour"],
        },
    },
    {
        "name": "handoff_to_human",
        "description": "Transfer to a human for complaints, refunds, anger, or anything you cannot resolve.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
]


def _future_date(value):
    try:
        d = date.fromisoformat(str(value))
    except ValueError:
        return None
    return d.isoformat() if d >= date.today() else None


def run_tool(biz, name, args):
    hours = biz["knowledge"].get("hours", {"start": 9, "end": 17})
    if name == "check_availability":
        d = _future_date(args.get("date"))
        if not d:
            return {"error": "Use today or a future date as YYYY-MM-DD"}
        taken = {r["hour"] for r in db.q(
            "SELECT hour FROM bookings WHERE business_id=? AND date=?", (biz["id"], d))}
        return {"date": d, "open_hours": [h for h in range(hours["start"], hours["end"]) if h not in taken]}
    if name == "book_appointment":
        d = _future_date(args.get("date"))
        hour = args.get("hour")
        if not d:
            return {"ok": False, "error": "Use today or a future date as YYYY-MM-DD"}
        if not isinstance(hour, int) or not hours["start"] <= hour < hours["end"]:
            return {"ok": False, "error": "Outside opening hours"}
        try:
            db.q(
                "INSERT INTO bookings (business_id, name, contact, service, date, hour) VALUES (?,?,?,?,?,?)",
                (biz["id"], args["name"], args["contact"], args["service"], d, hour),
                commit=True,
            )
        except sqlite3.IntegrityError:
            return {"ok": False, "error": "Slot already taken"}
        return {"ok": True, "message": "Booked"}
    if name == "handoff_to_human":
        return {"ok": True, "reason": args.get("reason", "")}
    return {"error": "Unknown tool"}
