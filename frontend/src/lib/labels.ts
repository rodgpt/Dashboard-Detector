/** Etiquetas compartidas por las vistas. Un tipo de evento se nombra igual en
 *  la tabla, en el detalle del clip y en el mapa — antes `ClipDetail` imprimía
 *  el valor crudo del contrato ("vessel") en una frase en español. */
import type { EventType } from "@/api/client";

export const TYPE_LABEL: Record<EventType, string> = {
  vessel: "embarcación", blast: "detonación", unknown: "desconocido",
};

/** Forma además de color (R-8.3, R-8.8). */
export const TYPE_MARK: Record<EventType, string> = { vessel: "▬", blast: "✦", unknown: "?" };

export function typeLabel(t: string | null | undefined): string {
  return t ? (TYPE_LABEL[t as EventType] ?? t) : "—";
}
