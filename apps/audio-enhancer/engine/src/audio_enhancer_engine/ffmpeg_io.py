"""Acceso a ffmpeg/ffprobe como EJECUTABLES externos (nunca enlazados): mantiene el repo MIT-compatible.

Búsqueda: variable AUDIO_ENHANCER_FFMPEG_DIR, luego junto al ejecutable de la app (sidecar), luego PATH.
La build que se DISTRIBUYE debe ser LGPL (ver scripts/check_ffmpeg_license.py).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .settings import SAMPLE_RATE

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # evita ventanas de consola en Windows


class FfmpegError(RuntimeError):
    """Error legible de ffmpeg/ffprobe (archivo corrupto, ejecutable ausente...)."""


def find_tool(name: str) -> str:
    exe = f"{name}.exe" if sys.platform == "win32" else name
    candidates = []
    if os.environ.get("AUDIO_ENHANCER_FFMPEG_DIR"):
        candidates.append(Path(os.environ["AUDIO_ENHANCER_FFMPEG_DIR"]) / exe)
    candidates.append(Path(sys.executable).parent / exe)
    for path in candidates:
        if path.is_file():
            return str(path)
    found = shutil.which(name)
    if found:
        return found
    raise FfmpegError(f"No se encontró '{name}'. Instala ffmpeg o define AUDIO_ENHANCER_FFMPEG_DIR.")


@dataclass(frozen=True)
class AudioStreamInfo:
    index: int  # índice entre los streams de audio (0 = primera pista de audio)
    channels: int
    sample_rate: int
    codec: str


@dataclass(frozen=True)
class MediaInfo:
    duration_s: float | None
    has_video: bool
    audio_streams: list[AudioStreamInfo]


def probe(path: str | os.PathLike[str]) -> MediaInfo:
    cmd = [find_tool("ffprobe"), "-v", "error", "-protocol_whitelist", "file", "-show_format", "-show_streams", "-of", "json", "--", os.fspath(path)]
    res = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW, check=False)
    if res.returncode != 0:
        raise FfmpegError(f"No se pudo leer el archivo: {res.stderr.decode(errors='replace').strip()}")
    data = json.loads(res.stdout.decode("utf-8", errors="replace"))
    audio = [
        AudioStreamInfo(i, int(s.get("channels", 0)), int(s.get("sample_rate", 0) or 0), s.get("codec_name", "?"))
        for i, s in enumerate(x for x in data.get("streams", []) if x.get("codec_type") == "audio")
    ]
    has_video = any(
        s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic", 0) == 0
        for s in data.get("streams", [])
    )
    duration = data.get("format", {}).get("duration")
    return MediaInfo(float(duration) if duration not in (None, "N/A") else None, has_video, audio)


def decode_to_raw(
    src: str | os.PathLike[str], dst: str | os.PathLike[str], *, audio_index: int, channels: int
) -> int:
    """Decodifica una pista a float32 intercalado a 48 kHz. Devuelve el número de muestras por canal.

    Escribe a `dst` directamente desde ffmpeg (sin pasar el audio por Python): memoria constante.
    La duración se mide del resultado real, no de la declarada en el contenedor.
    """
    cmd = [
        find_tool("ffmpeg"), "-v", "error", "-nostdin", "-y", "-protocol_whitelist", "file", "-i", os.fspath(src),
        "-map", f"0:a:{audio_index}", "-vn", "-ac", str(channels), "-ar", str(SAMPLE_RATE),
        "-f", "f32le", "-acodec", "pcm_f32le", os.fspath(dst),
    ]  # fmt: skip
    res = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW, check=False)
    if res.returncode != 0:
        raise FfmpegError(f"ffmpeg no pudo decodificar el audio: {res.stderr.decode(errors='replace').strip()}")
    size = os.path.getsize(dst)
    return size // (4 * channels)


REMUX_EXTENSIONS = (".mov", ".mkv", ".mp4")


def remux(video: str | os.PathLike[str], audio_wav: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
    """Sustituye el audio de `video` por `audio_wav` sin recomprimir el video (`-c:v copy`)."""
    ext = Path(dst).suffix.lower()
    codec = {".mov": ["-c:a", "pcm_s24le"], ".mkv": ["-c:a", "flac"], ".mp4": ["-c:a", "aac", "-b:a", "256k"]}.get(ext)
    if codec is None:
        raise FfmpegError(f"Contenedor no soportado para remux: {ext} (usa .mov, .mkv o .mp4)")
    cmd = [
        find_tool("ffmpeg"), "-v", "error", "-nostdin", "-y", "-protocol_whitelist", "file", "-i", os.fspath(video), "-protocol_whitelist", "file", "-i", os.fspath(audio_wav),
        "-map", "0:v", "-map", "1:a:0", "-c:v", "copy", *codec, "-shortest", os.fspath(dst),
    ]  # fmt: skip
    res = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW, check=False)
    if res.returncode != 0:
        raise FfmpegError(f"ffmpeg no pudo unir audio y video: {res.stderr.decode(errors='replace').strip()}")
