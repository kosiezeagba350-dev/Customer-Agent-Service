"""Plans, usage limits and Stripe subscriptions. Prices below are placeholders: set your own."""
import os

import db

TRIAL_DAYS = 14
PLANS = {
    "trial": {"label": "Free trial", "messages": 200, "price_usd": 0},
    "starter": {"label": "Starter", "messages": 1000, "price_usd": 49, "price_env": "STRIPE_PRICE_STARTER"},
    "pro": {"label": "Pro", "messages": 5000, "price_usd": 149, "price_env": "STRIPE_PRICE_PRO"},
}


def limit_for(biz) -> int:
    return biz.get("limit_override") or PLANS.get(biz.get("plan") or "trial", PLANS["trial"])["messages"]


def stripe_ready() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY"))


def _stripe():
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    return stripe


def _base():
    return os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


def plan_for_price(price_id):
    for key, p in PLANS.items():
        env = p.get("price_env")
        if env and os.getenv(env) == price_id:
            return key
    return None


def checkout_url(biz, plan: str) -> str:
    p = PLANS.get(plan)
    price = os.getenv(p["price_env"], "") if p and p.get("price_env") else ""
    if not price:
        raise ValueError("That plan isn't available yet.")
    kwargs = dict(
        mode="subscription",
        line_items=[{"price": price, "quantity": 1}],
        client_reference_id=biz["id"],
        metadata={"business_id": biz["id"], "plan": plan},
        subscription_data={"metadata": {"business_id": biz["id"]}},
        success_url=f"{_base()}/dashboard/?billing=success",
        cancel_url=f"{_base()}/dashboard/?billing=canceled",
    )
    if biz.get("stripe_customer_id"):
        kwargs["customer"] = biz["stripe_customer_id"]
    elif biz.get("owner_email"):
        kwargs["customer_email"] = biz["owner_email"]
    return _stripe().checkout.Session.create(**kwargs).url


def portal_url(biz) -> str:
    if not biz.get("stripe_customer_id"):
        raise ValueError("No billing account yet. Choose a plan first.")
    s = _stripe().billing_portal.Session.create(
        customer=biz["stripe_customer_id"], return_url=f"{_base()}/dashboard/")
    return s.url


def handle_webhook(payload: bytes, signature: str):
    stripe = _stripe()
    event = stripe.Webhook.construct_event(payload, signature, os.environ["STRIPE_WEBHOOK_SECRET"])
    kind, obj = event["type"], event["data"]["object"]

    if kind == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        bid = obj.get("client_reference_id") or meta.get("business_id")
        if bid and db.get_business(bid):
            fields = {"status": "active", "stripe_customer_id": obj.get("customer"),
                      "stripe_subscription_id": obj.get("subscription")}
            if meta.get("plan") in PLANS:
                fields["plan"] = meta["plan"]
            db.update_billing(bid, fields)

    elif kind in ("customer.subscription.updated", "customer.subscription.deleted"):
        bid = (obj.get("metadata") or {}).get("business_id")
        biz = db.get_business(bid) if bid else db.find_by_stripe("stripe_subscription_id", obj.get("id"))
        if biz:
            st = obj.get("status")
            fields = {"stripe_subscription_id": obj.get("id")}
            if kind.endswith("deleted") or st == "canceled":
                fields["status"] = "canceled"
            elif st in ("active", "trialing"):
                fields["status"] = "active"
            elif st in ("past_due", "unpaid"):
                fields["status"] = "past_due"
            try:
                plan = plan_for_price(obj["items"]["data"][0]["price"]["id"])
                if plan:
                    fields["plan"] = plan
            except (KeyError, IndexError, TypeError):
                pass
            db.update_billing(biz["id"], fields)

    elif kind == "invoice.payment_failed":
        biz = db.find_by_stripe("stripe_customer_id", obj.get("customer"))
        if biz:
            db.update_billing(biz["id"], {"status": "past_due"})
    return True
