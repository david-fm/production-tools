"""Construye la cadena de etapas (separar -> reducir ruido) a partir de los ajustes y los modelos instalados."""

from __future__ import annotations

import threading
from typing import Any

from . import models
from .denoise import Chain, DeepFilterNet3
from .mdx import MdxNet, MdxParams
from .models import ModelError

_cache: dict[tuple[str, str], Any] = {}
_lock = threading.Lock()


def needed_models(settings) -> list[str]:
    """Ids de los modelos de las etapas activas, sin repetir y en orden."""
    ids: list[str] = []
    for st in settings.active_stages():
        if st.kind == "model" and st.model not in ids:
            ids.append(st.model)
    return ids


def _mdx_params_for_hf(path: str) -> MdxParams:
    import onnxruntime as ort

    shape = ort.InferenceSession(path, providers=["CPUExecutionProvider"]).get_inputs()[0].shape
    if len(shape) == 4 and shape[1] == 4 and all(isinstance(d, int) for d in shape[2:]):
        dim_f, dim_t = shape[2], shape[3]
        n_fft = 6144 if dim_f == 3072 else 2 * dim_f
        return MdxParams(n_fft=n_fft, dim_f=dim_f, dim_t=dim_t, compensate=1.0)
    raise ModelError(
        "Modelo descargado pero no compatible: la app solo sabe ejecutar modelos MDX-Net (entrada [N,4,F,T])."
    )


def load_model(model_id: str, models_dir=None):
    """Carga (con caché) un modelo instalado. La caché usa la huella: cambiar pesos recarga."""
    fingerprint = models.model_fingerprint(model_id, models_dir)
    key = (model_id, fingerprint)
    with _lock:
        if key in _cache:
            return _cache[key]
        folder = models.model_folder(model_id, models_dir)
        if model_id == "deepfilternet3":
            loaded: Any = DeepFilterNet3(folder)
        elif model_id in models.CATALOG:
            p = models.CATALOG[model_id].params
            if p.get("adapter") != "mdx":
                raise ModelError(f"El modelo {model_id} no tiene adaptador.")
            loaded = MdxNet(str(folder / models.CATALOG[model_id].files[0].name),
                            MdxParams(p["n_fft"], p["dim_f"], p["dim_t"], p["compensate"], p["keep"]))  # fmt: skip
        else:
            info = models._read_info(folder)
            if not info:
                raise ModelError(f"El modelo {model_id} no tiene metadatos.")
            path = str(folder / info["file"])
            models.check_onnx_safe(folder / info["file"])  # también al cargar, no solo al instalar
            loaded = MdxNet(path, _mdx_params_for_hf(path))
        _cache[key] = loaded
        return loaded


class _KeepStage:
    """Un modelo MDX con su parámetro `keep` (conservar la voz o el resto) fijado para esta etapa."""

    def __init__(self, model: MdxNet, keep: str) -> None:
        self._model, self._keep = model, keep
        self.providers = model.providers
        self.context_s = model.context_s

    def enhance(self, audio):
        return self._model.enhance(audio, keep=self._keep)


def build_chain(settings, models_dir=None) -> Chain | None:
    """Ejecutor de la cadena activa (filtros y modelos, en orden), o None si no hay etapas activas.

    Los modelos deben estar reservados con `models.use_models`. Falla de forma legible si el contexto que
    necesitan las etapas juntas no cabe en el que el pipeline da a cada bloque.
    """
    from .dsp import SosFilter, highpass_sos, notch_sos
    from .pipeline import CONTEXT_S

    active = settings.active_stages()
    if not active:
        return None
    stages, fingerprints, providers, context = [], {}, [], 0.0
    for st in active:
        p = st.resolved()
        if st.kind == "highpass":
            stages.append((SosFilter(highpass_sos(p["hz"])), 1.0))
            continue
        if st.kind == "notch":
            sos = notch_sos(p["hz"], p["harmonics"])
            if sos is not None:
                stages.append((SosFilter(sos), 1.0))
            continue
        model = load_model(st.model, models_dir)
        if "keep" in p and isinstance(model, MdxNet):
            model = _KeepStage(model, p["keep"])
        stages.append((model, p["strength"]))
        fingerprints[st.model] = models.model_fingerprint(st.model, models_dir)
        providers.extend(x for x in model.providers if x not in providers)
        context += getattr(model, "context_s", 0.0)
    if context > CONTEXT_S:
        raise ModelError(
            f"La cadena necesita {context:.1f} s de contexto por bloque y el máximo es {CONTEXT_S:.1f} s: usa menos modelos."
        )
    return Chain(stages, fingerprints, providers)
