"""Motor de renombrado individual y por lote.

Plantilla con etiquetas:
  {nombre}   nombre original sin extensión
  {n}        número consecutivo (se rellena con ceros según 'digitos')
  {fecha}    fecha de captura EXIF (fotos) o de modificación, AAAA-MM-DD
  {hora}     hora HH-MM-SS de la misma fuente
  {carpeta}  nombre de la carpeta que contiene el archivo
  {tipo}     foto / audio / video
La extensión original se conserva siempre.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .scanner import category_of

INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class RenameRules:
    template: str = "{nombre}"
    start: int = 1
    step: int = 1
    digits: int = 3
    find: str = ""
    replace: str = ""
    use_regex: bool = False
    case: str = "ninguno"   # ninguno | minusculas | mayusculas | titulo
    ext_lower: bool = False


def file_datetime(path: Path) -> datetime:
    """Fecha EXIF de captura si existe; si no, fecha de modificación."""
    if category_of(path) == "foto":
        try:
            from PIL import Image
            with Image.open(path) as img:
                exif = img.getexif()
                raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal / DateTime
                if raw:
                    return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def build_name(path: Path, index: int, rules: RenameRules, date_cache: dict | None = None) -> str:
    stem, ext = path.stem, path.suffix
    if date_cache is not None and path in date_cache:
        dt = date_cache[path]
    else:
        dt = None

    def get_dt() -> datetime:
        nonlocal dt
        if dt is None:
            dt = file_datetime(path)
            if date_cache is not None:
                date_cache[path] = dt
        return dt

    number = rules.start + index * rules.step
    tokens = {
        "nombre": lambda: stem,
        "n": lambda: str(number).zfill(rules.digits),
        "fecha": lambda: get_dt().strftime("%Y-%m-%d"),
        "hora": lambda: get_dt().strftime("%H-%M-%S"),
        "carpeta": lambda: path.parent.name,
        "tipo": lambda: category_of(path) or "archivo",
    }
    new = re.sub(r"\{(\w+)\}", lambda m: tokens[m.group(1)]() if m.group(1) in tokens else m.group(0),
                 rules.template)

    if rules.find:
        if rules.use_regex:
            new = re.sub(rules.find, rules.replace, new)
        else:
            new = new.replace(rules.find, rules.replace)

    if rules.case == "minusculas":
        new = new.lower()
    elif rules.case == "mayusculas":
        new = new.upper()
    elif rules.case == "titulo":
        new = new.title()

    new = INVALID_CHARS.sub("_", new).strip().rstrip(".")
    if rules.ext_lower:
        ext = ext.lower()
    return (new or stem) + ext


def find_conflicts(pairs: list[tuple[Path, str]]) -> set[int]:
    """Índices de filas cuyo nuevo nombre choca con otro o con un archivo existente."""
    targets: dict[str, list[int]] = {}
    sources = {str(p).lower() for p, _ in pairs}
    for i, (p, new) in enumerate(pairs):
        targets.setdefault(str(p.parent / new).lower(), []).append(i)
    bad: set[int] = set()
    for key, idxs in targets.items():
        if len(idxs) > 1:
            bad.update(idxs)
    for i, (p, new) in enumerate(pairs):
        dest = p.parent / new
        if dest.name.lower() != p.name.lower() and dest.exists() and str(dest).lower() not in sources:
            bad.add(i)
    return bad


def apply_renames(pairs: list[tuple[Path, str]]) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Renombra en dos pasos (vía nombre temporal) para permitir intercambios A<->B.

    Devuelve (lista de (nuevo, original) para deshacer, errores).
    """
    work = [(p, p.parent / n) for p, n in pairs if p.name != n]
    temps: list[tuple[Path, Path, Path]] = []
    errors: list[str] = []
    for i, (src, dst) in enumerate(work):
        tmp = src.with_name(f".__giplicado_tmp_{i}__{src.suffix}")
        try:
            src.rename(tmp)
            temps.append((src, tmp, dst))
        except OSError as e:
            errors.append(f"{src.name}: {e}")
    undo: list[tuple[Path, Path]] = []
    for src, tmp, dst in temps:
        try:
            tmp.rename(dst)
            undo.append((dst, src))
        except OSError as e:
            tmp.rename(src)
            errors.append(f"{src.name}: {e}")
    return undo, errors
