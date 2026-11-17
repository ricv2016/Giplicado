from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.renamer import RenameRules, apply_renames, build_name, file_datetime, find_conflicts
from ..core.scanner import CATEGORIES, category_of
from .media_player import MediaPreview

ALL_MEDIA = set().union(*CATEGORIES.values())


class RenameTab(QWidget):
    def __init__(self):
        super().__init__()
        self.files: list[Path] = []
        self.manual: dict[Path, str] = {}     # nombres editados a mano (renombrado individual)
        self.date_cache: dict = {}
        self.undo_stack: list[list[tuple[Path, Path]]] = []
        self._updating = False

        # --- Archivos ---
        b_files = QPushButton("Agregar archivos…")
        b_files.clicked.connect(self.add_files)
        b_dir = QPushButton("Agregar carpeta…")
        b_dir.clicked.connect(self.add_folder)
        self.chk_sub = QCheckBox("incluir subcarpetas")
        self.chk_media = QCheckBox("solo foto/audio/video")
        self.chk_media.setChecked(True)
        b_rm = QPushButton("Quitar seleccionados")
        b_rm.clicked.connect(self.remove_selected)
        b_clear = QPushButton("Limpiar lista")
        b_clear.clicked.connect(self.clear)
        top = QHBoxLayout()
        for w in (b_files, b_dir, self.chk_sub, self.chk_media):
            top.addWidget(w)
        top.addStretch()
        top.addWidget(b_rm)
        top.addWidget(b_clear)

        # --- Reglas ---
        self.template = QLineEdit("{nombre}")
        tok_row = QHBoxLayout()
        tok_row.addWidget(self.template, 1)
        for tok in ("{nombre}", "{n}", "{fecha}", "{hora}", "{carpeta}", "{tipo}"):
            b = QPushButton(tok)
            b.setMaximumWidth(80)
            b.clicked.connect(lambda _=False, t=tok: self.template.insert(t))
            tok_row.addWidget(b)

        self.start = QSpinBox(); self.start.setRange(0, 10**7); self.start.setValue(1)
        self.step = QSpinBox(); self.step.setRange(1, 1000); self.step.setValue(1)
        self.digits = QSpinBox(); self.digits.setRange(1, 10); self.digits.setValue(3)
        num_row = QHBoxLayout()
        for lbl, w in (("Inicio", self.start), ("Incremento", self.step), ("Dígitos", self.digits)):
            num_row.addWidget(QLabel(lbl)); num_row.addWidget(w)
        num_row.addStretch()

        self.find = QLineEdit(); self.find.setPlaceholderText("buscar texto")
        self.replace = QLineEdit(); self.replace.setPlaceholderText("reemplazar por")
        self.regex = QCheckBox("expresión regular")
        fr_row = QHBoxLayout()
        fr_row.addWidget(self.find); fr_row.addWidget(self.replace); fr_row.addWidget(self.regex)

        self.case = QComboBox()
        self.case.addItems(["ninguno", "minusculas", "mayusculas", "titulo"])
        self.ext_lower = QCheckBox("extensión en minúsculas")
        self.order = QComboBox()
        self.order.addItems(["Orden de la lista", "Por nombre", "Por fecha (EXIF / modificación)",
                             "Por tamaño"])
        misc = QHBoxLayout()
        misc.addWidget(QLabel("Mayúsculas:")); misc.addWidget(self.case)
        misc.addWidget(self.ext_lower)
        misc.addSpacing(20)
        misc.addWidget(QLabel("Numerar en:")); misc.addWidget(self.order)
        misc.addStretch()

        rules = QGroupBox("Reglas de renombrado por lote")
        form = QFormLayout(rules)
        form.addRow("Plantilla:", tok_row)
        form.addRow("Numeración {n}:", num_row)
        form.addRow("Buscar/Reemplazar:", fr_row)
        form.addRow("", misc)
        hint = QLabel("<small>Ej.: <b>Vacaciones_{fecha}_{n}</b> → Vacaciones_2024-07-15_001.jpg · "
                      "La extensión se conserva. Doble clic en “Nuevo nombre” para cambiar un "
                      "archivo individualmente.</small>")
        hint.setWordWrap(True)
        form.addRow(hint)

        for w in (self.template, self.find, self.replace):
            w.textChanged.connect(self.refresh)
        for w in (self.start, self.step, self.digits):
            w.valueChanged.connect(self.refresh)
        for w in (self.regex, self.ext_lower):
            w.toggled.connect(self.refresh)
        self.case.currentIndexChanged.connect(self.refresh)
        self.order.currentIndexChanged.connect(self.reorder)

        # --- Tabla ---
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Nombre actual", "Nuevo nombre", "Carpeta", "Estado"])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.setSectionResizeMode(1, QHeaderView.Interactive)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(1, 280)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.itemChanged.connect(self.on_cell_edited)
        self.table.currentCellChanged.connect(self.on_row_changed)

        self.player = MediaPreview()
        split = QSplitter()
        split.addWidget(self.table)
        split.addWidget(self.player)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([700, 380])

        # --- Acciones ---
        self.summary = QLabel("")
        b_reset = QPushButton("Descartar ediciones manuales")
        b_reset.clicked.connect(lambda: (self.manual.clear(), self.refresh()))
        self.b_undo = QPushButton("↶ Deshacer último")
        self.b_undo.setEnabled(False)
        self.b_undo.clicked.connect(self.undo)
        self.b_apply = QPushButton("✔ Renombrar")
        self.b_apply.setStyleSheet("font-weight:bold; padding:6px 14px;")
        self.b_apply.clicked.connect(self.apply)
        acts = QHBoxLayout()
        acts.addWidget(self.summary); acts.addStretch()
        acts.addWidget(b_reset); acts.addWidget(self.b_undo); acts.addWidget(self.b_apply)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(rules)
        lay.addWidget(split, 1)
        lay.addLayout(acts)

    # ---------- lista de archivos ----------
    def add_paths(self, paths):
        known = set(self.files)
        for p in paths:
            p = Path(p)
            if p.is_file() and p not in known:
                self.files.append(p)
                known.add(p)
        self.reorder()

    def add_files(self):
        names, _ = QFileDialog.getOpenFileNames(self, "Elegir archivos")
        self.add_paths(names)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Elegir carpeta")
        if not d:
            return
        root = Path(d)
        it = root.rglob("*") if self.chk_sub.isChecked() else root.iterdir()
        paths = [p for p in it if p.is_file()
                 and (not self.chk_media.isChecked() or p.suffix.lower() in ALL_MEDIA)]
        self.add_paths(sorted(paths, key=lambda p: str(p).lower()))

    def remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            p = self.files.pop(r)
            self.manual.pop(p, None)
        self.refresh()

    def clear(self):
        self.files.clear()
        self.manual.clear()
        self.refresh()

    def reorder(self):
        mode = self.order.currentIndex()
        if mode == 1:
            self.files.sort(key=lambda p: p.name.lower())
        elif mode == 2:
            self.files.sort(key=self._date)
        elif mode == 3:
            self.files.sort(key=lambda p: p.stat().st_size if p.exists() else 0)
        self.refresh()

    def _date(self, p: Path):
        if p not in self.date_cache:
            try:
                self.date_cache[p] = file_datetime(p)
            except OSError:
                from datetime import datetime
                self.date_cache[p] = datetime.min
        return self.date_cache[p]

    # ---------- vista previa ----------
    def rules(self) -> RenameRules:
        return RenameRules(
            template=self.template.text() or "{nombre}",
            start=self.start.value(), step=self.step.value(), digits=self.digits.value(),
            find=self.find.text(), replace=self.replace.text(), use_regex=self.regex.isChecked(),
            case=self.case.currentText(), ext_lower=self.ext_lower.isChecked(),
        )

    def compute(self) -> tuple[list[tuple[Path, str]], str | None]:
        r = self.rules()
        out, err = [], None
        for i, p in enumerate(self.files):
            if p in self.manual:
                out.append((p, self.manual[p]))
                continue
            try:
                out.append((p, build_name(p, i, r, self.date_cache)))
            except Exception as e:  # regex inválida, etc.
                err = str(e)
                out.append((p, p.name))
        return out, err

    def refresh(self):
        pairs, err = self.compute()
        conflicts = find_conflicts(pairs)
        self._updating = True
        self.table.setRowCount(len(pairs))
        changes = 0
        for row, (p, new) in enumerate(pairs):
            a = QTableWidgetItem(p.name); a.setFlags(a.flags() & ~Qt.ItemIsEditable)
            b = QTableWidgetItem(new)
            c = QTableWidgetItem(str(p.parent)); c.setFlags(c.flags() & ~Qt.ItemIsEditable)
            if row in conflicts:
                state, color = "⚠ Conflicto", QColor("#e74c3c")
            elif new != p.name:
                state, color = ("✎ Manual" if p in self.manual else "Cambiará"), QColor("#27ae60")
                changes += 1
            else:
                state, color = "Sin cambio", None
            d = QTableWidgetItem(state); d.setFlags(d.flags() & ~Qt.ItemIsEditable)
            if color:
                d.setForeground(QBrush(color))
                b.setForeground(QBrush(color))
            for col, item in enumerate((a, b, c, d)):
                self.table.setItem(row, col, item)
        self._updating = False
        txt = f"{len(pairs)} archivos · {changes} cambiarán"
        if conflicts:
            txt += f" · ⚠ {len(conflicts)} con conflicto"
        if err:
            txt += f" · Error en reglas: {err}"
        self.summary.setText(txt)
        self.b_apply.setEnabled(changes > 0 and not conflicts and not err)

    def on_cell_edited(self, item: QTableWidgetItem):
        if self._updating or item.column() != 1:
            return
        p = self.files[item.row()]
        new = item.text().strip()
        if not new:
            self.manual.pop(p, None)
        else:
            if not Path(new).suffix:
                new += p.suffix
            self.manual[p] = new
        self.refresh()

    def on_row_changed(self, row, _col=0, prev_row=-1, _pc=0):
        if 0 <= row < len(self.files):
            if self.files[row] != self.player.path:   # no reiniciar al editar las reglas
                self.player.load(self.files[row])
        else:
            self.player.clear()

    # ---------- aplicar ----------
    def apply(self):
        pairs, _ = self.compute()
        pairs = [(p, n) for p, n in pairs if p.name != n]
        if not pairs:
            return
        if QMessageBox.question(self, "Confirmar", f"¿Renombrar {len(pairs)} archivo(s)?") != QMessageBox.Yes:
            return
        self.player.clear()            # Windows: soltar el archivo antes de renombrar
        undo, errs = apply_renames(pairs)
        mapping = {orig: new for new, orig in undo}
        self.files = [mapping.get(p, p) for p in self.files]
        self.manual.clear()
        self.date_cache = {mapping.get(k, k): v for k, v in self.date_cache.items()}
        if undo:
            self.undo_stack.append(undo)
            self.b_undo.setEnabled(True)
        self.refresh()
        self.on_row_changed(self.table.currentRow())
        msg = f"{len(undo)} archivo(s) renombrados."
        if errs:
            msg += "\n\nErrores:\n" + "\n".join(errs[:15])
        QMessageBox.information(self, "Resultado", msg)

    def undo(self):
        if not self.undo_stack:
            return
        batch = self.undo_stack.pop()
        pairs = [(new, orig.name) for new, orig in batch if new.exists()]
        self.player.clear()
        redo, errs = apply_renames(pairs)
        mapping = {orig: new for new, orig in redo}
        self.files = [mapping.get(p, p) for p in self.files]
        self.b_undo.setEnabled(bool(self.undo_stack))
        self.refresh()
        self.on_row_changed(self.table.currentRow())
        msg = f"Se restauraron {len(redo)} nombre(s)."
        if errs:
            msg += "\n\nErrores:\n" + "\n".join(errs[:15])
        QMessageBox.information(self, "Deshacer", msg)
