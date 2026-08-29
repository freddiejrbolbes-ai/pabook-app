from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import math

db = SQLAlchemy()

CATEGORIES = [
    ("salon", "Salon", "💇"),
    ("barber", "Barbershop", "💈"),
    ("electrician", "Electrician", "🔌"),
    ("mekaniko", "Mekaniko / Auto Repair", "🔧"),
    ("nails", "Nail Salon", "💅"),
    ("trucking", "Transportation / Lipat-bahay", "🚚"),
    ("paupahan", "Paupahan (Bahay/Apartment)", "🏠"),
    ("renttoown", "Rent-to-Own", "🔑"),
    ("laundry", "Laundry", "🧺"),
    ("aircon", "Aircon Cleaning/Repair", "❄️"),
    ("cleaning", "Cleaning Services", "🧹"),
    ("catering", "Catering / Events", "🍽️"),
    ("tutor", "Tutor", "📚"),
    ("gadget", "Cellphone/Computer Repair", "📱"),       
    ("store", "Store / Retail / Wholesale", "🛒"),
    ("plumbing", "Plumbing", "🔧"),
    ("carpenter", "Carpenter / Kahoy", "🪚"),
]

PACKAGE_TIERS = {
    "starter":  {"label": "Starter",  "monthly_fee": 300,  "setup_fee": 2500, "max_services": 10, "featured": False},
    "standard": {"label": "Standard", "monthly_fee": 600,  "setup_fee": 4000, "max_services": 25, "featured": False},
    "premium":  {"label": "Premium",  "monthly_fee": 1000, "setup_fee": 6000, "max_services": 999, "featured": True},
}


class Provider(db.Model):
    __tablename__ = "providers"

    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(30), nullable=False)          # matches CATEGORIES key
    owner_name = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))

    # Location
    address_text = db.Column(db.String(255))
    barangay = db.Column(db.String(120))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    service_radius_km = db.Column(db.Float, default=3.0)

    # Hours (simple text for MVP, e.g. "09:00", "19:00")
    hours_open = db.Column(db.String(10), default="09:00")
    hours_close = db.Column(db.String(10), default="18:00")
    days_open = db.Column(db.String(30), default="Mon-Sat")       # e.g. "Mon-Sat"
    closed_sunday = db.Column(db.Boolean, default=True)

    # Business / billing
    package_tier = db.Column(db.String(20), default="starter")   # starter/standard/premium
    status = db.Column(db.String(20), default="pending")         # pending/active/suspended
    quote_only = db.Column(db.Boolean, default=False)            # True for electrician/mekaniko-style variable pricing

    # Subscription / trial gating — providers need an active trial or paid
    # subscription to appear in search and access their dashboard. Customers
    # never need any of this — booking always stays free and passwordless.
    access_code = db.Column(db.String(10))                       # PIN providers use to open their dashboard
    trial_ends_at = db.Column(db.DateTime)                       # set on signup: now + 15 days
    subscription_active = db.Column(db.Boolean, default=False)   # True once they've paid
    subscription_expires_at = db.Column(db.DateTime)             # renews monthly once paid

    rating = db.Column(db.Float, default=5.0)
    review_count = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    services = db.relationship("Service", backref="provider", cascade="all, delete-orphan")
    bookings = db.relationship("Booking", backref="provider", cascade="all, delete-orphan")

    def distance_km(self, lat, lng):
        """Straight-line distance using haversine formula."""
        if self.latitude is None or self.longitude is None or lat is None or lng is None:
            return None
        R = 6371
        dlat = math.radians(self.latitude - lat)
        dlng = math.radians(self.longitude - lng)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat)) * math.cos(math.radians(self.latitude))
             * math.sin(dlng / 2) ** 2)
        c = 2 * math.asin(math.sqrt(a))
        return round(R * c, 2)

    def category_label(self):
        for key, label, icon in CATEGORIES:
            if key == self.category:
                return label, icon
        return self.category, "🏪"

    def tier_info(self):
        return PACKAGE_TIERS.get(self.package_tier, PACKAGE_TIERS["starter"])

    def has_access(self):
        return True  # PROMO: libre muna lahat, walang expiration habang wala pang bayad
        """True if provider can appear in search + open their dashboard —
        either still inside their 15-day free trial, or has an active paid
        subscription that hasn't expired."""
        now = datetime.utcnow()
        if self.trial_ends_at and now <= self.trial_ends_at:
            return True
        if self.subscription_active and self.subscription_expires_at and now <= self.subscription_expires_at:
            return True
        return False

    def is_on_trial(self):
        now = datetime.utcnow()
        return bool(self.trial_ends_at and now <= self.trial_ends_at and not (self.subscription_active and self.subscription_expires_at and now <= self.subscription_expires_at))

    def days_left_in_trial(self):
        if not self.trial_ends_at:
            return 0
        delta = self.trial_ends_at - datetime.utcnow()
        return max(0, delta.days)


class Service(db.Model):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("providers.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    price = db.Column(db.Float)               # nullable if quote_only
    duration_minutes = db.Column(db.Integer, default=30)
    active = db.Column(db.Boolean, default=True)

    bookings = db.relationship("Booking", backref="service")


class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("providers.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=True)

    customer_name = db.Column(db.String(120), nullable=False)
    customer_phone = db.Column(db.String(30), nullable=False)
    customer_email = db.Column(db.String(120))

    booking_date = db.Column(db.String(10), nullable=False)   # YYYY-MM-DD
    booking_time = db.Column(db.String(10), nullable=False)   # HH:MM

    status = db.Column(db.String(20), default="pending")      # pending/confirmed/declined/completed/cancelled
    notes = db.Column(db.String(255))
    quoted_price = db.Column(db.Float)                        # used when service is quote_only

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChatSession(db.Model):
    __tablename__ = "chat_sessions"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.String(64), unique=True, nullable=False)  # Facebook PSID
    state = db.Column(db.String(30), default="start")
    data = db.Column(db.Text, default="{}")  # JSON blob: category, provider_id, service_id, etc.
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
