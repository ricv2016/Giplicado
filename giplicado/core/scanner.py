"""Detección de archivos duplicados por contenido exacto.

Estrategia en 3 fases (el nombre del archivo nunca importa):
  1. Agrupar por tamaño en bytes (archivos de tamaño distinto no pueden ser iguales).
  2. Hash parcial (inicio + final del archivo) para descartar rápido.
  3. Hash completo BLAKE2b para confirmar que el contenido es idéntico.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

PHOTO_EXT = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic",
    ".heif", ".raw", ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".svg",
}
AUDIO_EXT = {
    ".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".oga", ".opus", ".wma",
    ".aiff", ".aif", ".alac", ".amr", ".mid", ".midi",
}
VIDEO_EXT = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg",
    ".mpeg", ".3gp", ".mts", ".m2ts", ".ts", ".vob",
}
CATEGORIES = {"foto": PHOTO_EXT, "audio": AUDIO_EXT, "video": VIDEO_EXT}

PARTIAL_CHUNK = 64 * 1024          # 64 KB del inicio y del final
FULL_CHUNK = 1024 * 1024           # lectura en bloques de 1 MB


def category_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    for name, exts in CATEGORIES.items():
        if ext in exts:
            return name
    return None


@dataclass
class FileInfo:
    path: Path
    size: int
    mtime: float
    category: str
    note: str = ""          # detalle mostrado en la interfaz (resolución, % similitud…)
    quality: float = 0.0    # mayor = mejor calidad (píxeles, bitrate…)


@dataclass
class DuplicateGroup:
    digest: str
    size: int
    files: list[FileInfo] = field(default_factory=list)
    kind: str = "exacto"    # exacto | foto_parecida | audio_igual

    @property
    def wasted(self) -> int:
        """Bytes que se liberarían conservando una sola copia (la más grande si no son idénticos)."""
        if self.kind == "exacto":
            return self.size * (len(self.files) - 1)
        sizes = [f.size for f in self.files]
        return sum(sizes) - max(sizes)


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra

    def groups(self) -> list[list[int]]:
        out: dict[int, list[int]] = {}
        for i in range(len(self.parent)):
            out.setdefault(self.find(i), []).append(i)
        return [g for g in out.values() if len(g) > 1]


class Cancelled(Exception):
    pass


ProgressCb = Callable[[str, int, int], None]   # (fase, actual, total)


def _noop(*_a) -> None:
    pass


def compute_all(
    files: list[FileInfo],
    kind: str,
    compute: Callable[[FileInfo], object],
    cache=None,
    workers: int = 4,
    phase: str = "Analizando",
    is_cancelled: Callable[[], bool] = lambda: False,
    progress: ProgressCb = _noop,
    errors: list[str] | None = None,
) -> list[tuple[FileInfo, object]]:
    """Calcula `compute(fi)` para cada archivo usando la caché cuando es posible.

    Devuelve [(archivo, valor)] en el mismo orden, omitiendo los que fallaron.
    Los resultados nuevos se guardan en la caché por lotes (sobreviven a una cancelación).
    """
    from concurrent.futures import ThreadPoolExecutor

    errors = errors if errors is not None else []
    results: dict[int, object] = {}
    pending: list[int] = []
    for i, fi in enumerate(files):
        v = cache.get(fi.path, kind, fi.size, fi.mtime) if cache else None
        if v is not None:
            results[i] = v
        else:
            pending.append(i)
    done = len(results)
    total = len(files)
    progress(phase, done, total)

    batch: list[tuple[Path, int, float, object]] = []
    with ThreadPoolExecutor(max(1, workers)) as pool:
        futures = [(i, pool.submit(compute, files[i])) for i in pending]
        try:
            for i, fut in futures:
                if is_cancelled():
                    raise Cancelled
                fi = files[i]
                try:
                    v = fut.result()
                    results[i] = v
                    batch.append((fi.path, fi.size, fi.mtime, v))
                except Exception as e:  # noqa: BLE001 - archivo dañado, formato no soportado…
                    errors.append(f"{fi.path}: {e}")
                done += 1
                progress(phase, done, total)
                if cache and len(batch) >= 100:
                    cache.put_many(kind, batch)
                    batch = []
        finally:
            for _, f in futures:
                f.cancel()
            if cache:
                cache.put_many(kind, batch)
    return [(files[i], results[i]) for i in range(total) if i in results]


def _partial_hash(path: Path, size: int) -> str:
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        h.update(f.read(PARTIAL_CHUNK))
        if size > PARTIAL_CHUNK * 2:
            f.seek(-PARTIAL_CHUNK, os.SEEK_END)
            h.update(f.read(PARTIAL_CHUNK))
    return h.hexdigest()


def _full_hash(path: Path, is_cancelled: Callable[[], bool]) -> str:
    h = hashlib.blake2b()
    with open(path, "rb") as f:
        while chunk := f.read(FULL_CHUNK):
            if is_cancelled():
                raise Cancelled
            h.update(chunk)
    return h.hexdigest()


def collect_files(
    roots: Iterable[Path],
    categories: set[str],
    min_size: int = 1,
    is_cancelled: Callable[[], bool] = lambda: False,
    progress: ProgressCb = _noop,
) -> list[FileInfo]:
    """Recorre las carpetas y devuelve los archivos multimedia encontrados."""
    seen: set[str] = set()
    found: list[FileInfo] = []
    for root in roots:
        for dirpath, _dirs, names in os.walk(root):
            if is_cancelled():
                raise Cancelled
            for name in names:
                p = Path(dirpath) / name
                cat = category_of(p)
                if cat is None or cat not in categories:
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                key = os.path.normcase(str(p.resolve()))
                if key in seen or st.st_size < min_size:
                    continue
                seen.add(key)
                found.append(FileInfo(p, st.st_size, st.st_mtime, cat))
            progress("Buscando archivos", len(found), 0)
    return found


def find_duplicates(
    roots: Iterable[Path],
    categories: set[str] | None = None,
    min_size: int = 1,
    is_cancelled: Callable[[], bool] = lambda: False,
    progress: ProgressCb = _noop,
    errors: list[str] | None = None,
    cache=None,
) -> list[DuplicateGroup]:
    categories = categories or set(CATEGORIES)
    files = collect_files(roots, categories, min_size, is_cancelled, progress)
    return exact_duplicates(files, is_cancelled, progress, errors, cache)


def exact_duplicates(
    files: list[FileInfo],
    is_cancelled: Callable[[], bool] = lambda: False,
    progress: ProgressCb = _noop,
    errors: list[str] | None = None,
    cache=None,
) -> list[DuplicateGroup]:
    errors = errors if errors is not None else []

    # Fase 1: por tamaño
    by_size: dict[int, list[FileInfo]] = {}
    for fi in files:
        by_size.setdefault(fi.size, []).append(fi)
    candidates = [g for g in by_size.values() if len(g) > 1]

    # Fase 2: hash parcial
    total = sum(len(g) for g in candidates)
    done = 0
    stage2: list[list[FileInfo]] = []
    for group in candidates:
        buckets: dict[str, list[FileInfo]] = {}
        for fi in group:
            if is_cancelled():
                raise Cancelled
            try:
                buckets.setdefault(_partial_hash(fi.path, fi.size), []).append(fi)
            except OSError as e:
                errors.append(f"{fi.path}: {e}")
            done += 1
            progress("Comparación rápida", done, total)
        stage2.extend(b for b in buckets.values() if len(b) > 1)

    # Fase 3: hash completo (con caché)
    flat = [fi for g in stage2 for fi in g]
    hashed = compute_all(flat, "blake2b", lambda fi: _full_hash(fi.path, is_cancelled), cache,
                         workers=2, phase="Verificando contenido", is_cancelled=is_cancelled,
                         progress=progress, errors=errors)
    digest_of = {id(fi): h for fi, h in hashed}
    result: list[DuplicateGroup] = []
    for group in stage2:
        buckets = {}
        for fi in group:
            if id(fi) in digest_of:
                buckets.setdefault(digest_of[id(fi)], []).append(fi)
        for digest, b in buckets.items():
            if len(b) > 1:
                b.sort(key=lambda x: (x.mtime, len(str(x.path))))
                result.append(DuplicateGroup(digest, b[0].size, b))

    result.sort(key=lambda g: g.wasted, reverse=True)
    return result


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"
