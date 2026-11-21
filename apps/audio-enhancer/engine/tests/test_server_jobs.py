"""Comandos de trabajo del motor a través del protocolo stdio (lo que usa la interfaz)."""

from __future__ import annotations

import os

import pytest
import soundfile as sf
from conftest import EngineClient
from helpers import SR, have_ffmpeg, noise, speechlike, write_wav

pytestmark = pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg no disponible")


@pytest.fixture
def engine(tmp_path):
    os.environ["AUDIO_ENHANCER_WORK_DIR"] = str(tmp_path / "work")
    client = EngineClient()
    yield client
    client.close()
    os.environ.pop("AUDIO_ENHANCER_WORK_DIR", None)


def wait_result(engine, req_id, timeout=60):
    events = []
    while True:
        msg = engine.recv(timeout=timeout)
        if msg.get("id") == req_id and "ok" in msg:
            return msg, events
        if msg.get("event") == "progress" and msg.get("id") == req_id:
            events.append(msg)


def test_probe_waveform_extract_and_preview(engine, tmp_path):
    src = write_wav(tmp_path / "in.wav", speechlike(12, 2))
    engine.send({"id": 1, "cmd": "probe", "path": str(src)})
    probe, _ = wait_result(engine, 1)
    assert probe["ok"] and probe["result"]["audio_streams"][0]["channels"] == 2

    engine.send({"id": 2, "cmd": "waveform", "path": str(src), "points": 100})
    wave, _ = wait_result(engine, 2)
    assert len(wave["result"]["min"]) == 100 and wave["result"]["duration_s"] == pytest.approx(12, abs=0.01)

    engine.send({"id": 3, "cmd": "extract", "input": str(src), "output": str(tmp_path / "orig.wav"), "region": [2, 6]})
    orig, _ = wait_result(engine, 3)
    assert orig["ok"] and sf.info(tmp_path / "orig.wav").frames == 4 * SR

    engine.send({"id": 4, "cmd": "enhance", "input": str(src), "output": str(tmp_path / "prev.wav"),
                 "region": [2, 6], "settings": {"denoise": False, "target_lufs": -20}})  # fmt: skip
    prev, events = wait_result(engine, 4)
    assert prev["ok"], prev
    assert sf.info(tmp_path / "prev.wav").frames == 4 * SR
    assert events and events[-1]["value"] == 1.0
    assert prev["result"]["output_lufs"] is not None


def test_errors_are_readable_not_crashes(engine, tmp_path):
    engine.send({"id": 1, "cmd": "enhance", "input": str(tmp_path / "no_existe.wav"), "output": str(tmp_path / "o.wav")})
    res, _ = wait_result(engine, 1)
    assert res["ok"] is False and "No se pudo leer" in res["error"]

    src = write_wav(tmp_path / "in.wav", noise(3, 1))
    engine.send({"id": 2, "cmd": "enhance", "input": str(src), "output": str(tmp_path / "o.wav"), "settings": {"x": 1}})
    res, _ = wait_result(engine, 2)
    assert res["ok"] is False and "desconocidos" in res["error"]
    assert engine.rpc({"id": 3, "cmd": "ping"})["ok"] is True  # el motor sigue vivo


def test_cancel_stops_enhance(engine, tmp_path):
    from audio_enhancer_engine.pipeline import B

    src = write_wav(tmp_path / "long.wav", noise(B / SR * 3, 1, 0.05))
    engine.send({"id": 1, "cmd": "enhance", "input": str(src), "output": str(tmp_path / "o.wav"),
                 "settings": {"denoise": False}})  # fmt: skip
    engine.send({"id": 2, "cmd": "cancel", "target": 1})
    res, _ = wait_result(engine, 1)
    assert res["ok"] is False and res["error"] == "cancelado"


def test_job_key_cancels_and_events_echo_job(engine, tmp_path):
    from audio_enhancer_engine.pipeline import B

    src = write_wav(tmp_path / "long.wav", noise(B / SR * 3, 1, 0.05))
    engine.send({"id": 1, "cmd": "enhance", "job": "mi-trabajo", "input": str(src),
                 "output": str(tmp_path / "o.wav"), "settings": {"denoise": False}})  # fmt: skip
    first = engine.recv(timeout=60)
    while first.get("event") != "progress":
        first = engine.recv(timeout=60)
    assert first["job"] == "mi-trabajo"
    engine.send({"id": 2, "cmd": "enhance", "job": "mi-trabajo", "input": str(src), "output": str(tmp_path / "p.wav")})
    engine.send({"id": 3, "cmd": "cancel", "target": "mi-trabajo"})
    seen_dup, seen_cancel = False, False
    while not (seen_dup and seen_cancel):
        msg = engine.recv(timeout=60)
        if msg.get("id") == 2 and msg.get("ok") is False:
            seen_dup = "en curso" in msg["error"]
        if msg.get("id") == 1 and msg.get("ok") is False:
            seen_cancel = msg["error"] == "cancelado"
