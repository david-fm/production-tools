"""Tests del protocolo, ejecutando el motor como subproceso real (como lo hace la app)."""

from __future__ import annotations

import pytest
from conftest import EngineClient


@pytest.fixture
def engine():
    client = EngineClient()
    yield client
    client.close()


def test_health_and_ping(engine):
    assert engine.rpc({"id": 1, "cmd": "health"})["result"]["version"]
    assert engine.rpc({"id": 2, "cmd": "ping"})["result"] == "pong"


def test_invalid_input_does_not_kill_engine(engine):
    engine.send_raw(b"esto no es json\n")
    assert engine.recv()["ok"] is False
    engine.send_raw(b"[1, 2]\n")  # JSON válido pero no es un objeto
    assert engine.recv()["ok"] is False
    engine.send_raw(b"\xff\xfe\xfd basura no utf-8\n")
    assert engine.recv()["ok"] is False
    assert engine.rpc({"id": 3, "cmd": "ping"})["ok"] is True


def test_unknown_command_is_reported(engine):
    reply = engine.rpc({"id": 4, "cmd": "no_existe"})
    assert reply["ok"] is False and "desconocido" in reply["error"]


@pytest.mark.parametrize("params", [{"steps": "x"}, {"steps": 0}, {"delay": -1}, {"steps": True}])
def test_invalid_params_get_an_error_reply(engine, params):
    reply = engine.rpc({"id": 5, "cmd": "progress_demo", **params})
    assert reply["ok"] is False and "inválidos" in reply["error"]
    assert engine.rpc({"id": 6, "cmd": "ping"})["ok"] is True


def test_providers_lists_cpu(engine):
    pytest.importorskip("onnxruntime")
    reply = engine.rpc({"id": 7, "cmd": "providers"}, timeout=60)
    assert reply["ok"] is True
    assert "CPUExecutionProvider" in reply["result"]


def test_ping_answers_while_task_runs(engine):
    engine.send({"id": 8, "cmd": "progress_demo", "steps": 1000, "delay": 0.05})
    engine.recv()  # primer evento de progreso
    engine.send({"id": 9, "cmd": "ping"})
    while True:  # el pong llega entre eventos de progreso
        msg = engine.recv()
        if msg.get("id") == 9:
            assert msg["result"] == "pong"
            break


def test_progress_events_then_result(engine):
    engine.send({"id": 10, "cmd": "progress_demo", "steps": 3, "delay": 0})
    msgs = [engine.recv() for _ in range(4)]
    assert [m.get("value") for m in msgs[:3]] == pytest.approx([1 / 3, 2 / 3, 1.0])
    assert msgs[3]["result"] == "listo"


def test_cancel_immediately_after_start_is_not_lost(engine):
    """Regresión: cancel enviado justo después de arrancar la tarea no debe perderse."""
    for i in range(20):
        task_id = 100 + i
        engine.send({"id": task_id, "cmd": "progress_demo", "steps": 100_000, "delay": 0.01})
        engine.send({"id": 1000 + i, "cmd": "cancel", "target": task_id})
        seen_cancelled = False
        while not seen_cancelled:
            msg = engine.recv(timeout=5)
            if msg.get("id") == task_id and "ok" in msg:
                assert msg["error"] == "cancelado"
                seen_cancelled = True


def test_cancel_targets_only_the_given_task(engine):
    engine.send({"id": 20, "cmd": "progress_demo", "steps": 100_000, "delay": 0.01})
    engine.send({"id": 21, "cmd": "progress_demo", "steps": 3, "delay": 0})
    engine.send({"id": 22, "cmd": "cancel", "target": 20})
    finished, cancelled = False, False
    while not (finished and cancelled):
        msg = engine.recv(timeout=5)
        if msg.get("id") == 21 and msg.get("result") == "listo":
            finished = True
        if msg.get("id") == 20 and msg.get("error") == "cancelado":
            cancelled = True


def test_duplicate_task_id_is_rejected(engine):
    engine.send({"id": 30, "cmd": "progress_demo", "steps": 100_000, "delay": 0.01})
    engine.send({"id": 30, "cmd": "progress_demo", "steps": 2, "delay": 0})
    while True:
        msg = engine.recv()
        if msg.get("ok") is False and "ya hay una tarea" in msg.get("error", ""):
            break


def test_exits_when_stdin_closes():
    """Garantía anti-huérfanos: si la app muere, stdin se cierra y el motor termina solo."""
    client = EngineClient()
    assert client.proc.stdin
    client.proc.stdin.close()
    assert client.proc.wait(timeout=5) == 0


def test_shutdown_command_exits():
    client = EngineClient()
    assert client.rpc({"id": 40, "cmd": "shutdown"})["ok"] is True
    assert client.proc.wait(timeout=5) == 0


def test_native_stdout_noise_does_not_corrupt_protocol():
    """Regresión (CI Windows): ONNX Runtime escribe avisos en el fd 1 nativo; no deben llegar al protocolo."""
    code = (
        "import os, threading\n"
        "from audio_enhancer_engine import server\n"
        "orig = server.handle\n"
        "def noisy(req, out, tasks):\n"
        "    os.write(1, b'*** EP Error ***\\n')\n"
        "    return orig(req, out, tasks)\n"
        "server.handle = noisy\n"
        "server.main()\n"
    )
    import sys

    client = EngineClient([sys.executable, "-c", code])
    try:
        assert client.rpc({"id": 1, "cmd": "ping"})["result"] == "pong"
    finally:
        client.close()
