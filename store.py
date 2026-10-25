"""SQLite metadata store with JSON sample sequences. Does not modify recordings.jsonl."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from imu import SOURCES, normalize_label, recording_stats, validate_samples


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / 'visionglove.sqlite3'
        self.jsonl_path = self.data_dir / 'recordings.jsonl'
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute('PRAGMA foreign_keys = ON')
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS gestures (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY,
                gesture_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                source TEXT NOT NULL,
                sample_count INTEGER NOT NULL,
                duration_ms REAL NOT NULL,
                created_at TEXT NOT NULL,
                samples TEXT NOT NULL,
                FOREIGN KEY (gesture_id) REFERENCES gestures(id) ON DELETE CASCADE,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def _meta_get(self, key: str) -> str | None:
        row = self._conn.execute('SELECT value FROM meta WHERE key = ?', (key,)).fetchone()
        return None if row is None else row['value']

    def _meta_set(self, key: str, value: str) -> None:
        self._conn.execute(
            'INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
            (key, value),
        )

    def create_session(self, session_id: str | None = None) -> dict[str, str]:
        with self._lock:
            sid = session_id or new_id()
            existing = self._conn.execute('SELECT id, created_at FROM sessions WHERE id = ?', (sid,)).fetchone()
            if existing:
                return {'id': existing['id'], 'created_at': existing['created_at']}
            created = utcnow()
            self._conn.execute('INSERT INTO sessions(id, created_at) VALUES(?, ?)', (sid, created))
            self._conn.commit()
            return {'id': sid, 'created_at': created}

    def get_or_create_gesture(self, name: str) -> dict[str, str]:
        label = normalize_label(name)
        with self._lock:
            row = self._conn.execute(
                'SELECT id, name, created_at, updated_at FROM gestures WHERE name = ?', (label,)
            ).fetchone()
            if row:
                return dict(row)
            now = utcnow()
            gesture = {'id': new_id(), 'name': label, 'created_at': now, 'updated_at': now}
            self._conn.execute(
                'INSERT INTO gestures(id, name, created_at, updated_at) VALUES(?, ?, ?, ?)',
                (gesture['id'], gesture['name'], gesture['created_at'], gesture['updated_at']),
            )
            self._conn.commit()
            return gesture

    def create_gesture(self, name: str) -> dict[str, str]:
        label = normalize_label(name)
        with self._lock:
            now = utcnow()
            gesture = {'id': new_id(), 'name': label, 'created_at': now, 'updated_at': now}
            try:
                self._conn.execute(
                    'INSERT INTO gestures(id, name, created_at, updated_at) VALUES(?, ?, ?, ?)',
                    (gesture['id'], gesture['name'], gesture['created_at'], gesture['updated_at']),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError(f'Gesture name already exists: {label}') from exc
            return gesture

    def list_gestures(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT g.id, g.name, g.created_at, g.updated_at,
                       COUNT(r.id) AS recording_count
                FROM gestures g
                LEFT JOIN recordings r ON r.gesture_id = g.id
                GROUP BY g.id
                ORDER BY g.created_at
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_gesture(self, gesture_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                'SELECT id, name, created_at, updated_at FROM gestures WHERE id = ?', (gesture_id,)
            ).fetchone()
            return None if row is None else dict(row)

    def rename_gesture(self, gesture_id: str, name: str) -> dict[str, str]:
        label = normalize_label(name)
        with self._lock:
            if self._gesture_row(gesture_id) is None:
                raise KeyError('Gesture not found.')
            try:
                self._conn.execute(
                    'UPDATE gestures SET name = ?, updated_at = ? WHERE id = ?',
                    (label, utcnow(), gesture_id),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError(f'Gesture name already exists: {label}') from exc
            row = self._conn.execute(
                'SELECT id, name, created_at, updated_at FROM gestures WHERE id = ?', (gesture_id,)
            ).fetchone()
            return dict(row)

    def _gesture_row(self, gesture_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            'SELECT id, name, created_at, updated_at FROM gestures WHERE id = ?', (gesture_id,)
        ).fetchone()

    def delete_gesture(self, gesture_id: str) -> None:
        with self._lock:
            cur = self._conn.execute('DELETE FROM gestures WHERE id = ?', (gesture_id,))
            if cur.rowcount == 0:
                raise KeyError('Gesture not found.')
            self._conn.commit()

    def save_recording(self, *, gesture_id: str, session_id: str, source: str,
                       samples: list[dict], recording_id: str | None = None) -> dict[str, Any]:
        if source not in SOURCES:
            raise ValueError(f'Unsupported source. Expected one of {SOURCES}.')
        parsed = validate_samples(samples)
        stats = recording_stats(parsed)
        with self._lock:
            gesture = self._gesture_row(gesture_id)
            if gesture is None:
                raise KeyError('Gesture not found.')
            session = self._conn.execute('SELECT id FROM sessions WHERE id = ?', (session_id,)).fetchone()
            if session is None:
                raise KeyError('Session not found.')
            rid = recording_id or new_id()
            created = utcnow()
            self._conn.execute(
                """
                INSERT INTO recordings(
                    id, gesture_id, session_id, source, sample_count, duration_ms, created_at, samples
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (rid, gesture_id, session_id, source, stats['sample_count'], stats['duration_ms'],
                 created, json.dumps(parsed)),
            )
            self._conn.commit()
            return self._recording_from_row(
                self._conn.execute('SELECT * FROM recordings WHERE id = ?', (rid,)).fetchone(),
                include_samples=True,
                gesture_name=gesture['name'],
            )

    def list_recordings(self, *, include_samples: bool = False, gesture_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            sql = """
                SELECT r.*, g.name AS gesture_name
                FROM recordings r
                JOIN gestures g ON g.id = r.gesture_id
            """
            params: tuple[Any, ...] = ()
            if gesture_id:
                sql += ' WHERE r.gesture_id = ?'
                params = (gesture_id,)
            sql += ' ORDER BY r.created_at'
            rows = self._conn.execute(sql, params).fetchall()
            return [self._recording_from_row(row, include_samples=include_samples) for row in rows]

    def get_recording(self, recording_id: str, *, include_samples: bool = True) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT r.*, g.name AS gesture_name
                FROM recordings r
                JOIN gestures g ON g.id = r.gesture_id
                WHERE r.id = ?
                """,
                (recording_id,),
            ).fetchone()
            if row is None:
                return None
            return self._recording_from_row(row, include_samples=include_samples)

    def delete_recording(self, recording_id: str) -> None:
        with self._lock:
            cur = self._conn.execute('DELETE FROM recordings WHERE id = ?', (recording_id,))
            if cur.rowcount == 0:
                raise KeyError('Recording not found.')
            self._conn.commit()

    def append_jsonl(self, rec: dict[str, Any]) -> None:
        payload = {
            'label': rec['label'],
            'samples': rec['samples'],
            'source': rec['source'],
        }
        with self.jsonl_path.open('a', encoding='utf-8') as file:
            file.write(json.dumps(payload) + '\n')
        with self._lock:
            offset = self.jsonl_path.stat().st_size
            self._meta_set('jsonl_offset', str(offset))
            self._conn.commit()

    def import_legacy_jsonl(self) -> int:
        """Import new lines from recordings.jsonl without rewriting that file."""
        if not self.jsonl_path.exists():
            return 0
        imported = 0
        with self._lock:
            offset = int(self._meta_get('jsonl_offset') or 0)
            with self.jsonl_path.open('r', encoding='utf-8') as file:
                file.seek(offset)
                while True:
                    line = file.readline()
                    if line == '':
                        break
                    if not line.strip():
                        self._meta_set('jsonl_offset', str(file.tell()))
                        continue
                    try:
                        rec = json.loads(line)
                        self._import_legacy_unlocked(rec)
                        imported += 1
                    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                        pass
                    self._meta_set('jsonl_offset', str(file.tell()))
            self._conn.commit()
        return imported

    def _import_legacy_unlocked(self, rec: dict[str, Any]) -> None:
        label = normalize_label(rec['label'])
        source = rec.get('source', 'hardware')
        if source not in SOURCES:
            source = 'public_dataset'
        samples = validate_samples(rec['samples'])
        row = self._conn.execute(
            'SELECT id FROM gestures WHERE name = ?', (label,)
        ).fetchone()
        if row:
            gesture_id = row['id']
        else:
            now = utcnow()
            gesture_id = new_id()
            self._conn.execute(
                'INSERT INTO gestures(id, name, created_at, updated_at) VALUES(?, ?, ?, ?)',
                (gesture_id, label, now, now),
            )
        session_id = 'legacy-jsonl'
        if self._conn.execute('SELECT id FROM sessions WHERE id = ?', (session_id,)).fetchone() is None:
            self._conn.execute(
                'INSERT INTO sessions(id, created_at) VALUES(?, ?)', (session_id, utcnow())
            )
        stats = recording_stats(samples)
        self._conn.execute(
            """
            INSERT INTO recordings(
                id, gesture_id, session_id, source, sample_count, duration_ms, created_at, samples
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id(), gesture_id, session_id, source, stats['sample_count'], stats['duration_ms'],
             utcnow(), json.dumps(samples)),
        )

    def _recording_from_row(self, row: sqlite3.Row, *, include_samples: bool,
                            gesture_name: str | None = None) -> dict[str, Any]:
        name = gesture_name if gesture_name is not None else row['gesture_name']
        payload = {
            'id': row['id'],
            'recording_id': row['id'],
            'gesture_id': row['gesture_id'],
            'label': name,
            'session_id': row['session_id'],
            'source': row['source'],
            'sample_count': row['sample_count'],
            'duration_ms': row['duration_ms'],
            'created_at': row['created_at'],
        }
        if include_samples:
            payload['samples'] = json.loads(row['samples'])
        return payload
