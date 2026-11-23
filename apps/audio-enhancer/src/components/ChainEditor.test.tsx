import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { FALLBACK_CATALOG, type StageCatalog } from "../catalog";
import { es } from "../i18n/es";
import { makeStage, MAX_STAGES, type Stage } from "../settings";
import { ChainEditor, moveItem, type BoxId } from "./ChainEditor";
import type { ModelInfo } from "./ModelsPanel";

const model = (over: Partial<ModelInfo>): ModelInfo => ({
  id: "deepfilternet3", name: "DeepFilterNet3", task: "denoise", description: "", license: "MIT", license_url: "", verified_license: true,
  default: true, size_bytes: 1, status: "installed", source: "catalog", in_use: false, ...over,
});
const catalog: StageCatalog = {
  ...FALLBACK_CATALOG,
  models: [model({}), model({ id: "kim-vocal-2", name: "Kim Vocal 2", task: "separate", verified_license: false }), model({ id: "otro", name: "Modelo extra", status: "missing" })],
};

function Harness({ initial, onChain, disabled }: { initial: Stage[]; onChain?: (c: Stage[]) => void; disabled?: boolean }) {
  const [chain, setChain] = useState(initial);
  const [sel, setSel] = useState<BoxId>("input");
  return (
    <>
      <ChainEditor chain={chain} catalog={catalog} selectedId={sel} onSelect={setSel} disabled={disabled}
                   onChange={(c) => { setChain(c); onChain?.(c); }} />
      <output data-testid="sel">{sel}</output>
      <output data-testid="order">{chain.map((s) => s.id).join(",")}</output>
    </>
  );
}
const stages = () => [{ ...makeStage("highpass"), id: "a" }, { ...makeStage("notch"), id: "b" }, { ...makeStage("model", "deepfilternet3"), id: "c" }];
const order = () => screen.getByTestId("order").textContent;
const boxes = () => screen.getAllByRole("button", { pressed: false }).concat(screen.queryAllByRole("button", { pressed: true }));

describe("moveItem", () => {
  it("mueve y no hace nada fuera de rango", () => {
    expect(moveItem([1, 2, 3], 0, 2)).toEqual([2, 3, 1]);
    expect(moveItem([1, 2, 3], 2, 0)).toEqual([3, 1, 2]);
    const same = [1, 2];
    expect(moveItem(same, 0, 5)).toBe(same);
    expect(moveItem(same, 1, 1)).toBe(same);
  });
});

describe("ChainEditor", () => {
  it("muestra Entrada, las cajas en orden, Volumen y Salida", () => {
    render(<Harness initial={stages()} />);
    const names = within(screen.getByRole("list")).getAllByRole("button").map((b) => b.querySelector(".box-name")?.textContent);
    expect(names).toEqual([es.boxInput, "Recorte de graves", "Zumbido eléctrico", "DeepFilterNet3", es.boxVolume, es.boxOutput]);
  });

  it("las cajas fijas no se pueden mover ni quitar (no hay acciones)", async () => {
    render(<Harness initial={stages()} />);
    await userEvent.click(screen.getByRole("button", { name: new RegExp(es.boxVolume) }));
    expect(screen.queryByRole("button", { name: es.moveBefore })).toBeNull();
    expect(screen.queryByRole("button", { name: es.removeBox })).toBeNull();
    expect(boxes().length).toBeGreaterThan(0);
  });

  it("reordena con los botones «Mover antes/después» (vía sin arrastrar)", async () => {
    render(<Harness initial={stages()} />);
    await userEvent.click(screen.getByRole("button", { name: /Recorte de graves/ }));
    expect(screen.getByRole("button", { name: es.moveBefore })).toBeDisabled(); // es la primera
    await userEvent.click(screen.getByRole("button", { name: es.moveAfter }));
    expect(order()).toBe("b,a,c");
    await userEvent.click(screen.getByRole("button", { name: es.moveAfter }));
    await userEvent.click(screen.getByRole("button", { name: es.moveAfter }));
    expect(screen.getByRole("button", { name: es.moveAfter })).toBeDisabled(); // llegó al final
    expect(order()).toBe("b,c,a");
  });

  it("con el teclado: flechas eligen caja y Alt+flechas la mueven", async () => {
    render(<Harness initial={stages()} />);
    const first = screen.getByRole("button", { name: new RegExp(es.boxInput) });
    first.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByTestId("sel").textContent).toBe("a");
    await userEvent.keyboard("{Alt>}{ArrowRight}{/Alt}");
    expect(order()).toBe("b,a,c");
    await userEvent.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(screen.getByTestId("sel").textContent).toBe("input"); // no pasa del principio
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByTestId("sel").textContent).toBe("input");
  });

  it("también se reordena arrastrando una caja sobre otra", () => {
    render(<Harness initial={stages()} />);
    const items = within(screen.getByRole("list")).getAllByRole("listitem").filter((li) => li.classList.contains("box"));
    const data: Record<string, string> = {};
    const dataTransfer = { setData: (k: string, v: string) => { data[k] = v; }, getData: (k: string) => data[k], effectAllowed: "" };
    fireEvent.dragStart(items[1], { dataTransfer }); // «Recorte de graves»
    fireEvent.dragOver(items[3], { dataTransfer });
    fireEvent.drop(items[3], { dataTransfer }); // sobre «DeepFilterNet3»
    expect(order()).toBe("b,c,a");
  });

  it("las cajas fijas no son arrastrables", () => {
    render(<Harness initial={stages()} />);
    const fixed = within(screen.getByRole("list")).getAllByRole("listitem").filter((li) => li.classList.contains("fixed"));
    expect(fixed).toHaveLength(3);
    for (const li of fixed) expect(li.getAttribute("draggable")).toBeNull();
  });

  it("activa/desactiva y quita una caja, y la selección pasa a una vecina", async () => {
    render(<Harness initial={stages()} />);
    await userEvent.click(screen.getByRole("button", { name: /Zumbido/ }));
    await userEvent.click(screen.getByRole("button", { name: es.disableBox }));
    expect(screen.getByText(es.boxDisabled)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: es.enableBox })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: es.removeBox }));
    expect(order()).toBe("a,c");
    expect(screen.getByTestId("sel").textContent).toBe("c");
  });

  it("añade filtros y modelos instalados; los no instalados aparecen deshabilitados", async () => {
    render(<Harness initial={[]} />);
    expect(screen.getByText(es.chainEmpty)).toBeInTheDocument();
    const select = screen.getByLabelText(es.addBoxLabel);
    expect(screen.getByRole("option", { name: "Modelo extra" })).toBeDisabled();
    await userEvent.selectOptions(select, "highpass");
    await userEvent.click(screen.getByRole("button", { name: es.addBoxButton }));
    await userEvent.selectOptions(select, "model:kim-vocal-2");
    await userEvent.click(screen.getByRole("button", { name: es.addBoxButton }));
    const kinds = within(screen.getByRole("list")).getAllByRole("button").map((b) => b.querySelector(".box-name")?.textContent);
    expect(kinds).toEqual([es.boxInput, "Recorte de graves", "Kim Vocal 2", es.boxVolume, es.boxOutput]);
    expect(screen.getByText(es.boxUnverified)).toBeInTheDocument(); // licencia sin verificar
  });

  it("se pueden repetir cajas y hay un máximo", async () => {
    const full = Array.from({ length: MAX_STAGES - 1 }, (_, i) => ({ ...makeStage("highpass"), id: `h${i}` }));
    const changes = vi.fn();
    render(<Harness initial={full} onChain={changes} />);
    await userEvent.selectOptions(screen.getByLabelText(es.addBoxLabel), "highpass"); // repetida: permitido
    await userEvent.click(screen.getByRole("button", { name: es.addBoxButton }));
    expect(changes).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText(es.addBoxLabel)).toBeDisabled();
    expect(screen.getByRole("button", { name: es.addBoxButton })).toBeDisabled();
    expect(screen.getByText(es.chainLimit(MAX_STAGES))).toBeInTheDocument();
  });

  it("marca los modelos sin instalar y deshabilita los controles mientras hay un trabajo", () => {
    const missingModel = [{ ...makeStage("model", "otro"), id: "m" }];
    render(<Harness initial={missingModel} disabled />);
    expect(screen.getByText(es.boxNotInstalled)).toBeInTheDocument();
    expect(screen.getByLabelText(es.addBoxLabel)).toBeDisabled();
  });
});
