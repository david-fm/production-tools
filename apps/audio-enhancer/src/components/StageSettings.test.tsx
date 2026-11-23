import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { FALLBACK_CATALOG, type StageCatalog } from "../catalog";
import { es } from "../i18n/es";
import { makeStage, sanitizeSettings, type Settings } from "../settings";
import type { BoxId } from "./ChainEditor";
import type { ModelInfo } from "./ModelsPanel";
import { StageSettings } from "./StageSettings";

const kim: ModelInfo = {
  id: "kim-vocal-2", name: "Kim Vocal 2", task: "separate", description: "Aísla la voz.", license: "?", license_url: "", verified_license: false,
  default: false, size_bytes: 1, status: "installed", source: "catalog", in_use: false,
  params: [
    { id: "strength", type: "number", label: "Intensidad", help: "ayuda de intensidad", default: 1, min: 0, max: 1, step: 0.05, unit: "%" },
    { id: "keep", type: "choice", label: "Qué conservar", help: "ayuda de conservar", default: "primary", options: [{ value: "primary", label: "La voz" }, { value: "residual", label: "El resto" }] },
  ],
};
const catalog = (over: Partial<ModelInfo> = {}): StageCatalog => ({ ...FALLBACK_CATALOG, models: [{ ...kim, ...over }] });

function setup(id: BoxId, settings: Settings, cat = catalog(), extra: { onGoModels?: () => void; onChange?: (s: Settings) => void } = {}) {
  function H() {
    const [s, setS] = useState(settings);
    return (
      <>
        <StageSettings selectedId={id} settings={s} catalog={cat} fileLabel="a.wav · 0:10" onChange={(n) => { setS(n); extra.onChange?.(n); }} onGoModels={extra.onGoModels ?? (() => undefined)} />
        <output data-testid="json">{JSON.stringify(s.chain.map((x) => x.params))}</output>
      </>
    );
  }
  render(<H />);
}
const withStage = (stage: ReturnType<typeof makeStage>, over: Partial<Settings> = {}) => ({ ...sanitizeSettings({}), chain: [stage], ...over });

describe("StageSettings", () => {
  it("un modelo muestra solo sus parámetros, generados desde su esquema, con su ayuda", async () => {
    const st = { ...makeStage("model", "kim-vocal-2"), id: "k" };
    setup("k", withStage(st));
    expect(screen.getByText(/Intensidad: 100 %/)).toBeInTheDocument();
    expect(screen.getByText("ayuda de intensidad")).toBeInTheDocument();
    expect(screen.getByLabelText("Qué conservar")).toHaveValue("primary");
    expect(screen.getByText(es.modelUnverifiedWarning)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Qué conservar"), "residual");
    expect(screen.getByTestId("json").textContent).toContain('"keep":"residual"');
  });

  it("DeepFilterNet3 (sin más parámetros en su esquema) solo ofrece la intensidad y lo dice", () => {
    const st = { ...makeStage("model", "deepfilternet3"), id: "d" };
    setup("d", withStage(st), { ...FALLBACK_CATALOG, models: [{ ...kim, id: "deepfilternet3", name: "DeepFilterNet3", verified_license: true, params: [kim.params![0]] }] });
    expect(screen.queryByLabelText("Qué conservar")).toBeNull();
    expect(screen.getByText(es.modelNoParams)).toBeInTheDocument();
  });

  it("el slider de intensidad cambia el valor de ESA caja y «Restablecer» vuelve al valor por defecto", async () => {
    const st = { ...makeStage("model", "kim-vocal-2", { strength: 0.3, keep: "residual" }), id: "k" };
    setup("k", withStage(st));
    expect(screen.getByText(/Intensidad: 30 %/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: es.resetStage }));
    expect(screen.getByTestId("json").textContent).toBe('[{"strength":1,"keep":"primary"}]');
  });

  it("los filtros usan su esquema de respaldo y se restablecen", async () => {
    const st = { ...makeStage("highpass", null, { hz: 200 }), id: "h" };
    setup("h", withStage(st));
    expect(screen.getByText(/Frecuencia de corte: 200 Hz/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: es.resetStage }));
    expect(screen.getByTestId("json").textContent).toBe('[{"hz":80}]');
  });

  it("zumbido: la frecuencia es una lista de opciones (50/60 Hz)", async () => {
    const st = { ...makeStage("notch", null, { hz: 50 }), id: "n" };
    setup("n", withStage(st));
    await userEvent.selectOptions(screen.getByLabelText("Frecuencia de la red eléctrica"), "60");
    expect(screen.getByTestId("json").textContent).toContain('"hz":60');
  });

  it("un modelo sin instalar avisa y lleva a la pestaña Modelos", async () => {
    const onGoModels = vi.fn();
    const st = { ...makeStage("model", "kim-vocal-2"), id: "k" };
    setup("k", withStage(st), catalog({ status: "missing" }), { onGoModels });
    expect(screen.getByText(es.stageMissingModel)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: es.goToModels }));
    expect(onGoModels).toHaveBeenCalled();
  });

  it("activar/desactivar la caja desde su configuración", async () => {
    const onChange = vi.fn();
    const st = { ...makeStage("highpass"), id: "h" };
    setup("h", withStage(st), catalog(), { onChange });
    await userEvent.click(screen.getByRole("checkbox", { name: es.enableBox }));
    expect(onChange.mock.calls[0][0].chain[0].enabled).toBe(false);
  });

  it("Volumen y Salida tienen sus propios ajustes; Entrada solo informa", async () => {
    const base = sanitizeSettings({});
    setup("volume", base);
    await userEvent.selectOptions(screen.getByLabelText(es.target), "-23");
    expect(screen.getByText(es.volumeInfo)).toBeInTheDocument();
  });

  it("Salida: canales y formato", async () => {
    const onChange = vi.fn();
    setup("output", sanitizeSettings({}), catalog(), { onChange });
    await userEvent.selectOptions(screen.getByLabelText(es.channels), "mix");
    await userEvent.selectOptions(screen.getByLabelText(es.format), "flac24");
    expect(onChange.mock.calls.at(-1)![0]).toMatchObject({ channels: "mix", output_format: "flac24" });
  });

  it("Entrada muestra el archivo abierto", () => {
    setup("input", sanitizeSettings({}));
    expect(screen.getByText("a.wav · 0:10")).toBeInTheDocument();
  });
});
