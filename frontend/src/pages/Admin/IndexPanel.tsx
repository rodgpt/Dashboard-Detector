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
 */
import { useCallback, useEffect, useState } from "react";
import { admin, ApiError, type IndexSite } from "@/api/client";
import { formatDateTime, timeAgo } from "@/lib/time";

export default function IndexPanel() {
  const [rows, setRows] = useState<IndexSite[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await admin.index());
      setError(null);
    } catch (e) {
      // Una falla al leer la deriva se muestra: no saber si hay deriva no es lo
      // mismo que no tenerla.
      setError(e instanceof ApiError ? e.message : "no se pudo leer el estado del índice");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function reconcile(siteId: string) {
    setBusy(siteId); setNotice(null);
    try {
      const [r] = await admin.reconcile(siteId);
      setNotice(r.ok
        ? `${siteId}: ${r.newly_indexed} evento(s) indexado(s), sin deriva.`
        : `${siteId}: deriva ${r.drift}, ${r.conflicting} en conflicto, ${r.rejected} rechazado(s)`
          + (r.error ? ` — ${r.error}` : ""));
      await load();
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "la reconciliación falló");
    } finally { setBusy(null); }
  }

  async function rebuild(siteId: string) {
    // Confirmación explícita: esto borra filas a propósito, y una acción
    // destructiva sin confirmar es una que alguien ejecuta por accidente.
    if (!window.confirm(
      `Reconstruir el índice de "${siteId}".\n\n`
      + "Se borran sus filas y se vuelven a leer desde el almacenamiento. No se "
      + "pierde ninguna detección: el almacenamiento es el registro. Sirve para "
      + "comprobar que el índice es realmente derivado.")) return;
    setBusy(siteId); setNotice(null);
    try {
      const r = await admin.rebuildIndex(siteId);
      setNotice(`${siteId}: reconstruido, ${r.newly_indexed} evento(s), deriva ${r.drift}.`);
      await load();
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "la reconstrucción falló");
    } finally { setBusy(null); }
  }

  if (error) return <p className="form-feedback error">Índice: {error}</p>;
  if (!rows) return <div className="loading">Cargando estado del índice…</div>;

  return (
    <section className="panel">
      <h2>Índice de detecciones</h2>
      <p className="panel-note">
        El almacenamiento es el registro; el índice es una copia consultable y se
        puede reconstruir. Deriva distinta de cero significa que hay eventos
        guardados que el panel no está mostrando.
      </p>

      {notice && <p className="form-feedback ok">{notice}</p>}

      <div className="table-wrap"><table className="data">
        <thead>
          <tr>
            <th>Sitio</th><th>Ventana</th><th>Blobs</th><th>Indexados</th>
            <th>Deriva</th><th>Última pasada</th><th></th>
          </tr>
        </thead>
        <tbody>
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
                {r.last_run_utc === null ? (
                  // Nunca verificado no es lo mismo que verificado y limpio.
                  <span className="idx-never">nunca</span>
                ) : (
                  <span title={formatDateTime(r.last_run_utc)}>
                    {timeAgo(r.last_run_utc)}
                    {r.last_run_trigger === "manual" && <span className="hint"> (manual)</span>}
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

      {rows.every((r) => r.last_run_utc === null) && (
        <p className="form-feedback error">
          La pasada de reconciliación no ha corrido todavía. Corre sola cada 24 h;
          si esto sigue diciendo «nunca» mañana, el temporizador no está activo.
        </p>
      )}
    </section>
  );
}
