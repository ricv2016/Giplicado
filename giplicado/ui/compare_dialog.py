"""Comparación lado a lado de dos archivos (foto, audio o video)."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QSplitter, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core.scanner import FileInfo, human_size
from .media_player import MediaPreview


class _Side(QWidget):
    def __init__(self, item: QTreeWidgetItem, fi: FileInfo, other: FileInfo, role):
        super().__init__()
        self.item = item
        self.player = MediaPreview()
        self.player.load(fi.path, fi.note)

        def mark(text, better):
            color = "#27ae60" if better else "#888"
            return f"<span style='color:{color}'>{text}{' ✔' if better else ''}</span>"

        rows = [
            ("Tamaño", mark(human_size(fi.size), fi.size > other.size)),
            ("Modificado", mark(datetime.fromtimestamp(fi.mtime).strftime("%Y-%m-%d %H:%M"),
                                fi.mtime < other.mtime) + " <small>(✔ = más antiguo)</small>"),
        ]
        if fi.quality or other.quality:
            parts = [p for p in fi.note.split(" · ") if "×" in p or "kbps" in p]
            rows.insert(0, ("Calidad", mark(parts[0] if parts else "—", fi.quality > other.quality)))
        self.details = QLabel("<table>" + "".join(
            f"<tr><td><b>{k}:</b>&nbsp;</td><td>{v}</td></tr>" for k, v in rows) + "</table>")

        self.btn = QPushButton()
        self.btn.setCheckable(True)
        self.btn.setChecked(item.checkState(0) == Qt.Checked)
        self.btn.toggled.connect(self._toggle)
        self._update_btn()

        lay = QVBoxLayout(self)
        lay.addWidget(self.player, 1)
        lay.addWidget(self.details)
        lay.addWidget(self.btn)

    def _toggle(self, on: bool):
        self.item.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
        self._update_btn()

    def _update_btn(self):
        on = self.btn.isChecked()
        self.btn.setText("🗑 Marcado para eliminar" if on else "Conservar (clic para marcar)")
        self.btn.setStyleSheet("color:#c0392b; font-weight:bold;" if on else "")


class CompareDialog(QDialog):
    def __init__(self, parent, a: QTreeWidgetItem, b: QTreeWidgetItem, role):
        super().__init__(parent)
        self.setWindowTitle("Comparar lado a lado")
        self.resize(1200, 720)
        fa, fb = a.data(0, role), b.data(0, role)
        self.sides = [_Side(a, fa, fb, role), _Side(b, fb, fa, role)]
        split = QSplitter(Qt.Horizontal)
        for s in self.sides:
            split.addWidget(s)
        hint = QLabel("<small>✔ verde = mejor en ese aspecto. "
                      "Ctrl+Espacio reproduce/pausa el lado activo.</small>")
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addWidget(hint, 1)
        bottom.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(split, 1)
        lay.addLayout(bottom)

    def done(self, r):
        for s in self.sides:       # soltar archivos (Windows) antes de cerrar
            s.player.release()
        super().done(r)
