"""Ajustes de un trabajo de mejora. Se serializan a JSON (presets) y se usan para el hash de checkpoints."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, fields
from typing import Any

SETTINGS_VERSION = 2
PIPELINE_VERSION = 3  # v3: cadena de etapas en orden libre (el orden y los parámetros entran en el hash); súbela al cambiar el algoritmo o el modelo: invalida los bloques en caché
SAMPLE_RATE = 48_000  # frecuencia interna fija (la que usa DeepFilterNet3)


MAX_STAGES = 12
STAGE_KINDS = ("highpass", "notch", "model")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}")


@dataclass(frozen=True)
class Stage:
    """Una caja de la cadena. `id` identifica la instancia (se pueden repetir cajas del mismo tipo)."""

    id: str
    kind: str  # "highpass" | "notch" | "model"
    model: str | None = None  # solo para kind == "model"
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        from .schema import resolve_params

        if not (isinstance(self.id, str) and _ID_RE.fullmatch(self.id)):
            raise ValueError("el id de una etapa debe ser texto sencillo")
        if self.kind not in STAGE_KINDS:
            raise ValueError(f"tipo de etapa desconocido: {self.kind!r}")
        if not isinstance(self.enabled, bool):
            raise TypeError("'enabled' debe ser booleano")
        if self.kind == "model":
            if not (isinstance(self.model, str) and _ID_RE.fullmatch(self.model)):
                raise ValueError("una etapa de modelo necesita un id de modelo válido")
        elif self.model is not None:
            raise ValueError("solo las etapas de modelo llevan 'model'")
        resolve_params(self.kind, self.model, self.params)

    def resolved(self) -> dict[str, Any]:
        from .schema import resolve_params

        return resolve_params(self.kind, self.model, self.params)

    @property
    def active(self) -> bool:
        """Una etapa desactivada, o de modelo con intensidad 0, no hace nada."""
        if not self.enabled:
            return False
        return not (self.kind == "model" and self.resolved()["strength"] <= 0)


@dataclass(frozen=True)
class Settings:
    """Todos los valores tienen un rango validado en `validate()`."""

    # Limpieza determinista
    highpass_hz: float | None = 80.0  # recorta graves inaudibles/ruido de viento; None = desactivado
    notch_hz: float | None = None  # zumbido eléctrico: 50 o 60 Hz; None = desactivado
    notch_harmonics: int = 3  # cuántos armónicos filtrar (f, 2f, 3f...)
    # Aislar voz / quitar fondo (modelo del catálogo, p. ej. "kim-vocal-2"); se aplica ANTES de la reducción de ruido
    separate_model: str | None = None
    separate_strength: float = 1.0  # 0 = solo audio original, 1 = solo voz aislada
    # Reducción de ruido por IA
    denoise: bool = True
    denoise_strength: float = 1.0  # 0 = solo audio original, 1 = solo audio limpiado
    # Volumen
    normalize: bool = True
    target_lufs: float = -16.0  # -16 online, -23 broadcast (EBU R128)
    max_true_peak_db: float = -1.0
    # Canales y salida
    channels: str = "each"  # "each": cada canal por separado; "mix": mezclar a mono
    output_format: str = "wav24"  # "wav24" | "flac24"
    version: int = SETTINGS_VERSION
    #: Cadena explícita (v0.3.0). Si es None se usan los campos planos de arriba (formato de v0.1.0/v0.2.0),
    #: que equivalen a la cadena graves -> zumbido -> separar -> reducir ruido (`effective_chain`).
    chain: tuple[Stage, ...] | None = None

    def effective_chain(self) -> tuple[Stage, ...]:
        if self.chain is not None:
            return self.chain
        stages: list[Stage] = []
        if self.highpass_hz is not None:
            stages.append(Stage("highpass", "highpass", params={"hz": float(self.highpass_hz)}))
        if self.notch_hz is not None:
            stages.append(Stage("notch", "notch", params={"hz": float(self.notch_hz), "harmonics": self.notch_harmonics}))
        if self.separate_model is not None:
            stages.append(Stage("separate", "model", self.separate_model, params={"strength": float(self.separate_strength)}))
        if self.denoise:
            stages.append(Stage("denoise", "model", "deepfilternet3", params={"strength": float(self.denoise_strength)}))
        return tuple(stages)

    def active_stages(self) -> tuple[Stage, ...]:
        return tuple(st for st in self.effective_chain() if st.active)

    def validate(self) -> None:
        def check(cond: bool, msg: str) -> None:
            if not cond:
                raise ValueError(msg)

        def is_num(v: object) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool)

        check(self.highpass_hz is None or is_num(self.highpass_hz), "highpass_hz debe ser un número o None")
        check(self.notch_hz is None or is_num(self.notch_hz), "notch_hz debe ser un número o None")
        check(isinstance(self.notch_harmonics, int) and not isinstance(self.notch_harmonics, bool), "notch_harmonics debe ser entero")
        check(is_num(self.denoise_strength), "denoise_strength debe ser un número")
        check(is_num(self.separate_strength), "separate_strength debe ser un número")
        check(
            self.separate_model is None
            or (isinstance(self.separate_model, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}", self.separate_model)),
            "separate_model debe ser un identificador de modelo o None",
        )
        check(is_num(self.target_lufs) and is_num(self.max_true_peak_db), "target_lufs y max_true_peak_db deben ser números")
        check(isinstance(self.denoise, bool) and isinstance(self.normalize, bool), "denoise y normalize deben ser booleanos")

        check(self.highpass_hz is None or 10 <= self.highpass_hz <= 500, "highpass_hz debe estar entre 10 y 500")
        check(self.notch_hz is None or self.notch_hz in (50.0, 60.0), "notch_hz debe ser 50, 60 o None")
        check(1 <= self.notch_harmonics <= 6, "notch_harmonics debe estar entre 1 y 6")
        check(0.0 <= self.denoise_strength <= 1.0, "denoise_strength debe estar entre 0 y 1")
        check(0.0 <= self.separate_strength <= 1.0, "separate_strength debe estar entre 0 y 1")
        check(-40 <= self.target_lufs <= -5, "target_lufs debe estar entre -40 y -5")
        check(-6 <= self.max_true_peak_db <= 0, "max_true_peak_db debe estar entre -6 y 0")
        if self.chain is not None:
            check(isinstance(self.chain, tuple) and all(isinstance(st, Stage) for st in self.chain), "chain debe ser una lista de etapas")
            check(len(self.chain) <= MAX_STAGES, f"la cadena admite como máximo {MAX_STAGES} etapas")
            check(len({st.id for st in self.chain}) == len(self.chain), "los ids de las etapas deben ser únicos")
            for st in self.chain:
                st.validate()
        check(self.channels in ("each", "mix"), "channels debe ser 'each' o 'mix'")
        check(self.output_format in ("wav24", "flac24"), "output_format debe ser 'wav24' o 'flac24'")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data.get("chain") is not None:
            data["chain"] = list(data["chain"])
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        known = {f.name for f in fields(cls)}
        unknown = (set(data) - known) if isinstance(data, dict) else set()
        if unknown:
            raise ValueError(f"ajustes desconocidos: {sorted(unknown)}")
        if not isinstance(data, dict):
            raise TypeError("los ajustes deben ser un objeto")
        data = dict(data)
        raw_chain = data.pop("chain", None)
        chain = None
        if raw_chain is not None:
            if not isinstance(raw_chain, list):
                raise TypeError("chain debe ser una lista")
            stages = []
            for item in raw_chain:
                if not isinstance(item, dict):
                    raise TypeError("cada etapa debe ser un objeto")
                extra = set(item) - {"id", "kind", "model", "enabled", "params"}
                if extra:
                    raise ValueError(f"campos desconocidos en la etapa: {sorted(extra)}")
                stages.append(Stage(**item))
            chain = tuple(stages)
        settings = cls(**data, chain=chain)
        settings.validate()
        return settings

    def processing_hash(self, model_fingerprints: dict[str, str] | None = None) -> str:
        """Hash de lo que afecta al audio de cada bloque (no al volumen final ni al formato de salida).

        Incluye el ORDEN de las etapas activas, sus parámetros y la huella (sha256) de cada modelo usado:
        cambiar pesos bajo el mismo id nunca mezcla caché. Una etapa desactivada no entra (forma canónica),
        y los ajustes planos antiguos dan el mismo hash que su cadena equivalente.
        """
        relevant: dict[str, Any] = {
            "chain": [{"kind": st.kind, "model": st.model, "params": st.resolved()} for st in self.active_stages()],
            "channels": self.channels,
            "models": dict(sorted((model_fingerprints or {}).items())),
            "pipeline_version": PIPELINE_VERSION,
        }
        return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()[:16]
