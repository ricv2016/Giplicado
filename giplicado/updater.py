"""Actualización automática desde GitHub Releases.

Flujo:
  1. Consulta https://api.github.com/repos/<repo>/releases/latest
  2. Si la etiqueta (v1.2.3) es mayor que la versión actual, ofrece actualizar.
  3. Descarga el instalador, verifica su SHA-256 (archivo .sha256 del release)
  4. Lo ejecuta en modo silencioso; el instalador cierra Giplicado, actualiza y lo vuelve a abrir.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__
from .config import GITHUB_REPO

API = "https://api.github.com/repos/{repo}/releases/latest"
HEADERS = {"User-Agent": "Giplicado-Updater", "Accept": "application/vnd.github+json"}
INSTALLER_SUFFIX = "-instalador.exe"


@dataclass
class UpdateInfo:
    version: str
    notes: str
    page_url: str
    installer_url: str
    installer_name: str
    size: int
    sha256_url: str | None


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0].split("+")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def _get(url: str, timeout: float = 15):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout)


def check_for_update(repo: str = GITHUB_REPO, current: str = __version__) -> UpdateInfo | None:
    """Devuelve la información de la nueva versión o None si ya está al día."""
    with _get(API.format(repo=repo)) as r:
        data = json.load(r)
    tag = data.get("tag_name", "")
    if data.get("draft") or data.get("prerelease") or not is_newer(tag, current):
        return None
    assets = {a["name"]: a for a in data.get("assets", [])}
    inst = next((a for n, a in assets.items() if n.endswith(INSTALLER_SUFFIX)), None)
    if not inst:
        return None
    sha = assets.get(inst["name"] + ".sha256")
    return UpdateInfo(
        version=tag.lstrip("vV"),
        notes=(data.get("body") or "").strip(),
        page_url=data.get("html_url", ""),
        installer_url=inst["browser_download_url"],
        installer_name=inst["name"],
        size=int(inst.get("size", 0)),
        sha256_url=sha["browser_download_url"] if sha else None,
    )


def download_installer(
    info: UpdateInfo,
    progress: Callable[[int, int], None] = lambda *_: None,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> Path | None:
    """Descarga y verifica el instalador. Devuelve la ruta o None si se canceló."""
    dest = Path(tempfile.mkdtemp(prefix="giplicado_update_")) / info.installer_name
    h = hashlib.sha256()
    done = 0
    with _get(info.installer_url, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or info.size or 0)
        while chunk := r.read(256 * 1024):
            if is_cancelled():
                f.close()
                dest.unlink(missing_ok=True)
                return None
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            progress(done, total)
    if info.sha256_url:
        with _get(info.sha256_url) as r:
            expected = r.read().decode().split()[0].lower()
        if h.hexdigest().lower() != expected:
            dest.unlink(missing_ok=True)
            raise ValueError("La descarga está dañada (la verificación SHA-256 no coincide).")
    return dest


def can_self_install() -> bool:
    """Solo la versión instalada (.exe empaquetado) puede reemplazarse a sí misma."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def launch_installer(path: Path) -> None:
    """Ejecuta el instalador en modo silencioso; luego la app debe cerrarse."""
    subprocess.Popen(
        [str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
        close_fds=True,
    )
