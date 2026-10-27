
import json
import os
import re
import time
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import mysql.connector
from mysql.connector import Error


# ---------------- CONFIGURATION ----------------

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "blood_bank"),
}

BLOOD_GROUPS = {
    "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"
}

RATE_LOCK = threading.Lock()
RATE_LIMITS = {}


# ---------------- DATABASE ----------------

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)


# ---------------- VALIDATION ----------------

def clean_text(value, max_length=100):
    if not isinstance(value, str):
        raise ValueError("Please enter valid details.")

    value = value.strip()

    if not value or len(value) > max_length:
        raise ValueError("Please enter valid details.")

    if any(ord(char) < 32 for char in value):
        raise ValueError("Invalid characters in input.")

    return value


def clean_phone(value):
    value = clean_text(value, 20)

    if not re.fullmatch(r"[0-9+\-() ]{7,20}", value):
        raise ValueError("Please enter a valid phone number.")

    return value


def clean_group(value):
    value = clean_text(value, 3).upper()

    if value not in BLOOD_GROUPS:
        raise ValueError("Please select a valid blood group.")

    return value


# ---------------- WEB SERVER ----------------

class BloodBankHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            directory=str(FRONTEND_DIR),
            **kwargs
        )

    def send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid request size.")

        if length < 2 or length > 10000:
            raise ValueError("Request size is invalid.")

        try:
            data = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("Invalid JSON data.")

        if not isinstance(data, dict):
            raise ValueError("Invalid request data.")

        return data

    def allowed_rate(self):
        ip = self.client_address[0]
        now = time.time()

        with RATE_LOCK:
            recent = [
                stamp
                for stamp in RATE_LIMITS.get(ip, [])
                if now - stamp < 60
            ]

            if len(recent) >= 30:
                RATE_LIMITS[ip] = recent
                return False

            recent.append(now)
            RATE_LIMITS[ip] = recent

        return True

    # ---------------- GET REQUESTS ----------------

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/health":
            self.send_json(200, {"ok": True})
            return

        if path == "/api/blood":
            params = parse_qs(urlparse(self.path).query)

            group = params.get("group", [""])[0].strip().upper()
            city = params.get("city", [""])[0].strip()

            if group and group not in BLOOD_GROUPS:
                self.send_json(
                    400,
                    {"error": "Invalid blood group."}
                )
                return

            if len(city) > 100:
                self.send_json(
                    400,
                    {"error": "City name is too long."}
                )
                return

            conn = None
            cursor = None

            try:
                conn = get_connection()
                cursor = conn.cursor(dictionary=True)

                cursor.execute(
                    """
                    SELECT id, name, city, blood_group
                    FROM donors
                    WHERE (%s = '' OR blood_group = %s)
                      AND (%s = '' OR city LIKE %s)
                    ORDER BY created_at DESC
                    LIMIT 100
                    """,
                    (
                        group,
                        group,
                        city,
                        "%" + city + "%"
                    )
                )

                donors = cursor.fetchall()

                self.send_json(200, {"donors": donors})

            except Error:
                self.log_error("Database error while searching donors")
                self.send_json(
                    500,
                    {"error": "Unable to search donors. Check MySQL."}
                )

            finally:
                if cursor:
                    cursor.close()

                if conn and conn.is_connected():
                    conn.close()

            return

        # Serve frontend files.
        if path == "/":
            self.path = "/index.html"

        super().do_GET()

    # ---------------- POST REQUESTS ----------------

    def do_POST(self):
        path = urlparse(self.path).path

        if path not in {"/api/donors", "/api/requests"}:
            self.send_json(404, {"error": "API route not found."})
            return

        if not self.allowed_rate():
            self.send_json(
                429,
                {"error": "Too many requests. Try again later."}
            )
            return

        try:
            data = self.read_json()

            # DONOR REGISTRATION
            if path == "/api/donors":
                name = clean_text(data.get("name"))
                phone = clean_phone(data.get("phone"))
                city = clean_text(data.get("city"))
                group = clean_group(data.get("blood_group"))

                conn = get_connection()
                cursor = conn.cursor()

                try:
                    cursor.execute(
                        """
                        INSERT INTO donors
                            (name, phone, city, blood_group)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (name, phone, city, group)
                    )

                    conn.commit()

                finally:
                    cursor.close()
                    conn.close()

                self.send_json(
                    201,
                    {"message": "Donor registered successfully."}
                )
                return

            # BLOOD REQUEST
            if path == "/api/requests":
                name = clean_text(data.get("patient_name"))
                phone = clean_phone(data.get("phone"))
                city = clean_text(data.get("city"))
                group = clean_group(data.get("blood_group"))

                units = data.get("units", 1)

                if isinstance(units, bool) or not isinstance(units, int):
                    raise ValueError("Units must be a whole number.")

                if not 1 <= units <= 20:
                    raise ValueError("Units must be between 1 and 20.")

                conn = get_connection()
                cursor = conn.cursor()

                try:
                    cursor.execute(
                        """
                        INSERT INTO blood_requests
                            (patient_name, phone, city, blood_group, units)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (name, phone, city, group, units)
                    )

                    conn.commit()

                finally:
                    cursor.close()
                    conn.close()

                self.send_json(
                    201,
                    {"message": "Blood request submitted successfully."}
                )
                return

        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})

        except Error:
            self.log_error("MySQL database operation failed")
            self.send_json(
                500,
                {"error": "Database operation failed. Check MySQL settings."}
            )

        except Exception:
            self.log_error("Unexpected server error")
            self.send_json(
                500,
                {"error": "Internal server error."}
            )

    def log_message(self, format, *args):
        # Keep the default request log in the terminal.
        super().log_message(format, *args)


# ---------------- START SERVER ----------------

if __name__ == "__main__":
    if not FRONTEND_DIR.is_dir():
        raise SystemExit(
            "ERROR: frontend folder not found. Check your project structure."
        )

    try:
        connection = get_connection()
        connection.close()

        server = ThreadingHTTPServer(
            ("127.0.0.1", 8000),
            BloodBankHandler
        )

        print("MySQL connected successfully!")
        print("LifeDrop running at http://127.0.0.1:8000")
        print("Press Ctrl+C to stop the server.")

        server.serve_forever()

    except Error as exc:
        print("MySQL connection failed.")
        print("Check that MySQL Server is running and credentials are correct.")
        print(exc)

    except OSError as exc:
        print("Unable to start the web server.")
        print("Check whether port 8000 is already in use.")
        print(exc)
