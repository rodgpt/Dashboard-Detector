/**
 * Un clip: audio y espectrograma. El destino de `?play=` (R-8.5).
 *
 * Enlaces de este tipo se comparten por WhatsApp, así que quien lo abre puede
 * no tener sesión, puede no tener permiso sobre ese sitio, o el clip puede no
 * existir porque la subida falló después de mandar el aviso (F-13). Los tres
 * casos se dicen distinto:
 *
 *   sin sesión      -> al acceso, y de vuelta aquí después
 *   403             -> no tienes permiso sobre este sitio. No es un error tuyo
 *   404             -> el aviso se envió pero el audio nunca llegó a subirse
 *
 * Un enlace roto que dice "no existe" sin explicar cuál de las tres cosas pasó
 * hace que quien lo recibió piense que se lo inventaron.
 */
import { useSearchParams } from "react-router-dom";
import Panel from "@/components/Panel";
import Spectrogram from "@/components/Spectrogram";
import { useResource } from "@/hooks/useResource";
import { data, type DetectionEvent, type Page } from "@/api/client";
import { formatDateTime } from "@/lib/time";

export default function ClipDetail({ siteId }: { siteId: string }) {
  const [params] = useSearchParams();
  const play = params.get("play");

  // Se busca el evento por su clip para poder mostrar contexto — hora de
  // captura, tipo, puntaje — en vez de un reproductor suelto sin explicación.
  const events = useResource<Page<DetectionEvent>>(
    () => data.events(siteId, { since: new Date(Date.now() - 365 * 86_400_000), limit: 500 }),
    [siteId, play], { enabled: !!play });

  if (!play) return null;

  const match = events.data?.items.find(
    (e) => e.clip?.path === play || e.clip?.path?.endsWith(play) || e.event_id === play);
  const clipPath = match?.clip?.path ?? play;
  const url = data.clipUrl(siteId, clipPath);

  return (
    <Panel
      title="Clip"
      resource={events}
      emptyMessage="No se pudo buscar el evento de este clip."
    >
      {() => (
        <>
          {match ? (
            <p className="panel-note">
              {formatDateTime(match.captured_utc)} · {match.event_type} ·
              detector {match.detector || "—"} ·
              puntaje {match.score ?? "sin dato"}
              {match.suppressed && " · suprimida"}
            </p>
          ) : (
            <p className="panel-note">
              No se encontró el evento de <code>{play}</code> en el último año.
              El audio puede seguir existiendo; se intenta reproducir igual.
            </p>
          )}

          {match?.suppressed ? (
            <div className="banner error" role="alert">
              Esta detección fue suprimida por la pausa entre avisos. Es real y
              está registrada, pero su audio nunca se guardó (D-008), así que no
              hay nada que reproducir.
            </div>
          ) : match && !match.clip?.uploaded ? (
            <div className="banner error" role="alert">
              El aviso se envió pero la subida del audio falló, así que este clip
              no existe en el almacenamiento (F-13). No es un enlace roto: es una
              subida que no ocurrió.
            </div>
          ) : (
            <>
              <audio controls preload="metadata" className="clip-player wide" src={url}>
                Tu navegador no reproduce audio.
              </audio>
              <h3 className="section-head">Espectrograma</h3>
              <Spectrogram url={url} label={clipPath} />
            </>
          )}
        </>
      )}
    </Panel>
  );
}
