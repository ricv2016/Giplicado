from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QMessageBox, QProgressBar, QPushButton, QSpinBox, QSplitter,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from send2trash import send2trash

from ..core.audio_match import find_fpcalc, find_same_audio
from ..core.scanner import Cancelled, DuplicateGroup, FileInfo, collect_files, exact_duplicates, human_size
from ..core.similar_images import find_similar_images
from .compare_dialog import CompareDialog
from .media_player import MediaPreview

ROLE_INFO = Qt.UserRole + 1

MODES = [
    ("exacto", "Contenido idéntico (byte a byte)"),
    ("foto", "Fotos parecidas (redimensionadas, recomprimidas, otro formato)"),
    ("audio", "Misma canción en otro formato o calidad"),
]
KEEP = [
    ("calidad", "Conservar: mejor calidad"),
    ("antiguo", "Conservar: el más antiguo"),
    ("reciente", "Conservar: el más reciente"),
    ("ruta", "Conservar: ruta más corta"),
]
COL_NAME, COL_NOTE, COL_DIR, COL_SIZE, COL_DATE = range(5)


class ScanThread(QThread):
    progress = Signal(str, int, int)
    finished_ok = Signal(list, list)
    failed = Signal(str)

    def __init__(self, mode, roots, categories, min_size, sensitivity):
        super().__init__()
        self.mode, self.roots, self.categories = mode, roots, categories
        self.min_size, self.sensitivity = min_size, sensitivity
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        errors: list[str] = []
        kw = dict(is_cancelled=lambda: self._cancel,
                  progress=lambda *a: self.progress.emit(*a), errors=errors)
        try:
            files = collect_files(self.roots, self.categories, self.min_size,
                                  kw["is_cancelled"], kw["progress"])
            if self.mode == "foto":
                groups = find_similar_images(files, max_distance=self.sensitivity, **kw)
            elif self.mode == "audio":
                groups = find_same_audio(files, min_similarity=self.sensitivity / 100, **kw)
            else:
                groups = exact_duplicates(files, **kw)
            self.finished_ok.emit(groups, errors)
        except Cancelled:
            self.failed.emit("Búsqueda cancelada.")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"Error: {e}")


class DuplicatesTab(QWidget):
    send_to_rename = Signal(list)

    def __init__(self):
        super().__init__()
        self.thread: ScanThread | None = None
        self.groups: list[DuplicateGroup] = []

        # --- Configuración ---
        self.folders = QListWidget()
        self.folders.setMaximumHeight(80)
        btn_add = QPushButton("Agregar carpeta…")
        btn_del = QPushButton("Quitar")
        btn_add.clicked.connect(self.add_folder)
        btn_del.clicked.connect(lambda: [self.folders.takeItem(self.folders.row(i))
                                         for i in self.folders.selectedItems()])

        self.mode = QComboBox()
        for key, text in MODES:
            self.mode.addItem(text, key)
        self.mode.currentIndexChanged.connect(self.on_mode)

        self.chk = {k: QCheckBox(t) for k, t in
                    (("foto", "Fotos"), ("audio", "Audio"), ("video", "Video"))}
        for c in self.chk.values():
            c.setChecked(True)
        self.min_kb = QSpinBox()
        self.min_kb.setRange(0, 10_000_000)
        self.min_kb.setSuffix(" KB")
        self.min_kb.setValue(1)
        self.sens_lbl = QLabel()
        self.sens = QSpinBox()

        self.btn_scan = QPushButton("🔍 Buscar")
        self.btn_scan.setStyleSheet("font-weight:bold; padding:6px 14px;")
        self.btn_scan.clicked.connect(self.start_scan)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(lambda: self.thread and self.thread.cancel())

        cfg = QGroupBox("Dónde y cómo buscar")
        cl = QVBoxLayout(cfg)
        row = QHBoxLayout()
        row.addWidget(self.folders, 1)
        col = QVBoxLayout()
        col.addWidget(btn_add)
        col.addWidget(btn_del)
        col.addStretch()
        row.addLayout(col)
        cl.addLayout(row)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Modo:"))
        r1.addWidget(self.mode, 1)
        r1.addSpacing(10)
        r1.addWidget(self.sens_lbl)
        r1.addWidget(self.sens)
        cl.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Tipos:"))
        for c in self.chk.values():
            r2.addWidget(c)
        r2.addSpacing(20)
        r2.addWidget(QLabel("Tamaño mínimo:"))
        r2.addWidget(self.min_kb)
        r2.addStretch()
        r2.addWidget(self.btn_cancel)
        r2.addWidget(self.btn_scan)
        cl.addLayout(r2)

        self.progress = QProgressBar()
        self.status = QLabel("Agrega una o más carpetas y presiona Buscar.")
        self.status.setWordWrap(True)

        # --- Resultados + reproductor ---
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Nombre", "Detalle", "Carpeta", "Tamaño", "Modificado"])
        hdr = self.tree.header()
        hdr.setSectionResizeMode(COL_DIR, QHeaderView.Stretch)
        self.tree.setColumnWidth(COL_NAME, 250)
        self.tree.setColumnWidth(COL_NOTE, 190)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.currentItemChanged.connect(self.show_preview)
        self.tree.itemDoubleClicked.connect(self.open_item)
        self.tree.itemChanged.connect(lambda *_: self.update_marked_label())

        self.player = MediaPreview()

        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(self.player)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([650, 420])

        # --- Acciones ---
        self.keep = QComboBox()
        for key, text in KEEP:
            self.keep.addItem(text, key)
        b_auto = QPushButton("Marcar el resto")
        b_auto.setToolTip("En cada grupo deja sin marcar la copia a conservar y marca las demás")
        b_auto.clicked.connect(self.auto_mark)
        b_none = QPushButton("Desmarcar todo")
        b_none.clicked.connect(lambda: self.set_all_checks(False))
        b_cmp = QPushButton("⇆ Comparar lado a lado")
        b_cmp.setToolTip("Selecciona 2 archivos (Ctrl+clic) o un grupo")
        b_cmp.clicked.connect(self.compare)
        b_open = QPushButton("Abrir ubicación")
        b_open.clicked.connect(self.reveal_current)
        b_ren = QPushButton("Marcados → Renombrar")
        b_ren.clicked.connect(lambda: self.send_to_rename.emit(self.checked_paths()))
        b_move = QPushButton("Mover marcados a…")
        b_move.clicked.connect(self.move_checked)
        b_trash = QPushButton("🗑 Marcados a la Papelera")
        b_trash.setStyleSheet("color:#c0392b; font-weight:bold;")
        b_trash.clicked.connect(self.trash_checked)
        self.lbl_marked = QLabel("")

        acts = QHBoxLayout()
        for w in (self.keep, b_auto, b_none, b_cmp, b_open, b_ren):
            acts.addWidget(w)
        acts.addStretch()
        acts.addWidget(self.lbl_marked)
        acts.addWidget(b_move)
        acts.addWidget(b_trash)

        lay = QVBoxLayout(self)
        lay.addWidget(cfg)
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        lay.addWidget(split, 1)
        lay.addLayout(acts)

        self.on_mode()

    # ---------- modo ----------
    def current_mode(self) -> str:
        return self.mode.currentData()

    def on_mode(self):
        m = self.current_mode()
        self.sens.blockSignals(True)
        if m == "foto":
            self.sens_lbl.setText("Tolerancia (0 = idénticas, 12 = muy flexible):")
            self.sens.setRange(0, 16)
            self.sens.setValue(6)
            self.sens.setSuffix("")
        elif m == "audio":
            self.sens_lbl.setText("Coincidencia mínima:")
            self.sens.setRange(60, 99)
            self.sens.setValue(80)
            self.sens.setSuffix(" %")
        self.sens.blockSignals(False)
        self.sens.setVisible(m != "exacto")
        self.sens_lbl.setVisible(m != "exacto")
        allowed = {"exacto": {"foto", "audio", "video"}, "foto": {"foto"},
                   "audio": {"audio", "video"}}[m]
        for k, c in self.chk.items():
            c.setEnabled(k in allowed)
            if m != "exacto":
                c.setChecked(k in allowed and (k != "video" or m != "audio"))
        self.keep.setCurrentIndex(0 if m != "exacto" else 1)

    # ---------- búsqueda ----------
    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Elegir carpeta")
        if d and not self.folders.findItems(d, Qt.MatchExactly):
            self.folders.addItem(d)

    def start_scan(self):
        roots = [Path(self.folders.item(i).text()) for i in range(self.folders.count())]
        cats = {k for k, c in self.chk.items() if c.isChecked() and c.isEnabled()}
        if not roots:
            QMessageBox.information(self, "Giplicado", "Agrega al menos una carpeta.")
            return
        if not cats:
            QMessageBox.information(self, "Giplicado", "Elige al menos un tipo de archivo.")
            return
        if self.current_mode() == "audio" and not find_fpcalc():
            QMessageBox.warning(
                self, "Falta Chromaprint",
                "Para comparar canciones por cómo suenan se necesita <b>fpcalc.exe</b> "
                "(Chromaprint, gratuito y de código abierto).<br><br>"
                "Descárgalo de <a href='https://acoustid.org/chromaprint'>acoustid.org/chromaprint</a> "
                "y copia <b>fpcalc.exe</b> en la carpeta <b>tools</b> de Giplicado.")
            return
        self.player.clear()
        self.tree.clear()
        self.btn_scan.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.thread = ScanThread(self.current_mode(), roots, cats,
                                 max(1, self.min_kb.value() * 1024), self.sens.value())
        self.thread.progress.connect(self.on_progress)
        self.thread.finished_ok.connect(self.on_done)
        self.thread.failed.connect(self.on_failed)
        self.thread.start()

    def on_progress(self, phase, cur, total):
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(cur)
            self.progress.setFormat(f"{phase}: {cur}/{total}")
        else:
            self.progress.setRange(0, 0)
            self.status.setText(f"{phase}… {cur} archivos multimedia encontrados")

    def _finish(self):
        self.btn_scan.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)

    def on_failed(self, msg):
        self._finish()
        self.progress.setFormat("")
        self.status.setText(msg)

    def on_done(self, groups, errors):
        self._finish()
        self.groups = groups
        self.progress.setFormat("Listo")
        wasted = sum(g.wasted for g in groups)
        files = sum(len(g.files) for g in groups)
        txt = (f"{len(groups)} grupos ({files} archivos). "
               f"Espacio recuperable conservando una copia por grupo: {human_size(wasted)}.")
        if errors:
            txt += f"  ⚠ {len(errors)} archivos no se pudieron leer."
        if not groups:
            txt = "No se encontraron duplicados. 🎉" + (f"  ⚠ {len(errors)} archivos no se pudieron leer."
                                                        if errors else "")
        self.status.setText(txt)
        self.populate()

    def populate(self):
        titles = {"exacto": "copias idénticas", "foto_parecida": "fotos parecidas",
                  "audio_igual": "versiones de la misma canción"}
        self.tree.blockSignals(True)
        self.tree.clear()
        for n, g in enumerate(self.groups, 1):
            top = QTreeWidgetItem([f"Grupo {n} — {len(g.files)} {titles.get(g.kind, '')}",
                                   "", "", human_size(sum(f.size for f in g.files)), ""])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setFirstColumnSpanned(False)
            for fi in g.files:
                it = QTreeWidgetItem([fi.path.name, fi.note, str(fi.path.parent), human_size(fi.size),
                                      datetime.fromtimestamp(fi.mtime).strftime("%Y-%m-%d %H:%M")])
                it.setData(0, ROLE_INFO, fi)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Unchecked)
                it.setToolTip(0, str(fi.path))
                top.addChild(it)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        self.tree.blockSignals(False)
        self.update_marked_label()

    # ---------- marcado ----------
    def file_items(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield top, top.child(j)

    def set_all_checks(self, on: bool):
        self.tree.blockSignals(True)
        for _, it in self.file_items():
            it.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
        self.tree.blockSignals(False)
        self.update_marked_label()

    def _keeper_index(self, top: QTreeWidgetItem) -> int:
        infos: list[FileInfo] = [top.child(j).data(0, ROLE_INFO) for j in range(top.childCount())]
        rule = self.keep.currentData()
        keys = {
            "calidad": lambda f: (-f.quality, -f.size, f.mtime),
            "antiguo": lambda f: (f.mtime, len(str(f.path))),
            "reciente": lambda f: (-f.mtime, len(str(f.path))),
            "ruta": lambda f: (len(str(f.path)), f.mtime),
        }
        return min(range(len(infos)), key=lambda j: keys[rule](infos[j]))

    def auto_mark(self):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            keep = self._keeper_index(top)
            for j in range(top.childCount()):
                top.child(j).setCheckState(0, Qt.Unchecked if j == keep else Qt.Checked)
        self.tree.blockSignals(False)
        self.update_marked_label()

    def checked_items(self):
        return [(top, it) for top, it in self.file_items() if it.checkState(0) == Qt.Checked]

    def checked_paths(self) -> list[Path]:
        return [it.data(0, ROLE_INFO).path for _, it in self.checked_items()]

    def update_marked_label(self):
        items = self.checked_items()
        size = sum(it.data(0, ROLE_INFO).size for _, it in items)
        self.lbl_marked.setText(f"Marcados: {len(items)} ({human_size(size)})" if items else "")

    def _groups_fully_marked(self) -> int:
        count = 0
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.childCount() and all(top.child(j).checkState(0) == Qt.Checked
                                        for j in range(top.childCount())):
                count += 1
        return count

    def _confirm_safe(self, verb: str) -> bool:
        items = self.checked_items()
        if not items:
            QMessageBox.information(self, "Giplicado", "No hay archivos marcados.")
            return False
        full = self._groups_fully_marked()
        msg = f"¿{verb} {len(items)} archivo(s)?"
        if self.current_mode() != "exacto":
            msg += ("\n\nEn este modo los archivos son PARECIDOS, no idénticos. "
                    "Revísalos en el reproductor antes de continuar.")
        if full:
            msg += (f"\n\n⚠ ATENCIÓN: en {full} grupo(s) marcaste TODAS las copias; "
                    "no quedaría ninguna en su lugar original.")
        return QMessageBox.question(self, "Confirmar", msg) == QMessageBox.Yes

    def _remove_items(self, done: list[QTreeWidgetItem]):
        self.tree.blockSignals(True)
        for it in done:
            top = it.parent()
            top.removeChild(it)
            if top.childCount() < 2:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(top))
        self.tree.blockSignals(False)
        self.update_marked_label()
        self.show_preview(self.tree.currentItem())

    def trash_checked(self):
        if not self._confirm_safe("Enviar a la Papelera"):
            return
        self.player.release()          # Windows: soltar el archivo antes de borrarlo
        done, errs = [], []
        for _, it in self.checked_items():
            p = it.data(0, ROLE_INFO).path
            try:
                send2trash(str(p))
                done.append(it)
            except Exception as e:  # noqa: BLE001
                errs.append(f"{p.name}: {e}")
        self._remove_items(done)
        self._report(len(done), errs, "enviados a la Papelera")

    def move_checked(self):
        if not self.checked_items():
            QMessageBox.information(self, "Giplicado", "No hay archivos marcados.")
            return
        dest = QFileDialog.getExistingDirectory(self, "Mover a carpeta")
        if not dest or not self._confirm_safe(f"Mover a {dest}"):
            return
        self.player.release()
        done, errs = [], []
        for _, it in self.checked_items():
            p = it.data(0, ROLE_INFO).path
            target = Path(dest) / p.name
            k = 1
            while target.exists():
                target = Path(dest) / f"{p.stem} ({k}){p.suffix}"
                k += 1
            try:
                shutil.move(str(p), str(target))
                done.append(it)
            except OSError as e:
                errs.append(f"{p.name}: {e}")
        self._remove_items(done)
        self._report(len(done), errs, "movidos")

    def _report(self, n, errs, verb):
        msg = f"{n} archivo(s) {verb}."
        if errs:
            msg += "\n\nErrores:\n" + "\n".join(errs[:15])
        QMessageBox.information(self, "Resultado", msg)

    # ---------- vista previa ----------
    def show_preview(self, item: QTreeWidgetItem | None, _prev=None):
        fi: FileInfo | None = item.data(0, ROLE_INFO) if item else None
        if fi:
            self.player.load(fi.path, fi.note)
        elif item is not None and item.childCount():
            self.player.load(item.child(0).data(0, ROLE_INFO).path, item.child(0).data(0, ROLE_INFO).note)
        else:
            self.player.clear()

    def compare(self):
        sel = [it for it in self.tree.selectedItems() if it.data(0, ROLE_INFO)]
        if len(sel) != 2:
            cur = self.tree.currentItem()
            top = cur if cur is not None and cur.parent() is None else (cur.parent() if cur else None)
            if top is None or top.childCount() < 2:
                QMessageBox.information(self, "Comparar",
                                        "Selecciona dos archivos (Ctrl+clic) o un grupo para comparar.")
                return
            first = cur if cur is not None and cur.parent() is top else top.child(0)
            other = next(top.child(j) for j in range(top.childCount()) if top.child(j) is not first)
            sel = [first, other]
        self.player.release()
        CompareDialog(self, sel[0], sel[1], ROLE_INFO).exec()
        self.update_marked_label()

    def open_item(self, item, _col=0):
        fi = item.data(0, ROLE_INFO)
        if fi:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(fi.path)))

    def reveal_current(self):
        it = self.tree.currentItem()
        fi = it.data(0, ROLE_INFO) if it else None
        if fi:
            subprocess.Popen(["explorer", "/select,", str(fi.path)])
