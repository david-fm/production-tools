import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { es } from "../i18n/es";
import { ABPlayer } from "./ABPlayer";

beforeEach(() => {
  // jsdom no implementa la reproducción de medios.
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
});

const audios = (container: HTMLElement) => container.querySelectorAll("audio");

describe("ABPlayer", () => {
  it("atenúa el más fuerte al comparar (compensación activada por defecto)", () => {
    const { container } = render(<ABPlayer originalUrl="o.wav" enhancedUrl="e.wav" originalLufs={-30} enhancedLufs={-24} />);
    const [orig, enh] = audios(container);
    expect(orig.volume).toBe(1);
    expect(enh.volume).toBeCloseTo(10 ** (-6 / 20), 5);
  });

  it("desactivar la compensación restablece los volúmenes", async () => {
    const { container } = render(<ABPlayer originalUrl="o.wav" enhancedUrl="e.wav" originalLufs={-30} enhancedLufs={-24} />);
    await userEvent.click(screen.getByLabelText(es.loudnessComp));
    const [orig, enh] = audios(container);
    expect(orig.volume).toBe(1);
    expect(enh.volume).toBe(1);
  });

  it("al alternar conserva la posición de reproducción", async () => {
    const { container } = render(<ABPlayer originalUrl="o.wav" enhancedUrl="e.wav" originalLufs={null} enhancedLufs={null} />);
    const [orig, enh] = audios(container);
    enh.currentTime = 7.5;
    await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${es.original}`) }));
    expect(orig.currentTime).toBe(7.5);
  });

  it("muestra el volumen medido de cada versión", () => {
    render(<ABPlayer originalUrl="o.wav" enhancedUrl="e.wav" originalLufs={-30} enhancedLufs={-24} />);
    expect(screen.getByText(es.lufsOf(-30))).toBeInTheDocument();
    expect(screen.getByText(es.lufsOf(-24))).toBeInTheDocument();
  });
});
