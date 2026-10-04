"""Emergency Blood Finder - simple Flask college project."""

import os
import re
import sqlite3
import json
from datetime import datetime
from functools import wraps
from flask import Flask, flash, redirect, render_template, request, session, url_for
from markupsafe import escape
from werkzeug.security import check_password_hash, generate_password_hash
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False

from database import get_db_connection, init_db
from email_service import send_email

load_dotenv()


app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "development-only-change-me")
BLOOD_GROUPS = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")
EMERGENCY_LEVELS = ("Normal", "Urgent", "Critical")
SUPPORT_CATEGORIES = ("Account", "Blood request", "Donor match", "Technical issue", "General support")
SUPPORT_STATUSES = ("Open", "In Progress", "Waiting for user", "Waiting for admin", "Resolved", "Closed")
STATUSES = ("Request Created", "Searching Donor", "Donor Responded", "Blood Arranged", "Request Closed", "Request Expired")
CITY_COORDINATES = {
    "salem": (11.6643, 78.1460), "erode": (11.3410, 77.7172), "chennai": (13.0827, 80.2707),
    "coimbatore": (11.0168, 76.9558), "madurai": (9.9252, 78.1198), "trichy": (10.7905, 78.7047),
    "tiruchirappalli": (10.7905, 78.7047), "vellore": (12.9165, 79.1325),
    "komarapalayam": (11.4390, 77.7260), "konganapuram": (11.5720, 77.8840),
}


def city_coordinates(city):
    """Return approximate city-centre coordinates, never an exact address."""
    return CITY_COORDINATES.get(city.strip().lower(), (11.1271, 78.6569))


def parse_datetime(value):
    try:
        return datetime.fromisoformat((value or "").strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def datetime_local_value(value):
    parsed = parse_datetime(value)
    return parsed.strftime("%Y-%m-%dT%H:%M") if parsed else ""


def add_notification(connection, user_id, message, category="general"):
    connection.execute(
        "INSERT INTO notifications (user_id, message, category) VALUES (?, ?, ?)",
        (user_id, message, category),
    )


def log_admin_action(connection, admin_id, action, target_user_id=None, details=None):
    connection.execute(
        "INSERT INTO admin_audit_logs (admin_id, action, target_user_id, details) VALUES (?, ?, ?, ?)",
        (admin_id, action, target_user_id, details or ""),
    )


def validate_request_form(form):
    try:
        units = int(form.get("units", "0"))
    except (TypeError, ValueError):
        units = 0
    blood_group = form.get("blood_group", "").strip()
    city = form.get("city", "").strip()
    emergency = form.get("emergency", "").strip()
    required_at = parse_datetime(form.get("required_at", ""))
    expiry_at = parse_datetime(form.get("expiry_at", ""))
    now = datetime.now().replace(second=0, microsecond=0)
    errors = []
    if blood_group not in BLOOD_GROUPS:
        errors.append("Please select a valid blood group.")
    if not city or len(city) > 100:
        errors.append("Please enter a valid city.")
    if units < 1 or units > 100:
        errors.append("Units must be between 1 and 100.")
    if emergency not in EMERGENCY_LEVELS:
        errors.append("Please select a valid emergency level.")
    if not required_at or not expiry_at:
        errors.append("Enter valid required and expiry date/time values.")
    elif required_at.tzinfo or expiry_at.tzinfo:
        errors.append("Use local date/time values.")
    elif required_at < now or expiry_at <= now or expiry_at < required_at:
        errors.append("Required time must be now or later, and expiry must be after the required time.")
    return errors, {
        "blood_group": blood_group,
        "city": city,
        "units": units,
        "emergency": emergency,
        "required_at": required_at.isoformat(timespec="minutes") if required_at else "",
        "expiry_at": expiry_at.isoformat(timespec="minutes") if expiry_at else "",
    }


def user_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            flash("Administrator access is required.", "error")
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_globals():
    connection = get_db_connection()
    try:
        unread = connection.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0", (session.get("user_id", 0),)).fetchone()[0]
    finally:
        connection.close()
    return {"blood_groups": BLOOD_GROUPS, "emergency_levels": EMERGENCY_LEVELS, "statuses": STATUSES, "unread_count": unread}


@app.route("/")
def home():
    connection = get_db_connection()
    try:
        donor_count = connection.execute("SELECT COUNT(*) FROM users WHERE available = 1").fetchone()[0]
    finally:
        connection.close()
    return render_template("index.html", donor_count=donor_count)


@app.route("/find-donor")
def find_donor():
    selected_group = request.args.get("blood_group", "").strip()
    selected_city = request.args.get("city", "").strip()
    selected_availability = request.args.get("availability", "available").strip()
    has_searched = request.args.get("search") == "1" or bool(selected_group or selected_city)
    donors = []

    if has_searched:
        query = "SELECT id, name, blood_group, city, available FROM users WHERE 1=1"
        parameters = []
        if selected_availability == "unavailable":
            query += " AND available = 0"
        elif selected_availability != "all":
            query += " AND available = 1"
        if selected_group:
            query += " AND blood_group = ?"
            parameters.append(selected_group)
        if selected_city:
            query += " AND LOWER(city) LIKE LOWER(?)"
            parameters.append(f"%{selected_city}%")
        query += " ORDER BY created_at DESC"

        connection = get_db_connection()
        try:
            donors = connection.execute(query, parameters).fetchall()
        finally:
            connection.close()

    return render_template(
        "find_donor.html",
        donors=donors,
        selected_group=selected_group,
        selected_city=selected_city,
        selected_availability=selected_availability,
        has_searched=has_searched,
    )


@app.route("/quick-match", methods=["GET", "POST"])
@user_required
def quick_match():
    selected_group = request.values.get("blood_group", "").strip()
    selected_city = request.values.get("city", "").strip()
    donors = []
    has_searched = request.method == "POST" or bool(selected_group or selected_city)
    if has_searched and selected_group in BLOOD_GROUPS and selected_city:
        connection = get_db_connection()
        donors = connection.execute(
            "SELECT id, name, blood_group, city, available FROM users "
            "WHERE available = 1 AND blood_group = ? AND LOWER(city) LIKE LOWER(?) "
            "ORDER BY CASE WHEN LOWER(city) = LOWER(?) THEN 0 ELSE 1 END, available DESC, created_at DESC",
            (selected_group, f"%{selected_city}%", selected_city),
        ).fetchall()
        connection.close()
    elif has_searched:
        flash("Select a blood group and enter a city to use Quick Match.", "error")
    return render_template(
        "quick_match.html", donors=donors, selected_group=selected_group,
        selected_city=selected_city, has_searched=has_searched,
    )


@app.get("/map")
def donor_map():
    selected_group = request.args.get("blood_group", "").strip()
    selected_city = request.args.get("city", "").strip()
    query = "SELECT id, name, blood_group, city, available, latitude, longitude FROM users WHERE 1=1"
    if not session.get("admin_id"):
        query += " AND available = 1"
    parameters = []
    if selected_group:
        query += " AND blood_group = ?"
        parameters.append(selected_group)
    if selected_city:
        query += " AND LOWER(city) LIKE LOWER(?)"
        parameters.append(f"%{selected_city}%")
    query += " ORDER BY name COLLATE NOCASE"
    connection = get_db_connection()
    donors = connection.execute(query, parameters).fetchall()
    connection.close()
    marker_data = []
    for donor in donors:
        item = dict(donor)
        item["latitude"], item["longitude"] = city_coordinates(item["city"])
        item["name"] = str(escape(item["name"]))
        item["city"] = str(escape(item["city"]))
        marker_data.append(item)
    marker_json = json.dumps(marker_data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return render_template("map.html", donors=marker_data, selected_group=selected_group, selected_city=selected_city, marker_json=marker_json)


@app.route("/register", methods=["GET", "POST"])
def register():
    form_data = {"name": "", "email": "", "password": "", "blood_group": "", "phone": "", "city": "", "available": "1"}
    if request.method == "POST":
        form_data = {field: request.form.get(field, "").strip() for field in form_data}
        errors = []
        if not all(form_data[field] for field in ("name", "email", "password", "blood_group", "phone", "city")):
            errors.append("Please complete every field.")
        if len(form_data["name"]) > 100 or not re.fullmatch(r"[\w .'-]+", form_data["name"], re.UNICODE):
            errors.append("Please enter a valid name (up to 100 characters).")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", form_data["email"]):
            errors.append("Please enter a valid email address.")
        if form_data["blood_group"] not in BLOOD_GROUPS:
            errors.append("Please select a valid blood group.")
        if form_data["phone"] and not re.fullmatch(r"[+()\-\s\d]{7,20}", form_data["phone"]):
            errors.append("Please enter a valid phone number.")
        if not form_data["city"] or len(form_data["city"]) > 100:
            errors.append("Please enter a valid city (up to 100 characters).")
        if len(form_data["password"]) < 6:
            errors.append("Password must be at least 6 characters.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("register.html", form_data=form_data)

        connection = get_db_connection()
        try:
            connection.execute(
                "INSERT INTO users (name, email, password_hash, blood_group, city, phone, available, latitude, longitude) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (form_data["name"], form_data["email"].lower(), generate_password_hash(form_data["password"]), form_data["blood_group"], form_data["city"], form_data["phone"], int(form_data["available"] == "1"), *city_coordinates(form_data["city"])),
            )
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            flash("That email is already registered. Please log in instead.", "error")
            return render_template("register.html", form_data=form_data)
        except sqlite3.Error:
            connection.rollback()
            flash("We could not save your registration. Please try again.", "error")
            return render_template("register.html", form_data=form_data)
        finally:
            connection.close()

        flash("Registration successful. Please log in.", "success")
        send_email("New donor registration", f"A new donor registered: {form_data['name']} ({form_data['blood_group']}, {form_data['city']}).")
        return redirect(url_for("login"))

    return render_template("register.html", form_data=form_data)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        connection = get_db_connection()
        user = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        connection.close()
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html", email=email)
        session.clear(); session["user_id"] = user["id"]
        return redirect(url_for("dashboard"))
    return render_template("login.html", email="")


@app.get("/logout")
def logout():
    session.clear(); flash("You have been logged out.", "success"); return redirect(url_for("home"))


@app.get("/dashboard")
@user_required
def dashboard():
    connection = get_db_connection()
    user = connection.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    refresh_expired(connection)
    stats = {
        "available_donors": connection.execute("SELECT COUNT(*) FROM users WHERE available = 1").fetchone()[0],
        "requests": connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
        "critical": connection.execute("SELECT COUNT(*) FROM requests WHERE emergency='Critical' AND status NOT IN ('Request Closed','Request Expired')").fetchone()[0],
        "urgent": connection.execute("SELECT COUNT(*) FROM requests WHERE emergency='Urgent' AND status NOT IN ('Request Closed','Request Expired')").fetchone()[0],
        "completed": connection.execute("SELECT COUNT(*) FROM requests WHERE status='Request Closed'").fetchone()[0],
        "my_requests": connection.execute("SELECT COUNT(*) FROM requests WHERE user_id=?", (session["user_id"],)).fetchone()[0],
        "pending": connection.execute("SELECT COUNT(*) FROM requests WHERE user_id=? AND status NOT IN ('Request Closed','Request Expired')", (session["user_id"],)).fetchone()[0],
        "unread": connection.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (session["user_id"],)).fetchone()[0],
    }
    connection.commit()
    connection.close()
    return render_template("dashboard.html", user=user, stats=stats)


@app.route("/profile", methods=["GET", "POST"])
@user_required
def profile():
    connection = get_db_connection(); user = connection.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if request.method == "POST":
        data = {key: request.form.get(key, "").strip() for key in ("name", "blood_group", "city", "phone")}; available = int(request.form.get("available") == "1")
        if (not all(data.values()) or data["blood_group"] not in BLOOD_GROUPS
            or len(data["name"]) > 100 or not re.fullmatch(r"[\w .'-]+", data["name"], re.UNICODE)
            or not data["city"] or len(data["city"]) > 100
            or not re.fullmatch(r"[+()\-\s\d]{7,20}", data["phone"])):
            flash("Please enter valid profile details.", "error")
        else:
            latitude, longitude = city_coordinates(data["city"])
            connection.execute("UPDATE users SET name=?, blood_group=?, city=?, phone=?, available=?, latitude=?, longitude=? WHERE id=?", (*data.values(), available, latitude, longitude, session["user_id"])); add_notification(connection, session["user_id"], "Your profile was updated.", "profile"); connection.commit(); flash("Profile updated successfully.", "success")
            user = connection.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    connection.close(); return render_template("profile.html", user=user)


@app.post("/availability")
@user_required
def update_own_availability():
    value = request.form.get("available", "")
    if value not in ("0", "1"):
        flash("Choose a valid availability setting.", "error")
    else:
        connection = get_db_connection()
        connection.execute("UPDATE users SET available=? WHERE id=?", (int(value), session["user_id"]))
        connection.commit()
        connection.close()
        flash("Availability updated.", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/request-blood", methods=["GET", "POST"])
@user_required
def request_blood():
    if request.method == "POST":
        errors, data = validate_request_form(request.form)
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("request_blood.html", form_data=data)
        else:
            connection = get_db_connection()
            connection.execute("INSERT INTO requests (user_id,blood_group,city,units,emergency,required_at,expiry_at) VALUES (?,?,?,?,?,?,?)", (session["user_id"], data["blood_group"], data["city"], data["units"], data["emergency"], data["required_at"], data["expiry_at"]))
            add_notification(connection, session["user_id"], "Your emergency request was created.", "request")
            connection.execute(
                "INSERT INTO notifications (user_id, message, category) "
                "SELECT id, ?, 'emergency' FROM users WHERE id != ?",
                (f"New {data['emergency'].lower()} blood request: {data['blood_group']} needed in {data['city']}.", session["user_id"]),
            )
            connection.commit()
            connection.close()
            flash("Emergency request created.", "success")
            if data["emergency"] == "Critical": send_email("New Critical emergency request", f"A Critical request was created for {data['blood_group']} in {data['city']}.")
            return redirect(url_for("my_requests"))
    return render_template("request_blood.html")


@app.route("/my-requests/<int:request_id>/edit", methods=["GET", "POST"])
@user_required
def edit_my_request(request_id):
    connection = get_db_connection()
    blood_request = connection.execute("SELECT * FROM requests WHERE id = ? AND user_id = ?", (request_id, session["user_id"])).fetchone()
    if not blood_request:
        connection.close(); flash("Request not found or access denied.", "error"); return redirect(url_for("my_requests"))
    if blood_request["status"] not in ("Request Created", "Searching Donor"):
        connection.close(); flash("This request can no longer be edited.", "error"); return redirect(url_for("my_requests"))
    if request.method == "POST":
        errors, data = validate_request_form(request.form)
        if errors:
            for error in errors:
                flash(error, "error")
        else:
            connection.execute("UPDATE requests SET blood_group=?, city=?, units=?, emergency=?, required_at=?, expiry_at=? WHERE id=? AND user_id=?", (data["blood_group"], data["city"], data["units"], data["emergency"], data["required_at"], data["expiry_at"], request_id, session["user_id"])); connection.commit(); connection.close(); flash("Request updated successfully.", "success"); return redirect(url_for("my_requests"))
    else:
        data = dict(blood_request)
        data["required_at"] = datetime_local_value(data.get("required_at"))
        data["expiry_at"] = datetime_local_value(data.get("expiry_at"))
    connection.close(); return render_template("edit_request.html", blood_request=blood_request, form_data=data)


def refresh_expired(connection):
    rows = connection.execute(
        "SELECT id, user_id, expiry_at FROM requests WHERE status NOT IN ('Request Closed', 'Request Expired')"
    ).fetchall()
    now = datetime.now().astimezone().replace(tzinfo=None)
    for row in rows:
        expiry = parse_datetime(row["expiry_at"])
        if expiry and expiry.tzinfo:
            expiry = expiry.astimezone().replace(tzinfo=None)
        if not expiry or expiry <= now:
            connection.execute("UPDATE requests SET status='Request Expired' WHERE id=?", (row["id"],))
            add_notification(connection, row["user_id"], f"Request #{row['id']} expired.", "expired")


@app.get("/my-requests")
@user_required
def my_requests():
    connection = get_db_connection(); refresh_expired(connection); connection.commit(); rows = connection.execute("SELECT * FROM requests WHERE user_id=? ORDER BY CASE emergency WHEN 'Critical' THEN 1 WHEN 'Urgent' THEN 2 ELSE 3 END, created_at DESC", (session["user_id"],)).fetchall(); connection.close(); return render_template("my_requests.html", requests=rows)


@app.get("/notifications")
@user_required
def notifications():
    connection = get_db_connection()
    rows = connection.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC", (session["user_id"],)).fetchall()
    connection.close()
    return render_template("notifications.html", notifications=rows)


@app.post("/notifications/<int:notification_id>/read")
@user_required
def mark_notification_read(notification_id):
    connection = get_db_connection()
    connection.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (notification_id, session["user_id"]))
    connection.commit()
    connection.close()
    return redirect(url_for("notifications"))


@app.post("/notifications/read-all")
@user_required
def mark_all_notifications_read():
    connection = get_db_connection()
    connection.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["user_id"],))
    connection.commit()
    connection.close()
    return redirect(url_for("notifications"))


@app.route("/support", methods=["GET"])
@user_required
def support_tickets():
    connection = get_db_connection()
    tickets = connection.execute(
        """
        SELECT t.*, COUNT(m.id) AS reply_count, MAX(m.created_at) AS last_message
        FROM support_tickets t
        LEFT JOIN support_messages m ON m.ticket_id = t.id
        WHERE t.user_id = ?
        GROUP BY t.id
        ORDER BY datetime(t.updated_at) DESC, datetime(t.created_at) DESC
        """,
        (session["user_id"],),
    ).fetchall()
    connection.close()
    return render_template("support_tickets.html", tickets=tickets)


@app.route("/support/new", methods=["GET", "POST"])
@user_required
def new_support_ticket():
    connection = get_db_connection()
    open_requests = connection.execute(
        "SELECT id, blood_group, city, emergency, status FROM requests WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
        (session["user_id"],),
    ).fetchall()
    connection.close()

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        category = request.form.get("category", "").strip()
        priority = request.form.get("priority", "").strip()
        message = request.form.get("message", "").strip()
        request_id = request.form.get("request_id", "").strip()
        errors = []

        if len(subject) < 3 or len(subject) > 140:
            errors.append("Enter a ticket subject between 3 and 140 characters.")
        if category not in SUPPORT_CATEGORIES:
            errors.append("Choose a valid support category.")
        if priority not in EMERGENCY_LEVELS:
            errors.append("Choose a valid priority.")
        if len(message) < 5 or len(message) > 4000:
            errors.append("Write a support message between 5 and 4000 characters.")

        linked_request_id = None
        if request_id:
            try:
                linked_request_id = int(request_id)
            except ValueError:
                linked_request_id = None
                errors.append("Select a valid linked request.")
            if linked_request_id:
                connection = get_db_connection()
                owned_request = connection.execute("SELECT id FROM requests WHERE id = ? AND user_id = ?", (linked_request_id, session["user_id"])).fetchone()
                connection.close()
                if not owned_request:
                    errors.append("The linked request is not available for your account.")
                    linked_request_id = None

        request_id = linked_request_id

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("support_ticket_form.html", requests=open_requests, categories=SUPPORT_CATEGORIES, form_data={
                "subject": subject,
                "category": category,
                "priority": priority,
                "message": message,
                "request_id": request_id or "",
            })

        connection = get_db_connection()
        ticket_result = connection.execute(
            "INSERT INTO support_tickets (user_id, subject, category, priority, status, request_id, message, updated_at) VALUES (?, ?, ?, ?, 'Open', ?, ?, CURRENT_TIMESTAMP)",
            (session["user_id"], subject, category, priority, request_id, message),
        )
        ticket_id = ticket_result.lastrowid
        connection.execute(
            "INSERT INTO support_messages (ticket_id, sender_role, sender_id, message, is_read) VALUES (?, 'user', ?, ?, 0)",
            (ticket_id, session["user_id"], message),
        )
        add_notification(connection, session["user_id"], f"Support ticket #{ticket_id} has been created.", "support")
        connection.commit()
        connection.close()
        flash("Your support ticket was sent to the administrator.", "success")
        return redirect(url_for("support_ticket_detail", ticket_id=ticket_id))

    return render_template("support_ticket_form.html", requests=open_requests, categories=SUPPORT_CATEGORIES, form_data={})


@app.route("/support/<int:ticket_id>", methods=["GET", "POST"])
@user_required
def support_ticket_detail(ticket_id):
    connection = get_db_connection()
    ticket = connection.execute(
        "SELECT t.*, u.name AS user_name, u.email AS user_email, r.blood_group, r.city AS request_city, r.emergency AS request_emergency FROM support_tickets t JOIN users u ON u.id = t.user_id LEFT JOIN requests r ON r.id = t.request_id WHERE t.id = ? AND t.user_id = ?",
        (ticket_id, session["user_id"]),
    ).fetchone()
    if not ticket:
        connection.close()
        flash("Support ticket not found.", "error")
        return redirect(url_for("support_tickets"))

    connection.execute("UPDATE support_messages SET is_read = 1 WHERE ticket_id = ? AND sender_role = 'admin' AND is_read = 0", (ticket_id,))
    messages = connection.execute(
        "SELECT * FROM support_messages WHERE ticket_id = ? ORDER BY created_at ASC",
        (ticket_id,),
    ).fetchall()

    if request.method == "POST":
        reply = request.form.get("message", "").strip()
        if len(reply) < 2 or len(reply) > 4000:
            flash("Enter a reply between 2 and 4000 characters.", "error")
        else:
            connection.execute(
                "INSERT INTO support_messages (ticket_id, sender_role, sender_id, message, is_read) VALUES (?, 'user', ?, ?, 0)",
                (ticket_id, session["user_id"], reply),
            )
            connection.execute(
                "UPDATE support_tickets SET status = 'Waiting for admin', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (ticket_id,),
            )
            add_notification(connection, session["user_id"], f"Your support ticket #{ticket_id} was updated.", "support")
            connection.commit()
            flash("Reply added successfully.", "success")
            return redirect(url_for("support_ticket_detail", ticket_id=ticket_id))

    connection.close()
    return render_template("support_ticket_detail.html", ticket=ticket, messages=messages)


@app.route("/admin/support", methods=["GET"])
@admin_required
def admin_support():
    status_filter = request.args.get("status", "").strip()
    priority_filter = request.args.get("priority", "").strip()
    connection = get_db_connection()
    query = """
        SELECT t.*, u.name AS user_name, u.email AS user_email, COUNT(m.id) AS reply_count, MAX(m.created_at) AS last_message
        FROM support_tickets t
        JOIN users u ON u.id = t.user_id
        LEFT JOIN support_messages m ON m.ticket_id = t.id
        WHERE 1 = 1
    """
    params = []
    if status_filter in SUPPORT_STATUSES:
        query += " AND t.status = ?"
        params.append(status_filter)
    if priority_filter in EMERGENCY_LEVELS:
        query += " AND t.priority = ?"
        params.append(priority_filter)
    query += " GROUP BY t.id ORDER BY CASE t.priority WHEN 'Critical' THEN 1 WHEN 'Urgent' THEN 2 ELSE 3 END, datetime(t.updated_at) DESC"
    tickets = connection.execute(query, params).fetchall()
    connection.close()
    return render_template("admin_support.html", tickets=tickets, selected_status=status_filter, selected_priority=priority_filter)


@app.route("/admin/support/<int:ticket_id>", methods=["GET", "POST"])
@admin_required
def admin_support_ticket(ticket_id):
    connection = get_db_connection()
    ticket = connection.execute(
        "SELECT t.*, u.name AS user_name, u.email AS user_email, r.blood_group, r.city AS request_city, r.emergency AS request_emergency FROM support_tickets t JOIN users u ON u.id = t.user_id LEFT JOIN requests r ON r.id = t.request_id WHERE t.id = ?",
        (ticket_id,),
    ).fetchone()
    if not ticket:
        connection.close(); flash("Support ticket not found.", "error"); return redirect(url_for("admin_support"))

    connection.execute("UPDATE support_messages SET is_read = 1 WHERE ticket_id = ? AND sender_role = 'user' AND is_read = 0", (ticket_id,))
    messages = connection.execute("SELECT * FROM support_messages WHERE ticket_id = ? ORDER BY created_at ASC", (ticket_id,)).fetchall()

    if request.method == "POST":
        reply = request.form.get("message", "").strip()
        if len(reply) < 2 or len(reply) > 4000:
            flash("Enter a reply between 2 and 4000 characters.", "error")
        else:
            connection.execute(
                "INSERT INTO support_messages (ticket_id, sender_role, sender_id, message, is_read) VALUES (?, 'admin', ?, ?, 0)",
                (ticket_id, session["admin_id"], reply),
            )
            connection.execute(
                "UPDATE support_tickets SET status = 'In Progress', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (ticket_id,),
            )
            connection.execute(
                "INSERT INTO notifications (user_id, message, category) VALUES (?, ?, 'support')",
                (ticket["user_id"], f"Admin replied to support ticket #{ticket_id}."),
            )
            connection.commit()
            flash("Administrator reply added.", "success")
            return redirect(url_for("admin_support_ticket", ticket_id=ticket_id))

    connection.close()
    return render_template("admin_support_ticket.html", ticket=ticket, messages=messages)


@app.post("/admin/support/<int:ticket_id>/status")
@admin_required
def update_support_ticket_status(ticket_id):
    status = request.form.get("status", "").strip()
    if status not in SUPPORT_STATUSES:
        flash("Choose a valid support status.", "error")
        return redirect(url_for("admin_support_ticket", ticket_id=ticket_id))
    connection = get_db_connection()
    ticket = connection.execute("SELECT user_id FROM support_tickets WHERE id = ?", (ticket_id,)).fetchone()
    if ticket:
        connection.execute("UPDATE support_tickets SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, ticket_id))
        connection.execute(
            "INSERT INTO notifications (user_id, message, category) VALUES (?, ?, 'support')",
            (ticket["user_id"], f"Support ticket #{ticket_id} status changed to {status}."),
        )
        connection.commit()
        flash("Support ticket status updated.", "success")
    else:
        flash("Support ticket not found.", "error")
    connection.close()
    return redirect(url_for("admin_support_ticket", ticket_id=ticket_id))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        connection = get_db_connection()
        try:
            admin = connection.execute("SELECT * FROM admin WHERE username=?", (request.form.get("username", "").strip(),)).fetchone()
            if admin and check_password_hash(admin["password_hash"], request.form.get("password", "")):
                session.clear(); session["admin_id"] = admin["id"]
                log_admin_action(connection, admin["id"], "Admin logged in", admin["id"], "Administrator logged in successfully.")
                connection.commit()
                return redirect(url_for("admin_dashboard"))
            flash("Invalid administrator credentials.", "error")
        finally:
            connection.close()
    return render_template("admin_login.html")


@app.get("/admin/logout")
def admin_logout(): session.clear(); return redirect(url_for("home"))


@app.get("/admin")
@admin_required
def admin_dashboard():
    connection = get_db_connection()
    refresh_expired(connection)
    stats = {
        "donors": connection.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "available": connection.execute("SELECT COUNT(*) FROM users WHERE available=1").fetchone()[0],
        "unavailable": connection.execute("SELECT COUNT(*) FROM users WHERE available=0").fetchone()[0],
        "requests": connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
        "pending": connection.execute("SELECT COUNT(*) FROM requests WHERE status NOT IN ('Request Closed','Request Expired')").fetchone()[0],
        "critical": connection.execute("SELECT COUNT(*) FROM requests WHERE emergency='Critical' AND status NOT IN ('Request Closed','Request Expired')").fetchone()[0],
        "urgent": connection.execute("SELECT COUNT(*) FROM requests WHERE emergency='Urgent' AND status NOT IN ('Request Closed','Request Expired')").fetchone()[0],
        "completed": connection.execute("SELECT COUNT(*) FROM requests WHERE status='Request Closed'").fetchone()[0],
    }
    recent = connection.execute("SELECT * FROM requests ORDER BY created_at DESC LIMIT 8").fetchall()
    recent_donors = connection.execute("SELECT name, blood_group, city, created_at FROM users ORDER BY created_at DESC LIMIT 5").fetchall()
    blood_stats = connection.execute("SELECT blood_group, COUNT(*) AS total FROM users GROUP BY blood_group ORDER BY total DESC").fetchall()
    status_stats = connection.execute("SELECT status, COUNT(*) AS total FROM requests GROUP BY status ORDER BY total DESC").fetchall()
    audit_logs = connection.execute(
        "SELECT a.id, a.action, a.target_user_id, a.details, a.created_at, admin.username FROM admin_audit_logs a JOIN admin ON admin.id = a.admin_id ORDER BY a.created_at DESC LIMIT 8"
    ).fetchall()
    connection.commit()
    connection.close()
    return render_template("admin.html", stats=stats, requests=recent, recent_donors=recent_donors, blood_stats=blood_stats, status_stats=status_stats, audit_logs=audit_logs)


@app.get("/admin/donors")
@admin_required
def manage_donors():
    group = request.args.get("blood_group", "").strip()
    city = request.args.get("city", "").strip()
    availability = request.args.get("availability", "").strip()
    search = request.args.get("search", "").strip()
    query = "SELECT * FROM users WHERE 1=1"
    parameters = []
    if search:
        query += " AND (LOWER(name) LIKE LOWER(?) OR LOWER(email) LIKE LOWER(?))"
        parameters.extend((f"%{search}%", f"%{search}%"))
    if group:
        query += " AND blood_group = ?"; parameters.append(group)
    if city:
        query += " AND LOWER(city) LIKE LOWER(?)"; parameters.append(f"%{city}%")
    if availability in ("0", "1"):
        query += " AND available = ?"; parameters.append(int(availability))
    query += " ORDER BY created_at DESC"
    connection = get_db_connection(); donors = connection.execute(query, parameters).fetchall(); connection.close()
    return render_template("manage_donors.html", donors=donors, selected_group=group, selected_city=city, selected_availability=availability, search=search)


@app.route("/admin/donors/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_donor(user_id):
    connection = get_db_connection(); donor = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not donor: connection.close(); flash("Donor not found.", "error"); return redirect(url_for("manage_donors"))
    if request.method == "POST":
        name = request.form.get("name", "").strip(); blood_group = request.form.get("blood_group", ""); city = request.form.get("city", "").strip(); phone = request.form.get("phone", "").strip(); available = int(request.form.get("available") == "1")
        latitude_text = request.form.get("latitude", "").strip(); longitude_text = request.form.get("longitude", "").strip()
        if (not name or len(name) > 100 or not re.fullmatch(r"[\w .'-]+", name, re.UNICODE)
                or blood_group not in BLOOD_GROUPS or not city or len(city) > 100
                or not re.fullmatch(r"[+()\-\s\d]{7,20}", phone)):
            connection.close(); flash("Please enter valid donor details.", "error"); return render_template("edit_donor.html", donor=donor)
        try:
            if latitude_text or longitude_text:
                latitude = float(latitude_text)
                longitude = float(longitude_text)
                if latitude < -90 or latitude > 90 or longitude < -180 or longitude > 180:
                    raise ValueError
            else:
                latitude, longitude = city_coordinates(city)
        except (TypeError, ValueError):
            connection.close(); flash("Please enter valid latitude and longitude numbers or leave them blank to use city coordinates.", "error"); return render_template("edit_donor.html", donor=donor)
        connection.execute("UPDATE users SET name=?, blood_group=?, city=?, phone=?, available=?, latitude=?, longitude=? WHERE id=?", (name, blood_group, city, phone, available, latitude, longitude, user_id))
        log_admin_action(connection, session["admin_id"], "Donor updated", user_id, f"Updated donor #{user_id}: {name} in {city}.")
        connection.commit(); connection.close(); flash("Donor updated successfully.", "success"); return redirect(url_for("manage_donors"))
    connection.close(); return render_template("edit_donor.html", donor=donor)


@app.post("/admin/donors/<int:user_id>/delete")
@admin_required
def delete_donor(user_id):
    connection = get_db_connection()
    donor = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not donor:
        connection.close(); flash("Donor not found.", "error"); return redirect(url_for("manage_donors"))
    connection.execute("DELETE FROM users WHERE id=?", (user_id,))
    log_admin_action(connection, session["admin_id"], "Donor deleted", user_id, f"Deleted donor #{user_id}: {donor['name']} ({donor['email']}).")
    connection.commit(); connection.close(); flash("Donor deleted.", "success"); return redirect(url_for("manage_donors"))


@app.get("/admin/requests")
@admin_required
def manage_requests():
    emergency = request.args.get("emergency", "").strip()
    status = request.args.get("status", "").strip()
    query = "SELECT requests.*, users.name FROM requests JOIN users ON users.id=requests.user_id WHERE 1=1"
    parameters = []
    if emergency in EMERGENCY_LEVELS:
        query += " AND requests.emergency = ?"; parameters.append(emergency)
    if status in STATUSES:
        query += " AND requests.status = ?"; parameters.append(status)
    query += " ORDER BY CASE emergency WHEN 'Critical' THEN 1 WHEN 'Urgent' THEN 2 ELSE 3 END, requests.created_at DESC"
    connection = get_db_connection(); refresh_expired(connection); rows = connection.execute(query, parameters).fetchall(); connection.commit(); connection.close()
    return render_template("manage_requests.html", requests=rows, selected_emergency=emergency, selected_status=status)


@app.route("/admin/requests/<int:request_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_admin_request(request_id):
    connection = get_db_connection(); blood_request = connection.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
    if not blood_request:
        connection.close(); flash("Request not found.", "error"); return redirect(url_for("manage_requests"))
    if request.method == "POST":
        errors, data = validate_request_form(request.form)
        if errors:
            for error in errors:
                flash(error, "error")
        else:
            connection.execute("UPDATE requests SET blood_group=?, city=?, units=?, emergency=?, required_at=?, expiry_at=? WHERE id=?", (data["blood_group"], data["city"], data["units"], data["emergency"], data["required_at"], data["expiry_at"], request_id)); connection.commit(); connection.close(); flash("Request updated successfully.", "success"); return redirect(url_for("manage_requests"))
    else:
        data = dict(blood_request)
        data["required_at"] = datetime_local_value(data.get("required_at"))
        data["expiry_at"] = datetime_local_value(data.get("expiry_at"))
    connection.close(); return render_template("admin_edit_request.html", blood_request=blood_request, form_data=data)


@app.post("/admin/requests/<int:request_id>/status")
@admin_required
def update_request_status(request_id):
    status = request.form.get("status", "")
    if status in STATUSES:
        connection = get_db_connection()
        refresh_expired(connection)
        connection.commit()
        row = connection.execute("SELECT user_id, status FROM requests WHERE id=?", (request_id,)).fetchone()
        changed = row and row["status"] != status
        if changed and row["status"] != "Request Expired":
            connection.execute("UPDATE requests SET status=? WHERE id=?", (status, request_id))
            add_notification(connection, row["user_id"], f"Request #{request_id} status updated to {status}.", "status")
            connection.commit()
            flash("Request status updated.", "success")
        elif row:
            flash("Request status is unchanged or this expired request cannot be reopened.", "error")
        connection.close()
        if changed and status in ("Donor Responded", "Blood Arranged", "Request Closed"):
            send_email(f"Request #{request_id} status update", f"Request #{request_id} is now: {status}.")
    return redirect(url_for("manage_requests"))


@app.route("/admin/notifications", methods=["GET", "POST"])
@admin_required
def admin_notifications():
    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if not message or len(message) > 500:
            flash("Enter a message of 1 to 500 characters.", "error")
        else:
            connection = get_db_connection()
            users = connection.execute("SELECT id FROM users").fetchall()
            connection.executemany(
                "INSERT INTO notifications (user_id, message, category) VALUES (?, ?, 'admin')",
                [(row["id"], message) for row in users],
            )
            connection.commit()
            connection.close()
            flash(f"Message sent to {len(users)} user(s).", "success")
            return redirect(url_for("admin_notifications"))
    return render_template("admin_notifications.html")


@app.post("/admin/requests/<int:request_id>/delete")
@admin_required
def delete_request(request_id):
    connection = get_db_connection(); connection.execute("DELETE FROM requests WHERE id=?", (request_id,)); connection.commit(); connection.close(); flash("Request deleted.", "success"); return redirect(url_for("manage_requests"))


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()
        if not name or len(name) > 100 or not re.fullmatch(r"[\w .'-]+", name, re.UNICODE) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or not message or len(message) > 2000:
            flash("Please complete your name, email, and message.", "error")
        else:
            flash("Thanks for reaching out. Our support team will be in touch soon.", "success")
            return redirect(url_for("contact"))
    return render_template("contact.html")


init_db()

if __name__ == "__main__":
    app.run(debug=True)
