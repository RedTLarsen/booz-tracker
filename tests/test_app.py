import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import create_app


class AlcoholTrackerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "test.sqlite3"
        self.app = create_app({"TESTING": True, "DATABASE": str(database)})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_database_path_can_be_configured_for_persistent_volume(self):
        database = Path(self.temp_dir.name) / "volume" / "tracker.sqlite3"
        with patch.dict("os.environ", {"DATABASE_PATH": str(database)}):
            app = create_app({"TESTING": True})

        self.assertEqual(app.config["DATABASE"], str(database))
        self.assertTrue(database.is_file())

    def test_add_entry_persists_and_is_shown(self):
        occurred_at = datetime.now().replace(microsecond=0).isoformat(timespec="minutes")
        response = self.client.post(
            "/entries",
            data={"units": "2.5", "occurred_at": occurred_at},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"2.50", response.data)
        self.assertIn(b"Entry added.", response.data)
        with self.app.app_context():
            connection = sqlite3.connect(self.app.config["DATABASE"])
            try:
                row = connection.execute("SELECT units FROM entries").fetchone()
            finally:
                connection.close()
        self.assertEqual(row[0], 2.5)

        reopened_app = create_app(
            {"TESTING": True, "DATABASE": self.app.config["DATABASE"]}
        )
        response_after_restart = reopened_app.test_client().get("/")
        self.assertIn(b"2.50", response_after_restart.data)

    def test_rolling_total_includes_only_entries_in_last_24_hours(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with self.app.app_context():
            connection = sqlite3.connect(self.app.config["DATABASE"])
            connection.executemany(
                "INSERT INTO entries (units, occurred_at) VALUES (?, ?)",
                [
                    (1.25, (now - timedelta(hours=23)).isoformat(timespec="seconds")),
                    (5.0, (now - timedelta(hours=25)).isoformat(timespec="seconds")),
                    (3.0, (now + timedelta(hours=1)).isoformat(timespec="seconds")),
                ],
            )
            connection.commit()
            connection.close()

        response = self.client.get("/")
        self.assertIn(b"<span>1.25</span>", response.data)
        self.assertIn(b"Last 24 hours", response.data)

    def test_invalid_units_are_rejected(self):
        response = self.client.post(
            "/entries",
            data={"units": "-1", "occurred_at": ""},
            follow_redirects=True,
        )

        self.assertIn(b"Enter a positive number", response.data)
        with self.app.app_context():
            count = sqlite3.connect(self.app.config["DATABASE"]).execute(
                "SELECT COUNT(*) FROM entries"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_entry_can_be_edited_and_deleted(self):
        with self.app.app_context():
            connection = sqlite3.connect(self.app.config["DATABASE"])
            cursor = connection.execute(
                "INSERT INTO entries (units, occurred_at) VALUES (?, ?)",
                (
                    1.0,
                    datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(timespec="seconds"),
                ),
            )
            entry_id = cursor.lastrowid
            connection.commit()
            connection.close()

        updated = self.client.post(
            f"/entries/{entry_id}/edit",
            data={
                "units": "4",
                "occurred_at": datetime.now().replace(microsecond=0).isoformat(timespec="minutes"),
            },
            follow_redirects=True,
        )
        self.assertIn(b"4.00", updated.data)
        deleted = self.client.post(
            f"/entries/{entry_id}/delete", follow_redirects=True
        )
        self.assertIn(b"No entries yet.", deleted.data)


if __name__ == "__main__":
    unittest.main()
