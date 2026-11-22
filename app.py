import math
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, current_app, flash, g, redirect, render_template, request, url_for


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.environ.get(
            "DATABASE_PATH", str(Path(app.instance_path) / "alcohol-tracker.sqlite3")
        ),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)

    @app.teardown_appcontext
    def close_db(_error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    with app.app_context():
        init_db()

    @app.get("/")
    def index():
        now = datetime.now(timezone.utc).replace(microsecond=0)
        cutoff = now - timedelta(hours=24)
        db = get_db()
        total = db.execute(
            "SELECT COALESCE(SUM(units), 0) FROM entries "
            "WHERE occurred_at >= ? AND occurred_at <= ?",
            (cutoff.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
        ).fetchone()[0]
        entry_rows = db.execute(
            "SELECT id, alcohol_type, units, occurred_at FROM entries "
            "ORDER BY occurred_at DESC, id DESC"
        ).fetchall()
        entries = []
        for row in entry_rows:
            local_time = datetime.fromisoformat(row["occurred_at"]).astimezone()
            entries.append(
                {
                    "id": row["id"],
                    "alcohol_type": row["alcohol_type"],
                    "units": row["units"],
                    "occurred_at_display": local_time.strftime("%Y-%m-%d %H:%M"),
                    "occurred_at_input": local_time.strftime("%Y-%m-%dT%H:%M"),
                }
            )
        trend = get_daily_trend(db, now.astimezone().date())
        trend_max = max((day["units"] for day in trend), default=0)
        return render_template(
            "index.html",
            entries=entries,
            total=total,
            trend=trend,
            trend_max=trend_max,
        )

    @app.post("/entries")
    def add_entry():
        values = parse_entry(request.form)
        if values is None:
            flash("Enter an alcohol type, positive units, and a valid date and time.", "error")
            return redirect(url_for("index"))
        db = get_db()
        db.execute(
            "INSERT INTO entries (alcohol_type, units, occurred_at) VALUES (?, ?, ?)",
            (values[0], values[1], values[2].isoformat(timespec="seconds")),
        )
        db.commit()
        flash("Entry added.", "success")
        return redirect(url_for("index"))

    @app.post("/entries/<int:entry_id>/edit")
    def edit_entry(entry_id):
        values = parse_entry(request.form)
        if values is None:
            flash("Enter an alcohol type, positive units, and a valid date and time.", "error")
            return redirect(url_for("index"))
        db = get_db()
        result = db.execute(
            "UPDATE entries SET alcohol_type = ?, units = ?, occurred_at = ? WHERE id = ?",
            (values[0], values[1], values[2].isoformat(timespec="seconds"), entry_id),
        )
        if result.rowcount == 0:
            flash("That entry no longer exists.", "error")
        else:
            db.commit()
            flash("Entry updated.", "success")
        return redirect(url_for("index"))

    @app.post("/entries/<int:entry_id>/delete")
    def delete_entry(entry_id):
        db = get_db()
        result = db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        if result.rowcount == 0:
            flash("That entry no longer exists.", "error")
        else:
            db.commit()
            flash("Entry deleted.", "success")
        return redirect(url_for("index"))

    return app


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def init_db():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alcohol_type TEXT NOT NULL DEFAULT '',
            units REAL NOT NULL CHECK (units > 0),
            occurred_at TEXT NOT NULL
        )
        """
    )
    columns = {row["name"] for row in db.execute("PRAGMA table_info(entries)")}
    if "alcohol_type" not in columns:
        db.execute(
            "ALTER TABLE entries ADD COLUMN alcohol_type TEXT NOT NULL DEFAULT ''"
        )
    db.commit()


def parse_entry(form):
    try:
        alcohol_type = form.get("alcohol_type", "").strip()
        if not alcohol_type or len(alcohol_type) > 80:
            return None
        units = float(form.get("units", ""))
        if not math.isfinite(units) or units <= 0:
            return None
        raw_timestamp = form.get("occurred_at", "").strip()
        if raw_timestamp:
            occurred_at = datetime.fromisoformat(raw_timestamp)
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.astimezone()
        else:
            occurred_at = datetime.now(timezone.utc)
        return (
            alcohol_type,
            units,
            occurred_at.astimezone(timezone.utc).replace(microsecond=0),
        )
    except (TypeError, ValueError, OverflowError):
        return None


def get_daily_trend(db, today):
    first_day = today - timedelta(days=13)
    rows = db.execute(
        """
        SELECT date(occurred_at, 'localtime') AS day, SUM(units) AS units
        FROM entries
        WHERE date(occurred_at, 'localtime') BETWEEN ? AND ?
        GROUP BY date(occurred_at, 'localtime')
        """,
        (first_day.isoformat(), today.isoformat()),
    ).fetchall()
    totals = {row["day"]: row["units"] for row in rows}
    return [
        {
            "date": (first_day + timedelta(days=offset)),
            "units": totals.get((first_day + timedelta(days=offset)).isoformat(), 0),
        }
        for offset in range(14)
    ]


if __name__ == "__main__":
    app = create_app()
    app.run()
