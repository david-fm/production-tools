import { describe, expect, it } from "vitest";
import { clampRegion, compensatedVolumes, fileName, formatTime, MAX_PREVIEW_S } from "./format";

describe("formatTime", () => {
  it("formatea minutos y horas", () => {
    expect(formatTime(0)).toBe("0:00");
    expect(formatTime(65)).toBe("1:05");
    expect(formatTime(3661)).toBe("1:01:01");
  });
  it("tolera valores inválidos", () => {
    expect(formatTime(NaN)).toBe("0:00");
    expect(formatTime(-5)).toBe("0:00");
  });
});

describe("fileName", () => {
  it("funciona con rutas de Windows y de macOS", () => {
    expect(fileName("C:\\Videos\\ñandú\\entrevista final.mov")).toBe("entrevista final.mov");
    expect(fileName("/Users/ana/Película/toma 1.wav")).toBe("toma 1.wav");
  });
});

describe("compensatedVolumes", () => {
  it("atenúa el más fuerte hasta igualar al más débil", () => {
    const v = compensatedVolumes(-20, -14, true); // mejorado 6 dB más fuerte
    expect(v.original).toBe(1);
    expect(v.enhanced).toBeCloseTo(10 ** (-6 / 20), 6);
    const w = compensatedVolumes(-14, -20, true);
    expect(w.enhanced).toBe(1);
    expect(w.original).toBeCloseTo(10 ** (-6 / 20), 6);
  });
  it("no compensa si está desactivado o falta una medición", () => {
    expect(compensatedVolumes(-20, -14, false)).toEqual({ original: 1, enhanced: 1 });
    expect(compensatedVolumes(null, -14, true)).toEqual({ original: 1, enhanced: 1 });
  });
});

describe("clampRegion", () => {
  it("ordena, recorta a la duración y exige 1 s mínimo", () => {
    expect(clampRegion(10, 5, 100)).toEqual([5, 10]);
    expect(clampRegion(-3, 400, 100)).toEqual([0, MAX_PREVIEW_S]);
    expect(clampRegion(5, 5.2, 100)).toEqual([5, 6]);
    expect(clampRegion(99.8, 100, 100)).toEqual([99, 100]);
  });
  it("funciona con audios más cortos que 1 s", () => {
    expect(clampRegion(0, 0.5, 0.5)).toEqual([0, 0.5]);
  });
});
