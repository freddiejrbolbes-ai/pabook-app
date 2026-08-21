# PaBook — Multi-Service Booking App (MVP Demo)

Booking platform para sa lokal na service providers (salon, barbershop,
electrician, mekaniko). Ang bawat provider ay sila mismo mag-se-self-setup
ng sarili nilang presyo, services, lokasyon (with GPS radius), at oras ng
bukas — parang self-onboarding SaaS, hindi ikaw ang gagawa ng site per client.

## Paano patakbuhin lokal

```
pip install -r requirements.txt
python app.py
```

Pagkatapos, buksan ang browser sa http://localhost:5000

Para ma-populate ng SAMPLE data (4 sample providers — barbershop, salon,
electrician, mekaniko) na parang totoong negosyo:

```
http://localhost:5000/dev/seed
```
(Isang beses lang ito i-visit — wiwipe-clean nito yung DB bawat tawag.)

## Mga pangunahing pages

- `/` — home / browse ng customer, by category, by distance
- `/provider/<id>` — public profile ng isang provider (services + presyo)
- `/book/<id>` — booking form (date, time, contact info)
- `/provider/setup` — **ito yung ibebenta mo** — self-onboarding form kung
  saan mag-se-setup ang bagong negosyo (presyo, lokasyon, oras)
- `/provider/<id>/dashboard` — dashboard ng provider — makikita bookings,
  pwedeng i-accept/i-decline

## Deploy sa Render

1. I-push ang folder na ito sa isang GitHub repo
2. Sa Render: New → Web Service → connect sa repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add environment variable kung gusto mo ng production DB (PostgreSQL) —
   sa ngayon SQLite muna ang default, ok lang para sa demo/MVP

## Susunod na dapat idagdag (para maging totoong bentable na product)

- Login/password para sa providers (ngayon, kahit sino makaka-access sa
  dashboard kung alam yung provider ID sa URL — kailangan i-secure ito)
- SMS notifications (Twilio) — kasalukuyan wala pang aktwal na SMS na
  pinapadala, "confirmation page" lang muna
- Payment integration para sa monthly subscription (GCash/PayMongo)
- Presyo ng distance filter — kasalukuyan gumagamit ng default na
  Kapalong coordinates kung walang GPS location ang customer; pwede
  palitan ng browser geolocation API
