"""Detección de la misma canción en distintos formatos (MP3, FLAC, M4A, WAV…).

Usa Chromaprint (fpcalc), el motor libre de AcoustID: genera una huella acústica a
partir de lo que *suena*, no de los bytes. Se comparan las huellas bit a bit probando
pequeños desfases (silencios distintos al inicio) y se calcula el % de coincidencia.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import numpy as np

from .scanner import Cancelled, DuplicateGroup, FileInfo, UnionFind, _noop, ProgressCb, compute_all

FP_SECONDS = 120          # segundos analizados por canción
MAX_OFFSET = 30           # desfase máximo probado (~0.12 s por elemento → ±3.7 s)
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def find_fpcalc() -> str | None:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    for cand in (base / "tools" / "fpcalc.exe", base / "tools" / "fpcalc"):
        if cand.is_file():
            return str(cand)
    return shutil.which("fpcalc")


def fingerprint(path: Path, fpcalc: str) -> tuple[float, np.ndarray]:
    out = subprocess.run(
        [fpcalc, "-raw", "-json", "-length", str(FP_SECONDS), str(path)],
        capture_output=True, timeout=180, creationflags=_NO_WINDOW,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode(errors="replace").strip() or "fpcalc falló")
    data = json.loads(out.stdout)
    fp = np.array(data["fingerprint"], dtype=np.int64).astype(np.uint32)
    return float(data.get("duration", 0)), fp


def _bits(x: np.ndarray) -> int:
    if hasattr(np, "bitwise_count"):
        return int(np.bitwise_count(x).sum())
    return int(np.unpackbits(x.view(np.uint8)).sum())


def fp_similarity(a: np.ndarray, b: np.ndarray, max_offset: int = MAX_OFFSET) -> float:
    """1.0 = idénticas, ~0.5 = sin relación."""
    best = 0.0
    min_overlap = max(10, min(len(a), len(b)) // 2)
    for off in range(-max_offset, max_offset + 1):
        if off >= 0:
            x, y = a[off:], b
        else:
            x, y = a, b[-off:]
        n = min(len(x), len(y))
        if n < min_overlap:
            continue
        sim = 1.0 - _bits(x[:n] ^ y[:n]) / (32.0 * n)
        best = max(best, sim)
    return best


def find_same_audio(
    files: list[FileInfo],
    min_similarity: float = 0.80,
    duration_tolerance: float = 5.0,
    fpcalc: str | None = None,
    is_cancelled: Callable[[], bool] = lambda: False,
    progress: ProgressCb = _noop,
    errors: list[str] | None = None,
    workers: int = 4,
    cache=None,
) -> list[DuplicateGroup]:
    errors = errors if errors is not None else []
    fpcalc = fpcalc or find_fpcalc()
    if not fpcalc:
        raise FileNotFoundError("No se encontró fpcalc (Chromaprint).")

    # También se analizan videos si se pidieron: detecta el mismo audio en un clip
    items = [f for f in files if f.category in ("audio", "video")]
    done = compute_all(items, "chromaprint", lambda fi: fingerprint(fi.path, fpcalc), cache,
                       workers, "Escuchando audio", is_cancelled, progress, errors)
    ok: list[tuple[FileInfo, float, np.ndarray]] = []
    for fi, (dur, fp) in done:
        if len(fp) >= 10:
            kbps = fi.size * 8 / 1000 / dur if dur else 0
            fi.quality = kbps
            fi.note = f"{int(dur // 60)}:{int(dur % 60):02d} · ~{kbps:.0f} kbps"
            ok.append((fi, dur, fp))

    # Solo se comparan pistas de duración parecida (ventana deslizante por duración)
    ok.sort(key=lambda t: t[1])
    uf = UnionFind(len(ok))
    best_sim: dict[tuple[int, int], float] = {}
    for i in range(len(ok)):
        if is_cancelled():
            raise Cancelled
        for j in range(i + 1, len(ok)):
            if ok[j][1] - ok[i][1] > duration_tolerance:
                break
            s = fp_similarity(ok[i][2], ok[j][2])
            if s >= min_similarity:
                uf.union(i, j)
                best_sim[(i, j)] = s
        progress("Comparando huellas", i + 1, len(ok))

    groups: list[DuplicateGroup] = []
    for idxs in uf.groups():
        idxs.sort(key=lambda k: (-ok[k][0].quality, -ok[k][0].size))
        ref = idxs[0]
        members = []
        for k in idxs:
            fi = ok[k][0]
            if k != ref:
                s = best_sim.get((min(ref, k), max(ref, k))) or fp_similarity(ok[ref][2], ok[k][2])
                fi.note += f" · {s * 100:.0f}% igual"
            else:
                fi.note += " · referencia"
            members.append(fi)
        groups.append(DuplicateGroup(f"audio {ref}", members[0].size, members, "audio_igual"))
    groups.sort(key=lambda g: g.wasted, reverse=True)
    return groups
