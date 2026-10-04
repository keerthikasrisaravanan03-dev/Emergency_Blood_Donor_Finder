"""SQLite setup and connection helpers for the Blood Finder prototype."""

import os
import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "blood_finder.db"


def get_db_connection():
    """Return a connection configured for safe row access and foreign keys."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    """Create the application schema and migrate the original donor table."""
    connection = get_db_connection()
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, blood_group TEXT NOT NULL, city TEXT NOT NULL, phone TEXT NOT NULL, available INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        user_columns = {row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
        if "latitude" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN latitude REAL")
        if "longitude" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN longitude REAL")
        connection.execute("CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, blood_group TEXT NOT NULL, city TEXT NOT NULL, units INTEGER NOT NULL, emergency TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Request Created', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, expiry_at TEXT NOT NULL, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)")
        request_columns = {row[1] for row in connection.execute("PRAGMA table_info(requests)").fetchall()}
        if "required_at" not in request_columns:
            connection.execute("ALTER TABLE requests ADD COLUMN required_at TEXT NOT NULL DEFAULT ''")
            connection.execute("UPDATE requests SET required_at = created_at WHERE required_at = ''")
        connection.execute("CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, message TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)")
        notification_columns = {row[1] for row in connection.execute("PRAGMA table_info(notifications)").fetchall()}
        if "category" not in notification_columns:
            connection.execute("ALTER TABLE notifications ADD COLUMN category TEXT NOT NULL DEFAULT 'general'")
        connection.execute("CREATE TABLE IF NOT EXISTS support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, subject TEXT NOT NULL, category TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'Normal', status TEXT NOT NULL DEFAULT 'Open', request_id INTEGER, message TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE, FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE SET NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS support_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL, sender_role TEXT NOT NULL, sender_id INTEGER NOT NULL, message TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (ticket_id) REFERENCES support_tickets(id) ON DELETE CASCADE)")
        connection.execute("CREATE TABLE IF NOT EXISTS admin (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, email TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS admin_audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER NOT NULL, action TEXT NOT NULL, target_user_id INTEGER, details TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (admin_id) REFERENCES admin(id) ON DELETE CASCADE)")
        connection.execute("CREATE TABLE IF NOT EXISTS donors (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, blood_group TEXT NOT NULL, phone TEXT NOT NULL, city TEXT NOT NULL)")
        legacy = connection.execute("SELECT name, blood_group, phone, city FROM donors WHERE NOT EXISTS (SELECT 1 FROM users)").fetchall()
        for donor in legacy:
            email = f"legacy-{donor['name'].lower().replace(' ', '-')}-{donor['phone'].replace(' ', '')}@example.invalid"
            connection.execute("INSERT OR IGNORE INTO users (name, email, password_hash, blood_group, city, phone) VALUES (?, ?, ?, ?, ?, ?)", (donor["name"], email, generate_password_hash(os.urandom(16).hex()), donor["blood_group"], donor["city"], donor["phone"]))
        connection.execute("UPDATE users SET latitude = 11.1271, longitude = 78.6569 WHERE latitude IS NULL OR longitude IS NULL")
        username = os.getenv("ADMIN_USERNAME", "admin")
        password = os.getenv("ADMIN_PASSWORD", "admin123")
        email = os.getenv("ADMIN_EMAIL", "admin@example.com")
        admin_row = connection.execute("SELECT id FROM admin WHERE username = ?", (username,)).fetchone()
        if admin_row:
            connection.execute("UPDATE admin SET password_hash = ?, email = ? WHERE id = ?", (generate_password_hash(password), email, admin_row["id"]))
        else:
            connection.execute("INSERT INTO admin (username, password_hash, email) VALUES (?, ?, ?)", (username, generate_password_hash(password), email))
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    init_db()
    print(f"Database ready: {DATABASE_PATH}")
