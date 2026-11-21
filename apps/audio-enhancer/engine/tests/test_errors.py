"""Errores del entorno que el usuario debe poder entender (ffmpeg ausente, disco lleno)."""

from __future__ import annotations

import shutil
from collections import namedtuple

import pytest
from helpers import have_ffmpeg, noise, write_wav

from audio_enhancer_engine import ffmpeg_io
from audio_enhancer_engine.pipeline import InsufficientDisk, render
from audio_enhancer_engine.settings import Settings


def test_missing_ffmpeg_gives_actionable_message(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIO_ENHANCER_FFMPEG_DIR", str(tmp_path / "vacio"))
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr("sys.executable", str(tmp_path / "python"))
    with pytest.raises(ffmpeg_io.FfmpegError, match="No se encontró 'ffprobe'"):
        ffmpeg_io.probe(tmp_path / "x.wav")


@pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg no disponible")
def test_insufficient_disk_is_reported_before_decoding(monkeypatch, tmp_path):
    src = write_wav(tmp_path / "in.wav", noise(5, 2))
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: usage(100, 100, 1000))  # 1 KB libre
    with pytest.raises(InsufficientDisk, match="GB libres"):
        render(src, tmp_path / "o.wav", Settings(), None, work_root=tmp_path / "w")
    assert not (tmp_path / "w").exists() or not list((tmp_path / "w").rglob("source.f32"))


def test_settings_validation_rejects_out_of_range():
    for bad in ({"denoise_strength": 2}, {"notch_hz": 55}, {"target_lufs": 3}, {"channels": "x"}, {"output_format": "mp3"}):
        with pytest.raises(ValueError):
            Settings.from_dict(bad)
    with pytest.raises(ValueError, match="desconocidos"):
        Settings.from_dict({"nope": 1})


def test_processing_hash_ignores_loudness_and_format_only():
    base = Settings()
    assert base.processing_hash() == Settings(target_lufs=-23, output_format="flac24").processing_hash()
    assert base.processing_hash() != Settings(denoise_strength=0.5).processing_hash()
    assert base.processing_hash() != Settings(highpass_hz=120).processing_hash()
