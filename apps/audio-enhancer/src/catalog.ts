import type { ModelInfo } from "./components/ModelsPanel";
import type { ParamValue, Stage } from "./settings";

export interface ParamSpec {
  id: string;
  type: "number" | "choice";
  label: string;
  help: string;
  default: ParamValue;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  options?: { value: ParamValue; label: string }[];
}

export interface FilterInfo {
  kind: "highpass" | "notch";
  name: string;
  description: string;
  params: ParamSpec[];
}

export interface StageCatalog {
  filters: FilterInfo[];
  models: ModelInfo[];
}

/** Esquema mínimo de respaldo (antes de que el motor responda); el motor es la fuente de verdad. */
const STRENGTH: ParamSpec = {
  id: "strength", type: "number", label: "Intensidad", default: 1, min: 0, max: 1, step: 0.05, unit: "%",
  help: "100 % usa solo el audio procesado por esta caja. Valores más bajos mezclan parte del audio que entra.",
};

export const FALLBACK_CATALOG: StageCatalog = {
  filters: [
    {
      kind: "highpass", name: "Recorte de graves", description: "Quita retumbos y viento por debajo de una frecuencia.",
      params: [{ id: "hz", type: "number", label: "Frecuencia de corte", default: 80, min: 10, max: 500, step: 5, unit: "Hz",
        help: "Quita retumbos y viento por debajo de esta frecuencia. 80–100 Hz es seguro para voz." }],
    },
    {
      kind: "notch", name: "Zumbido eléctrico", description: "Elimina el zumbido de la red eléctrica y sus armónicos.",
      params: [
        { id: "hz", type: "choice", label: "Frecuencia de la red eléctrica", default: 50,
          options: [{ value: 50, label: "50 Hz" }, { value: 60, label: "60 Hz" }],
          help: "50 Hz en Europa y gran parte de Latinoamérica, 60 Hz en América del Norte, México y Centroamérica." },
        { id: "harmonics", type: "number", label: "Armónicos", default: 3, min: 1, max: 6, step: 1, help: "Cuántos armónicos del zumbido se filtran." },
      ],
    },
  ],
  models: [],
};

export function modelOf(stage: Stage, catalog: StageCatalog): ModelInfo | undefined {
  return stage.kind === "model" ? catalog.models.find((m) => m.id === stage.model) : undefined;
}

export function stageName(stage: Stage, catalog: StageCatalog): string {
  if (stage.kind === "model") return modelOf(stage, catalog)?.name ?? stage.model ?? "Modelo";
  return (catalog.filters.find((f) => f.kind === stage.kind) ?? FALLBACK_CATALOG.filters.find((f) => f.kind === stage.kind))?.name ?? stage.kind;
}

export function stageSchema(stage: Stage, catalog: StageCatalog): ParamSpec[] {
  if (stage.kind === "model") {
    const params = modelOf(stage, catalog)?.params as ParamSpec[] | undefined;
    return params && params.length > 0 ? params : [STRENGTH];
  }
  return (catalog.filters.find((f) => f.kind === stage.kind) ?? FALLBACK_CATALOG.filters.find((f) => f.kind === stage.kind))!.params;
}

export function formatParam(spec: ParamSpec, value: ParamValue): string {
  if (spec.type === "choice") return spec.options?.find((o) => o.value === value)?.label ?? String(value);
  const n = Number(value);
  return spec.unit === "%" ? `${Math.round(n * 100)} %` : `${n}${spec.unit ? ` ${spec.unit}` : ""}`;
}

/** Resumen corto del valor más relevante de la caja (para mostrarlo dentro de ella). */
export function stageSummary(stage: Stage, catalog: StageCatalog): string {
  const spec = stageSchema(stage, catalog)[0];
  return spec ? formatParam(spec, stage.params[spec.id] ?? spec.default) : "";
}

/** Una caja de modelo con intensidad 0 o desactivada no hace nada. */
export function isActive(stage: Stage): boolean {
  return stage.enabled && !(stage.kind === "model" && Number(stage.params.strength ?? 1) <= 0);
}

/** Valores por defecto de un esquema. */
export function defaultParamsFor(schema: ParamSpec[]): Record<string, ParamValue> {
  return Object.fromEntries(schema.map((p) => [p.id, p.default]));
}
