from flask import Flask, render_template, request, redirect
from datetime import datetime
import csv
import os

app = Flask(__name__)

CSV_FILE = "appointments.csv"

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

    data = {field: request.form.get(field, "").strip()
            for field in fields}

    required = [
        "full_name", "email", "phone",
        "service", "date", "time"
    ]

    if any(not data[field] for field in required):
        return "Please fill in all required fields.", 400

    file_exists = os.path.isfile(CSV_FILE)

    with open(CSV_FILE, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)

        if not file_exists:
            writer.writerow([
                "Timestamp", "FullName", "Email", "Phone",
                "Service", "Date", "Time", "Message"
            ])

        writer.writerow([
            datetime.now().isoformat(timespec="seconds"),
            data["full_name"],
            data["email"],
            data["phone"],
            data["service"],
            data["date"],
            data["time"],
            data["message"]
        ])

    return redirect("/?success=1")

if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))