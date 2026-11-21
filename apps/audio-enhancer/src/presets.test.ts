import { describe, expect, it } from "vitest";
import { BUILTIN_PRESETS, loadCustomPresets, saveCustomPresets, upsertPreset } from "./presets";
import { DEFAULT_SETTINGS, sanitizeSettings } from "./settings";

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
    const s = sanitizeSettings({ denoise_strength: 7, target_lufs: -99, highpass_hz: 5, channels: "x" as never });
    expect(s.denoise_strength).toBe(1);
    expect(s.target_lufs).toBe(-40);
    expect(s.highpass_hz).toBe(10);
    expect(s.channels).toBe("each");
  });
  it("conserva ceros válidos y null", () => {
    const s = sanitizeSettings({ max_true_peak_db: 0, denoise_strength: 0, highpass_hz: null });
    expect(s.max_true_peak_db).toBe(0);
    expect(s.denoise_strength).toBe(0);
    expect(s.highpass_hz).toBeNull();
  });
  it("ignora NaN y basura", () => {
    expect(sanitizeSettings({ denoise_strength: NaN as never }).denoise_strength).toBe(1);
    expect(sanitizeSettings(null)).toEqual(DEFAULT_SETTINGS);
  });
});

describe("preajustes integrados", () => {
  it("todos tienen ajustes válidos y son idempotentes al sanear", () => {
    for (const p of BUILTIN_PRESETS) expect(sanitizeSettings(p.settings)).toEqual(p.settings);
  });
  it("hum50 y hum60 activan el notch correcto sin IA", () => {
    const get = (id: string) => BUILTIN_PRESETS.find((p) => p.id === id)!.settings;
    expect(get("hum50")).toMatchObject({ notch_hz: 50, denoise: false });
    expect(get("hum60")).toMatchObject({ notch_hz: 60, denoise: false });
  });
});

describe("preajustes propios", () => {
  it("se guardan y recuperan con versión", () => {
    const st = memoryStorage();
    const list = upsertPreset([], "  Mi entrevista ", { ...DEFAULT_SETTINGS, denoise_strength: 0.5 });
    expect(saveCustomPresets(list, st)).toBe(true);
    expect(JSON.parse(st.data["audio-enhancer.presets"]).version).toBe(1);
    expect(loadCustomPresets(st)).toEqual([{ name: "Mi entrevista", settings: { ...DEFAULT_SETTINGS, denoise_strength: 0.5 } }]);
  });
  it("reemplaza por nombre y rechaza nombres vacíos", () => {
    const a = upsertPreset([], "A", DEFAULT_SETTINGS);
    expect(upsertPreset(a, "A", { ...DEFAULT_SETTINGS, normalize: false })).toHaveLength(1);
    expect(upsertPreset(a, "   ", DEFAULT_SETTINGS)).toEqual(a);
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
