import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelsPanel, type ModelInfo } from "./ModelsPanel";

const base: ModelInfo = {
  id: "deepfilternet3", name: "DeepFilterNet3", task: "denoise", description: "Reduce ruido.", license: "MIT / Apache-2.0",
  license_url: "https://example.com/dfn3", verified_license: true, default: true, size_bytes: 8e6, status: "missing",
  source: "catalog", in_use: false,
};
const kim: ModelInfo = { ...base, id: "kim-vocal-2", name: "Kim Vocal 2", task: "separate", license: "Sin verificar", verified_license: false, default: false, size_bytes: 66e6 };

const calls: { cmd: string; params: Record<string, unknown> }[] = [];
let catalog: ModelInfo[] = [];
let failWith: string | null = null;

vi.mock("../engine", () => ({
  LONG_TIMEOUT_S: 86400,
  onEngineProgress: vi.fn(async () => () => undefined),
  engineCall: vi.fn(async (cmd: string, params: Record<string, unknown> = {}) => {
    calls.push({ cmd, params });
    if (failWith && cmd !== "models_catalog") throw failWith;
    if (cmd === "models_catalog") return catalog;
    return {};
  }),
}));

beforeEach(() => { calls.length = 0; catalog = [{ ...base }, { ...kim }]; failWith = null; });

describe("ModelsPanel", () => {
  it("lista el catálogo con tarea, tamaño, licencia y aviso de no verificado", async () => {
    render(<ModelsPanel onClose={() => undefined} onChanged={() => undefined} />);
    expect(await screen.findByText("DeepFilterNet3")).toBeInTheDocument();
    expect(screen.getByText("Kim Vocal 2")).toBeInTheDocument();
    expect(screen.getByText("Licencia sin verificar")).toBeInTheDocument();
    expect(screen.getByText("Modelo sin verificar: úsalo bajo tu responsabilidad.")).toBeInTheDocument();
    expect(screen.getByText(/Licencia: MIT/)).toBeInTheDocument();
  });

  it("un modelo con licencia verificada se instala sin confirmación", async () => {
    const onChanged = vi.fn();
    render(<ModelsPanel onClose={() => undefined} onChanged={onChanged} />);
    await screen.findByText("DeepFilterNet3");
    await userEvent.click(screen.getAllByRole("button", { name: "Instalar" })[0]);
    await waitFor(() => expect(calls.some((c) => c.cmd === "install_model" && c.params.model === "deepfilternet3")).toBe(true));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("un modelo sin licencia verificada espera la confirmación antes de instalar", async () => {
    render(<ModelsPanel onClose={() => undefined} onChanged={() => undefined} />);
    await screen.findByText("Kim Vocal 2");
    await userEvent.click(screen.getAllByRole("button", { name: "Instalar" })[1]);
    expect(screen.getByRole("alertdialog")).toHaveTextContent("licencia sin verificar");
    expect(calls.some((c) => c.cmd === "install_model")).toBe(false); // todavía no se instaló
    await userEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(calls.some((c) => c.cmd === "install_model")).toBe(false);
    await userEvent.click(screen.getAllByRole("button", { name: "Instalar" })[1]);
    await userEvent.click(screen.getByRole("button", { name: "Entiendo, instalar" }));
    await waitFor(() => expect(calls.some((c) => c.cmd === "install_model" && c.params.model === "kim-vocal-2")).toBe(true));
  });

  it("no permite quitar un modelo en uso", async () => {
    catalog = [{ ...base, status: "installed", in_use: true }];
    render(<ModelsPanel onClose={() => undefined} onChanged={() => undefined} />);
    expect(await screen.findByRole("button", { name: "Quitar" })).toBeDisabled();
    expect(screen.getByText(/En uso por un trabajo/)).toBeInTheDocument();
  });

  it("instala desde Hugging Face con aviso permanente y muestra los errores", async () => {
    failWith = "Repositorio inválido: usa el formato usuario/nombre.";
    render(<ModelsPanel onClose={() => undefined} onChanged={() => undefined} />);
    await screen.findByText("DeepFilterNet3");
    expect(screen.getByText(/Solo se aceptan archivos .onnx/)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Descargar de Hugging Face" });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Repositorio (usuario/nombre)"), "  alguien/modelo ");
    await userEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent("Repositorio inválido");
    expect(calls.find((c) => c.cmd === "install_hf")?.params.repo).toBe("alguien/modelo");
  });

  it("muestra como texto plano lo que venga del origen (sin interpretar HTML)", async () => {
    catalog = [{ ...base, name: "<img src=x onerror=alert(1)>", description: "<b>hola</b>", status: "installed", source: "huggingface", verified_license: false }];
    const { container } = render(<ModelsPanel onClose={() => undefined} onChanged={() => undefined} />);
    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });
});
