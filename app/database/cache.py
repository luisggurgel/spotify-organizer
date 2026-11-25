import sqlite3
import time
from contextlib import contextmanager

from app.models.schemas import LanguageResult


class CacheDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS track_language_cache (
                    track_id TEXT PRIMARY KEY,
                    language TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    isrc TEXT,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    access_token TEXT NOT NULL,
                    refresh_token TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )

    def save_tokens(self, access_token: str, refresh_token: str, expires_in: int) -> None:
        expires_at = int(time.time()) + expires_in
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO oauth_tokens (id, access_token, refresh_token, expires_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    expires_at = excluded.expires_at
                """,
                (access_token, refresh_token, expires_at),
            )

    def get_tokens(self) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM oauth_tokens WHERE id = 1").fetchone()
            return dict(row) if row else None

    def get_track_language(self, track_id: str) -> LanguageResult | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT language, confidence FROM track_language_cache WHERE track_id = ?",
                (track_id,),
            ).fetchone()
            if not row:
                return None
            return LanguageResult(
                language=row["language"],
                confidence=row["confidence"],
                source="cache",
            )

    def save_track_language(
        self, track_id: str, result: LanguageResult, isrc: str | None = None
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO track_language_cache (track_id, language, confidence, source, isrc, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(track_id) DO UPDATE SET
                    language = excluded.language,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    isrc = excluded.isrc,
                    updated_at = excluded.updated_at
                """,
                (
                    track_id,
                    result.language,
                    result.confidence,
                    result.source,
                    isrc,
                    int(time.time()),
                ),
            )

    def clear_language_cache(self) -> int:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM track_language_cache")
            return cur.rowcount
