import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import app, get_db_connection
from werkzeug.security import generate_password_hash


def test_admin_audit_log_table_exists():
    db_path = PROJECT_ROOT / "blood_finder.db"
    conn = sqlite3.connect(db_path)
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()
    assert "admin_audit_logs" in tables


def test_admin_login_dashboard_and_audit_log():
    client = app.test_client()
    admin_username = "admin"
    admin_password = "admin123"

    response = client.post("/admin/login", data={"username": admin_username, "password": "wrong"}, follow_redirects=False)
    assert response.status_code == 200
    assert b"Invalid administrator credentials" in response.data

    response = client.post("/admin/login", data={"username": admin_username, "password": admin_password}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin")

    response = client.get("/admin")
    assert response.status_code == 200
    assert b"Admin dashboard" in response.data
    assert b"Latest audit log" in response.data


def test_user_route_blocking_and_profile_update():
    email = "temp_user_admin_check@example.com"
    password = "Secret123"
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO users (name, email, password_hash, blood_group, city, phone, available) VALUES (?, ?, ?, ?, ?, ?, 1)",
        ("Temp User", email, generate_password_hash(password), "A+", "Chennai", "9876543210"),
    )
    conn.commit()
    user_id = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]
    conn.close()

    client = app.test_client()
    login = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login.status_code == 302

    admin_response = client.get("/admin", follow_redirects=False)
    assert admin_response.status_code == 302
    assert admin_response.headers["Location"].endswith("/admin/login")

    profile_response = client.post(
        "/profile",
        data={"name": "Temp User Updated", "blood_group": "O+", "city": "Salem", "phone": "9000000000", "available": "1"},
        follow_redirects=False,
    )
    assert profile_response.status_code == 200
    assert b"Profile updated successfully" in profile_response.data

    other_admin_edit = client.get(f"/admin/donors/{user_id}/edit", follow_redirects=False)
    assert other_admin_edit.status_code == 302
    assert other_admin_edit.headers["Location"].endswith("/admin/login")

    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def test_support_ticket_tables_exist():
    db_path = PROJECT_ROOT / "blood_finder.db"
    conn = sqlite3.connect(db_path)
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()
    assert "support_tickets" in tables
    assert "support_messages" in tables


def test_support_ticket_user_flow():
    email = "temp_support_user@example.com"
    password = "Secret123"
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE email = ?", (email,))
    conn.execute(
        "INSERT INTO users (name, email, password_hash, blood_group, city, phone, available) VALUES (?, ?, ?, ?, ?, ?, 1)",
        ("Support User", email, generate_password_hash(password), "O+", "Coimbatore", "8901234567"),
    )
    conn.commit()
    conn.close()

    client = app.test_client()
    login = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert login.status_code == 302

    ticket = client.post(
        "/support/new",
        data={
            "subject": "Blood request coordination issue",
            "category": "Blood request",
            "priority": "Urgent",
            "request_id": "",
            "message": "I need help with a donor matching issue for my urgent request.",
        },
        follow_redirects=False,
    )
    assert ticket.status_code == 302
    assert "/support/" in ticket.headers["Location"]

    list_response = client.get("/support")
    assert list_response.status_code == 200
    assert b"Support center" in list_response.data
    assert b"Blood request coordination issue" in list_response.data

    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE email = ?", (email,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    test_admin_audit_log_table_exists()
    test_admin_login_dashboard_and_audit_log()
    test_user_route_blocking_and_profile_update()
    test_support_ticket_tables_exist()
    test_support_ticket_user_flow()
    print("Admin feature checks passed")
