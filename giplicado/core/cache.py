"""Caché persistente de huellas (hash exacto, pHash, huella de audio y de video).

Se guarda en SQLite en %LOCALAPPDATA%\\Giplicado\\cache.db. Cada entrada se identifica
por ruta + tamaño + fecha de modificación: si el archivo cambia, la entrada deja de
coincidir y se recalcula. Así, volver a analizar una biblioteca grande es casi instantáneo.
"""
from __future__ import annotations

import os
import pickle
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1


def default_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(base) / "Giplicado" / "cache.db"


def _key(path: Path) -> str:
    return os.path.normcase(str(path))


class FingerprintCache:
    def __init__(self, db_path: Path | None = None):
        self.path = Path(db_path) if db_path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS fp (path TEXT, kind TEXT, size INTEGER, mtime INTEGER,"
            " value BLOB, PRIMARY KEY (path, kind))")
        self._db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
        row = self._db.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
        if row is None or int(row[0]) != SCHEMA_VERSION:
            self._db.execute("DELETE FROM fp")
            self._db.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
        self._db.commit()

    def get(self, path: Path, kind: str, size: int, mtime: float) -> Any | None:
        with self._lock:
            row = self._db.execute(
                "SELECT value FROM fp WHERE path=? AND kind=? AND size=? AND mtime=?",
                (_key(path), kind, size, int(mtime * 1000))).fetchone()
        if row is None:
            return None
        try:
            return pickle.loads(row[0])
        except Exception:  # noqa: BLE001 - entrada dañada: se recalcula
            return None

    def put_many(self, kind: str, items: Iterable[tuple[Path, int, float, Any]]) -> None:
        rows = [(_key(p), kind, size, int(mtime * 1000), pickle.dumps(v, protocol=5))
                for p, size, mtime, v in items]
        if not rows:
            return
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO fp VALUES (?,?,?,?,?)", rows)
            self._db.commit()

    def stats(self) -> tuple[int, int]:
        """(número de entradas, tamaño del archivo en bytes)."""
        with self._lock:
            n = self._db.execute("SELECT COUNT(*) FROM fp").fetchone()[0]
        try:
            size = self.path.stat().st_size
        except OSError:
            size = 0
        return n, size

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM fp")
            self._db.commit()
            self._db.execute("VACUUM")

    def close(self) -> None:
        with self._lock:
            self._db.close()


_shared: FingerprintCache | None = None


def shared_cache() -> FingerprintCache | None:
    """Caché global de la app (None si no se puede abrir: la app sigue funcionando sin ella)."""
    global _shared
    if _shared is None:
        try:
            _shared = FingerprintCache()
        except Exception:  # noqa: BLE001
            return None
    return _shared
