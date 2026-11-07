"""Looping background music and the packaged-asset self check.

The song is pure background music: while the option is enabled it loops
regardless of the clicker's ON/OFF state.  Missing QtMultimedia or a
missing/corrupt file is a silent no-op, never a crash.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, QUrl

from ..core.paths import asset_path
from ..core.settings import DEFAULT_MUSIC_VOLUME


class MusicPlayer(QObject):
    """QMediaPlayer wrapper: one looping source, 0.0-1.0 volume, quiet failures."""

    def __init__(self, source: str | Path | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._player = None
        self._output = None
        self._volume = DEFAULT_MUSIC_VOLUME
        if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
            return  # headless tests: never open a real audio stream
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except Exception:  # noqa: BLE001 - no multimedia build is not fatal
            return
        path = Path(source) if source else asset_path("luolei.mp3")
        if not path.exists():
            return
        try:
            self._player = QMediaPlayer(self)
            self._output = QAudioOutput(self)
            self._player.setAudioOutput(self._output)
            self._player.setSource(QUrl.fromLocalFile(str(path)))
            self._player.setLoops(-1)  # loop forever
        except Exception:  # noqa: BLE001
            self._player = None
            self._output = None
        self._output.setVolume(self._volume) if self._output else None

    @property
    def available(self) -> bool:
        return self._player is not None

    def set_volume(self, value: float) -> None:
        self._volume = min(max(float(value), 0.0), 1.0)
        if self._output is not None:
            self._output.setVolume(self._volume)

    def volume(self) -> float:
        return self._volume

    def set_playing(self, playing: bool) -> None:
        if self._player is None:
            return
        if playing:
            if not self.is_playing():
                self._player.play()
        else:
            self._player.stop()

    def is_playing(self) -> bool:
        if self._player is None:
            return False
        try:
            from PySide6.QtMultimedia import QMediaPlayer

            return self._player.playbackState() == QMediaPlayer.PlayingState
        except Exception:  # noqa: BLE001
            return False

    def position_ms(self) -> int:
        return int(self._player.position()) if self._player is not None else 0

    def error_string(self) -> str:
        if self._player is None:
            return "unavailable"
        return self._player.errorString()


def selftest(out_path: str | Path) -> dict:
    """Verify gif + audio + icon inside the frozen build (used by build/verify_exe_env.ps1)."""
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QMovie
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    result: dict = {"assets": {}}

    gif = asset_path("cat.gif")
    movie = QMovie(str(gif))
    movie.start()
    movie.jumpToFrame(0)
    result["assets"]["gif"] = {
        "path": str(gif),
        "exists": gif.exists(),
    }
    icon = asset_path("icon.png")
    result["assets"]["icon"] = {"exists": icon.exists(), "bytes": icon.stat().st_size if icon.exists() else 0}

    song = asset_path("luolei.mp3")
    player = MusicPlayer(song)
    player.set_volume(DEFAULT_MUSIC_VOLUME)
    player.set_playing(True)
    result["assets"]["music"] = {
        "path": str(song),
        "exists": song.exists(),
        "available": player.available,
        "volume": player.volume(),
    }

    def finish() -> None:
        frame = movie.currentPixmap()
        result["assets"]["gif"].update(
            {
                "valid": movie.isValid(),
                "frame_count": movie.frameCount(),
                "size": [frame.width(), frame.height()],
            }
        )
        result["assets"]["music"].update(
            {
                "playing": player.is_playing(),
                "position_ms": player.position_ms(),
                "error": player.error_string(),
            }
        )
        player.set_playing(False)
        movie.stop()
        Path(out_path).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        app.quit()

    QTimer.singleShot(2500, finish)
    app.exec()
    return result
