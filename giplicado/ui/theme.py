"""Tema claro / oscuro / según Windows."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES = [("sistema", "Según Windows"), ("claro", "Claro"), ("oscuro", "Oscuro")]


def dark_palette() -> QPalette:
    p = QPalette()
    c = {
        QPalette.Window: "#202124", QPalette.WindowText: "#e8eaed",
        QPalette.Base: "#17181a", QPalette.AlternateBase: "#26282b",
        QPalette.ToolTipBase: "#2d2f33", QPalette.ToolTipText: "#e8eaed",
        QPalette.Text: "#e8eaed", QPalette.Button: "#2b2d31", QPalette.ButtonText: "#e8eaed",
        QPalette.BrightText: "#ff6b6b", QPalette.Link: "#6ab0f3", QPalette.LinkVisited: "#b39ddb",
        QPalette.Highlight: "#2f6fbd", QPalette.HighlightedText: "#ffffff",
        QPalette.PlaceholderText: "#8a8f98", QPalette.Light: "#3a3d42", QPalette.Midlight: "#33363a",
        QPalette.Mid: "#2a2c30", QPalette.Dark: "#141517", QPalette.Shadow: "#000000",
    }
    for role, color in c.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor("#6b6f76"))
    p.setColor(QPalette.Disabled, QPalette.Highlight, QColor("#3a3d42"))
    return p


def current_theme() -> str:
    return QSettings("Giplicado", "Giplicado").value("ui/theme", "sistema")


def system_is_dark(app: QApplication) -> bool:
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return False


def apply_theme(app: QApplication, theme: str | None = None) -> None:
    theme = theme or current_theme()
    QSettings("Giplicado", "Giplicado").setValue("ui/theme", theme)
    dark = theme == "oscuro" or (theme == "sistema" and system_is_dark(app))
    app.setPalette(dark_palette() if dark else app.style().standardPalette())
    app.setProperty("giplicado_dark", dark)


def follow_system(app: QApplication) -> None:
    """Si el tema es 'Según Windows', reacciona cuando el usuario cambia el modo de Windows."""
    try:
        app.styleHints().colorSchemeChanged.connect(
            lambda *_: apply_theme(app) if current_theme() == "sistema" else None)
    except AttributeError:
        pass
