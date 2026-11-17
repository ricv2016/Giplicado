"""Detección de fotos parecidas mediante hash perceptual (pHash).

El pHash resume la "forma" visual de la imagen en 64 bits. Dos fotos iguales pero
redimensionadas, recomprimidas, convertidas de formato o con leves retoques tienen
hashes casi idénticos. La distancia de Hamming (bits distintos) mide la diferencia:
  0      → visualmente idénticas
  1-6    → la misma foto con cambios menores (recomendado)
  7-12   → muy parecidas (ráfagas, ligeros recortes); más falsos positivos
"""
from __future__ import annotations

from typing import Callable

import numpy as np
from PIL import Image, ImageOps

from .scanner import Cancelled, DuplicateGroup, FileInfo, UnionFind, _noop, ProgressCb, compute_all

try:  # soporte opcional HEIC/HEIF (fotos de iPhone)
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass


# pHash: DCT 2D sobre la imagen en gris 32x32, se conservan las 8x8 frecuencias bajas
# y cada bit indica si el coeficiente supera la mediana. Equivale exactamente a
# imagehash.phash(), pero solo con NumPy (evita incluir SciPy, ~80 MB, en el .exe).
_N = 32
_DCT = 2 * np.cos(np.pi * np.arange(_N)[:, None] * (2 * np.arange(_N)[None, :] + 1) / (2 * _N))
_WEIGHTS = 1 << np.arange(63, -1, -1, dtype=np.uint64)


def phash(img: Image.Image) -> int:
    px = np.asarray(img.convert("L").resize((_N, _N), Image.Resampling.LANCZOS), dtype=np.float64)
    low = (_DCT @ px @ _DCT.T)[:8, :8]
    bits = (low > np.median(low)).flatten().astype(np.uint64)
    return int((bits * _WEIGHTS).sum())


def image_phash(fi: FileInfo) -> tuple[int, int, int]:
    """Devuelve (hash de 64 bits, ancho, alto)."""
    with Image.open(fi.path) as img:
        w, h = img.size
        img.draft("RGB", (512, 512))          # decodificación reducida para JPEG: mucho más rápido
        img = ImageOps.exif_transpose(img)    # respeta la rotación de la cámara
        return phash(img), w, h


def popcount(x: np.ndarray) -> np.ndarray:
    if hasattr(np, "bitwise_count"):
        return np.bitwise_count(x)
    return np.unpackbits(x.view(np.uint8), axis=-1).reshape(*x.shape, 64).sum(-1)


def find_similar_images(
    files: list[FileInfo],
    max_distance: int = 6,
    is_cancelled: Callable[[], bool] = lambda: False,
    progress: ProgressCb = _noop,
    errors: list[str] | None = None,
    workers: int = 8,
    cache=None,
) -> list[DuplicateGroup]:
    errors = errors if errors is not None else []
    photos = [f for f in files if f.category == "foto"]
    done = compute_all(photos, "phash", image_phash, cache, workers, "Analizando fotos",
                       is_cancelled, progress, errors)
    ok: list[FileInfo] = []
    hashes: list[int] = []
    for fi, (h, w, hgt) in done:
        fi.quality = w * hgt
        fi.note = f"{w}×{hgt}"
        ok.append(fi)
        hashes.append(h)

    if len(ok) < 2:
        return []

    arr = np.array(hashes, dtype=np.uint64)
    uf = UnionFind(len(arr))
    block = 1024
    total = len(arr)
    for start in range(0, total, block):
        if is_cancelled():
            raise Cancelled
        chunk = arr[start:start + block]
        dist = popcount(chunk[:, None] ^ arr[None, :])
        ii, jj = np.nonzero(dist <= max_distance)
        for i, j in zip(ii + start, jj):
            if i < j:
                uf.union(int(i), int(j))
        progress("Comparando fotos", min(start + block, total), total)

    groups: list[DuplicateGroup] = []
    for idxs in uf.groups():
        idxs.sort(key=lambda i: (-ok[i].quality, -ok[i].size))   # la mejor calidad primero
        members = [ok[i] for i in idxs]
        ref = hashes[idxs[0]]
        for i, f in zip(idxs, members):
            d = bin(ref ^ hashes[i]).count("1")
            sim = round(100 * (1 - d / 64))
            f.note = f"{f.note} · {sim}% parecida" if f is not members[0] else f"{f.note} · referencia"
        groups.append(DuplicateGroup(f"phash {ref:016x}", members[0].size, members, "foto_parecida"))
    groups.sort(key=lambda g: g.wasted, reverse=True)
    return groups
