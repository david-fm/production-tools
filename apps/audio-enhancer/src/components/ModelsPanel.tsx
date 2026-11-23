import { useCallback, useEffect, useRef, useState } from "react";
import { engineCall, LONG_TIMEOUT_S, onEngineProgress } from "../engine";
import { es } from "../i18n/es";

export interface ModelInfo {
  id: string;
  name: string;
  task: string;
  description: string;
  license: string;
  license_url: string;
  verified_license: boolean;
  default: boolean;
  size_bytes: number;
  status: "installed" | "missing" | "outdated";
  source: "catalog" | "huggingface";
  in_use: boolean;
}

interface Props {
  onClose: () => void;
  onChanged: () => void;
}

/** Catálogo de modelos: instalar, quitar y añadir modelos .onnx de Hugging Face (siempre desde su origen). */
export function ModelsPanel({ onClose, onChanged }: Props) {
  const [items, setItems] = useState<ModelInfo[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [repo, setRepo] = useState("");
  const [file, setFile] = useState("");
  const job = useRef<string | null>(null);
  const counter = useRef(0);

  const refresh = useCallback(async () => {
    try {
      setItems((await engineCall<ModelInfo[]>("models_catalog")) ?? []);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const un = onEngineProgress((e) => { if (e.job && e.job === job.current) setProgress(e.value); });
    return () => { void un.then((f) => f()); };
  }, []);

  const run = async (id: string, fn: (key: string) => Promise<unknown>) => {
    if (busyId) return;
    const key = `model:${++counter.current}`;
    job.current = key;
    setBusyId(id);
    setProgress(0);
    setError(null);
    try {
      await fn(key);
      await refresh();
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      job.current = null;
      setBusyId(null);
    }
  };

  const install = (m: ModelInfo) =>
    run(m.id, (key) => engineCall("install_model", { model: m.id }, { job: key, timeoutS: LONG_TIMEOUT_S }));
  const requestInstall = (m: ModelInfo) => (m.verified_license ? install(m) : setConfirmId(m.id));
  const remove = (m: ModelInfo) => run(m.id, () => engineCall("remove_model", { model: m.id }));
  const installHf = () =>
    run("hf", async (key) => {
      await engineCall("install_hf", { repo: repo.trim(), ...(file.trim() ? { file: file.trim() } : {}) }, { job: key, timeoutS: LONG_TIMEOUT_S });
      setRepo("");
      setFile("");
    });

  const confirming = items?.find((m) => m.id === confirmId) ?? null;

  return (
    <section className="models" aria-label={es.modelsTitle}>
      <div className="row">
        <h2>{es.modelsTitle}</h2>
        <button type="button" onClick={onClose}>{es.modelsBack}</button>
      </div>
      <p className="help">{es.modelsIntro}</p>
      {error && <div className="banner error" role="alert">{error}</div>}

      {confirming && (
        <div className="banner warn" role="alertdialog" aria-label={es.modelConfirmTitle}>
          <p><strong>{es.modelConfirmTitle}</strong></p>
          <p>{es.modelConfirmBody(confirming.name, confirming.license)}</p>
          <div className="row">
            <button type="button" className="primary" onClick={() => { setConfirmId(null); void install(confirming); }}>{es.modelConfirmYes}</button>
            <button type="button" onClick={() => setConfirmId(null)}>{es.modelConfirmNo}</button>
          </div>
        </div>
      )}

      <ul className="model-list">
        {(items ?? []).map((m) => (
          <li key={m.id} className="model">
            <div>
              <strong>{m.name}</strong> <span className="hint">· {es.modelTasks[m.task] ?? m.task} · {es.modelSize(m.size_bytes / 1e6)}</span>
              <p className="help">{m.description}</p>
              <p className="hint">
                {m.verified_license ? es.modelLicense(m.license) : <span className="warn">{es.modelLicenseUnverified}</span>}
                {" · "}
                <a href={m.license_url} target="_blank" rel="noreferrer">{m.license_url}</a>
              </p>
              {(!m.verified_license || m.source === "huggingface") && <p className="warn">{es.modelUnverifiedWarning}</p>}
              <p className="hint">{es.modelStatus[m.status]}{m.in_use ? ` · ${es.modelInUse}` : ""}</p>
              {busyId === m.id && <progress value={progress} max={1} aria-label={es.stages.descargando} />}
            </div>
            <div className="row">
              {m.status !== "installed" && m.source === "catalog" && (
                <button type="button" onClick={() => requestInstall(m)} disabled={busyId !== null}>
                  {m.status === "outdated" ? es.modelReinstallBtn : es.modelInstallBtn}
                </button>
              )}
              {m.status === "installed" && (
                <button type="button" onClick={() => remove(m)} disabled={busyId !== null || m.in_use}>{es.modelRemoveBtn}</button>
              )}
            </div>
          </li>
        ))}
      </ul>

      <h3>{es.hfTitle}</h3>
      <p className="help">{es.hfHelp}</p>
      <div className="row">
        <label>{es.hfRepo}<input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="usuario/nombre" /></label>
        <label>{es.hfFile}<input value={file} onChange={(e) => setFile(e.target.value)} /></label>
        <button type="button" onClick={installHf} disabled={!repo.trim() || busyId !== null}>{es.hfInstall}</button>
      </div>
      {busyId === "hf" && <progress value={progress} max={1} aria-label={es.stages.descargando} />}
    </section>
  );
}
