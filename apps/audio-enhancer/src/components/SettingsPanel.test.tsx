import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { es } from "../i18n/es";
import { DEFAULT_SETTINGS } from "../settings";
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
});
