import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { es } from "../i18n/es";
import { DEFAULT_SETTINGS } from "../settings";
import type { ModelInfo } from "./ModelsPanel";
import { SettingsPanel } from "./SettingsPanel";

const setup = (over = {}) => {
  const onChange = vi.fn();
  const onSavePreset = vi.fn();
  render(
    <SettingsPanel settings={{ ...DEFAULT_SETTINGS, ...over }} onChange={onChange} customPresets={[]}
                   onSavePreset={onSavePreset} onDeletePreset={vi.fn()} />,
  );
  return { onChange, onSavePreset };
};

describe("SettingsPanel", () => {
  it("muestra una explicación en lenguaje llano para cada control principal", () => {
    setup();
    for (const text of [es.denoiseHelp, es.highpassHelp, es.notchHelp, es.normalizeHelp, es.channelsHelp]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
  });

  it("al elegir un preajuste aplica sus ajustes", async () => {
    const { onChange } = setup();
    await userEvent.selectOptions(screen.getByLabelText(es.preset), "builtin:hum50");
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ notch_hz: 50, denoise: false }));
  });

  it("cambiar la intensidad emite un valor entre 0 y 1", () => {
    const { onChange } = setup();
    const slider = screen.getByLabelText(new RegExp(es.denoiseStrength));
    fireEvent.change(slider, { target: { value: "35" } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ denoise_strength: 0.35 }));
  });

  it("oculta la intensidad si la reducción de ruido está desactivada", () => {
    setup({ denoise: false });
    expect(screen.queryByLabelText(new RegExp(es.denoiseStrength))).toBeNull();
  });

  it("no permite guardar un preajuste sin nombre y lo guarda con nombre", async () => {
    const { onSavePreset } = setup();
    const button = screen.getByRole("button", { name: es.savePreset });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByPlaceholderText(es.presetNamePrompt), "Mi cámara");
    await userEvent.click(button);
    expect(onSavePreset).toHaveBeenCalledWith("Mi cámara");
  });

  it("el selector de zumbido ofrece desactivado, 50 y 60 Hz", async () => {
    const { onChange } = setup();
    await userEvent.selectOptions(screen.getByLabelText(es.notch), "60");
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ notch_hz: 60 }));
  });

  describe("etapa de aislar voz", () => {
    const kim: ModelInfo = { id: "kim-vocal-2", name: "Kim Vocal 2", task: "separate", description: "", license: "?", license_url: "",
      verified_license: false, default: false, size_bytes: 1, status: "installed", source: "catalog", in_use: false };
    const mount = (models: ModelInfo[], over = {}) => {
      const onChange = vi.fn();
      render(<SettingsPanel settings={{ ...DEFAULT_SETTINGS, ...over }} onChange={onChange} customPresets={[]}
                            onSavePreset={vi.fn()} onDeletePreset={vi.fn()} models={models} />);
      return onChange;
    };

    it("no aparece si el catálogo no tiene modelos de separación", () => {
      mount([]);
      expect(screen.queryByLabelText(es.separateStage)).toBeNull();
    });

    it("lista solo los modelos instalados y permite elegir uno", async () => {
      const onChange = mount([kim, { ...kim, id: "otro", name: "Otro", status: "missing" }]);
      const select = screen.getByLabelText(es.separateStage);
      expect(screen.queryByRole("option", { name: "Otro" })).toBeNull();
      await userEvent.selectOptions(select, "kim-vocal-2");
      expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ separate_model: "kim-vocal-2" }));
    });

    it("avisa si hay que instalar un modelo y muestra la intensidad al elegir uno", () => {
      mount([{ ...kim, status: "missing" }]);
      expect(screen.getByText(es.separateNeedsInstall)).toBeInTheDocument();
    });

    it("muestra la intensidad y avisa si el modelo elegido ya no está instalado", () => {
      mount([{ ...kim, status: "missing" }], { separate_model: "kim-vocal-2" });
      expect(screen.getByLabelText(new RegExp(es.separateStrength))).toBeInTheDocument();
      expect(screen.getByText(es.separateMissingNote)).toBeInTheDocument();
    });
  });
});
