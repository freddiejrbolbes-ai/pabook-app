from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta
import random
import os
from models import db, Provider, Service, Booking, CATEGORIES, PACKAGE_TIERS
from mailer import (send_booking_confirmation_to_customer,
                     send_new_booking_alert_to_provider,
                     send_provider_welcome_email)

app = Flask(__name__)

# Use PostgreSQL in production (Render) via DATABASE_URL, fall back to local
# SQLite when running on your own laptop for development/testing.
# Render's DATABASE_URL starts with "postgres://" but SQLAlchemy needs
# "postgresql://" — the replace below fixes that automatically.
database_url = os.environ.get("DATABASE_URL", "sqlite:///pabook.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
db.init_app(app)

# Default reference point: Kapalong, Davao del Norte (used when customer location unknown)
DEFAULT_LAT = 7.5906
DEFAULT_LNG = 125.6772


# ---------- helpers ----------

def next_14_days():
    today = datetime.now()
    days = []
    for i in range(14):
        d = today + timedelta(days=i)
        days.append({"iso": d.strftime("%Y-%m-%d"), "label": d.strftime("%a %-d") if hasattr(d, "strftime") else str(d)})
    return days


def time_slots(open_str="09:00", close_str="18:00", step_minutes=60):
    slots = []
    t = datetime.strptime(open_str, "%H:%M")
    end = datetime.strptime(close_str, "%H:%M")
    while t < end:
        slots.append(t.strftime("%H:%M"))
        t += timedelta(minutes=step_minutes)
    return slots


# ---------- customer-facing: browse ----------

@app.route("/")
def home():
    category = request.args.get("category")
    lat = request.args.get("lat", type=float) or DEFAULT_LAT
    lng = request.args.get("lng", type=float) or DEFAULT_LNG

    query = Provider.query.filter_by(status="active")
    if category:
        query = query.filter_by(category=category)
    providers = query.all()

    # attach distance & sort nearest first, featured (premium) providers bumped up
    results = []
    for p in providers:
        if not p.has_access():
            continue  # trial expired and no active subscription — hidden from search
        dist = p.distance_km(lat, lng)
        if dist is not None and dist > p.service_radius_km:
            continue  # outside their service area
        results.append((p, dist))

    results.sort(key=lambda pair: (not pair[0].tier_info()["featured"], pair[1] if pair[1] is not None else 999))

    return render_template("home.html", categories=CATEGORIES, results=results,
                            selected_category=category)


@app.route("/provider/<int:provider_id>")
def provider_profile(provider_id):
    provider = Provider.query.get_or_404(provider_id)
    services = Service.query.filter_by(provider_id=provider.id, active=True).all()
    return render_template("provider_profile.html", provider=provider, services=services)


@app.route("/book/<int:provider_id>", methods=["GET", "POST"])
def book(provider_id):
    provider = Provider.query.get_or_404(provider_id)
    services = Service.query.filter_by(provider_id=provider.id, active=True).all()
    service_id = request.args.get("service_id", type=int)

    if request.method == "POST":
        booking = Booking(
            provider_id=provider.id,
            service_id=request.form.get("service_id", type=int),
            customer_name=request.form["customer_name"],
            customer_phone=request.form["customer_phone"],
            customer_email=request.form.get("customer_email", "").strip(),
            booking_date=request.form["booking_date"],
            booking_time=request.form["booking_time"],
            notes=request.form.get("notes", ""),
            status="pending",
        )
        db.session.add(booking)
        db.session.commit()

        service_name = booking.service.name if booking.service else "Quote request"

        # Email confirmation to customer (if they gave an email)
        send_booking_confirmation_to_customer(
            customer_email=booking.customer_email,
            customer_name=booking.customer_name,
            provider_name=provider.business_name,
            service_name=service_name,
            booking_date=booking.booking_date,
            booking_time=booking.booking_time,
        )

        # Email alert to provider
        send_new_booking_alert_to_provider(
            provider_email=provider.email,
            provider_name=provider.business_name,
            customer_name=booking.customer_name,
            customer_phone=booking.customer_phone,
            service_name=service_name,
            booking_date=booking.booking_date,
            booking_time=booking.booking_time,
            notes=booking.notes,
        )

        flash("Na-submit na ang booking mo! Maghihintay ka na lang ng SMS confirmation.", "success")
        return redirect(url_for("booking_confirmation", booking_id=booking.id))

    days = next_14_days()
    slots = time_slots(provider.hours_open, provider.hours_close)
    return render_template("book.html", provider=provider, services=services,
                            selected_service_id=service_id, days=days, slots=slots)


@app.route("/booking/<int:booking_id>/confirmation")
def booking_confirmation(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    return render_template("confirmation.html", booking=booking)


# ---------- provider signup (package selection) ----------

@app.route("/provider/signup")
def provider_signup():
    return render_template("provider_signup.html", tiers=PACKAGE_TIERS)


# ---------- provider self-setup (this is what you SELL) ----------

@app.route("/provider/setup", methods=["GET", "POST"])
def provider_setup():
    preselected_package = request.args.get("package", "starter")
    if request.method == "POST":
        access_code = f"{random.randint(0, 999999):06d}"
        provider = Provider(
            business_name=request.form["business_name"],
            category=request.form["category"],
            owner_name=request.form.get("owner_name"),
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            address_text=request.form.get("address_text"),
            barangay=request.form.get("barangay"),
            latitude=request.form.get("latitude", type=float) or DEFAULT_LAT,
            longitude=request.form.get("longitude", type=float) or DEFAULT_LNG,
            service_radius_km=request.form.get("service_radius_km", type=float) or 3.0,
            hours_open=request.form.get("hours_open", "09:00"),
            hours_close=request.form.get("hours_close", "18:00"),
            package_tier=request.form.get("package_tier", "starter"),
            quote_only=bool(request.form.get("quote_only")),
            status="active",
            access_code=access_code,
            trial_ends_at=datetime.utcnow() + timedelta(days=15),
        )
        db.session.add(provider)
        db.session.commit()

        # services (submitted as parallel arrays)
        names = request.form.getlist("service_name[]")
        prices = request.form.getlist("service_price[]")
        for name, price in zip(names, prices):
            if name.strip():
                db.session.add(Service(
                    provider_id=provider.id,
                    name=name.strip(),
                    price=float(price) if price else None,
                ))
        db.session.commit()

        send_provider_welcome_email(
            provider_email=provider.email,
            business_name=provider.business_name,
            package_label=provider.tier_info()["label"],
        )

        flash(f"Live na ang {provider.business_name}! May 15-day free trial ka. Access code: {access_code}", "success")
        return redirect(url_for("provider_welcome", provider_id=provider.id))

    return render_template("provider_setup.html", categories=CATEGORIES, tiers=PACKAGE_TIERS, preselected_package=preselected_package)


@app.route("/provider/<int:provider_id>/welcome")
def provider_welcome(provider_id):
    provider = Provider.query.get_or_404(provider_id)
    return render_template("provider_welcome.html", provider=provider)


# ---------- provider dashboard ----------

@app.route("/provider/<int:provider_id>/dashboard", methods=["GET", "POST"])
def provider_dashboard(provider_id):
    provider = Provider.query.get_or_404(provider_id)

    # Access code check — the provider must enter their PIN once per browser
    # session before seeing bookings. Customers never touch this at all.
    unlocked = request.args.get("unlocked") == provider.access_code
    if request.method == "POST":
        entered_code = request.form.get("access_code", "").strip()
        if entered_code == provider.access_code:
            return redirect(url_for("provider_dashboard", provider_id=provider.id, unlocked=entered_code))
        flash("Maling access code. Subukan ulit.", "error")
        return render_template("provider_login.html", provider=provider)

    if not unlocked:
        return render_template("provider_login.html", provider=provider)

    if not provider.has_access():
        return render_template("provider_trial_expired.html", provider=provider, unlocked=unlocked)

    bookings = Booking.query.filter_by(provider_id=provider.id).order_by(Booking.booking_date, Booking.booking_time).all()
    pending = [b for b in bookings if b.status == "pending"]
    confirmed = [b for b in bookings if b.status == "confirmed"]
    today_str = datetime.now().strftime("%Y-%m-%d")
    earnings_today = sum((b.service.price or b.quoted_price or 0) for b in bookings
                         if b.booking_date == today_str and b.status in ("confirmed", "completed") and b.service)
    return render_template("provider_dashboard.html", provider=provider, pending=pending,
                            confirmed=confirmed, earnings_today=earnings_today, today_str=today_str,
                            unlocked=unlocked)


@app.route("/booking/<int:booking_id>/status", methods=["POST"])
def update_booking_status(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    new_status = request.form.get("status")
    if new_status in ("confirmed", "declined", "completed", "cancelled"):
        booking.status = new_status
        db.session.commit()
    unlocked = request.form.get("unlocked", "")
    return redirect(url_for("provider_dashboard", provider_id=booking.provider_id, unlocked=unlocked))


# ---------- seed sample data (so you have a working demo) ----------

@app.route("/dev/seed")
def dev_seed():
    """Wipes and re-seeds sample providers so there's a working demo.
    DANGEROUS in production — wipes the whole database. Protected by
    ADMIN_SECRET and refuses to run if any provider already has a paid
    subscription, so it can't accidentally nuke real subscriber data."""
    admin_secret = os.environ.get("ADMIN_SECRET", "changeme")
    if request.args.get("secret") != admin_secret:
        return "Forbidden — add ?secret=yoursecret to the URL", 403

    try:
        existing_paid = Provider.query.filter_by(subscription_active=True).count()
    except Exception:
        # Old table schema (column doesn't exist yet) — safe to reset since
        # there's no way real paid subscribers exist under the old schema.
        existing_paid = 0
    if existing_paid > 0:
        return jsonify({
            "status": "blocked",
            "message": f"Refusing to wipe database — {existing_paid} provider(s) have active paid subscriptions. Remove this safeguard manually if you really intend to reset."
        }), 400

    db.drop_all()
    db.create_all()

    samples = [
        dict(business_name="Kuya Ronnie's Barbershop", category="barber",
             owner_name="Ronnie Dela Cruz", phone="09171234567",
             address_text="Purok 3, Brgy. Poblacion", barangay="Poblacion",
             latitude=7.5906, longitude=125.6772, service_radius_km=3,
             hours_open="09:00", hours_close="19:00", package_tier="starter",
             status="active", rating=4.8, review_count=212,
             services=[("Regular haircut", 80), ("Haircut + shave", 130), ("Hair color (basic)", 350), ("Kids haircut", 60)]),
        dict(business_name="Glow Up Salon & Spa", category="salon",
             owner_name="Cristy Panganiban", phone="09182223344",
             address_text="Rizal St., Brgy. Poblacion", barangay="Poblacion",
             latitude=7.5960, longitude=125.6810, service_radius_km=5,
             hours_open="09:00", hours_close="18:00", package_tier="standard",
             status="active", rating=4.7, review_count=98,
             services=[("Rebond", 1200), ("Gel manicure", 250), ("Basic facial", 300), ("Hair spa", 400)]),
        dict(business_name="JB Electrical Services", category="electrician",
             owner_name="Jayson Batomalaque", phone="09193334455",
             address_text="Sitio Malipayon, Brgy. Luna", barangay="Luna",
             latitude=7.6020, longitude=125.6650, service_radius_km=8,
             hours_open="07:00", hours_close="20:00", package_tier="premium",
             status="active", quote_only=True, rating=4.9, review_count=64,
             services=[("Wiring inspection", None), ("Outlet installation", None), ("Emergency repair", None)]),
        dict(business_name="Ka-Dodong Auto Repair", category="mekaniko",
             owner_name="Rodolfo Ibañez", phone="09204445566",
             address_text="National Highway, Brgy. Mabantao", barangay="Mabantao",
             latitude=7.5810, longitude=125.6900, service_radius_km=6,
             hours_open="08:00", hours_close="18:00", package_tier="starter",
             status="active", quote_only=True, rating=4.6, review_count=41,
             services=[("Motor tune-up", None), ("Tricycle repair", None), ("Oil change", 250)]),
        dict(business_name="FBJR Trucking Services", category="trucking",
             owner_name="Freddie Bolbes", phone="09215556677",
             address_text="National Highway, Brgy. Mabantao", barangay="Mabantao",
             latitude=7.5850, longitude=125.6850, service_radius_km=25,
             hours_open="06:00", hours_close="20:00", package_tier="premium",
             status="active", quote_only=True, rating=4.9, review_count=37,
             services=[("Lipat-bahay (small)", None), ("Lipat-bahay (large)", None), ("Freight hauling", None), ("Cargo delivery", None)]),
    ]

    for s in samples:
        svc_list = s.pop("services")
        s["access_code"] = f"{random.randint(0, 999999):06d}"
        s["subscription_active"] = True
        s["subscription_expires_at"] = datetime.utcnow() + timedelta(days=365)
        provider = Provider(**s)
        db.session.add(provider)
        db.session.flush()
        for name, price in svc_list:
            db.session.add(Service(provider_id=provider.id, name=name, price=price))
    db.session.commit()
    return jsonify({"status": "seeded", "providers": len(samples)})


# ---------- Facebook Messenger webhook ----------

@app.route("/webhook", methods=["GET"])
def messenger_verify():
    from messenger import VERIFY_TOKEN
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def messenger_webhook():
    from messenger import handle_message
    payload = request.get_json(silent=True) or {}
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            if not sender_id:
                continue
            if "message" in event:
                text = event["message"].get("text")
                quick_reply = event["message"].get("quick_reply", {}).get("payload")
                handle_message(sender_id, text=text, payload=quick_reply)
            elif "postback" in event:
                payload_str = event["postback"].get("payload")
                handle_message(sender_id, payload=payload_str)
    return "OK", 200


@app.route("/provider/<int:provider_id>/subscribe")
def provider_subscribe(provider_id):
    """Sends the provider to a PayMongo hosted checkout page (GCash/card/Maya)
    to pay their monthly subscription online."""
    from paymongo import create_checkout_session
    provider = Provider.query.get_or_404(provider_id)
    tier = provider.tier_info()
    base_url = request.host_url.rstrip("/")
    unlocked = request.args.get("unlocked", provider.access_code)
    success_url = f"{base_url}/provider/{provider.id}/dashboard?unlocked={unlocked}&paid=1"
    cancel_url = f"{base_url}/provider/{provider.id}/dashboard?unlocked={unlocked}"

    checkout_url = create_checkout_session(
        provider,
        tier["monthly_fee"],
        f"PaBook {tier['label']} — Monthly Subscription",
        success_url,
        cancel_url,
    )
    if not checkout_url:
        flash("Hindi pa available ang online payment ngayon. I-message na lang kami para mag-subscribe.", "error")
        return redirect(url_for("provider_dashboard", provider_id=provider.id, unlocked=unlocked))
    return redirect(checkout_url)


@app.route("/webhook/paymongo", methods=["POST"])
def paymongo_webhook():
    """PayMongo calls this automatically when a checkout session is paid.
    Activates the provider's subscription without you needing to click
    the manual /admin/activate link."""
    payload = request.get_json(silent=True) or {}
    event_type = payload.get("data", {}).get("attributes", {}).get("type", "")

    if event_type == "checkout_session.payment.paid":
        try:
            session_data = payload["data"]["attributes"]["data"]
            metadata = session_data["attributes"].get("metadata", {})
            provider_id = metadata.get("provider_id")
            if provider_id:
                provider = Provider.query.get(int(provider_id))
                if provider:
                    provider.subscription_active = True
                    provider.subscription_expires_at = datetime.utcnow() + timedelta(days=30)
                    db.session.commit()
                    print(f"[paymongo] Activated subscription for provider {provider_id}")
        except Exception as e:
            print(f"[paymongo] Webhook processing error: {e}")

    return "OK", 200


@app.route("/admin/activate/<int:provider_id>")
def admin_activate_subscription(provider_id):
    """Manually activate a provider's paid subscription after you've confirmed
    their GCash payment. Protected by a secret in the URL so randos can't
    activate themselves for free — set ADMIN_SECRET on Render and use:
    /admin/activate/<id>?secret=yoursecret"""
    admin_secret = os.environ.get("ADMIN_SECRET", "changeme")
    if request.args.get("secret") != admin_secret:
        return "Forbidden", 403
    provider = Provider.query.get_or_404(provider_id)
    provider.subscription_active = True
    provider.subscription_expires_at = datetime.utcnow() + timedelta(days=30)
    db.session.commit()
    return jsonify({
        "status": "activated",
        "provider": provider.business_name,
        "expires_at": provider.subscription_expires_at.isoformat(),
    })


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
    return days


def time_slots(open_str="09:00", close_str="18:00", step_minutes=60):
    slots = []
    t = datetime.strptime(open_str, "%H:%M")
    end = datetime.strptime(close_str, "%H:%M")
    while t < end:
        slots.append(t.strftime("%H:%M"))
        t += timedelta(minutes=step_minutes)
    return slots


# ---------- customer-facing: browse ----------

@app.route("/")
def home():
    category = request.args.get("category")
    lat = request.args.get("lat", type=float) or DEFAULT_LAT
    lng = request.args.get("lng", type=float) or DEFAULT_LNG

    query = Provider.query.filter_by(status="active")
    if category:
        query = query.filter_by(category=category)
    providers = query.all()

    # attach distance & sort nearest first, featured (premium) providers bumped up
    results = []
    for p in providers:
        if not p.has_access():
            continue  # trial expired and no active subscription — hidden from search
        dist = p.distance_km(lat, lng)
        if dist is not None and dist > p.service_radius_km:
            continue  # outside their service area
        results.append((p, dist))

    results.sort(key=lambda pair: (not pair[0].tier_info()["featured"], pair[1] if pair[1] is not None else 999))

    return render_template("home.html", categories=CATEGORIES, results=results,
                            selected_category=category)


@app.route("/provider/<int:provider_id>")
def provider_profile(provider_id):
    provider = Provider.query.get_or_404(provider_id)
    services = Service.query.filter_by(provider_id=provider.id, active=True).all()
    return render_template("provider_profile.html", provider=provider, services=services)


@app.route("/book/<int:provider_id>", methods=["GET", "POST"])
def book(provider_id):
    provider = Provider.query.get_or_404(provider_id)
    services = Service.query.filter_by(provider_id=provider.id, active=True).all()
    service_id = request.args.get("service_id", type=int)

    if request.method == "POST":
        booking = Booking(
            provider_id=provider.id,
            service_id=request.form.get("service_id", type=int),
            customer_name=request.form["customer_name"],
            customer_phone=request.form["customer_phone"],
            customer_email=request.form.get("customer_email", "").strip(),
            booking_date=request.form["booking_date"],
            booking_time=request.form["booking_time"],
            notes=request.form.get("notes", ""),
            status="pending",
        )
        db.session.add(booking)
        db.session.commit()

        service_name = booking.service.name if booking.service else "Quote request"

        # Email confirmation to customer (if they gave an email)
        send_booking_confirmation_to_customer(
            customer_email=booking.customer_email,
            customer_name=booking.customer_name,
            provider_name=provider.business_name,
            service_name=service_name,
            booking_date=booking.booking_date,
            booking_time=booking.booking_time,
        )

        # Email alert to provider
        send_new_booking_alert_to_provider(
            provider_email=provider.email,
            provider_name=provider.business_name,
            customer_name=booking.customer_name,
            customer_phone=booking.customer_phone,
            service_name=service_name,
            booking_date=booking.booking_date,
            booking_time=booking.booking_time,
            notes=booking.notes,
        )

        flash("Na-submit na ang booking mo! Maghihintay ka na lang ng SMS confirmation.", "success")
        return redirect(url_for("booking_confirmation", booking_id=booking.id))

    days = next_14_days()
    slots = time_slots(provider.hours_open, provider.hours_close)
    return render_template("book.html", provider=provider, services=services,
                            selected_service_id=service_id, days=days, slots=slots)


@app.route("/booking/<int:booking_id>/confirmation")
def booking_confirmation(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    return render_template("confirmation.html", booking=booking)


# ---------- provider signup (package selection) ----------

@app.route("/provider/signup")
def provider_signup():
    return render_template("provider_signup.html", tiers=PACKAGE_TIERS)


# ---------- provider self-setup (this is what you SELL) ----------

@app.route("/provider/setup", methods=["GET", "POST"])
def provider_setup():
    preselected_package = request.args.get("package", "starter")
    if request.method == "POST":
        access_code = f"{random.randint(0, 999999):06d}"
        provider = Provider(
            business_name=request.form["business_name"],
            category=request.form["category"],
            owner_name=request.form.get("owner_name"),
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            address_text=request.form.get("address_text"),
            barangay=request.form.get("barangay"),
            latitude=request.form.get("latitude", type=float) or DEFAULT_LAT,
            longitude=request.form.get("longitude", type=float) or DEFAULT_LNG,
            service_radius_km=request.form.get("service_radius_km", type=float) or 3.0,
            hours_open=request.form.get("hours_open", "09:00"),
            hours_close=request.form.get("hours_close", "18:00"),
            package_tier=request.form.get("package_tier", "starter"),
            quote_only=bool(request.form.get("quote_only")),
            status="active",
            access_code=access_code,
            trial_ends_at=datetime.utcnow() + timedelta(days=15),
        )
        db.session.add(provider)
        db.session.commit()

        # services (submitted as parallel arrays)
        names = request.form.getlist("service_name[]")
        prices = request.form.getlist("service_price[]")
        for name, price in zip(names, prices):
            if name.strip():
                db.session.add(Service(
                    provider_id=provider.id,
                    name=name.strip(),
                    price=float(price) if price else None,
                ))
        db.session.commit()

        send_provider_welcome_email(
            provider_email=provider.email,
            business_name=provider.business_name,
            package_label=provider.tier_info()["label"],
        )

        flash(f"Live na ang {provider.business_name}! May 15-day free trial ka. Access code: {access_code}", "success")
        return redirect(url_for("provider_welcome", provider_id=provider.id))

    return render_template("provider_setup.html", categories=CATEGORIES, tiers=PACKAGE_TIERS, preselected_package=preselected_package)


@app.route("/provider/<int:provider_id>/welcome")
def provider_welcome(provider_id):
    provider = Provider.query.get_or_404(provider_id)
    return render_template("provider_welcome.html", provider=provider)


# ---------- provider dashboard ----------

@app.route("/provider/<int:provider_id>/dashboard", methods=["GET", "POST"])
def provider_dashboard(provider_id):
    provider = Provider.query.get_or_404(provider_id)

    # Access code check — the provider must enter their PIN once per browser
    # session before seeing bookings. Customers never touch this at all.
    unlocked = request.args.get("unlocked") == provider.access_code
    if request.method == "POST":
        entered_code = request.form.get("access_code", "").strip()
        if entered_code == provider.access_code:
            return redirect(url_for("provider_dashboard", provider_id=provider.id, unlocked=entered_code))
        flash("Maling access code. Subukan ulit.", "error")
        return render_template("provider_login.html", provider=provider)

    if not unlocked:
        return render_template("provider_login.html", provider=provider)

    if not provider.has_access():
        return render_template("provider_trial_expired.html", provider=provider, unlocked=unlocked)

    bookings = Booking.query.filter_by(provider_id=provider.id).order_by(Booking.booking_date, Booking.booking_time).all()
    pending = [b for b in bookings if b.status == "pending"]
    confirmed = [b for b in bookings if b.status == "confirmed"]
    today_str = datetime.now().strftime("%Y-%m-%d")
    earnings_today = sum((b.service.price or b.quoted_price or 0) for b in bookings
                         if b.booking_date == today_str and b.status in ("confirmed", "completed") and b.service)
    return render_template("provider_dashboard.html", provider=provider, pending=pending,
                            confirmed=confirmed, earnings_today=earnings_today, today_str=today_str,
                            unlocked=unlocked)


@app.route("/booking/<int:booking_id>/status", methods=["POST"])
def update_booking_status(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    new_status = request.form.get("status")
    if new_status in ("confirmed", "declined", "completed", "cancelled"):
        booking.status = new_status
        db.session.commit()
    unlocked = request.form.get("unlocked", "")
    return redirect(url_for("provider_dashboard", provider_id=booking.provider_id, unlocked=unlocked))


# ---------- seed sample data (so you have a working demo) ----------

@app.route("/dev/seed")
def dev_seed():
    """Wipes and re-seeds sample providers so there's a working demo.
    DANGEROUS in production — wipes the whole database. Protected by
    ADMIN_SECRET and refuses to run if any provider already has a paid
    subscription, so it can't accidentally nuke real subscriber data."""
    admin_secret = os.environ.get("ADMIN_SECRET", "changeme")
    if request.args.get("secret") != admin_secret:
        return "Forbidden — add ?secret=yoursecret to the URL", 403

    existing_paid = Provider.query.filter_by(subscription_active=True).count()
    if existing_paid > 0:
        return jsonify({
            "status": "blocked",
            "message": f"Refusing to wipe database — {existing_paid} provider(s) have active paid subscriptions. Remove this safeguard manually if you really intend to reset."
        }), 400

    db.drop_all()
    db.create_all()

    samples = [
        dict(business_name="Kuya Ronnie's Barbershop", category="barber",
             owner_name="Ronnie Dela Cruz", phone="09171234567",
             address_text="Purok 3, Brgy. Poblacion", barangay="Poblacion",
             latitude=7.5906, longitude=125.6772, service_radius_km=3,
             hours_open="09:00", hours_close="19:00", package_tier="starter",
             status="active", rating=4.8, review_count=212,
             services=[("Regular haircut", 80), ("Haircut + shave", 130), ("Hair color (basic)", 350), ("Kids haircut", 60)]),
        dict(business_name="Glow Up Salon & Spa", category="salon",
             owner_name="Cristy Panganiban", phone="09182223344",
             address_text="Rizal St., Brgy. Poblacion", barangay="Poblacion",
             latitude=7.5960, longitude=125.6810, service_radius_km=5,
             hours_open="09:00", hours_close="18:00", package_tier="standard",
             status="active", rating=4.7, review_count=98,
             services=[("Rebond", 1200), ("Gel manicure", 250), ("Basic facial", 300), ("Hair spa", 400)]),
        dict(business_name="JB Electrical Services", category="electrician",
             owner_name="Jayson Batomalaque", phone="09193334455",
             address_text="Sitio Malipayon, Brgy. Luna", barangay="Luna",
             latitude=7.6020, longitude=125.6650, service_radius_km=8,
             hours_open="07:00", hours_close="20:00", package_tier="premium",
             status="active", quote_only=True, rating=4.9, review_count=64,
             services=[("Wiring inspection", None), ("Outlet installation", None), ("Emergency repair", None)]),
        dict(business_name="Ka-Dodong Auto Repair", category="mekaniko",
             owner_name="Rodolfo Ibañez", phone="09204445566",
             address_text="National Highway, Brgy. Mabantao", barangay="Mabantao",
             latitude=7.5810, longitude=125.6900, service_radius_km=6,
             hours_open="08:00", hours_close="18:00", package_tier="starter",
             status="active", quote_only=True, rating=4.6, review_count=41,
             services=[("Motor tune-up", None), ("Tricycle repair", None), ("Oil change", 250)]),
        dict(business_name="FBJR Trucking Services", category="trucking",
             owner_name="Freddie Bolbes", phone="09215556677",
             address_text="National Highway, Brgy. Mabantao", barangay="Mabantao",
             latitude=7.5850, longitude=125.6850, service_radius_km=25,
             hours_open="06:00", hours_close="20:00", package_tier="premium",
             status="active", quote_only=True, rating=4.9, review_count=37,
             services=[("Lipat-bahay (small)", None), ("Lipat-bahay (large)", None), ("Freight hauling", None), ("Cargo delivery", None)]),
    ]

    for s in samples:
        svc_list = s.pop("services")
        s["access_code"] = f"{random.randint(0, 999999):06d}"
        s["subscription_active"] = True
        s["subscription_expires_at"] = datetime.utcnow() + timedelta(days=365)
        provider = Provider(**s)
        db.session.add(provider)
        db.session.flush()
        for name, price in svc_list:
            db.session.add(Service(provider_id=provider.id, name=name, price=price))
    db.session.commit()
    return jsonify({"status": "seeded", "providers": len(samples)})


# ---------- Facebook Messenger webhook ----------

@app.route("/webhook", methods=["GET"])
def messenger_verify():
    from messenger import VERIFY_TOKEN
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def messenger_webhook():
    from messenger import handle_message
    payload = request.get_json(silent=True) or {}
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            if not sender_id:
                continue
            if "message" in event:
                text = event["message"].get("text")
                quick_reply = event["message"].get("quick_reply", {}).get("payload")
                handle_message(sender_id, text=text, payload=quick_reply)
            elif "postback" in event:
                payload_str = event["postback"].get("payload")
                handle_message(sender_id, payload=payload_str)
    return "OK", 200


@app.route("/admin/activate/<int:provider_id>")
def admin_activate_subscription(provider_id):
    """Manually activate a provider's paid subscription after you've confirmed
    their GCash payment. Protected by a secret in the URL so randos can't
    activate themselves for free — set ADMIN_SECRET on Render and use:
    /admin/activate/<id>?secret=yoursecret"""
    admin_secret = os.environ.get("ADMIN_SECRET", "changeme")
    if request.args.get("secret") != admin_secret:
        return "Forbidden", 403
    provider = Provider.query.get_or_404(provider_id)
    provider.subscription_active = True
    provider.subscription_expires_at = datetime.utcnow() + timedelta(days=30)
    db.session.commit()
    return jsonify({
        "status": "activated",
        "provider": provider.business_name,
        "expires_at": provider.subscription_expires_at.isoformat(),
    })


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
