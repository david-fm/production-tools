import { Fragment } from "react";
import { stageName, stageSummary, isActive, type StageCatalog } from "../catalog";
import { es } from "../i18n/es";
import type { Stage } from "../settings";

/** La cadena activa en solo lectura, para saber qué se está escuchando sin salir de la pestaña Audio. */
export function ChainStrip({ chain, catalog, onEdit }: { chain: Stage[]; catalog: StageCatalog; onEdit: () => void }) {
  const active = chain.filter(isActive);
  return (
    <div className="chain-strip" role="group" aria-label={es.chainSummary}>
      <ol className="strip">
        <li>{es.boxInput}</li>
        {active.map((s) => (
          <Fragment key={s.id}>
            <li className="sep" aria-hidden="true">→</li>
            <li>{stageName(s, catalog)} <small>{stageSummary(s, catalog)}</small></li>
          </Fragment>
        ))}
        <li className="sep" aria-hidden="true">→</li>
        <li>{es.boxVolume}</li>
        <li className="sep" aria-hidden="true">→</li>
        <li>{es.boxOutput}</li>
      </ol>
      {active.length === 0 && <span className="hint">{es.chainSummaryEmpty}</span>}
      <button type="button" onClick={onEdit}>{es.editChain}</button>
    </div>
  );
}
