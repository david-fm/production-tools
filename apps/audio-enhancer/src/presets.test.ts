import { describe, expect, it } from "vitest";
import { BUILTIN_PRESETS, loadCustomPresets, saveCustomPresets, upsertPreset } from "./presets";
import { freshDefaults, sanitizeSettings, settingsFingerprint } from "./settings";

function memoryStorage(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return {
    getItem: (k: string) => data[k] ?? null,
    setItem: (k: string, v: string) => { data[k] = v; },
    data,
  };
}

describe("sanitizeSettings", () => {
  it("rellena y limita valores fuera de rango", () => {
    const s = sanitizeSettings({
      target_lufs: -99, channels: "x",
      chain: [{ id: "a", kind: "highpass", enabled: true, params: { hz: 5 } }, { id: "b", kind: "model", model: "deepfilternet3", enabled: true, params: { strength: 7 } }],
    });
    expect(s.target_lufs).toBe(-40);
    expect(s.channels).toBe("each");
    expect(s.chain[0].params.hz).toBe(10);
    expect(s.chain[1].params.strength).toBe(1);
  });
  it("conserva ceros válidos", () => {
    const s = sanitizeSettings({ max_true_peak_db: 0, chain: [{ id: "b", kind: "model", model: "deepfilternet3", enabled: true, params: { strength: 0 } }] });
    expect(s.max_true_peak_db).toBe(0);
    expect(s.chain[0].params.strength).toBe(0);
  });
  it("ignora basura: etapas inválidas, ids repetidos y más del máximo", () => {
    const junk = sanitizeSettings({ chain: [5, null, { kind: "volume" }, { kind: "model" }, { kind: "model", model: "../x" }] as never });
    expect(junk.chain).toEqual([]);
    const dup = sanitizeSettings({ chain: [{ id: "a", kind: "highpass", params: {} }, { id: "a", kind: "highpass", params: {} }] as never });
    expect(new Set(dup.chain.map((s) => s.id)).size).toBe(2);
    const many = sanitizeSettings({ chain: Array.from({ length: 30 }, () => ({ kind: "highpass", params: {} })) as never });
    expect(many.chain).toHaveLength(12);
    expect(sanitizeSettings(null).chain.map((s) => s.kind)).toEqual(["highpass", "model"]);
  });
  it("migra los ajustes planos de v0.1.0/v0.2.0 a cadena con el orden de entonces", () => {
    const s = sanitizeSettings({ highpass_hz: 100, notch_hz: 60, notch_harmonics: 2, separate_model: "kim-vocal-2", separate_strength: 0.5, denoise: true, denoise_strength: 0.7, target_lufs: -23 });
    expect(s.chain.map((x) => [x.kind, x.model ?? null, x.params])).toEqual([
      ["highpass", null, { hz: 100 }],
      ["notch", null, { hz: 60, harmonics: 2 }],
      ["model", "kim-vocal-2", { strength: 0.5 }],
      ["model", "deepfilternet3", { strength: 0.7 }],
    ]);
    expect(s.target_lufs).toBe(-23);
    expect(sanitizeSettings({ highpass_hz: null, denoise: false }).chain).toEqual([]);
  });
  it("el huella de ajustes ignora los ids pero distingue el orden y los parámetros", () => {
    const a = sanitizeSettings({ chain: [{ id: "x1", kind: "highpass", params: { hz: 80 } }, { id: "x2", kind: "notch", params: { hz: 50 } }] });
    const b = sanitizeSettings({ chain: [{ id: "y1", kind: "highpass", params: { hz: 80 } }, { id: "y2", kind: "notch", params: { hz: 50 } }] });
    const c = sanitizeSettings({ chain: [{ id: "y2", kind: "notch", params: { hz: 50 } }, { id: "y1", kind: "highpass", params: { hz: 80 } }] });
    expect(settingsFingerprint(a)).toBe(settingsFingerprint(b));
    expect(settingsFingerprint(a)).not.toBe(settingsFingerprint(c));
  });
});

describe("preajustes integrados", () => {
  it("todos generan ajustes válidos con cajas de ids únicos", () => {
    for (const p of BUILTIN_PRESETS) {
      const s = p.build();
      expect(sanitizeSettings(s).chain.map((x) => [x.kind, x.model, x.params])).toEqual(s.chain.map((x) => [x.kind, x.model, x.params]));
      expect(new Set(s.chain.map((x) => x.id)).size).toBe(s.chain.length);
    }
  });
  it("hum50 y hum60 son solo el filtro de zumbido, sin IA", () => {
    const get = (id: string) => BUILTIN_PRESETS.find((p) => p.id === id)!.build();
    expect(get("hum50").chain.map((s) => [s.kind, s.params.hz])).toEqual([["notch", 50]]);
    expect(get("hum60").chain.map((s) => [s.kind, s.params.hz])).toEqual([["notch", 60]]);
    expect(get("tv").target_lufs).toBe(-23);
    expect(get("volumen").chain).toEqual([]);
  });
});

describe("preajustes propios", () => {
  it("se guardan y recuperan con versión", () => {
    const st = memoryStorage();
    const base = freshDefaults();
    const settings = { ...base, chain: base.chain.map((x) => (x.kind === "model" ? { ...x, params: { strength: 0.5 } } : x)) };
    const list = upsertPreset([], "  Mi entrevista ", settings);
    expect(saveCustomPresets(list, st)).toBe(true);
    expect(JSON.parse(st.data["audio-enhancer.presets"]).version).toBe(2);
    expect(loadCustomPresets(st)).toEqual([{ name: "Mi entrevista", settings }]);
  });
  it("migra los preajustes guardados en v0.1.0/v0.2.0 (ajustes planos) a cadena", () => {
    const old = { version: 1, presets: [{ name: "Viejo", settings: { highpass_hz: 120, notch_hz: null, denoise: true, denoise_strength: 0.6, normalize: true, target_lufs: -23 } }] };
    const [p] = loadCustomPresets(memoryStorage({ "audio-enhancer.presets": JSON.stringify(old) }));
    expect(p.name).toBe("Viejo");
    expect(p.settings.chain.map((s) => [s.kind, s.params])).toEqual([["highpass", { hz: 120 }], ["model", { strength: 0.6 }]]);
    expect(p.settings.target_lufs).toBe(-23);
  });
  it("reemplaza por nombre y rechaza nombres vacíos", () => {
    const a = upsertPreset([], "A", freshDefaults());
    expect(upsertPreset(a, "A", { ...freshDefaults(), normalize: false })).toHaveLength(1);
    expect(upsertPreset(a, "   ", freshDefaults())).toEqual(a);
  });
  it("datos corruptos o de otra versión se ignoran sin romper", () => {
    expect(loadCustomPresets(memoryStorage({ "audio-enhancer.presets": "{no json" }))).toEqual([]);
    expect(loadCustomPresets(memoryStorage({ "audio-enhancer.presets": JSON.stringify({ version: 99, presets: [] }) }))).toEqual([]);
  });
  it("sin almacenamiento disponible no falla", () => {
    expect(loadCustomPresets(null)).toEqual([]);
    expect(saveCustomPresets([], null)).toBe(false);
  });
});
