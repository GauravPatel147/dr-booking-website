from flask import (
    Flask, render_template, request, redirect,
    session, abort, url_for
)
from datetime import datetime, timedelta
import csv
from io import StringIO
from functools import wraps
import os
import psycopg2
from flask_mail import Mail, Message

app = Flask(__name__)

# Security configuration
app.secret_key = os.environ.get("SECRET_KEY")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("RENDER") is not None,
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
)

# Email configuration - Brevo SMTP
app.config.update(
    MAIL_SERVER=os.environ.get("MAIL_SERVER", "smtp-relay.brevo.com"),
    MAIL_PORT=int(os.environ.get("MAIL_PORT", "587")),
    MAIL_USE_TLS=True,
    MAIL_USE_SSL=False,
    MAIL_TIMEOUT=10,
    MAIL_USERNAME=os.environ.get("MAIL_USERNAME"),
    MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD"),
    MAIL_DEFAULT_SENDER=os.environ.get("MAIL_FROM_EMAIL"),
)

mail = Mail(app)


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
                ADD COLUMN IF NOT EXISTS status
                TEXT NOT NULL DEFAULT 'Pending'
            """)

        conn.commit()


# Admin authentication helper
def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_logged_in"):
            abort(403)
        return view(*args, **kwargs)
    return wrapped_view


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
        return (
            "Booking could not be completed. Please try again later.",
            500
        )

    return redirect(url_for("home", success=1))


# Admin login and dashboard
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        password = request.form.get("password", "")
        admin_password = os.environ.get("ADMIN_PASSWORD")

        if not admin_password or password != admin_password:
            return "Incorrect password", 401

        session.clear()
        session["admin_logged_in"] = True
        session.permanent = True

        return redirect(url_for("admin"))

    if not session.get("admin_logged_in"):
        return render_template("admin_login.html")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (
                            WHERE status = 'Pending'
                        ) AS pending,
                        COUNT(*) FILTER (
                            WHERE status = 'Confirmed'
                        ) AS confirmed,
                        COUNT(*) FILTER (
                            WHERE status = 'Completed'
                        ) AS completed
                    FROM appointments
                """)

                row = cur.fetchone()

                dashboard_stats = {
                    "total": row[0],
                    "pending": row[1],
                    "confirmed": row[2],
                    "completed": row[3],
                }

                cur.execute("""
                    SELECT id, full_name, email, phone, service,
                           appointment_date, appointment_time, status
                    FROM appointments
                    ORDER BY id DESC
                    LIMIT 50
                """)

                appointments = cur.fetchall()

        response = app.make_response(
            render_template(
                "admin.html",
                appointments=appointments,
                dashboard_stats=dashboard_stats
            )
        )

        response.headers["Cache-Control"] = "no-store"
        return response

    except Exception:
        app.logger.exception("Admin dashboard failed")
        return "Could not load dashboard. Please try again.", 500


# Admin logout
@app.route("/logout", methods=["POST"])
@admin_required
def logout():
    session.clear()
    return redirect(url_for("admin"))


# Update appointment status and send confirmation email
@app.route("/update_status", methods=["POST"])
@admin_required
def update_status():
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
                    SELECT full_name, email, service,
                           appointment_date, appointment_time, status
                    FROM appointments
                    WHERE id = %s
                    FOR UPDATE
                """, (appointment_id,))

                patient = cur.fetchone()

                if patient is None:
                    return "Appointment not found", 404

                send_confirmation = (
                    status == "Confirmed"
                    and patient[5] != "Confirmed"
                )

                cur.execute("""
                    UPDATE appointments
                    SET status = %s
                    WHERE id = %s
                """, (status, appointment_id))

            conn.commit()

        # Send email only when the status changes to Confirmed
        if send_confirmation:
            try:
                name, email, service, date, time, old_status = patient

                message = Message(
                    subject="Your DoctorCare Appointment is Confirmed",
                    recipients=[email],
                    body=(
                        f"Hello {name},\n\n"
                        "Your DoctorCare appointment has been confirmed.\n\n"
                        f"Service: {service}\n"
                        f"Date: {date}\n"
                        f"Time: {time}\n\n"
                        "Thank you for choosing DoctorCare."
                    )
                )

                mail.send(message)

                app.logger.info(
                    "Confirmation email sent for appointment %s",
                    appointment_id
                )

            except Exception:
                app.logger.exception(
                    "Confirmation email failed for appointment %s",
                    appointment_id
                )

        return redirect(url_for("admin"))

    except Exception:
        app.logger.exception("Status update failed")
        return "Status update failed. Please try again.", 500


# Delete appointment
@app.route("/delete_appointment", methods=["POST"])
@admin_required
def delete_appointment():
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

                if cur.rowcount == 0:
                    return "Appointment not found", 404

            conn.commit()

        return redirect(url_for("admin"))

    except Exception:
        app.logger.exception("Appointment deletion failed")
        return "Delete failed. Please try again.", 500


# Export appointments to CSV
@app.route("/export_appointments")
def export_appointments():
    if not session.get("admin_logged_in"):
        abort(403)

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, created_at, full_name, email, phone,
                           service, appointment_date, appointment_time,
                           message, status
                    FROM appointments
                    ORDER BY id DESC
                """)

                rows = cur.fetchall()

        output = StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "ID", "Created At", "Full Name", "Email", "Phone",
            "Service", "Date", "Time", "Message", "Status"
        ])

        writer.writerows(rows)

        response = app.response_class(
            output.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={
                "Content-Disposition":
                    "attachment; filename=doctorcare_appointments.csv"
            }
        )

        response.headers["Cache-Control"] = "no-store"
        return response

    except Exception:
        app.logger.exception("CSV export failed")
        return "CSV export failed. Please try again.", 500


if __name__ == "__main__":
    if not app.secret_key:
        raise RuntimeError(
            "SECRET_KEY environment variable must be configured"
        )

    app.run(
        debug=False,
        port=int(os.environ.get("PORT", 5000))
    )