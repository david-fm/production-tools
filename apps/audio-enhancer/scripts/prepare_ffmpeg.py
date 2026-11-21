"""Prepara ffmpeg y ffprobe LGPL como sidecars de Tauri en src-tauri/binaries/<nombre>-<triple>[.exe].

- Windows: descarga una build LGPL de BtbN/FFmpeg-Builds fijada por tag y verificada con sha256.
- macOS:   compila ffmpeg desde el tarball oficial (sha256 fijado) con una configuración mínima SIN GPL.

Después comprueba que la build resultante NO incluya --enable-gpl ni --enable-nonfree.
Uso (desde apps/audio-enhancer):  python scripts/prepare_ffmpeg.py
"""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
BINARIES = APP / "src-tauri" / "binaries"

WIN_URL = (
    "https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/autobuild-2026-11-20-12-40/"
    "ffmpeg-n8.1.3-39-g660b5aa7db-win64-lgpl-8.1.zip"
)
WIN_SHA256 = "a16d63673d8b28ec0b4fb7311677fd8f6fa9f221f40bf00b48c01ce8e9122be8"
SRC_URL = "https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz"
SRC_SHA256 = "464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c"

# Solo lo necesario: decodificar cualquier cosa, escribir PCM/FLAC/AAC y empaquetar en wav/flac/mov/mp4/mkv.
CONFIGURE = [
    "--disable-gpl", "--disable-nonfree", "--disable-autodetect", "--disable-doc", "--disable-debug",
    "--disable-ffplay", "--disable-network", "--disable-shared", "--enable-static",
    "--disable-encoders", "--enable-encoder=pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,flac,aac",
    "--disable-muxers", "--enable-muxer=wav,flac,mov,mp4,matroska,null,md5,rawvideo,pcm_f32le,ipod",
    "--disable-devices", "--disable-bsfs", "--enable-bsf=aac_adtstoasc,extract_extradata,null",
]  # fmt: skip


def triple() -> str:
    out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
    m = re.search(r"^host: (.+)$", out, re.MULTILINE)
    if not m:
        raise SystemExit("rustc -vV no devolvió el target triple")
    return m.group(1).strip()


def download(url: str, sha256: str, dest: Path) -> None:
    print(f"Descargando {url}")
    with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:  # noqa: S310 - https fijo
        shutil.copyfileobj(r, f)
    got = hashlib.sha256(dest.read_bytes()).hexdigest()
    if got != sha256:
        raise SystemExit(f"sha256 no coincide para {url}: esperado {sha256}, recibido {got}")


def check_lgpl(exe: Path) -> None:
    out = subprocess.run([str(exe), "-version"], capture_output=True, text=True, check=True).stdout
    config = next((ln for ln in out.splitlines() if ln.startswith("configuration:")), "")
    bad = [flag for flag in ("--enable-gpl", "--enable-nonfree") if flag in config]
    if bad:
        raise SystemExit(f"{exe} NO es LGPL: contiene {bad}")
    print(f"OK LGPL: {exe.name} ({out.splitlines()[0]})")


def main() -> None:
    BINARIES.mkdir(parents=True, exist_ok=True)
    t = triple()
    exe = ".exe" if sys.platform == "win32" else ""
    built: dict[str, Path] = {}
    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        if sys.platform == "win32":
            zpath = tmp / "ffmpeg.zip"
            download(WIN_URL, WIN_SHA256, zpath)
            with zipfile.ZipFile(zpath) as z:
                for name in ("ffmpeg.exe", "ffprobe.exe"):
                    member = next(n for n in z.namelist() if n.endswith(f"/bin/{name}"))
                    target = tmp / name
                    target.write_bytes(z.read(member))
                    built[name.removesuffix(".exe")] = target
        else:
            tpath = tmp / "ffmpeg.tar.xz"
            download(SRC_URL, SRC_SHA256, tpath)
            with tarfile.open(tpath) as tar:
                tar.extractall(tmp, filter="data")  # noqa: S202 - origen verificado por sha256
            srcdir = next(p for p in tmp.iterdir() if p.is_dir() and p.name.startswith("ffmpeg-"))
            subprocess.run(["./configure", *CONFIGURE], cwd=srcdir, check=True)
            subprocess.run(["make", f"-j{multiprocessing.cpu_count()}", "ffmpeg", "ffprobe"], cwd=srcdir, check=True)
            built = {"ffmpeg": srcdir / "ffmpeg", "ffprobe": srcdir / "ffprobe"}
            for p in built.values():
                subprocess.run(["strip", str(p)], check=False)
        for name, path in built.items():
            check_lgpl(path)
            dest = BINARIES / f"{name}-{t}{exe}"
            shutil.copy2(path, dest)
            os.chmod(dest, 0o755)
            print(f"Instalado {dest}")


if __name__ == "__main__":
    main()
