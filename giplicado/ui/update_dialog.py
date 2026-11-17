from __future__ import annotations

from PySide6.QtCore import QSettings, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QWidget

from .. import __version__, updater


class CheckThread(QThread):
    result = Signal(object)    # UpdateInfo | None
    error = Signal(str)

    def run(self):
        try:
            self.result.emit(updater.check_for_update())
        except Exception as e:  # noqa: BLE001 - sin internet, límite de la API, etc.
            self.error.emit(str(e))


class DownloadThread(QThread):
    progress = Signal(int, int)
    done = Signal(object)      # Path | None
    error = Signal(str)

    def __init__(self, info):
        super().__init__()
        self.info = info
        self.cancelled = False

    def run(self):
        try:
            self.done.emit(updater.download_installer(
                self.info, lambda a, b: self.progress.emit(a, b), lambda: self.cancelled))
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class UpdateManager:
    """Comprueba actualizaciones al iniciar y bajo demanda (menú Ayuda)."""

    def __init__(self, parent: QWidget):
        self.parent = parent
        self.settings = QSettings("Giplicado", "Giplicado")
        self._threads: list[QThread] = []

    @property
    def auto_check(self) -> bool:
        return self.settings.value("update/auto_check", True, type=bool)

    @auto_check.setter
    def auto_check(self, on: bool):
        self.settings.setValue("update/auto_check", on)

    def check_on_startup(self, delay_ms: int = 4000):
        if self.auto_check and updater.GITHUB_REPO and not updater.GITHUB_REPO.startswith("USUARIO/"):
            QTimer.singleShot(delay_ms, lambda: self.check(silent=True))

    def check(self, silent: bool = False):
        t = CheckThread()
        t.result.connect(lambda info: self._on_result(info, silent))
        t.error.connect(lambda msg: None if silent else QMessageBox.warning(
            self.parent, "Actualizaciones", f"No se pudo comprobar si hay actualizaciones.\n\n{msg}"))
        self._keep(t)

    def _keep(self, t: QThread):
        self._threads.append(t)
        t.finished.connect(lambda: self._threads.remove(t) if t in self._threads else None)
        t.start()

    def _on_result(self, info, silent: bool):
        if info is None:
            if not silent:
                QMessageBox.information(self.parent, "Actualizaciones",
                                        f"Ya tienes la última versión ({__version__}).")
            return
        if silent and self.settings.value("update/skip", "") == info.version:
            return
        box = QMessageBox(self.parent)
        box.setWindowTitle("Actualización disponible")
        box.setText(f"<b>Hay una nueva versión de Giplicado: {info.version}</b><br>"
                    f"Tienes la versión {__version__}.")
        if info.notes:
            box.setInformativeText("Pulsa «Mostrar detalles» para ver las novedades.")
            box.setDetailedText(info.notes)
        b_now = box.addButton("Actualizar ahora", QMessageBox.AcceptRole)
        box.addButton("Más tarde", QMessageBox.RejectRole)
        b_skip = box.addButton("Omitir esta versión", QMessageBox.DestructiveRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_skip:
            self.settings.setValue("update/skip", info.version)
        elif clicked is b_now:
            if updater.can_self_install():
                self._download(info)
            else:   # ejecutando desde el código fuente: abrir la página del release
                QDesktopServices.openUrl(QUrl(info.page_url))

    def _download(self, info):
        dlg = QProgressDialog(f"Descargando Giplicado {info.version}…", "Cancelar", 0, 100, self.parent)
        dlg.setWindowTitle("Actualización")
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        t = DownloadThread(info)

        def on_progress(done, total):
            if total:
                dlg.setValue(int(done * 100 / total))
                dlg.setLabelText(f"Descargando Giplicado {info.version}…  "
                                 f"{done / 1048576:.1f} / {total / 1048576:.1f} MB")

        def on_done(path):
            dlg.close()
            if path is None:
                return
            QMessageBox.information(self.parent, "Actualización",
                                    "La descarga terminó. Giplicado se cerrará, se instalará la "
                                    "nueva versión y se volverá a abrir automáticamente.")
            updater.launch_installer(path)
            QApplication.quit()

        def on_error(msg):
            dlg.close()
            QMessageBox.warning(self.parent, "Actualización", f"No se pudo descargar la actualización.\n\n{msg}")

        t.progress.connect(on_progress)
        t.done.connect(on_done)
        t.error.connect(on_error)
        dlg.canceled.connect(lambda: setattr(t, "cancelled", True))
        self._keep(t)
