# Emergency Blood Finder

A beginner-friendly Flask and SQLite college project for coordinating local blood donors and emergency requests. This is an application prototype, not a medical compatibility or eligibility service.

## Features

- Donor registration with hashed passwords and availability control
- Session-based user login, profile ownership, request tracking, and notifications
- Donor search by blood group, city, and availability; available donors are the default
- Quick Match orders available donors by exact city, availability, and newest registration
- Emergency requests with required/expiry date-times and Critical, Urgent, and Normal priority
- Request status timeline with owner-only status and expiry notifications
- Explicit read/unread notification controls and admin broadcast messages
- City-center-only donor map markers; home coordinates are not shown
- Separate protected administrator login and dashboard
- Admin donor search/edit/update/delete and request status management
- Optional Gmail SMTP notifications through environment variables

## Technologies and structure

`app.py` contains routes and permission decorators. `database.py` creates the SQLite schema and preserves the original starter donor records. `email_service.py` is the optional SMTP integration. Jinja templates are in `templates/`, while the responsive CSS and vanilla JavaScript are in `static/`.

Tables: `users`, `requests`, `notifications`, `admin`, plus the original `donors` table retained for migration compatibility.

## Install and run

```powershell
cd "Emergency Blood Donor Finder"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

The entry point is `main.py`; run `python main.py`. It starts at http://127.0.0.1:5000. The database is created automatically.

## Main routes

- `/` — project home
- `/register`, `/login` — donor account access
- `/dashboard` — user dashboard and availability control
- `/find-donor`, `/quick-match`, `/map` — donor search and city-level matching/map
- `/request-blood`, `/my-requests`, `/notifications` — request workflow and alerts
- `/admin/login`, `/admin` — administrator login and dashboard
- `/admin/donors`, `/admin/requests`, `/admin/notifications` — protected management tools

Existing `blood_finder.db` data is preserved. Startup applies only additive schema migrations for required request time and notification category; it does not recreate or delete donor rows.

## Admin setup

On the first start, the app seeds an administrator from `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `ADMIN_EMAIL` in `.env`. The development defaults are `admin` and `admin123`; change them before sharing the project. Open `/admin/login` and use those values. Normal user sessions cannot access admin routes, even by manually entering their URLs.

## Gmail setup

Use a Gmail account with 2-Step Verification and an App Password. Put the values in `.env` as `ADMIN_EMAIL`, `EMAIL_USERNAME`, and `EMAIL_APP_PASSWORD`. Never place the app password in Python, templates, screenshots, or source control. Email sending is optional and safely skips itself when configuration is missing.

## Testing checklist

The application was exercised with Flask's test client against an isolated temporary SQLite database. For a manual pass, test registration, login/logout, own-profile and availability updates, donor filters, Quick Match, map, all emergency levels and request priority, required/expiry validation, status timeline, expiry, notification read controls, admin donor/request editing and deletion, broadcasts, and denial of admin actions from a normal account. Use dummy data only.

## Viva notes

The objective is a small emergency coordination workflow. Flask provides simple Python routing and sessions; SQLite is easy to inspect and deploy for a college prototype. Passwords use Werkzeug hashing, parameterized SQL protects database queries, and decorators enforce user/admin boundaries on the server. Quick Match sorts matching available donors at the application level; it does not make medical compatibility decisions. Request priorities order Critical, Urgent, then Normal, while the timeline tracks progress and expiry. Notifications are scoped to their owner, and map markers use approximate city centers. Future enhancements could include CSRF protection, audited admin actions, stronger deployment configuration, and a real notification queue.
