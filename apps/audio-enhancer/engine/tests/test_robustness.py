"""Robustez: modelos, caché, concurrencia, bordes de tamaño, remux y entradas mal formadas."""

from __future__ import annotations

import hashlib
import io
import os
import tarfile
import threading
import time

import numpy as np
import pytest
import soundfile as sf
from conftest import EngineClient
from helpers import SR, have_ffmpeg, noise, run_ffmpeg, write_wav

from audio_enhancer_engine import models
from audio_enhancer_engine.denoise import IdentityDenoiser
from audio_enhancer_engine.pipeline import (
    B,
    X,
    compute_block,
    purge_old_cache,
    render,
    render_remux,
)
from audio_enhancer_engine.pipeline import prepare_source as prepare
from audio_enhancer_engine.settings import Settings

ffmpeg_needed = pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg no disponible")
RAW = Settings(highpass_hz=None, denoise=True, normalize=False)


def read(path):
    return sf.read(path, dtype="float32", always_2d=True)[0]


# ---------- modelos ----------


def _fake_tar(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _serve(monkeypatch, blob: bytes, sha: str | None = None):
    monkeypatch.setattr(models, "_download", lambda: blob)
    monkeypatch.setattr(models, "DFN3_SHA256", sha or hashlib.sha256(blob).hexdigest())


def test_model_sha_mismatch_is_rejected_and_nothing_is_installed(monkeypatch, tmp_path):
    _serve(monkeypatch, b"contenido manipulado", sha="0" * 64)
    with pytest.raises(RuntimeError, match="sha256"):
        models.ensure_deepfilternet3(tmp_path)
    assert not models.is_installed(models.model_folder(tmp_path))


def test_model_tar_with_malicious_paths_cannot_escape(monkeypatch, tmp_path):
    names = {"../../evil.txt": b"x", "tmp/export/enc.onnx": b"e", "tmp/export/erb_dec.onnx": b"r",
             "tmp/export/df_dec.onnx": b"d", "tmp/export/config.ini": b"c"}  # fmt: skip
    _serve(monkeypatch, _fake_tar(names))
    folder = models.ensure_deepfilternet3(tmp_path / "m")
    assert models.is_installed(folder)
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path.parent / "evil.txt").exists()
    assert sorted(p.name for p in folder.iterdir()) == [".ok", "config.ini", "df_dec.onnx", "enc.onnx", "erb_dec.onnx"]


def test_incomplete_package_is_not_marked_installed(monkeypatch, tmp_path):
    _serve(monkeypatch, _fake_tar({"enc.onnx": b"e"}))
    with pytest.raises(RuntimeError, match="no contiene"):
        models.ensure_deepfilternet3(tmp_path)
    assert not models.is_installed(models.model_folder(tmp_path))
    assert not list(tmp_path.glob(".deepfilternet3.*"))  # sin restos temporales


def test_truncated_install_without_marker_is_repaired(monkeypatch, tmp_path):
    folder = models.model_folder(tmp_path)
    folder.mkdir(parents=True)
    for f in ("enc.onnx", "erb_dec.onnx", "df_dec.onnx", "config.ini"):
        (folder / f).write_bytes(b"truncado")  # instalación interrumpida: sin marcador
    assert not models.is_installed(folder)
    members = {f: b"ok" for f in ("enc.onnx", "erb_dec.onnx", "df_dec.onnx", "config.ini")}
    _serve(monkeypatch, _fake_tar(members))
    assert (models.ensure_deepfilternet3(tmp_path) / "enc.onnx").read_bytes() == b"ok"


# ---------- tamaños límite ----------


@ffmpeg_needed
@pytest.mark.parametrize("n", [3, 100, SR // 2, B - 1, B, B + 10, B + X, 2 * B, 2 * B + 1])
def test_edge_lengths_roundtrip_exactly(tmp_path, n):
    audio = noise(n / SR, 2, 0.1, seed=n % 97)
    src = write_wav(tmp_path / "in.wav", audio)
    render(src, tmp_path / "out.wav", RAW, IdentityDenoiser(), work_root=tmp_path / "w")
    out = read(tmp_path / "out.wav")
    assert out.shape == audio.shape
    assert np.abs(out - audio).max() < 2e-7


@ffmpeg_needed
def test_region_at_the_very_end(tmp_path):
    audio = noise(B / SR + 3, 1, 0.1)
    src = write_wav(tmp_path / "in.wav", audio)
    render(src, tmp_path / "p.wav", RAW, IdentityDenoiser(), region=(B / SR + 1, B / SR + 3), work_root=tmp_path / "w")
    assert np.abs(read(tmp_path / "p.wav") - audio[int((B / SR + 1) * SR) :]).max() < 2e-7


# ---------- caché corrupta ----------


@ffmpeg_needed
def test_corrupt_or_truncated_block_is_recomputed(tmp_path):
    audio = noise(5, 1, 0.1)
    src = write_wav(tmp_path / "in.wav", audio)
    work = tmp_path / "w"
    render(src, tmp_path / "a.wav", RAW, IdentityDenoiser(), work_root=work)
    block = next(work.rglob("000000.npy"))
    block.write_bytes(block.read_bytes()[:50])  # truncado
    again = render(src, tmp_path / "b.wav", RAW, IdentityDenoiser(), work_root=work)
    assert again.resumed_blocks == 1  # existía (aunque corrupto) y se recalculó sin error
    assert np.abs(read(tmp_path / "b.wav") - audio).max() < 2e-7


@ffmpeg_needed
def test_missing_model_with_denoise_is_a_clear_error(tmp_path):
    src = write_wav(tmp_path / "in.wav", noise(2, 1))
    source = prepare(src, RAW, work_root=tmp_path / "w")
    with pytest.raises(ValueError, match="ningún modelo"):
        compute_block(source, 0, RAW, None, tmp_path / "blocks")


# ---------- concurrencia ----------


@ffmpeg_needed
def test_two_jobs_on_the_same_source_do_not_corrupt_each_other(tmp_path):
    audio = noise(B / SR * 1.5, 1, 0.1, seed=4)
    src = write_wav(tmp_path / "in.wav", audio)
    work = tmp_path / "w"
    errors: list[BaseException] = []

    def job(name: str, settings: Settings):
        try:
            render(src, tmp_path / name, settings, IdentityDenoiser(), work_root=work)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=job, args=(f"o{i}.wav", RAW)) for i in range(3)]
    threads.append(threading.Thread(target=job, args=("hp.wav", Settings(highpass_hz=100.0, normalize=False))))
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    assert not errors, errors
    for i in range(3):
        assert np.abs(read(tmp_path / f"o{i}.wav") - audio).max() < 2e-7
    assert not list(work.rglob("assembled-*"))  # temporales limpios


@ffmpeg_needed
def test_temp_files_are_removed_after_cancel(tmp_path):
    from audio_enhancer_engine.pipeline import Cancelled

    src = write_wav(tmp_path / "in.wav", noise(B / SR * 2.2, 1, 0.1))
    state = {"n": 0}

    def cancel_late() -> bool:
        state["n"] += 1
        return state["n"] > 8  # tras procesar bloques y empezar a ensamblar

    with pytest.raises(Cancelled):
        render(src, tmp_path / "o.wav", RAW, IdentityDenoiser(), work_root=tmp_path / "w", cancelled=cancel_late)
    assert not list((tmp_path / "w").rglob("assembled-*"))
    assert not (tmp_path / "o.wav").exists()


# ---------- remux ----------


@ffmpeg_needed
def test_remux_validations_happen_before_processing(tmp_path):
    video = tmp_path / "v.mov"
    run_ffmpeg("-f", "lavfi", "-i", "testsrc=d=1:s=64x64:r=10", "-f", "lavfi", "-i", "sine=d=1", "-c:v", "mpeg4", "-c:a", "pcm_s16le", str(video))
    work = tmp_path / "w"
    with pytest.raises(ValueError, match="extensiones"):
        render_remux(video, tmp_path / "out.avi", Settings(denoise=False), None, work_root=work)
    with pytest.raises(ValueError, match="mismo"):
        render_remux(video, video, Settings(denoise=False), None, work_root=work)
    assert not work.exists() or not list(work.rglob("source.f32"))  # no se procesó nada


@ffmpeg_needed
def test_remux_via_server_leaves_no_intermediate_next_to_video(tmp_path):
    video = tmp_path / "v.mov"
    run_ffmpeg("-f", "lavfi", "-i", "testsrc=d=2:s=64x64:r=10", "-f", "lavfi", "-i", "sine=d=2", "-c:v", "mpeg4", "-c:a", "pcm_s16le", str(video))
    os.environ["AUDIO_ENHANCER_WORK_DIR"] = str(tmp_path / "work")
    client = EngineClient()
    try:
        out = tmp_path / "salida.mkv"
        client.send({"id": 1, "cmd": "enhance", "input": str(video), "output": str(out), "remux": True,
                     "settings": {"denoise": False}})  # fmt: skip
        while True:
            msg = client.recv(timeout=60)
            if msg.get("id") == 1 and "ok" in msg:
                break
        assert msg["ok"], msg
        assert out.exists()
        assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["salida.mkv", "v.mov"]
    finally:
        client.close()
        os.environ.pop("AUDIO_ENHANCER_WORK_DIR", None)


# ---------- servidor: entradas mal formadas ----------


@pytest.mark.parametrize(
    "bad",
    [
        {"cmd": "enhance", "settings": []},
        {"cmd": "enhance", "input": "a", "output": "b", "audio_index": None},
        {"cmd": "enhance", "input": "a", "output": "b", "settings": {"denoise_strength": "a"}},
        {"cmd": "enhance", "input": "a", "output": "b", "job": []},
        {"cmd": "enhance", "input": "a", "output": "b", "region": "x"},
        {"cmd": "probe", "path": 5},
        {"cmd": "waveform", "path": "a", "points": "mucho"},
    ],
)
def test_malformed_requests_never_kill_the_reader(bad):
    client = EngineClient()
    try:
        reply = client.rpc({"id": 1, **bad})
        if "ok" not in reply:  # un evento de progreso previo
            reply = client.recv()
        assert reply["ok"] is False
        assert client.rpc({"id": 2, "cmd": "ping"})["result"] == "pong"
    finally:
        client.close()


# ---------- purga de caché ----------


def test_purge_old_cache_removes_only_stale_dirs(tmp_path):
    old, new, keep = (tmp_path / n for n in ("old", "new", "keep"))
    for d in (old, new, keep):
        d.mkdir()
    past = time.time() - 30 * 86400
    os.utime(old, (past, past))
    os.utime(keep, (past, past))
    assert purge_old_cache(tmp_path, keep=keep, max_age_days=7) == 1
    assert not old.exists() and new.exists() and keep.exists()


def test_clear_cache_command_reports_freed_bytes(tmp_path):
    work = tmp_path / "work"
    (work / "k").mkdir(parents=True)
    (work / "k" / "blob").write_bytes(b"x" * 1234)
    os.environ["AUDIO_ENHANCER_WORK_DIR"] = str(work)
    client = EngineClient()
    try:
        assert client.rpc({"id": 1, "cmd": "cache_info"})["result"]["bytes"] == 1234
        assert client.rpc({"id": 2, "cmd": "clear_cache"})["result"]["freed_bytes"] == 1234
        assert not work.exists()
    finally:
        client.close()
        os.environ.pop("AUDIO_ENHANCER_WORK_DIR", None)


