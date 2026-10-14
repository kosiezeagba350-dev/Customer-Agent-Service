# Customer Chat and Call Agent (multi-business, Python)

One server hosts many US business customers. Each business gets its own knowledge, bookings, usage limits,
phone number, WhatsApp number, owner login and plan.
Channels: website chat widget, WhatsApp, phone calls (Twilio). Billing: Stripe subscriptions.

## Deploy on Render
1. Push this folder to a GitHub repo.
2. Render: New > Blueprint > select the repo (it reads `render.yaml`). This creates one web service with a 1 GB
   persistent disk at /var/data holding the database. Everything is served by that one service: API, chat
   widget (/widget/widget.js), dashboard (/dashboard/) and webhooks.
3. Fill the prompted values: ANTHROPIC_API_KEY, PUBLIC_BASE_URL (your Render URL or custom domain), and the
   Stripe, Twilio, SMTP and legal-page values when you have them. ADMIN_KEY and SECRET_KEY are generated for you
   (copy ADMIN_KEY from the Environment tab for the admin calls).
4. Check `https://YOUR-URL/health`, then open `/dashboard/`.
- Keep it as ONE instance: sessions and rate limits live in memory and the database is a single file.
- The free plan has no persistent disk, so the database would reset on every deploy. Use a paid plan.
- Add your custom domain in Render, then update PUBLIC_BASE_URL, Twilio and Stripe webhook URLs to match.

## Run locally
    pip install -r requirements.txt
    cp .env.example .env      # set ANTHROPIC_API_KEY, ADMIN_KEY, SECRET_KEY; COOKIE_SECURE=0 for http://localhost
    uvicorn main:app --reload

## Self-serve signup (default)
Customers go to `https://YOUR-URL/dashboard/`, choose Create an account, and get a 14-day trial. They confirm
their email (the assistant stays off until they do), fill in Business info, then paste the widget code.
"Forgot password" emails a one-hour, single-use reset link. Set the SMTP_* variables to send real email; without
them the links are printed in the server log (development only). Set `SIGNUP_ENABLED=0` to close signup.

## Onboard a customer yourself (admin, optional)
1. Create the business:

       curl -X PUT localhost:8000/admin/businesses \
         -H "X-Admin-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
         -d '{"id":"demo-salon","name":"Demo Salon","knowledge":{...see knowledge.example.json...},
              "allowed_origins":["https://demosalon.com"],
              "twilio_number":"+15550100001","whatsapp_number":"+15550100002","human_phone":"+15550100003"}'

2. Create the owner's login (returns a temporary password once):

       curl -X POST localhost:8000/admin/businesses/demo-salon/owner \
         -H "X-Admin-Key: $ADMIN_KEY" -H "Content-Type: application/json" -d '{"email":"owner@demosalon.com"}'

3. Send the owner to `https://YOUR-URL/dashboard/`. They can sign in, edit their info, copy the
   widget code, see bookings and usage, change their password and pick a plan. New businesses start on a
   14-day, 200-message free trial.

Other admin calls (all need X-Admin-Key):
- `POST /admin/businesses/{id}/reset-password`
- `PATCH /admin/businesses/{id}/billing` with `{"plan":"pro","status":"active","limit_override":2000}`
- `GET /admin/usage` shows messages, tokens and estimated AI cost per business, to check your margins.

## Owner dashboard (`/dashboard/`)
Overview (usage meter and warnings), Bookings (with cancel), Business info (services, hours, FAQs, transfer phone,
allowed websites), Install (widget code with color picker), Plan and billing (Stripe checkout and portal, password).

## Plans and limits
Edit `PLANS` in `billing.py` (placeholder prices: Starter $49 for 1,000 messages, Pro $149 for 5,000).
One customer message in chat, WhatsApp or on a call counts as one message. At the limit, an expired trial or a
canceled subscription, the assistant stops calling the AI and tells the customer to call the business instead.
A failed payment (`past_due`) keeps working while Stripe retries.

## Stripe setup
1. In Stripe, create two monthly recurring prices and put their IDs in `STRIPE_PRICE_STARTER` and `STRIPE_PRICE_PRO`.
2. Set `STRIPE_SECRET_KEY`, `PUBLIC_BASE_URL`, then add a webhook endpoint `POST https://YOUR-URL/stripe/webhook` for:
   `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`,
   `invoice.payment_failed`. Put its signing secret in `STRIPE_WEBHOOK_SECRET`.
3. Turn on the Customer Portal in Stripe so owners can change plans and update cards.
4. Test with Stripe test keys and the Stripe CLI before going live.

## Website widget
    <script src="https://YOUR-URL/widget/widget.js" data-api="https://YOUR-URL" data-business="demo-salon"
            data-name="Demo Salon" data-color="#1f5eff" data-suggestions="Book an appointment|Hours|Pricing"
            data-phone="+1 555 010 0001"></script>
Owners get this code, already filled in, from the dashboard's Install tab.

## Connect Twilio
- Voice webhook for each business's number: POST https://YOUR-URL/voice/incoming
- WhatsApp incoming webhook: POST https://YOUR-URL/whatsapp
- Set TWILIO_AUTH_TOKEN and PUBLIC_BASE_URL so webhooks are signature-checked.
- Twilio call minutes are not counted by the message limit. Price your plans with that cost in mind.

## Before charging customers
- Deploy over HTTPS with COOKIE_SECURE=1, and set SECRET_KEY, ADMIN_KEY and TWILIO_AUTH_TOKEN.
- Run one server, or move sessions (agent.py) to Redis and db.py to Postgres before scaling out.
- Set `allowed_origins` for every business. An empty list allows any website.
- Back up `agent.db` (or move to Postgres). Add a CAPTCHA (for example Cloudflare Turnstile) to signup if you see abuse.
- Publish Terms and Privacy pages and set TERMS_URL and PRIVACY_URL.
- US compliance: the call greeting discloses the AI. Check state call-recording consent laws before recording,
  get legal review before outbound calls (TCPA treats AI voices as artificial voices), and publish a privacy
  policy and terms covering chat data.
