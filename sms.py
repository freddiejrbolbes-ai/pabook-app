import os
import requests

SEMAPHORE_API_KEY = os.environ.get("SEMAPHORE_API_KEY", "")
SEMAPHORE_URL = "https://api.semaphore.co/api/v4/messages"
SENDER_NAME = os.environ.get("SEMAPHORE_SENDER_NAME", "SEMAPHORE")

def send_sms(number, message):
    """Sends an SMS via Semaphore. Silently skips (logs a warning) if the
    API key isn't configured yet, so the rest of the app keeps working."""
    if not SEMAPHORE_API_KEY:
        print(f"[sms] Skipped - SEMAPHORE_API_KEY not set. Would have sent to {number}: {message}")
        return False
    if not number:
        return False
    try:
        response = requests.post(SEMAPHORE_URL, data={
            "apikey": SEMAPHORE_API_KEY,
            "number": number,
            "message": message,
            "sendername": SENDER_NAME,
        }, timeout=10)
        if response.status_code == 200:
            print(f"[sms] Sent to {number}")
            return True
        print(f"[sms] Failed to send to {number}: {response.status_code} {response.text}")
        return False
    except Exception as e:
        print(f"[sms] Error sending to {number}: {e}")
        return False

def send_new_booking_sms_to_provider(provider_phone, provider_name, customer_name,
                                      customer_phone, service_name, booking_date, booking_time):
    """Notifies the business owner via SMS about a new booking request."""
    message = (
        f"PaBook: Bagong booking sa {provider_name}! "
        f"{customer_name} ({customer_phone}) - {service_name}, "
        f"{booking_date} {booking_time}. Tignan ang dashboard mo para mag-Accept."
    )
    return send_sms(provider_phone, message)
