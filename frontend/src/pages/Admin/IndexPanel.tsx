/**
 * Deriva del índice de detecciones (R-12.5).
 *
 * El índice es *derivado*: el almacenamiento es el registro y esta tabla es una
 * copia consultable. Un índice que se salta eventos en silencio produce un panel
 * que se ve perfectamente sano mientras reporta de menos — la misma falla que un
 * equipo que se reporta sano estando sordo. Por eso la deriva es una pantalla y
 * no una línea de log.
 *
 * Dos números, y hacen falta los dos:
 *  - **deriva**: blobs en almacenamiento sin fila en el índice. Distinto de cero
 *    es una falla, no una estadística.
 *  - **última pasada**: deriva cero que nunca se verificó no es evidencia de
 *    nada. Sin esto, "la reconciliación lleva una semana fallando" se ve igual
 *    que "la reconciliación no encuentra nada".
 *
 * Carga con `useResource` + `Panel` como todo lo demás: antes un error borraba
 * el panel entero sin reintento y la tabla nunca se refrescaba (review FE-05c).
 */
import { useState } from "react";
import Panel from "@/components/Panel";
import { admin, ApiError, type IndexSite } from "@/api/client";
import { useResource } from "@/hooks/useResource";
import { formatDateTime, timeAgo } from "@/lib/time";

const TRIGGER_LABEL: Record<string, string> = {
  manual: "manual", rebuild: "reconstrucción", scheduled: "programada",
};

export default function IndexPanel() {
  const index = useResource<IndexSite[]>(() => admin.index(), [], { pollMs: 60_000 });
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function reconcile(siteId: string) {
    setBusy(siteId); setNotice(null);
    try {
      const [r] = await admin.reconcile(siteId);
      if (!r) { setNotice(`${siteId}: la pasada no devolvió ningún resultado.`); return; }
      setNotice(r.ok
        ? `${siteId}: ${r.newly_indexed} evento(s) indexado(s), sin deriva.`
        : `${siteId}: deriva ${r.drift}, ${r.conflicting} en conflicto, ${r.rejected} rechazado(s)`
          + (r.error ? ` — ${r.error}` : ""));
      index.reload();
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "la reconciliación falló");
    } finally { setBusy(null); }
  }

  async function rebuild(siteId: string) {
    // Confirmación explícita: esto borra filas a propósito, y una acción
    // destructiva sin confirmar es una que alguien ejecuta por accidente.
    if (!window.confirm(
      `Reconstruir el índice de "${siteId}".\n\n`
      + "Se borran sus filas y se vuelven a leer desde el almacenamiento, toda la "
      + "historia. No se pierde ninguna detección: el almacenamiento es el registro. "
      + "Sirve para comprobar que el índice es realmente derivado.")) return;
    setBusy(siteId); setNotice(null);
    try {
      const r = await admin.rebuildIndex(siteId);
      setNotice(`${siteId}: reconstruido, ${r.newly_indexed} evento(s), deriva ${r.drift}.`);
      index.reload();
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "la reconstrucción falló");
    } finally { setBusy(null); }
  }

  return (
    <Panel title="Índice de detecciones" resource={index}>
      {(rows) => (
        <>
          <p className="panel-note">
            El almacenamiento es el registro; el índice es una copia consultable y se
            puede reconstruir. Deriva distinta de cero significa que hay eventos
            guardados que el panel no está mostrando.
          </p>

          {notice && <p className="form-feedback ok" role="status">{notice}</p>}

          <div className="table-wrap"><table className="data">
            <thead>
              <tr>
                <th scope="col">Sitio</th><th scope="col">Ventana</th><th scope="col">Blobs</th>
                <th scope="col">Indexados</th><th scope="col">Deriva</th>
                <th scope="col">Última pasada</th><th scope="col">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={7} className="loading">Sin sitios registrados; nada que indexar.</td></tr>
              )}
              {rows.map((r) => (
                <tr key={r.site_id} className={r.drift !== 0 ? "row-warn" : undefined}>
                  <td>{r.site_id}</td>
                  <td className="hint">{r.window_days} d</td>
                  <td>{r.blobs_in_storage}</td>
                  <td>{r.indexed}</td>
                  <td>
                    {r.drift === 0
                      ? <span className="idx-ok">0</span>
                      : <strong className="idx-bad" title={
                          r.days_with_drift.map((d) => `${d.day}: ${d.drift}`).join("\n")}>
                          {r.drift} sin indexar
                        </strong>}
                  </td>
                  <td>
                    {r.last_run_utc == null ? (
                      // Nunca verificado no es lo mismo que verificado y limpio.
                      <span className="idx-never">nunca</span>
                    ) : (
                      <span title={formatDateTime(r.last_run_utc)}>
                        {timeAgo(r.last_run_utc)}
                        {r.last_run_trigger && r.last_run_trigger !== "scheduled" && (
                          <span className="hint"> ({TRIGGER_LABEL[r.last_run_trigger] ?? r.last_run_trigger})</span>
                        )}
                        {r.last_run_ok === false && (
                          <strong className="idx-bad" title={r.last_run_error ?? undefined}> · falló</strong>
                        )}
                      </span>
                    )}
                  </td>
                  <td className="actions">
                    <button type="button" className="btn btn-ghost btn-sm" disabled={busy === r.site_id}
                            onClick={() => void reconcile(r.site_id)}>
                      Reconciliar
                    </button>
                    <button type="button" className="btn btn-danger btn-sm" disabled={busy === r.site_id}
                            onClick={() => void rebuild(r.site_id)}>
                      Reconstruir
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>

          {rows.length > 0 && rows.every((r) => r.last_run_utc == null) && (
            <p className="form-feedback error">
              La pasada de reconciliación no ha corrido todavía. Corre sola cada 24 h;
              si esto sigue diciendo «nunca» mañana, el temporizador no está activo.
            </p>
          )}
        </>
      )}
    </Panel>
  );
}
