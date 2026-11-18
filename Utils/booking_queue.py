import json
import sqlite3
from contextlib import closing

from .settings import settings_file


class BookingQueue:
    def __init__(self, path=None):
        self.path = path if path is not None else settings_file().with_name("bookings.sqlite")

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=3)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous = FULL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS bookings (
                    sequence INTEGER PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    server TEXT NOT NULL,
                    username TEXT NOT NULL,
                    title TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    rejection TEXT,
                    archived INTEGER NOT NULL DEFAULT 0
                )
            """)
        except sqlite3.Error:
            db.close()
            raise
        return db

    def add(self, server, username, title, action, payload):
        with closing(self.connect()) as db, db:
            db.execute(
                """INSERT INTO bookings(request_id, server, username, title, action, payload)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (payload["request_id"], server, username, title, action, json.dumps(payload)),
            )

    def pending(self, server, username):
        with closing(self.connect()) as db:
            return db.execute(
                """SELECT request_id, title, action, payload, rejection FROM bookings
                   WHERE server = ? AND username = ? AND archived = 0 ORDER BY sequence""",
                (server, username),
            ).fetchall()

    def confirm(self, request_id):
        with closing(self.connect()) as db, db:
            db.execute("DELETE FROM bookings WHERE request_id = ?", (request_id,))

    def reject(self, request_id, message):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE bookings SET rejection = ? WHERE request_id = ?", (message, request_id))

    def retry_rejection(self, request_id):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE bookings SET rejection = NULL WHERE request_id = ? AND archived = 0", (request_id,))

    def archive_rejection(self, request_id):
        with closing(self.connect()) as db, db:
            db.execute(
                "UPDATE bookings SET archived = 1 WHERE request_id = ? AND rejection IS NOT NULL",
                (request_id,),
            )
