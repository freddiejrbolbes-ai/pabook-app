"""
PaBook Messenger Chatbot
------------------------
Handles Facebook Messenger conversations: browsing providers, picking a
service, and creating a booking — all through chat, no app/website needed
on the customer's side.

Conversation state per user is stored in the ChatSession table (models.py)
so it survives server restarts (important on Render's free tier, which
sleeps and restarts the app).
"""

import os
import json
import requests
from models import db, Provider, Service, Booking, CATEGORIES

PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "pabook-verify")
GRAPH_API_URL = "https://graph.facebook.com/v19.0/me/messages"


# ---------- low-level send helpers ----------

def send_text(recipient_id, text):
    _call_send_api({
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    })


def send_quick_replies(recipient_id, text, options):
    """options: list of (title, payload) tuples, max 13"""
    quick_replies = [
        {"content_type": "text", "title": title[:20], "payload": payload}
        for title, payload in options[:13]
    ]
    _call_send_api({
        "recipient": {"id": recipient_id},
        "message": {"text": text, "quick_replies": quick_replies},
    })


def send_button_list(recipient_id, providers):
    """Sends up to 3 providers as a generic template carousel with a 'Piliin' button each."""
    elements = []
    for p in providers[:10]:
        label, icon = p.category_label()
        elements.append({
            "title": p.business_name[:80],
            "subtitle": f"⭐ {p.rating} · {p.barangay} · {label}",
            "buttons": [{
                "type": "postback",
                "title": "Piliin ito",
                "payload": f"PICK_PROVIDER_{p.id}",
            }],
        })
    if not elements:
        send_text(recipient_id, "Wala pang provider sa category na ito.")
        return
    _call_send_api({
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {"template_type": "generic", "elements": elements},
            }
        },
    })


def _call_send_api(payload):
    if not PAGE_ACCESS_TOKEN:
        print(f"[messenger] Skipped send — PAGE_ACCESS_TOKEN not set. Payload: {json.dumps(payload)[:200]}")
        return
    try:
        r = requests.post(
            GRAPH_API_URL,
            params={"access_token": PAGE_ACCESS_TOKEN},
            json=payload,
            timeout=10,
        )
        if r.status_code != 200:
            print(f"[messenger] Send failed: {r.status_code} {r.text}")
    except Exception as e:
        print(f"[messenger] Send error: {e}")


# ---------- conversation state ----------

def get_session(sender_id):
    from models import ChatSession
    session = ChatSession.query.filter_by(sender_id=sender_id).first()
    if not session:
        session = ChatSession(sender_id=sender_id, state="start", data="{}")
        db.session.add(session)
        db.session.commit()
    return session


def set_session(session, state, data=None):
    session.state = state
    if data is not None:
        session.data = json.dumps(data)
    db.session.commit()


def get_data(session):
    try:
        return json.loads(session.data or "{}")
    except Exception:
        return {}


# ---------- main conversation logic ----------

def handle_message(sender_id, text=None, payload=None):
    from models import ChatSession
    session = get_session(sender_id)
    data = get_data(session)
    text_lower = (text or "").strip().lower()

    # Global resets
    if payload == "GET_STARTED" or text_lower in ("start", "simula", "book", "book now"):
        show_categories(sender_id, session)
        return

    if payload and payload.startswith("CATEGORY_"):
        category = payload.replace("CATEGORY_", "")
        show_providers(sender_id, session, category)
        return

    if payload and payload.startswith("PICK_PROVIDER_"):
        provider_id = int(payload.replace("PICK_PROVIDER_", ""))
        show_services(sender_id, session, provider_id)
        return

    if payload and payload.startswith("PICK_SERVICE_"):
        service_id = int(payload.replace("PICK_SERVICE_", ""))
        data["service_id"] = service_id
        set_session(session, "awaiting_name", data)
        send_text(sender_id, "Ano ang pangalan mo?")
        return

    # Free-text steps based on current state
    if session.state == "awaiting_name" and text:
        data["customer_name"] = text.strip()
        set_session(session, "awaiting_phone", data)
        send_text(sender_id, "Salamat! Ano ang contact number mo?")
        return

    if session.state == "awaiting_phone" and text:
        data["customer_phone"] = text.strip()
        set_session(session, "awaiting_date", data)
        send_text(sender_id, "Kailan mo gustong i-book? (halimbawa: Aug 25)")
        return

    if session.state == "awaiting_date" and text:
        data["booking_date"] = text.strip()
        set_session(session, "awaiting_time", data)
        send_text(sender_id, "Anong oras? (halimbawa: 2:00 PM)")
        return

    if session.state == "awaiting_time" and text:
        data["booking_time"] = text.strip()
        finalize_booking(sender_id, session, data)
        return

    # Default / fallback
    send_quick_replies(
        sender_id,
        "Kumusta! Ako si PaBook Assistant 🤖 Ano ang gusto mong gawin?",
        [("Mag-book ngayon", "GET_STARTED")],
    )


def show_categories(sender_id, session):
    set_session(session, "choosing_category", {})
    options = [(f"{icon} {label.split(' ')[0]}", f"CATEGORY_{key}") for key, label, icon in CATEGORIES]
    send_quick_replies(sender_id, "Anong klaseng serbisyo ang hinahanap mo?", options)


def show_providers(sender_id, session, category):
    providers = Provider.query.filter_by(category=category, status="active").all()
    data = get_data(session)
    data["category"] = category
    set_session(session, "choosing_provider", data)
    send_button_list(sender_id, providers)


def show_services(sender_id, session, provider_id):
    provider = Provider.query.get(provider_id)
    if not provider:
        send_text(sender_id, "Pasensya, hindi nahanap ang provider na iyon.")
        return
    data = get_data(session)
    data["provider_id"] = provider_id
    set_session(session, "choosing_service", data)

    services = Service.query.filter_by(provider_id=provider.id, active=True).all()
    if not services:
        send_text(sender_id, f"Wala pang listed na services si {provider.business_name}.")
        return
    options = []
    for s in services:
        price_label = f"₱{s.price:.0f}" if s.price else "Quote"
        options.append((f"{s.name[:15]} ({price_label})", f"PICK_SERVICE_{s.id}"))
    send_quick_replies(sender_id, f"Anong serbisyo gusto mo kay {provider.business_name}?", options)


def finalize_booking(sender_id, session, data):
    provider = Provider.query.get(data.get("provider_id"))
    service = Service.query.get(data.get("service_id"))

    booking = Booking(
        provider_id=provider.id,
        service_id=service.id if service else None,
        customer_name=data.get("customer_name", "Messenger Customer"),
        customer_phone=data.get("customer_phone", ""),
        booking_date=data.get("booking_date", ""),
        booking_time=data.get("booking_time", ""),
        notes="Booked via Messenger",
        status="pending",
    )
    db.session.add(booking)
    db.session.commit()

    set_session(session, "start", {})

    send_text(
        sender_id,
        f"✅ Na-submit na ang booking mo!\n\n"
        f"Negosyo: {provider.business_name}\n"
        f"Serbisyo: {service.name if service else 'N/A'}\n"
        f"Petsa: {data.get('booking_date')}\n"
        f"Oras: {data.get('booking_time')}\n\n"
        f"Status: Pending — maghintay ka na lang ng kumpirmasyon mula sa provider.",
    )

    # Try to notify the provider by email too, if mailer is configured
    try:
        from mailer import send_new_booking_alert_to_provider
        send_new_booking_alert_to_provider(
            provider_email=provider.email,
            provider_name=provider.business_name,
            customer_name=booking.customer_name,
            customer_phone=booking.customer_phone,
            service_name=service.name if service else "N/A",
            booking_date=booking.booking_date,
            booking_time=booking.booking_time,
            notes=booking.notes,
        )
    except Exception as e:
        print(f"[messenger] Email notify skipped: {e}")
