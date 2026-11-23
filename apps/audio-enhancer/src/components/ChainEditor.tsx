import { Fragment, useState } from "react";
import { modelOf, stageName, stageSummary, type StageCatalog } from "../catalog";
import { es } from "../i18n/es";
import { makeStage, MAX_STAGES, type Stage } from "../settings";

export type FixedId = "input" | "volume" | "output";
export type BoxId = FixedId | string;

interface Props {
  chain: Stage[];
  catalog: StageCatalog;
  selectedId: BoxId;
  onSelect: (id: BoxId) => void;
  onChange: (chain: Stage[]) => void;
  disabled?: boolean;
}

/** Mueve un elemento de `from` a `to` (índices de la lista de etapas). */
export function moveItem<T>(list: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return list;
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

function Arrow() {
  return (
    <svg className="connector" width="28" height="16" viewBox="0 0 28 16" aria-hidden="true" focusable="false">
      <path d="M1 8h22M17 2l7 6-7 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Cadena lineal de cajas: Entrada → cajas → Volumen → Salida. Se reordena arrastrando, con botones o con el teclado. */
export function ChainEditor({ chain, catalog, selectedId, onSelect, onChange, disabled }: Props) {
  const [dragId, setDragId] = useState<string | null>(null);
  const [addValue, setAddValue] = useState("");
  const order: BoxId[] = ["input", ...chain.map((s) => s.id), "volume", "output"];
  const index = chain.findIndex((s) => s.id === selectedId);
  const selected = index >= 0 ? chain[index] : null;

  const move = (id: string, delta: number) => {
    const from = chain.findIndex((s) => s.id === id);
    onChange(moveItem(chain, from, from + delta));
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (disabled || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    const delta = e.key === "ArrowLeft" ? -1 : 1;
    e.preventDefault();
    if (e.altKey && selected) {
      move(selected.id, delta);
      return;
    }
    const at = order.indexOf(selectedId);
    const next = order[Math.min(order.length - 1, Math.max(0, at + delta))];
    onSelect(next);
    requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(`[data-box="${next}"]`)?.focus());
  };

  const add = () => {
    if (!addValue || chain.length >= MAX_STAGES) return;
    const stage = addValue.startsWith("model:") ? makeStage("model", addValue.slice(6)) : makeStage(addValue as "highpass" | "notch");
    onChange([...chain, stage]);
    onSelect(stage.id);
    setAddValue("");
  };

  const installed = catalog.models.filter((m) => m.status === "installed");
  const missing = catalog.models.filter((m) => m.status !== "installed");

  // La flecha va DESPUÉS de cada caja (salvo la última): al partir la fila en ventanas estrechas, la flecha
  // queda al final de la línea apuntando a la siguiente, nunca sola al principio.
  const fixedBox = (id: FixedId, label: string, arrow = true) => (
    <li className="box fixed">
      <button type="button" data-box={id} aria-pressed={selectedId === id} onClick={() => onSelect(id)} className="box-button">
        <span className="box-name">{label}</span>
        <span className="box-sub">{es.boxFixedHint}</span>
      </button>
      {arrow && <Arrow />}
    </li>
  );

  return (
    <section className="chain-editor" aria-label={es.chainListLabel}>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <ol className="chain" onKeyDown={onKeyDown}>
        {fixedBox("input", es.boxInput)}
        {chain.map((stage, i) => {
          const model = modelOf(stage, catalog);
          const missingModel = stage.kind === "model" && (!model || model.status !== "installed");
          const unverified = model && !model.verified_license;
          return (
            <Fragment key={stage.id}>
              <li
                className={`box${stage.enabled ? "" : " off"}${dragId === stage.id ? " dragging" : ""}`}
                draggable={!disabled}
                onDragStart={(e) => { setDragId(stage.id); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", stage.id); }}
                onDragEnd={() => setDragId(null)}
                onDragOver={(e) => { if (dragId) e.preventDefault(); }}
                onDrop={(e) => {
                  e.preventDefault();
                  if (dragId) onChange(moveItem(chain, chain.findIndex((s) => s.id === dragId), i));
                  setDragId(null);
                }}
              >
                <button type="button" data-box={stage.id} aria-pressed={selectedId === stage.id} onClick={() => onSelect(stage.id)} className="box-button">
                  <span className="box-name">{stageName(stage, catalog)}</span>
                  <span className="box-sub">{stageSummary(stage, catalog)}</span>
                  {!stage.enabled && <span className="tag">{es.boxDisabled}</span>}
                  {missingModel && <span className="tag warn-tag">{es.boxNotInstalled}</span>}
                  {unverified && <span className="tag">{es.boxUnverified}</span>}
                </button>
                <Arrow />
              </li>
            </Fragment>
          );
        })}
        {fixedBox("volume", es.boxVolume)}
        {fixedBox("output", es.boxOutput, false)}
      </ol>
      <p className="hint">{es.chainKeyboardHint}</p>
      {chain.length === 0 && <p className="help">{es.chainEmpty}</p>}

      {selected && (
        <div className="row box-actions" role="group" aria-label={stageName(selected, catalog)}>
          <button type="button" onClick={() => move(selected.id, -1)} disabled={disabled || index === 0}>{es.moveBefore}</button>
          <button type="button" onClick={() => move(selected.id, 1)} disabled={disabled || index === chain.length - 1}>{es.moveAfter}</button>
          <button type="button" onClick={() => onChange(chain.map((s) => (s.id === selected.id ? { ...s, enabled: !s.enabled } : s)))} disabled={disabled}>
            {selected.enabled ? es.disableBox : es.enableBox}
          </button>
          <button type="button" className="danger" disabled={disabled} onClick={() => {
            const next = chain.filter((s) => s.id !== selected.id);
            onChange(next);
            onSelect(next[Math.min(index, next.length - 1)]?.id ?? "input");
          }}>{es.removeBox}</button>
        </div>
      )}

      <div className="row add-box">
        <label>
          {es.addBoxLabel}
          <select value={addValue} onChange={(e) => setAddValue(e.target.value)} disabled={disabled || chain.length >= MAX_STAGES}>
            <option value="">{es.addBoxPlaceholder}</option>
            <optgroup label={es.addGroupFilters}>
              {catalog.filters.map((f) => <option key={f.kind} value={f.kind}>{f.name}</option>)}
            </optgroup>
            {installed.length > 0 && (
              <optgroup label={es.addGroupModels}>
                {installed.map((m) => <option key={m.id} value={`model:${m.id}`}>{m.name}</option>)}
              </optgroup>
            )}
            {missing.length > 0 && (
              <optgroup label={es.addGroupMissing}>
                {missing.map((m) => <option key={m.id} value={`model:${m.id}`} disabled>{m.name}</option>)}
              </optgroup>
            )}
          </select>
        </label>
        <button type="button" onClick={add} disabled={disabled || !addValue || chain.length >= MAX_STAGES}>{es.addBoxButton}</button>
        {chain.length >= MAX_STAGES && <span className="hint">{es.chainLimit(MAX_STAGES)}</span>}
      </div>
    </section>
  );
}
