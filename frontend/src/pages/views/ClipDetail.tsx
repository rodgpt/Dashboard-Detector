/**
 * Un clip: audio y espectrograma. El destino de `?play=` (R-8.5).
 *
 * Enlaces de este tipo se comparten por WhatsApp, así que quien lo abre puede
 * no tener sesión, puede no tener permiso sobre ese sitio, o el clip puede no
 * existir porque la subida falló después de mandar el aviso (F-13). Los tres
 * casos se dicen distinto:
 *
 *   sin sesión      -> al acceso, y de vuelta aquí después (App.tsx conserva ?play=)
 *   403             -> no tienes permiso sobre este sitio. No es un error tuyo
 *   404             -> el aviso se envió pero el audio nunca llegó a subirse
 *
 * Un enlace roto que dice "no existe" sin explicar cuál de las tres cosas pasó
 * hace que quien lo recibió piense que se lo inventaron.
 *
 * El evento se busca por su id, que viene en el nombre del clip. Antes se
 * recorría una página de 500 eventos del último año y cualquier clip más viejo
 * que los 500 más recientes aparecía como "no encontrado" (review FE-03).
 */
import { Suspense, lazy } from "react";
import { useSearchParams } from "react-router-dom";
import Panel from "@/components/Panel";
import { useResource } from "@/hooks/useResource";
import { data, type DetectionEvent } from "@/api/client";
import { typeLabel } from "@/lib/labels";
import { formatDateTime } from "@/lib/time";

// FFT y canvas sólo cuando hay un clip que mostrar: no pesan en la carga inicial.
const Spectrogram = lazy(() => import("@/components/Spectrogram"));

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

export default function ClipDetail({ siteId }: { siteId: string }) {
  const [params] = useSearchParams();
  const play = params.get("play");
  const eventId = play ? (UUID.exec(play)?.[0]?.toLowerCase() ?? null) : null;

  const event = useResource<DetectionEvent>(
    () => data.event(siteId, eventId!), [siteId, eventId], { enabled: !!eventId });

  if (!play) return null;

  const clipPath = event.data?.clip?.path ?? play;
  const url = data.clipUrl(siteId, clipPath);

  // Sin id en el enlace, o sin fila en el índice (404): no hay contexto de
  // captura, pero el audio puede existir igual (índice atrasado, subida
  // directa). Se ofrece reproducir y se dice por qué no hay más.
  if (!eventId || event.error?.status === 404) {
    return (
      <section className="panel">
        <div className="panel-head"><h2>Clip</h2></div>
        <p className="panel-note">
          {eventId
            ? `El evento ${eventId} no está en el índice de este sitio.`
            : "El enlace no trae un identificador de evento reconocible."}{" "}
          Sin contexto de captura; se intenta reproducir el audio igual.
        </p>
        <Player url={url} label={clipPath} />
      </section>
    );
  }

  return (
    <Panel title="Clip" resource={event}>
      {(ev) => (
        <>
          <p className="panel-note">
            {formatDateTime(ev.captured_utc)} · {typeLabel(ev.event_type)} ·
            detector {ev.detector || "—"} ·
            puntaje {ev.score ?? "sin dato"}
            {ev.suppressed && " · suprimida"}
          </p>

          {ev.suppressed ? (
            <div className="banner error" role="alert">
              Esta detección fue suprimida por la pausa entre avisos. Es real y
              está registrada, pero su audio nunca se guardó (D-008), así que no
              hay nada que reproducir.
            </div>
          ) : !ev.clip?.uploaded ? (
            <div className="banner error" role="alert">
              El aviso se envió pero la subida del audio falló, así que este clip
              no existe en el almacenamiento (F-13). No es un enlace roto: es una
              subida que no ocurrió.
            </div>
          ) : (
            <Player url={url} label={clipPath} />
          )}
        </>
      )}
    </Panel>
  );
}

function Player({ url, label }: { url: string; label: string }) {
  return (
    <>
      <audio controls preload="metadata" className="clip-player wide" src={url}>
        Tu navegador no reproduce audio.
      </audio>
      <h3 className="section-head">Espectrograma</h3>
      <Suspense fallback={<p className="loading">Cargando el analizador…</p>}>
        <Spectrogram url={url} label={label} />
      </Suspense>
    </>
  );
}
