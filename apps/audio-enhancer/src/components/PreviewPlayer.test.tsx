import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { es } from "../i18n/es";
import { PreviewPlayer } from "./PreviewPlayer";

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
});

const audios = (c: HTMLElement) => c.querySelectorAll("audio");
const mount = (over: Partial<React.ComponentProps<typeof PreviewPlayer>> = {}) =>
  render(<PreviewPlayer originalUrl="o.wav" enhancedUrl="e.wav" originalLufs={-30} enhancedLufs={-24} region={[20, 30]} {...over} />);

describe("PreviewPlayer", () => {
  it("atenúa el más fuerte al comparar y desactivarlo restablece los volúmenes", async () => {
    const { container } = mount();
    const [orig, enh] = audios(container);
    expect(orig.volume).toBe(1);
    expect(enh.volume).toBeCloseTo(10 ** (-6 / 20), 5);
    await userEvent.click(screen.getByLabelText(es.loudnessComp));
    expect(enh.volume).toBe(1);
  });

  it("muestra el fragmento y su duración; la barra solo abarca el fragmento", () => {
    mount();
    expect(screen.getByText(new RegExp(`${es.previewRange("0:20", "0:30")}`))).toBeInTheDocument();
    const seek = screen.getByRole("slider", { name: es.seek });
    expect(seek).toHaveAttribute("min", "0");
    expect(seek).toHaveAttribute("max", "10");
    expect(screen.getByText("0:00 / 0:10")).toBeInTheDocument();
  });

  it("al mover la barra salta ambos audios, queda dentro del fragmento y avisa con tiempo ABSOLUTO del archivo", () => {
    const onTime = vi.fn();
    const { container } = mount({ onTime });
    const [orig, enh] = audios(container);
    fireEvent.change(screen.getByRole("slider", { name: es.seek }), { target: { value: "4" } });
    expect(orig.currentTime).toBe(4);
    expect(enh.currentTime).toBe(4);
    expect(onTime).toHaveBeenLastCalledWith(24); // inicio del fragmento (20) + 4
    expect(screen.getByText("0:04 / 0:10")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("slider", { name: es.seek }), { target: { value: "99" } });
    expect(enh.currentTime).toBeLessThanOrEqual(10); // nunca fuera del fragmento
  });

  it("al alternar A/B conserva la posición", async () => {
    const { container } = mount({ originalLufs: null, enhancedLufs: null });
    const [orig, enh] = audios(container);
    enh.currentTime = 7.5;
    await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${es.original}`) }));
    expect(orig.currentTime).toBe(7.5);
  });

  it("reproduce y pausa", async () => {
    mount();
    await userEvent.click(screen.getByRole("button", { name: es.play }));
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: es.pause })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: es.pause }));
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it("con «repetir» vuelve al principio al terminar; sin él se detiene", async () => {
    const { container } = mount();
    const [, enh] = audios(container);
    await userEvent.click(screen.getByRole("button", { name: es.play }));
    await screen.findByRole("button", { name: es.pause });
    enh.currentTime = 9.9;
    fireEvent.ended(enh);
    expect(await screen.findByRole("button", { name: es.play })).toBeInTheDocument(); // se detuvo
    await userEvent.click(screen.getByLabelText(es.loop));
    await userEvent.click(screen.getByRole("button", { name: es.play }));
    await screen.findByRole("button", { name: es.pause });
    fireEvent.ended(enh);
    expect(enh.currentTime).toBe(0);
    expect(screen.getByRole("button", { name: es.pause })).toBeInTheDocument(); // sigue sonando
  });

  it("una prueba desactualizada se marca como tal y la actual no", () => {
    const { rerender } = mount();
    expect(screen.queryByText(es.stalePreview)).toBeNull();
    rerender(<PreviewPlayer originalUrl="o.wav" enhancedUrl="e.wav" originalLufs={-30} enhancedLufs={-24} region={[20, 30]} stale />);
    expect(screen.getByText(es.stalePreview)).toBeInTheDocument();
    expect(screen.getByText(es.staleHelp)).toBeInTheDocument();
  });

  it("una prueba nueva reinicia la posición", () => {
    const { rerender } = mount();
    fireEvent.change(screen.getByRole("slider", { name: es.seek }), { target: { value: "6" } });
    rerender(<PreviewPlayer originalUrl="o2.wav" enhancedUrl="e2.wav" originalLufs={-30} enhancedLufs={-24} region={[20, 30]} />);
    expect(screen.getByText("0:00 / 0:10")).toBeInTheDocument();
  });

  it("muestra el volumen medido de cada versión", () => {
    mount();
    expect(screen.getByText(es.lufsOf(-30))).toBeInTheDocument();
    expect(screen.getByText(es.lufsOf(-24))).toBeInTheDocument();
  });
});
