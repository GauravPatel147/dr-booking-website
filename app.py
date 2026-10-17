from flask import Flask, render_template, request, redirect
from datetime import datetime
import os
import psycopg2
from functools import wraps
from flask import session, abort
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")

def get_db_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg2.connect(database_url)

def init_db():
    if not os.environ.get("DATABASE_URL"):
        return

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS appointments (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    service TEXT NOT NULL,
                    appointment_date DATE NOT NULL,
                    appointment_time TEXT NOT NULL,
                    message TEXT DEFAULT ''
                )
            """)
        conn.commit()

@app.route("/")
def home():
    success = request.args.get("success") == "1"
    return render_template("index.html", success=success)

@app.route("/book", methods=["POST"])
def book():
    fields = [
        "full_name", "email", "phone",
        "service", "date", "time", "message"
    ]

    data = {
        field: request.form.get(field, "").strip()
        for field in fields
    }

    required = [
        "full_name", "email", "phone",
        "service", "date", "time"
    ]

    if any(not data[field] for field in required):
        return "Please fill in all required fields.", 400

    try:
        appointment_date = datetime.strptime(
            data["date"], "%Y-%m-%d"
        ).date()

        init_db()

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO appointments (
                        full_name, email, phone, service,
                        appointment_date, appointment_time, message
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    data["full_name"],
                    data["email"],
                    data["phone"],
                    data["service"],
                    appointment_date,
                    data["time"],
                    data["message"]
                ))
            conn.commit()

    except ValueError:
        return "Invalid appointment date.", 400
    except Exception:
        app.logger.exception("Appointment booking failed")
        return "Booking could not be completed. Please try again later.", 500

    return redirect("/?success=1")

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password != os.environ.get("ADMIN_PASSWORD"):
            return "Incorrect password", 401

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, full_name, email, phone, service,
                           appointment_date, appointment_time
                    FROM appointments
                    ORDER BY id DESC
                    LIMIT 50
                """)
                appointments = cur.fetchall()

        return render_template("admin.html", appointments=appointments)

    return render_template("admin_login.html")
if __name__ == "__main__":
    app.run(
        debug=False,
        port=int(os.environ.get("PORT", 5000))
    )
    