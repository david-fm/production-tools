"""Cadena de etapas en orden libre: esquema, migración de ajustes planos, hash y ejecución."""

from __future__ import annotations

import os
from typing import ClassVar

import numpy as np
import pytest
import soundfile as sf
from conftest import EngineClient
from helpers import have_ffmpeg, noise, write_wav

from audio_enhancer_engine import models, schema, stages
from audio_enhancer_engine.denoise import Chain
from audio_enhancer_engine.dsp import SosFilter, highpass_sos
from audio_enhancer_engine.pipeline import compute_block, render
from audio_enhancer_engine.pipeline import prepare_source as prepare
from audio_enhancer_engine.settings import MAX_STAGES, Settings, Stage

ffmpeg_needed = pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg no disponible")


def hp(id_="hp", hz=100.0, **kw):
    return Stage(id_, "highpass", params={"hz": hz}, **kw)


def cfg(*chain, **kw):
    return Settings(chain=tuple(chain), normalize=False, **kw)


# ---------- esquema y validación ----------


def test_schema_has_defaults_for_filters_and_models():
    assert [p["id"] for p in schema.params_schema("highpass")] == ["hz"]
    assert {p["id"]: p["default"] for p in schema.params_schema("notch")} == {"hz": 50.0, "harmonics": 3}
    assert [p["id"] for p in schema.params_schema("model", "kim-vocal-2")] == ["strength", "keep"]
    assert [p["id"] for p in schema.params_schema("model", "deepfilternet3")] == ["strength"]  # solo lo soportado
    assert [p["id"] for p in schema.params_schema("model", "hf--a--b--m")] == ["strength"]
    assert schema.resolve_params("model", "kim-vocal-2", {}) == {"strength": 1.0, "keep": "primary"}


@pytest.mark.parametrize(
    "stage",
    [
        Stage("a", "volume"),  # el volumen no es una caja movible
        Stage("a", "highpass", model="x"),
        Stage("a", "model"),  # modelo sin id
        Stage("a", "highpass", params={"hz": 5}),  # fuera de rango
        Stage("a", "highpass", params={"hz": "80"}),
        Stage("a", "highpass", params={"hz": True}),
        Stage("a", "highpass", params={"otro": 1}),  # parámetro desconocido
        Stage("a", "notch", params={"hz": 55.0}),
        Stage("a", "model", "kim-vocal-2", params={"keep": "todo"}),
        Stage("a", "model", "kim-vocal-2", params={"strength": 2}),
        Stage("../x", "highpass"),
        Stage("a", "highpass", enabled="si"),  # type: ignore[arg-type]
    ],
)
def test_invalid_stages_are_rejected(stage):
    with pytest.raises((ValueError, TypeError)):
        cfg(stage).validate()


def test_chain_level_validation():
    with pytest.raises(ValueError, match="únicos"):
        cfg(hp("a"), hp("a")).validate()
    with pytest.raises(ValueError, match="máximo"):
        cfg(*[hp(f"s{i}") for i in range(MAX_STAGES + 1)]).validate()
    cfg(*[hp(f"s{i}") for i in range(MAX_STAGES)]).validate()  # el tope exacto vale; repetir cajas está permitido


def test_from_dict_accepts_chain_and_legacy_formats():
    s = Settings.from_dict({"chain": [{"id": "a", "kind": "highpass", "params": {"hz": 90}}], "normalize": False})
    assert s.chain is not None and s.active_stages()[0].resolved() == {"hz": 90.0}
    assert Settings.from_dict(s.to_dict()) == s  # ida y vuelta (la lista JSON vuelve a tupla)
    legacy = Settings.from_dict({"highpass_hz": 100.0, "denoise": False})
    assert legacy.chain is None and [st.kind for st in legacy.active_stages()] == ["highpass"]
    for bad in ({"chain": "x"}, {"chain": [5]}, {"chain": [{"id": "a", "kind": "highpass", "zzz": 1}]}):
        with pytest.raises((ValueError, TypeError)):
            Settings.from_dict(bad)


def test_legacy_flat_settings_map_to_the_v020_order():
    s = Settings(highpass_hz=100.0, notch_hz=60.0, separate_model="kim-vocal-2", separate_strength=0.5, denoise=True, denoise_strength=0.7)
    assert [(st.kind, st.model) for st in s.effective_chain()] == [
        ("highpass", None), ("notch", None), ("model", "kim-vocal-2"), ("model", "deepfilternet3")]  # fmt: skip
    assert s.effective_chain()[2].resolved()["strength"] == 0.5 and s.effective_chain()[3].resolved()["strength"] == 0.7
    assert Settings(highpass_hz=None, denoise=False).effective_chain() == ()


# ---------- hash de caché ----------


def test_hash_depends_on_order_params_and_model_fingerprint():
    a, b = hp("a", 100.0), Stage("n", "notch", params={"hz": 50.0})
    assert cfg(a, b).processing_hash() != cfg(b, a).processing_hash()  # el orden importa
    assert cfg(hp("a", 100.0)).processing_hash() != cfg(hp("a", 120.0)).processing_hash()
    m = Stage("m", "model", "kim-vocal-2")
    assert cfg(m).processing_hash({"kim-vocal-2": "x"}) != cfg(m).processing_hash({"kim-vocal-2": "y"})
    assert cfg(hp("a")).processing_hash() == cfg(hp("otro-id")).processing_hash()  # el id de la instancia no cuenta


def test_hash_is_canonical_for_disabled_and_zero_strength_stages():
    base = cfg(hp("a")).processing_hash()
    assert cfg(hp("a"), Stage("m", "model", "kim-vocal-2", enabled=False)).processing_hash() == base
    assert cfg(hp("a"), Stage("m", "model", "kim-vocal-2", params={"strength": 0})).processing_hash() == base
    assert cfg(hp("a"), hp("off", 200.0, enabled=False)).processing_hash() == base


def test_flat_settings_and_their_equivalent_chain_share_the_hash():
    flat = Settings(highpass_hz=100.0, notch_hz=50.0, denoise=False)
    explicit = Settings(chain=flat.effective_chain())
    assert flat.processing_hash() == explicit.processing_hash()


# ---------- ejecución ----------


class Clip:
    providers: ClassVar[list[str]] = []
    context_s = 0.0

    def enhance(self, x):
        return np.clip(x, -0.05, 0.05).astype(np.float32)


@ffmpeg_needed
def test_order_changes_the_audio(tmp_path):
    src = write_wav(tmp_path / "in.wav", noise(4, 1, 0.2))
    hpf = (SosFilter(highpass_sos(400.0)), 1.0)
    clip = (Clip(), 1.0)
    outs = []
    for name, order in (("a", [hpf, clip]), ("b", [clip, hpf])):
        s = cfg(hp("x"), hp("y", 200.0))  # la cadena real da igual: se ejecuta la que lleva el Chain
        source = prepare(src, s, work_root=tmp_path / "w")
        path = compute_block(source, 0, s, Chain(order, {}, []), tmp_path / f"b{name}")
        outs.append(np.load(path))
    assert np.abs(outs[0] - outs[1]).max() > 1e-3  # filtrar y recortar no conmutan


@ffmpeg_needed
def test_flat_filters_equal_the_equivalent_chain(tmp_path):
    """Migración: los ajustes planos de v0.2.0 (camino antiguo) y su cadena dan el mismo audio."""
    src = write_wav(tmp_path / "in.wav", noise(5, 2, 0.1, seed=3))
    flat = Settings(highpass_hz=100.0, notch_hz=50.0, denoise=False, normalize=False)
    explicit = Settings(chain=flat.effective_chain(), normalize=False)
    render(src, tmp_path / "flat.wav", flat, None, work_root=tmp_path / "w")
    render(src, tmp_path / "chain.wav", explicit, stages.build_chain(explicit), work_root=tmp_path / "w")
    a, _ = sf.read(tmp_path / "flat.wav", dtype="float32")
    b, _ = sf.read(tmp_path / "chain.wav", dtype="float32")
    assert a.shape == b.shape and np.abs(a - b).max() < 1e-4


@ffmpeg_needed
def test_explicit_chain_without_active_stages_passes_audio_through(tmp_path):
    audio = noise(3, 1, 0.1)
    src = write_wav(tmp_path / "in.wav", audio)
    s = cfg(hp("off", enabled=False))
    assert stages.build_chain(s) is None
    render(src, tmp_path / "o.wav", s, None, work_root=tmp_path / "w")  # NO se aplica el recorte de graves por defecto
    out, _ = sf.read(tmp_path / "o.wav", dtype="float32", always_2d=True)
    assert np.abs(out - audio).max() < 2e-7


def test_explicit_chain_with_active_stages_requires_an_executor(tmp_path):
    src = write_wav(tmp_path / "in.wav", noise(2, 1))
    s = cfg(hp("a"))
    source = prepare(src, s, work_root=tmp_path / "w")
    with pytest.raises(ValueError, match="ninguno"):
        compute_block(source, 0, s, None, tmp_path / "b")


def test_chain_context_limit_fails_with_a_readable_message(monkeypatch):
    class Fake:
        providers: ClassVar[list[str]] = []
        context_s = 1.0

    monkeypatch.setattr(stages, "load_model", lambda *_a, **_k: Fake())
    monkeypatch.setattr(models, "model_fingerprint", lambda *_a, **_k: "x")
    four = cfg(*[Stage(f"d{i}", "model", "deepfilternet3") for i in range(4)])
    with pytest.raises(models.ModelError, match="contexto"):
        stages.build_chain(four)
    assert stages.build_chain(cfg(*[Stage(f"d{i}", "model", "deepfilternet3") for i in range(3)])) is not None


def test_needed_models_lists_active_models_once_in_order():
    s = cfg(Stage("a", "model", "kim-vocal-2"), Stage("b", "model", "deepfilternet3"), Stage("c", "model", "kim-vocal-2"),
            Stage("d", "model", "x-off", enabled=False))  # fmt: skip
    assert stages.needed_models(s) == ["kim-vocal-2", "deepfilternet3"]


# ---------- protocolo ----------


@ffmpeg_needed
def test_protocol_accepts_both_formats_and_lists_the_stage_catalog(tmp_path):
    src = write_wav(tmp_path / "in.wav", noise(3, 1, 0.1))
    client = EngineClient(env={**os.environ, "AUDIO_ENHANCER_MODELS_DIR": str(tmp_path / "m"), "AUDIO_ENHANCER_WORK_DIR": str(tmp_path / "w")})
    try:
        cat = client.rpc({"id": 1, "cmd": "stage_catalog"}, timeout=60)["result"]
        assert [f["kind"] for f in cat["filters"]] == ["highpass", "notch"] and cat["filters"][0]["params"][0]["id"] == "hz"
        kim = next(m for m in cat["models"] if m["id"] == "kim-vocal-2")
        assert [p["id"] for p in kim["params"]] == ["strength", "keep"]
        for i, settings in enumerate(
            [{"chain": [{"id": "a", "kind": "highpass", "params": {"hz": 100}}], "normalize": False},
             {"highpass_hz": 100.0, "denoise": False, "normalize": False}], start=2):  # fmt: skip
            reply = client.rpc({"id": i, "cmd": "enhance", "input": str(src), "output": str(tmp_path / f"o{i}.wav"), "settings": settings}, timeout=120)
            while "ok" not in reply:
                reply = client.recv(timeout=120)
            assert reply["ok"] is True, reply
        bad = client.rpc({"id": 9, "cmd": "enhance", "input": str(src), "output": str(tmp_path / "x.wav"),
                          "settings": {"chain": [{"id": "a", "kind": "highpass", "params": {"hz": 1}}]}}, timeout=60)  # fmt: skip
        assert bad["ok"] is False and "hz" in bad["error"]
        assert client.rpc({"id": 10, "cmd": "ping"})["result"] == "pong"
    finally:
        client.close()
