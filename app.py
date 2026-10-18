from flask import Flask, render_template, request, redirect, session, abort
from datetime import datetime
import os
import psycopg2

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")

# Database connection
def get_db_connection():
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    return psycopg2.connect(database_url)


# Create database table
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
                    message TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'Pending'
                )
            """)

            cur.execute("""
                ALTER TABLE appointments
                ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'Pending'
            """)

        conn.commit()


# Home page
@app.route("/")
def home():
    success = request.args.get("success") == "1"
    return render_template("index.html", success=success)


# Book appointment
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


# Admin login and appointments page
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        password = request.form.get("password", "")
        admin_password = os.environ.get("ADMIN_PASSWORD")

        if not admin_password or password != admin_password:
            return "Incorrect password", 401

        session["admin_logged_in"] = True

    if not session.get("admin_logged_in"):
        return render_template("admin_login.html")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, full_name, email, phone, service,
                           appointment_date, appointment_time, status
                    FROM appointments
                    ORDER BY id DESC
                    LIMIT 50
                """)
                appointments = cur.fetchall()

        return render_template(
            "admin.html",
            appointments=appointments
        )

    except Exception:
        app.logger.exception("Admin appointments page failed")
        return "Could not load appointments. Please try again.", 500


# Update appointment status
@app.route("/update_status", methods=["POST"])
def update_status():
    if not session.get("admin_logged_in"):
        abort(403)

    appointment_id = request.form.get("appointment_id", type=int)
    status = request.form.get("status", "")

    if not appointment_id:
        return "Invalid appointment ID", 400

    if status not in ["Pending", "Confirmed", "Completed"]:
        return "Invalid status", 400

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE appointments
                    SET status = %s
                    WHERE id = %s
                """, (status, appointment_id))

            conn.commit()

        return redirect("/admin")

    except Exception:
        app.logger.exception("Status update failed")
        return "Status update failed. Please try again.", 500


# Delete appointment
@app.route("/delete_appointment", methods=["POST"])
def delete_appointment():
    if not session.get("admin_logged_in"):
        abort(403)

    appointment_id = request.form.get("appointment_id", type=int)

    if not appointment_id:
        return "Invalid appointment ID", 400

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM appointments
                    WHERE id = %s
                """, (appointment_id,))

            conn.commit()

        return redirect("/admin")

    except Exception:
        app.logger.exception("Appointment deletion failed")
        return "Delete failed. Please try again.", 500


if __name__ == "__main__":
    app.run(
        debug=False,
        port=int(os.environ.get("PORT", 5000))
    )