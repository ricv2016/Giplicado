"""Detección de videos parecidos: el mismo video en otra resolución, formato o calidad.

Para cada video se toma la duración y el pHash de 9 cuadros en posiciones relativas
fijas (10 %, 20 % … 90 %). Dos videos se consideran el mismo si:
  · su duración difiere poco (para descartar rápido), y
  · la distancia media entre sus cuadros es baja y casi todos los cuadros coinciden.
Usa PyAV (FFmpeg, LGPL) para leer los cuadros.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from .scanner import Cancelled, DuplicateGroup, FileInfo, UnionFind, _noop, ProgressCb, compute_all
from .similar_images import phash, popcount

POSITIONS = [i / 10 for i in range(1, 10)]


def video_signature(fi: FileInfo) -> tuple[float, int, int, list[int]]:
    """Devuelve (duración s, ancho, alto, [pHash por cuadro])."""
    import av

    with av.open(str(fi.path)) as container:
        vs = next(s for s in container.streams if s.type == "video")
        vs.thread_type = "AUTO"
        if container.duration:
            duration = container.duration / av.time_base
        elif vs.duration and vs.time_base:
            duration = float(vs.duration * vs.time_base)
        else:
            duration = 0.0
        w, h = vs.codec_context.width, vs.codec_context.height
        hashes: list[int] = []
        if duration <= 0:
            raise ValueError("duración desconocida")
        for pos in POSITIONS:
            target = pos * duration
            ts = int(target / vs.time_base) + (vs.start_time or 0)
            container.seek(ts, stream=vs, any_frame=False, backward=True)
            frame = None
            for frame in container.decode(vs):
                if frame.time is None or frame.time >= target - 0.05:
                    break
            if frame is None:
                continue
            img = frame.to_image()
            img.thumbnail((256, 256))
            hashes.append(phash(img))
        if len(hashes) < 3:
            raise ValueError("no se pudieron leer cuadros")
        return duration, w, h, hashes


def frame_distance(a: list[int], b: list[int]) -> tuple[float, float]:
    """(distancia media en bits, fracción de cuadros que coinciden con ≤ 12 bits)."""
    n = min(len(a), len(b))
    x = np.array(a[:n], dtype=np.uint64) ^ np.array(b[:n], dtype=np.uint64)
    d = popcount(x).astype(float)
    return float(d.mean()), float((d <= 12).mean())


def find_similar_videos(
    files: list[FileInfo],
    max_distance: int = 10,
    duration_tolerance: float = 0.03,
    is_cancelled: Callable[[], bool] = lambda: False,
    progress: ProgressCb = _noop,
    errors: list[str] | None = None,
    workers: int = 3,
    cache=None,
) -> list[DuplicateGroup]:
    errors = errors if errors is not None else []
    videos = [f for f in files if f.category == "video"]
    done = compute_all(videos, "vsig", video_signature, cache, workers, "Analizando videos",
                       is_cancelled, progress, errors)
    ok: list[tuple[FileInfo, float, list[int]]] = []
    for fi, (dur, w, h, hashes) in done:
        fi.quality = w * h
        fi.note = f"{w}×{h} · {int(dur // 60)}:{int(dur % 60):02d}"
        ok.append((fi, dur, hashes))

    ok.sort(key=lambda t: t[1])
    uf = UnionFind(len(ok))
    score: dict[tuple[int, int], float] = {}
    for i in range(len(ok)):
        if is_cancelled():
            raise Cancelled
        di = ok[i][1]
        for j in range(i + 1, len(ok)):
            dj = ok[j][1]
            if dj - di > max(1.5, duration_tolerance * di):
                break
            mean, frac = frame_distance(ok[i][2], ok[j][2])
            if mean <= max_distance and frac >= 0.75:
                uf.union(i, j)
                score[(i, j)] = mean
        progress("Comparando videos", i + 1, len(ok))

    groups: list[DuplicateGroup] = []
    for idxs in uf.groups():
        idxs.sort(key=lambda k: (-ok[k][0].quality, -ok[k][0].size))
        ref = idxs[0]
        members = []
        for k in idxs:
            fi = ok[k][0]
            if k == ref:
                fi.note += " · referencia"
            else:
                mean = score.get((min(ref, k), max(ref, k)))
                if mean is None:
                    mean = frame_distance(ok[ref][2], ok[k][2])[0]
                fi.note += f" · {round(100 * (1 - mean / 64))}% parecido"
            members.append(fi)
        groups.append(DuplicateGroup(f"video {ref}", members[0].size, members, "video_parecido"))
    groups.sort(key=lambda g: g.wasted, reverse=True)
    return groups
