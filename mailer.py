import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Credentials are read from environment variables (set on Render dashboard,
# NEVER hardcoded here) so they don't get exposed in the public GitHub repo.
EMAIL_USER = os.environ.get("EMAIL_USER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


def send_email(to_address, subject, body_html):
    """Sends an email. Silently skips (logs a warning) if credentials aren't
    configured yet, so the rest of the app keeps working during setup."""
    if not EMAIL_USER or not EMAIL_PASSWORD:
        print(f"[email] Skipped — EMAIL_USER/EMAIL_PASSWORD not set. Would have sent to {to_address}: {subject}")
        return False
    if not to_address:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"PaBook <{EMAIL_USER}>"
    msg["To"] = to_address
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_USER, to_address, msg.as_string())
        print(f"[email] Sent to {to_address}: {subject}")
        return True
    except Exception as e:
        print(f"[email] FAILED to send to {to_address}: {e}")
        return False


def send_booking_confirmation_to_customer(customer_email, customer_name, provider_name, service_name, booking_date, booking_time):
    if not customer_email:
        return
    subject = f"Booking request natanggap — {provider_name}"
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;">
      <h2 style="color:#0F3D3E;">PaBook</h2>
      <p>Kumusta {customer_name},</p>
      <p>Natanggap na namin ang booking request mo:</p>
      <table style="width:100%;border-collapse:collapse;margin:16px 0;">
        <tr><td style="padding:6px 0;color:#8B8368;">Negosyo</td><td><b>{provider_name}</b></td></tr>
        <tr><td style="padding:6px 0;color:#8B8368;">Serbisyo</td><td>{service_name}</td></tr>
        <tr><td style="padding:6px 0;color:#8B8368;">Petsa</td><td>{booking_date}</td></tr>
        <tr><td style="padding:6px 0;color:#8B8368;">Oras</td><td>{booking_time}</td></tr>
      </table>
      <p>Status: <b style="color:#C24A3B;">Pending</b> — maghihintay ka na lang ng kumpirmasyon mula sa provider.</p>
      <p style="color:#8B8368;font-size:12px;">— PaBook</p>
    </div>
    """
    send_email(customer_email, subject, body)


def send_new_booking_alert_to_provider(provider_email, provider_name, customer_name, customer_phone, service_name, booking_date, booking_time, notes):
    if not provider_email:
        return
    subject = f"Bagong booking mula kay {customer_name}"
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;">
      <h2 style="color:#0F3D3E;">PaBook</h2>
      <p>Kumusta {provider_name},</p>
      <p>May bagong booking request ka:</p>
      <table style="width:100%;border-collapse:collapse;margin:16px 0;">
        <tr><td style="padding:6px 0;color:#8B8368;">Customer</td><td><b>{customer_name}</b></td></tr>
        <tr><td style="padding:6px 0;color:#8B8368;">Contact</td><td>{customer_phone}</td></tr>
        <tr><td style="padding:6px 0;color:#8B8368;">Serbisyo</td><td>{service_name}</td></tr>
        <tr><td style="padding:6px 0;color:#8B8368;">Petsa</td><td>{booking_date}</td></tr>
        <tr><td style="padding:6px 0;color:#8B8368;">Oras</td><td>{booking_time}</td></tr>
        {"<tr><td style='padding:6px 0;color:#8B8368;'>Note</td><td>" + notes + "</td></tr>" if notes else ""}
      </table>
      <p>I-login sa dashboard mo para i-accept o i-decline.</p>
      <p style="color:#8B8368;font-size:12px;">— PaBook</p>
    </div>
    """
    send_email(provider_email, subject, body)


def send_provider_welcome_email(provider_email, business_name, package_label):
    if not provider_email:
        return
    subject = f"Live ka na sa PaBook — {business_name}"
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;">
      <h2 style="color:#0F3D3E;">PaBook</h2>
      <p>Maligayang pagdating, {business_name}!</p>
      <p>Live na ang profile mo sa PaBook ({package_label} package). Makikita ka na ngayon ng mga customer sa search.</p>
      <p style="color:#8B8368;font-size:12px;">— PaBook</p>
    </div>
    """
    send_email(provider_email, subject, body)
