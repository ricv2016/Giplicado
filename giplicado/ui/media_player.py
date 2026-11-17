"""Visor/reproductor integrado para fotos, audio y video (Qt Multimedia)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QSize
from PySide6.QtGui import QImage, QImageReader, QPixmap, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QStackedWidget,
    QStyle, QVBoxLayout, QWidget,
)

from ..core.scanner import category_of, human_size


def load_qimage(path: Path) -> QImage:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    img = reader.read()
    if not img.isNull():
        return img
    try:  # respaldo con Pillow (HEIC con pillow-heif, algunos TIFF, etc.)
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGBA")
            data = im.tobytes("raw", "RGBA")
            return QImage(data, im.width, im.height, QImage.Format_RGBA8888).copy()
    except Exception:  # noqa: BLE001
        return QImage()


class ImageView(QLabel):
    """QLabel que reescala la imagen al cambiar de tamaño."""

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(QSize(200, 150))
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._pix = QPixmap()

    def set_image(self, img: QImage):
        self._pix = QPixmap.fromImage(img)
        self._rescale()

    def clear_image(self):
        self._pix = QPixmap()
        self.clear()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def _rescale(self):
        if not self._pix.isNull():
            self.setPixmap(self._pix.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


def fmt_ms(ms: int) -> str:
    s = max(0, ms // 1000)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class MediaPreview(QWidget):
    PAGE_EMPTY, PAGE_IMAGE, PAGE_VIDEO, PAGE_AUDIO = range(4)

    def __init__(self):
        super().__init__()
        self.path: Path | None = None

        self.stack = QStackedWidget()
        self.empty = QLabel("Selecciona un archivo para previsualizarlo")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color:#888;")
        self.image = ImageView()
        self.video = QVideoWidget()
        self.video.setMinimumSize(200, 150)
        self.audio_panel = QLabel()
        self.audio_panel.setAlignment(Qt.AlignCenter)
        self.audio_panel.setWordWrap(True)
        for w in (self.empty, self.image, self.video, self.audio_panel):
            self.stack.addWidget(w)
        self.stack.setStyleSheet("QStackedWidget{background:#1e1e1e; border-radius:4px;}"
                                 "QLabel{color:#ddd;}")

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)

        # Controles
        st = self.style()
        self.btn_play = QPushButton()
        self.btn_play.setIcon(st.standardIcon(QStyle.SP_MediaPlay))
        self.btn_play.clicked.connect(self.toggle)
        self.btn_stop = QPushButton()
        self.btn_stop.setIcon(st.standardIcon(QStyle.SP_MediaStop))
        self.btn_stop.clicked.connect(self._stop)
        self.pos = QSlider(Qt.Horizontal)
        self.pos.sliderMoved.connect(lambda v: self.player.setPosition(v))
        self.pos.sliderReleased.connect(lambda: self.player.setPosition(self.pos.value()))
        self.time = QLabel("0:00 / 0:00")
        self.btn_mute = QPushButton()
        self.btn_mute.setCheckable(True)
        self.btn_mute.setIcon(st.standardIcon(QStyle.SP_MediaVolume))
        self.btn_mute.toggled.connect(self._mute)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(70)
        self.vol.setMaximumWidth(90)
        self.vol.valueChanged.connect(lambda v: self.audio_out.setVolume(v / 100))
        self.autoplay = QCheckBox("Auto-reproducir")

        self.controls = QWidget()
        cl = QHBoxLayout(self.controls)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.btn_play)
        cl.addWidget(self.btn_stop)
        cl.addWidget(self.pos, 1)
        cl.addWidget(self.time)
        cl.addWidget(self.btn_mute)
        cl.addWidget(self.vol)
        self.controls.setEnabled(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack, 1)
        lay.addWidget(self.controls)
        row = QHBoxLayout()
        row.addWidget(self.info, 1)
        row.addWidget(self.autoplay, 0, Qt.AlignTop)
        lay.addLayout(row)

        # Motor de reproducción
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.audio_out.setVolume(0.7)
        self.player.setAudioOutput(self.audio_out)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(self._on_dur)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_error)

        QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Space), self, self.toggle,
                  context=Qt.WidgetWithChildrenShortcut)

    # ---------- API pública ----------
    def load(self, path: Path | None, extra: str = ""):
        self.release()
        self.path = path
        if path is None or not path.exists():
            self.stack.setCurrentIndex(self.PAGE_EMPTY)
            self.info.setText("" if path is None else "El archivo ya no existe.")
            return
        cat = category_of(path)
        try:
            size = human_size(path.stat().st_size)
        except OSError:
            size = "?"
        base = f"<b>{path.name}</b> · {size}"
        if extra:
            base += f" · {extra}"
        self.info.setText(f"{base}<br><small style='color:#888'>{path.parent}</small>")

        if cat == "foto":
            img = load_qimage(path)
            if img.isNull():
                self.audio_panel.setText("<span style='font-size:48px'>🖼</span><br>"
                                         "Vista previa no disponible para este formato")
                self.stack.setCurrentIndex(self.PAGE_AUDIO)
            else:
                self.image.set_image(img)
                self.stack.setCurrentIndex(self.PAGE_IMAGE)
                if f"{img.width()}×{img.height()}" not in extra:
                    self.info.setText(self.info.text().replace(
                        f" · {size}", f" · {size} · {img.width()}×{img.height()}", 1))
            return

        if cat in ("audio", "video"):
            if cat == "video":
                self.stack.setCurrentIndex(self.PAGE_VIDEO)
            else:
                self.audio_panel.setText(f"<span style='font-size:64px'>🎵</span><br><b>{path.stem}</b>")
                self.stack.setCurrentIndex(self.PAGE_AUDIO)
            self.controls.setEnabled(True)
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            if self.autoplay.isChecked():
                self.player.play()
            elif cat == "video":
                # muestra el primer cuadro: reproducir y pausar de inmediato
                self.player.play()
                self.player.pause()
            return

        self.audio_panel.setText("<span style='font-size:48px'>📄</span><br>Sin vista previa")
        self.stack.setCurrentIndex(self.PAGE_AUDIO)

    def release(self):
        """Detiene y suelta el archivo (necesario en Windows antes de borrar/renombrar)."""
        self.player.stop()
        self.player.setSource(QUrl())
        self.controls.setEnabled(False)
        self.pos.setValue(0)
        self.time.setText("0:00 / 0:00")

    def clear(self):
        self.release()
        self.image.clear_image()
        self.path = None
        self.info.setText("")
        self.stack.setCurrentIndex(self.PAGE_EMPTY)

    def toggle(self):
        if not self.controls.isEnabled():
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    # ---------- internos ----------
    def _stop(self):
        self.player.stop()

    def _mute(self, on: bool):
        self.audio_out.setMuted(on)
        self.btn_mute.setIcon(self.style().standardIcon(
            QStyle.SP_MediaVolumeMuted if on else QStyle.SP_MediaVolume))

    def _on_pos(self, ms: int):
        if not self.pos.isSliderDown():
            self.pos.setValue(ms)
        self.time.setText(f"{fmt_ms(ms)} / {fmt_ms(self.player.duration())}")

    def _on_dur(self, ms: int):
        self.pos.setRange(0, ms)
        self.time.setText(f"{fmt_ms(self.player.position())} / {fmt_ms(ms)}")

    def _on_state(self, state):
        icon = QStyle.SP_MediaPause if state == QMediaPlayer.PlayingState else QStyle.SP_MediaPlay
        self.btn_play.setIcon(self.style().standardIcon(icon))

    def _on_error(self, _err, msg: str):
        if msg:
            self.info.setText(self.info.text() + f"<br><span style='color:#e74c3c'>⚠ {msg}</span>")
