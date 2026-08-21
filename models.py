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

    booking_date = db.Column(db.String(10), nullable=False)   # YYYY-MM-DD
    booking_time = db.Column(db.String(10), nullable=False)   # HH:MM

    status = db.Column(db.String(20), default="pending")      # pending/confirmed/declined/completed/cancelled
    notes = db.Column(db.String(255))
    quoted_price = db.Column(db.Float)                        # used when service is quote_only

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
