from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta
from models import db, Provider, Service, Booking, CATEGORIES, PACKAGE_TIERS

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///pabook.db"
app.config["SECRET_KEY"] = "dev-secret-change-in-production"
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
            booking_date=request.form["booking_date"],
            booking_time=request.form["booking_time"],
            notes=request.form.get("notes", ""),
            status="pending",
        )
        db.session.add(booking)
        db.session.commit()
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


# ---------- provider self-setup (this is what you SELL) ----------

@app.route("/provider/setup", methods=["GET", "POST"])
def provider_setup():
    if request.method == "POST":
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
            status="active",  # auto-activate for MVP; in production this waits for payment confirmation
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

        flash(f"Live na ang {provider.business_name}! Makikita ka na sa search.", "success")
        return redirect(url_for("provider_dashboard", provider_id=provider.id))

    return render_template("provider_setup.html", categories=CATEGORIES, tiers=PACKAGE_TIERS)


# ---------- provider dashboard ----------

@app.route("/provider/<int:provider_id>/dashboard")
def provider_dashboard(provider_id):
    provider = Provider.query.get_or_404(provider_id)
    bookings = Booking.query.filter_by(provider_id=provider.id).order_by(Booking.booking_date, Booking.booking_time).all()
    pending = [b for b in bookings if b.status == "pending"]
    confirmed = [b for b in bookings if b.status == "confirmed"]
    today_str = datetime.now().strftime("%Y-%m-%d")
    earnings_today = sum((b.service.price or b.quoted_price or 0) for b in bookings
                         if b.booking_date == today_str and b.status in ("confirmed", "completed") and b.service)
    return render_template("provider_dashboard.html", provider=provider, pending=pending,
                            confirmed=confirmed, earnings_today=earnings_today, today_str=today_str)


@app.route("/booking/<int:booking_id>/status", methods=["POST"])
def update_booking_status(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    new_status = request.form.get("status")
    if new_status in ("confirmed", "declined", "completed", "cancelled"):
        booking.status = new_status
        db.session.commit()
    return redirect(url_for("provider_dashboard", provider_id=booking.provider_id))


# ---------- seed sample data (so you have a working demo) ----------

@app.route("/dev/seed")
def dev_seed():
    """Wipes and re-seeds sample providers so there's a working demo.
    Visit /dev/seed once after first run."""
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
    ]

    for s in samples:
        svc_list = s.pop("services")
        provider = Provider(**s)
        db.session.add(provider)
        db.session.flush()
        for name, price in svc_list:
            db.session.add(Service(provider_id=provider.id, name=name, price=price))
    db.session.commit()
    return jsonify({"status": "seeded", "providers": len(samples)})


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
