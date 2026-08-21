/**
 * Placeholder. The five client views — detecciones, monitoreo acústico,
 * condiciones del mar, análisis y estado del sensor — are Phase 2, rebuilt as
 * pages against the API. See docs/PROGRESS.md.
 *
 * This deliberately does not render the old monolith: `web/static/index.html`
 * fetched public blob storage straight from the browser, which is the thing the
 * backend exists to stop (D-019).
 */
import AppHeader from "@/components/AppHeader";

const VIEWS = [
  ["Detecciones", "eventos paginados, con filtros y audio"],
  ["Monitoreo acústico", "indicadores por clip y espectrograma"],
  ["Condiciones del mar", "oleaje, viento y pronóstico"],
  ["Análisis", "series y agregados"],
  ["Estado del sensor", "salud, energía, red y sistema"],
];

export default function Dashboard() {
  return (
    <div className="app-shell">
      <AppHeader title="Monitor acústico" subtitle="Panel principal" />

      <section className="panel">
        <h2>Vistas en construcción</h2>
        <p className="panel-note">
          Las cinco vistas se están reconstruyendo sobre la API en la Fase 2.
          Hasta entonces esta página no muestra datos: mostrar datos viejos como
          si fueran actuales es exactamente el fallo que este sistema existe para
          evitar.
        </p>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr><th scope="col">Vista</th><th scope="col">Contenido</th><th scope="col">Estado</th></tr>
            </thead>
            <tbody>
              {VIEWS.map(([name, what]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td>{what}</td>
                  <td><span className="chip none">pendiente</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
