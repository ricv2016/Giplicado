import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QTabWidget

from . import __version__
from .config import GITHUB_REPO
from .core.cache import shared_cache
from .core.scanner import human_size
from .ui.duplicates_tab import DuplicatesTab
from .ui.rename_tab import RenameTab
from .ui.theme import THEMES, apply_theme, current_theme, follow_system
from .ui.update_dialog import UpdateManager


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Giplicado {__version__} — Duplicados y renombrado")
        self.resize(1150, 760)
        tabs = QTabWidget()
        self.dup = DuplicatesTab()
        self.ren = RenameTab()
        tabs.addTab(self.dup, "🔁 Buscar duplicados")
        tabs.addTab(self.ren, "✏ Renombrar")
        self.dup.send_to_rename.connect(lambda paths: (self.ren.add_paths(paths),
                                                       tabs.setCurrentWidget(self.ren)))
        self.setCentralWidget(tabs)

        # --- Menú Ver: tema ---
        view = self.menuBar().addMenu("Ver")
        theme_menu = view.addMenu("Tema")
        group = QActionGroup(self)
        for key, label in THEMES:
            act = QAction(label, self, checkable=True)
            act.setChecked(current_theme() == key)
            act.triggered.connect(lambda _=False, k=key: apply_theme(QApplication.instance(), k))
            group.addAction(act)
            theme_menu.addAction(act)

        # --- Menú Herramientas: caché ---
        tools = self.menuBar().addMenu("Herramientas")
        act_cache = QAction("Borrar caché de análisis…", self)
        act_cache.triggered.connect(self.clear_cache)
        tools.addAction(act_cache)

        # --- Menú Ayuda / actualizaciones ---
        self.updates = UpdateManager(self)
        menu = self.menuBar().addMenu("Ayuda")
        act_check = QAction("Buscar actualizaciones…", self)
        act_check.triggered.connect(lambda: self.updates.check(silent=False))
        act_auto = QAction("Buscar actualizaciones al iniciar", self, checkable=True)
        act_auto.setChecked(self.updates.auto_check)
        act_auto.toggled.connect(lambda on: setattr(self.updates, "auto_check", on))
        act_web = QAction("Página del proyecto en GitHub", self)
        act_web.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(f"https://github.com/{GITHUB_REPO}")))
        act_about = QAction("Acerca de Giplicado", self)
        act_about.triggered.connect(lambda: QMessageBox.about(
            self, "Acerca de Giplicado",
            f"<b>Giplicado {__version__}</b><br>Duplicados de fotos, audio y video, y renombrado por lote."
            f"<br><br><a href='https://github.com/{GITHUB_REPO}'>github.com/{GITHUB_REPO}</a>"))
        for a in (act_check, act_auto, None, act_web, act_about):
            menu.addSeparator() if a is None else menu.addAction(a)
        self.updates.check_on_startup()

    def clear_cache(self):
        cache = shared_cache()
        if cache is None:
            QMessageBox.information(self, "Caché", "La caché no está disponible.")
            return
        n, size = cache.stats()
        msg = (f"La caché guarda las huellas de {n} archivo(s) ({human_size(size)}) para que "
               "las búsquedas repetidas sean casi instantáneas.\n\n"
               "¿Borrarla? Tus archivos no se tocan; solo se volverán a analizar la próxima vez.")
        if QMessageBox.question(self, "Borrar caché", msg) == QMessageBox.Yes:
            cache.clear()
            QMessageBox.information(self, "Caché", "Caché borrada.")


def main():
    if sys.platform == "win32":  # ícono propio en la barra de tareas
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Giplicado.App")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    app.setWindowIcon(QIcon(str(base / "assets" / "giplicado.png")))
    apply_theme(app)
    follow_system(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
