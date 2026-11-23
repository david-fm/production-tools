import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// --- Mocks de la capa Tauri y del cliente del motor ---
const calls: { cmd: string; params: Record<string, unknown>; job?: string }[] = [];
let progressHandler: ((e: { id: number; job: string; value: number; stage: string }) => void) | null = null;
let fullJobResolve: ((v: unknown) => void) | null = null;
let fullJobReject: ((e: unknown) => void) | null = null;
let dropHandler: ((e: { payload: { type: string; paths: string[] } }) => void) | null = null;
const unlistenDrop = vi.fn();
let dragResolve: ((f: () => void) => void) | null = null;
let extractGate: Promise<void> | null = null;

vi.mock("./engine", () => ({
  LONG_TIMEOUT_S: 86400,
  onEngineProgress: vi.fn(async (h: typeof progressHandler) => { progressHandler = h; return () => undefined; }),
  cancelJob: vi.fn(async () => { fullJobReject?.("cancelado"); }),
  engineCall: vi.fn(async (cmd: string, params: Record<string, unknown> = {}, opts: { job?: string } = {}) => {
    calls.push({ cmd, params, job: opts.job });
    switch (cmd) {
      case "health": return { version: "0.1.0" };
      case "preferred_providers": return ["CPUExecutionProvider"];
      case "models_status": return { deepfilternet3: { installed: true } };
      case "probe": return { duration_s: 120, has_video: true, audio_streams: [{ index: 0, channels: 2, sample_rate: 48000, codec: "aac" }] };
      case "waveform": return { duration_s: 120, channels: 2, min: Array(100).fill(-0.3), max: Array(100).fill(0.3) };
      case "extract": await extractGate; return { output: "o", duration_s: 10, lufs: -30 };
      case "enhance":
        if (!params.region) return new Promise((res, rej) => { fullJobResolve = res; fullJobReject = rej; });
        return { output: String(params.output), duration_s: 10, input_lufs: -30, output_lufs: -24, gain_db: 6, peak_limited: false, resumed_blocks: 0, warnings: [] };
      default: return null;
    }
  }),
}));
vi.mock("@tauri-apps/api/core", () => ({ convertFileSrc: (p: string) => `asset://${p}` }));
vi.mock("@tauri-apps/api/webview", () => ({
  getCurrentWebview: () => ({
    onDragDropEvent: (h: typeof dropHandler) => {
      dropHandler = h;
      return dragResolve ? new Promise<() => void>((res) => { dragResolve = res; }) : Promise.resolve(unlistenDrop);
    },
  }),
}));
vi.mock("@tauri-apps/api/path", () => ({ appCacheDir: async () => "/cache", join: async (...p: string[]) => p.join("/") }));
const dialog = { open: vi.fn(), save: vi.fn() };
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (...a: unknown[]) => dialog.open(...a), save: (...a: unknown[]) => dialog.save(...a) }));

import { App } from "./App";
import { es } from "./i18n/es";

beforeEach(() => {
  calls.length = 0;
  fullJobResolve = fullJobReject = progressHandler = null;
  dropHandler = null; dragResolve = null; extractGate = null; unlistenDrop.mockClear();
  dialog.open.mockResolvedValue("/media/entrevista.mov");
  dialog.save.mockResolvedValue("/out/entrevista_mejorado.mov");
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null); // jsdom no dibuja canvas
});

async function openFile() {
  render(<App />);
  await screen.findByText(new RegExp(es.engineReady("0.1.0").replace(/[()]/g, ".")));
  await userEvent.click(screen.getByRole("button", { name: new RegExp(es.openFile.slice(0, 12)) }));
  await screen.findByRole("heading", { name: "entrevista.mov" });
}

describe("App", () => {
  it("muestra cómo funciona antes de abrir un archivo", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: es.howTitle })).toBeInTheDocument();
  });

  it("abrir un archivo hace probe + forma de onda y propone un fragmento inicial de 10 s", async () => {
    await openFile();
    expect(calls.map((c) => c.cmd)).toEqual(expect.arrayContaining(["probe", "waveform"]));
    expect(screen.getByDisplayValue("10")).toBeInTheDocument();
  });

  it("la vista previa extrae el original y procesa solo la región con los ajustes actuales", async () => {
    await openFile();
    await userEvent.click(screen.getByRole("button", { name: es.previewButton }));
    await screen.findByLabelText(es.loudnessComp);
    const enhance = calls.find((c) => c.cmd === "enhance");
    expect(enhance?.params.region).toEqual([0, 10]);
    const sent = enhance?.params.settings as { chain: { kind: string; model: string | null }[]; target_lufs: number; version: number };
    expect(sent.chain.map((c) => [c.kind, c.model])).toEqual([["highpass", null], ["model", "deepfilternet3"]]);
    expect(sent).toMatchObject({ target_lufs: -16, version: 2 });
    expect(calls.find((c) => c.cmd === "extract")?.params.region).toEqual([0, 10]);
  });

  it("procesar todo, mostrar progreso y cancelar deja un aviso y vuelve a habilitar los controles", async () => {
    await openFile();
    await userEvent.click(screen.getAllByRole("button", { name: es.processAll })[0]);
    const job = await waitFor(() => {
      const j = calls.find((c) => c.cmd === "enhance" && !c.params.region)?.job;
      expect(j).toBeTruthy();
      return j!;
    });
    act(() => progressHandler?.({ id: 1, job, value: 0.4, stage: "procesando" }));
    expect(await screen.findByText(/Procesando 40 %/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: es.cancel }));
    expect(await screen.findByText(es.jobCancelled)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: es.processAll })[0]).toBeEnabled();
  });

  it("procesar todo con éxito muestra el archivo guardado y el volumen antes → después", async () => {
    await openFile();
    await userEvent.click(screen.getAllByRole("button", { name: es.processAll })[0]);
    await waitFor(() => expect(fullJobResolve).not.toBeNull());
    fullJobResolve!({ output: "/out/x.wav", duration_s: 120, input_lufs: -30, output_lufs: -16, gain_db: 14, peak_limited: true, resumed_blocks: 2, warnings: ["Se limitó el volumen"] });
    expect(await screen.findByText(/Archivo guardado/)).toBeInTheDocument();
    expect(screen.getByText(es.jobResult("-30.0 LUFS", "-16.0 LUFS"))).toBeInTheDocument();
    expect(screen.getByText(es.resumed(2))).toBeInTheDocument();
    expect(screen.getByText("Se limitó el volumen")).toBeInTheDocument();
  });

  it("un video ofrece guardar con el audio mejorado y envía remux=true", async () => {
    await openFile();
    await userEvent.click(screen.getByRole("button", { name: es.processVideo }));
    await waitFor(() => expect(calls.find((c) => c.cmd === "enhance" && c.params.remux === true)).toBeTruthy());
  });

  it("un archivo soltado mientras hay un trabajo en curso se ignora", async () => {
    await openFile();
    await userEvent.click(screen.getAllByRole("button", { name: es.processAll })[0]);
    await waitFor(() => expect(fullJobResolve).not.toBeNull());
    const probesBefore = calls.filter((c) => c.cmd === "probe").length;
    act(() => dropHandler?.({ payload: { type: "drop", paths: ["/media/otro.wav"] } }));
    await new Promise((r) => setTimeout(r, 30));
    expect(calls.filter((c) => c.cmd === "probe").length).toBe(probesBefore);
    expect(screen.getByRole("button", { name: es.cancel })).toBeInTheDocument(); // el trabajo sigue siendo el activo
  });

  it("soltar un archivo sin trabajos en curso lo carga", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: es.howTitle });
    act(() => dropHandler?.({ payload: { type: "drop", paths: ["/media/entrevista.mov"] } }));
    await screen.findByRole("heading", { name: "entrevista.mov" });
  });

  it("el listener de arrastrar se libera aunque el efecto se limpie antes de resolver la promesa", async () => {
    let release: ((f: () => void) => void) | null = null;
    dragResolve = () => undefined; // activa el modo "promesa pendiente"
    const { unmount } = render(<App />);
    await waitFor(() => expect(dropHandler).not.toBeNull());
    release = dragResolve;
    unmount(); // limpieza ANTES de que resuelva
    release?.(unlistenDrop);
    await waitFor(() => expect(unlistenDrop).toHaveBeenCalledTimes(1));
  });

  it("dos clics seguidos en la vista previa lanzan una sola", async () => {
    await openFile();
    let release!: () => void;
    extractGate = new Promise<void>((r) => { release = r; });
    const button = screen.getByRole("button", { name: es.previewButton });
    await userEvent.dblClick(button);
    release();
    await screen.findByLabelText(es.loudnessComp);
    expect(calls.filter((c) => c.cmd === "extract").length).toBe(1);
    expect(calls.filter((c) => c.cmd === "enhance" && c.params.region).length).toBe(1);
  });

  it("cancelar durante la fase 1 de la vista previa evita la fase 2 y cancela la clave de la fase activa", async () => {
    await openFile();
    let release!: () => void;
    extractGate = new Promise<void>((r) => { release = r; });
    await userEvent.click(screen.getByRole("button", { name: es.previewButton }));
    await userEvent.click(await screen.findByRole("button", { name: es.cancel }));
    release();
    expect(await screen.findByText(es.jobCancelled)).toBeInTheDocument();
    expect(calls.some((c) => c.cmd === "enhance" && c.params.region)).toBe(false);
  });

  it("si el usuario cierra el diálogo de guardado no se procesa nada", async () => {
    dialog.save.mockResolvedValue(null);
    await openFile();
    await userEvent.click(screen.getAllByRole("button", { name: es.processAll })[0]);
    await new Promise((r) => setTimeout(r, 50));
    expect(calls.some((c) => c.cmd === "enhance" && !c.params.region)).toBe(false);
  });

  describe("pestañas, cadena y prueba desactualizada", () => {
    const preview = async () => {
      await openFile();
      await userEvent.click(screen.getByRole("button", { name: es.previewButton }));
      await screen.findByLabelText(es.loudnessComp);
    };

    it("tiene pestañas Audio, Cadena y Modelos accesibles y navegables con flechas", async () => {
      await openFile();
      const tabs = screen.getAllByRole("tab");
      expect(tabs.map((t) => t.textContent)).toEqual([es.tabAudio, es.tabChain, es.tabModels]);
      expect(screen.getByRole("tab", { name: es.tabAudio })).toHaveAttribute("aria-selected", "true");
      screen.getByRole("tab", { name: es.tabAudio }).focus();
      await userEvent.keyboard("{ArrowRight}");
      expect(screen.getByRole("tab", { name: es.tabChain })).toHaveAttribute("aria-selected", "true");
      expect(screen.getByRole("tabpanel", { name: es.tabChain })).toBeVisible();
    });

    it("el estado de la prueba se conserva al cambiar de pestaña", async () => {
      await preview();
      await userEvent.click(screen.getByRole("tab", { name: es.tabChain }));
      await userEvent.click(screen.getByRole("tab", { name: es.tabAudio }));
      expect(screen.getByLabelText(es.loudnessComp)).toBeInTheDocument();
      expect(screen.queryByText(es.stalePreview)).toBeNull();
    });

    it("cambiar la cadena después de probar marca la prueba como desactualizada y «Probar de nuevo» la rehace", async () => {
      await preview();
      expect(screen.queryByText(es.stalePreview)).toBeNull();
      await userEvent.click(screen.getByRole("tab", { name: es.tabChain }));
      await userEvent.click(screen.getByRole("button", { name: /Recorte de graves/ }));
      await userEvent.click(screen.getByRole("button", { name: es.disableBox }));
      await userEvent.click(screen.getByRole("tab", { name: es.tabAudio }));
      expect(screen.getByText(es.stalePreview)).toBeInTheDocument();
      const before = calls.filter((c) => c.cmd === "enhance" && c.params.region).length;
      await userEvent.click(screen.getByRole("button", { name: es.previewAgain }));
      await waitFor(() => expect(calls.filter((c) => c.cmd === "enhance" && c.params.region).length).toBe(before + 1));
      await waitFor(() => expect(screen.queryByText(es.stalePreview)).toBeNull());
      const last = calls.filter((c) => c.cmd === "enhance" && c.params.region).at(-1)!.params.settings as { chain: { kind: string; enabled: boolean }[] };
      expect(last.chain.find((c) => c.kind === "highpass")?.enabled).toBe(false);
    });

    it("mover el fragmento después de probar también la desactualiza", async () => {
      await preview();
      const end = screen.getByDisplayValue("10");
      await userEvent.clear(end);
      await userEvent.type(end, "20");
      expect(await screen.findByText(es.stalePreview)).toBeInTheDocument();
    });

    it("un parámetro de una caja cambia lo que se envía al motor", async () => {
      await openFile();
      await userEvent.click(screen.getByRole("tab", { name: es.tabChain }));
      await userEvent.click(screen.getByRole("button", { name: /DeepFilterNet3|deepfilternet3/i }));
      const slider = screen.getByLabelText(/Intensidad/);
      fireEvent.change(slider, { target: { value: "40" } });
      await userEvent.click(screen.getByRole("tab", { name: es.tabAudio }));
      await userEvent.click(screen.getByRole("button", { name: es.previewButton }));
      await screen.findByLabelText(es.loudnessComp);
      const sent = calls.find((c) => c.cmd === "enhance" && c.params.region)!.params.settings as { chain: { model: string | null; params: { strength?: number } }[] };
      expect(sent.chain.find((c) => c.model === "deepfilternet3")?.params.strength).toBeCloseTo(0.4);
    });

    it("un preajuste reemplaza la cadena completa", async () => {
      await openFile();
      await userEvent.click(screen.getByRole("tab", { name: es.tabChain }));
      await userEvent.selectOptions(screen.getByLabelText(es.preset), "builtin:hum50");
      const list = screen.getAllByRole("list")[0];
      expect(within(list).getAllByRole("button").map((b) => b.querySelector(".box-name")?.textContent)).toEqual([es.boxInput, "Zumbido eléctrico", es.boxVolume, es.boxOutput]);
    });

    it("la cadena activa se ve en solo lectura en la pestaña Audio", async () => {
      await openFile();
      const strip = screen.getByRole("group", { name: es.chainSummary });
      expect(within(strip).getByText(/Recorte de graves/)).toBeInTheDocument();
      await userEvent.click(within(strip).getByRole("button", { name: es.editChain }));
      expect(screen.getByRole("tab", { name: es.tabChain })).toHaveAttribute("aria-selected", "true");
    });
  });
});
