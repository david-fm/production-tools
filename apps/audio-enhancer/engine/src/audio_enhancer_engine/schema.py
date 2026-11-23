"""Esquema de parámetros de cada caja de la cadena (filtros y modelos), con valores por defecto.

Solo se declaran parámetros que el motor soporta de verdad. La interfaz genera los controles desde
este esquema, así que añadir un parámetro a un modelo no exige tocar la interfaz.
"""

from __future__ import annotations

from typing import Any

FILTER_KINDS = ("highpass", "notch")


def _num(pid: str, label: str, help_: str, default: float, lo: float, hi: float, step: float, unit: str = "") -> dict[str, Any]:
    return {"id": pid, "type": "number", "label": label, "help": help_, "default": default, "min": lo, "max": hi, "step": step, "unit": unit}


def _choice(pid: str, label: str, help_: str, default: Any, options: list[tuple[Any, str]]) -> dict[str, Any]:
    return {"id": pid, "type": "choice", "label": label, "help": help_, "default": default,
            "options": [{"value": v, "label": lab} for v, lab in options]}  # fmt: skip


STRENGTH = _num(
    "strength", "Intensidad",
    "100 % usa solo el audio procesado por esta caja. Valores más bajos mezclan parte del audio que entra: más natural, con algo del original.",
    1.0, 0.0, 1.0, 0.05, "%",
)  # fmt: skip

HIGHPASS = [
    _num("hz", "Frecuencia de corte",
         "Quita retumbos y viento por debajo de esta frecuencia. 80–100 Hz es seguro para voz; sube a 120 Hz si hay mucho viento.",
         80.0, 10.0, 500.0, 5.0, "Hz"),
]  # fmt: skip
NOTCH = [
    _choice("hz", "Frecuencia de la red eléctrica",
            "Usa 50 Hz en Europa y gran parte de Latinoamérica, 60 Hz en América del Norte, México y Centroamérica.",
            50.0, [(50.0, "50 Hz"), (60.0, "60 Hz")]),
    _num("harmonics", "Armónicos", "Cuántos armónicos del zumbido se filtran (f, 2f, 3f…).", 3, 1, 6, 1),
]  # fmt: skip
KEEP = _choice(
    "keep", "Qué conservar",
    "«La voz» deja la voz y quita el fondo. «El resto» hace lo contrario: quita la voz y deja el fondo.",
    "primary", [("primary", "La voz"), ("residual", "El resto (quitar la voz)")],
)  # fmt: skip


def params_schema(kind: str, model_id: str | None = None) -> list[dict[str, Any]]:
    if kind == "highpass":
        return [dict(p) for p in HIGHPASS]
    if kind == "notch":
        return [dict(p) for p in NOTCH]
    if kind == "model":
        from . import models

        entry = models.CATALOG.get(model_id or "")
        out = [dict(STRENGTH)]
        if entry is not None and entry.params.get("adapter") == "mdx":
            out.append(dict(KEEP))
        return out
    raise ValueError(f"tipo de etapa desconocido: {kind!r}")


def resolve_params(kind: str, model_id: str | None, params: dict[str, Any]) -> dict[str, Any]:
    """Valida `params` contra el esquema y devuelve todos los valores (rellena los por defecto)."""
    if not isinstance(params, dict):
        raise TypeError("los parámetros de una etapa deben ser un objeto")
    schema = {p["id"]: p for p in params_schema(kind, model_id)}
    unknown = set(params) - set(schema)
    if unknown:
        raise ValueError(f"parámetros desconocidos para {kind}: {sorted(unknown)}")
    out: dict[str, Any] = {}
    for pid, spec in schema.items():
        value = params.get(pid, spec["default"])
        if spec["type"] == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{pid} debe ser un número")
            if not spec["min"] <= value <= spec["max"]:
                raise ValueError(f"{pid} debe estar entre {spec['min']} y {spec['max']}")
            value = int(value) if spec["step"] == 1 and float(value).is_integer() else float(value)
        else:
            if value not in [o["value"] for o in spec["options"]]:
                raise ValueError(f"{pid} debe ser uno de {[o['value'] for o in spec['options']]}")
        out[pid] = value
    return out
