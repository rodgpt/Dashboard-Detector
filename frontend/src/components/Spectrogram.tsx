/**
 * Espectrograma de un clip.
 *
 * El audio se descarga por la API (nunca desde el almacenamiento: el navegador
 * no tiene credencial, R-5.4), se decodifica con WebAudio y se transforma con
 * una FFT propia. No hay dependencia nueva: una FFT radix-2 son cuarenta líneas
 * y evita traer una librería entera para esto.
 *
 * Dos cosas que el original no hacía y aquí sí:
 *  - **Alternativa textual.** Un canvas sin texto es invisible para quien usa
 *    lector de pantalla, y este canvas es el único sitio donde se ve la forma
 *    del evento (A11y, R-8.8).
 *  - **Fallar visible.** Si el clip no está, o el navegador no decodifica el
 *    WAV, lo dice. No deja un rectángulo negro que se lee como "silencio".
 */
import { useEffect, useRef, useState } from "react";

const FFT_SIZE = 512;          // 256 bandas
const HOP = 256;               // 50 % de solape
const MAX_SECONDS = 30;        // un clip largo no debe colgar la pestaña

/** FFT radix-2 in-place, iterativa. re/im se modifican. */
function fft(re: Float32Array, im: Float32Array): void {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j]!, re[i]!];
      [im[i], im[j]] = [im[j]!, im[i]!];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    const wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const ur = re[i + k]!, ui = im[i + k]!;
        const vr = re[i + k + len / 2]! * cr - im[i + k + len / 2]! * ci;
        const vi = re[i + k + len / 2]! * ci + im[i + k + len / 2]! * cr;
        re[i + k] = ur + vr; im[i + k] = ui + vi;
        re[i + k + len / 2] = ur - vr; im[i + k + len / 2] = ui - vi;
        const ncr = cr * wr - ci * wi;
        ci = cr * wi + ci * wr; cr = ncr;
      }
    }
  }
}

interface Summary { peakHz: number; peakDb: number; bands: number; frames: number; seconds: number }

export default function Spectrogram({ url, label }: { url: string; label: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [summary, setSummary] = useState<Summary | null>(null);

  useEffect(() => {
    let cancelled = false;
    setBusy(true); setError(null); setSummary(null);

    (async () => {
      let ctx: AudioContext | null = null;
      try {
        const res = await fetch(url, { credentials: "same-origin" });
        if (!res.ok) {
          throw new Error(res.status === 404
            ? "el clip no está en el almacenamiento"
            : `no se pudo descargar el audio (${res.status})`);
        }
        const bytes = await res.arrayBuffer();
        ctx = new AudioContext();
        const buf = await ctx.decodeAudioData(bytes);
        if (cancelled) return;

        const rate = buf.sampleRate;
        const pcm = buf.getChannelData(0).slice(0, Math.floor(rate * MAX_SECONDS));
        const frames = Math.max(1, Math.floor((pcm.length - FFT_SIZE) / HOP));
        const bands = FFT_SIZE / 2;

        // Hann, para que los bordes de cada ventana no inventen frecuencias.
        const win = new Float32Array(FFT_SIZE);
        for (let i = 0; i < FFT_SIZE; i++) win[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (FFT_SIZE - 1)));

        const mags = new Float32Array(frames * bands);
        let peak = -Infinity, peakBand = 0;
        const re = new Float32Array(FFT_SIZE), im = new Float32Array(FFT_SIZE);

        for (let f = 0; f < frames; f++) {
          const off = f * HOP;
          for (let i = 0; i < FFT_SIZE; i++) { re[i] = (pcm[off + i] ?? 0) * win[i]!; im[i] = 0; }
          fft(re, im);
          for (let b = 0; b < bands; b++) {
            const m = Math.hypot(re[b]!, im[b]!);
            const db = 20 * Math.log10(m + 1e-9);
            mags[f * bands + b] = db;
            if (db > peak) { peak = db; peakBand = b; }
          }
        }
        if (cancelled) return;

        const canvas = canvasRef.current;
        if (canvas) {
          canvas.width = frames; canvas.height = bands;
          const g = canvas.getContext("2d");
          if (g) {
            const img = g.createImageData(frames, bands);
            const floor = peak - 70;                   // 70 dB de rango dinámico
            for (let f = 0; f < frames; f++) {
              for (let b = 0; b < bands; b++) {
                const v = Math.max(0, Math.min(1, (mags[f * bands + b]! - floor) / (peak - floor)));
                // Azul profundo -> marca. Misma familia que el tema.
                const px = ((bands - 1 - b) * frames + f) * 4;
                img.data[px] = Math.round(12 + v * 88);
                img.data[px + 1] = Math.round(34 + v * 143);
                img.data[px + 2] = Math.round(48 + v * 149);
                img.data[px + 3] = 255;
              }
            }
            g.putImageData(img, 0, 0);
          }
        }

        setSummary({
          peakHz: Math.round((peakBand * rate) / FFT_SIZE),
          peakDb: +peak.toFixed(1),
          bands, frames, seconds: +(pcm.length / rate).toFixed(1),
        });
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "no se pudo analizar el audio");
      } finally {
        void ctx?.close();
        if (!cancelled) setBusy(false);
      }
    })();

    return () => { cancelled = true; };
  }, [url]);

  if (busy) return <p className="loading">Analizando audio…</p>;

  if (error) {
    return (
      <div className="banner error" role="alert">
        No se pudo generar el espectrograma de {label}: {error}.
      </div>
    );
  }

  return (
    <>
      <canvas ref={canvasRef} className="spectrogram"
              role="img"
              aria-label={summary
                ? `Espectrograma de ${label}. ${summary.seconds} segundos, ${summary.bands} bandas. Pico en ${summary.peakHz} hercios a ${summary.peakDb} decibelios.`
                : `Espectrograma de ${label}`} />
      {summary && (
        <p className="chart-note">
          {summary.seconds} s · {summary.frames} ventanas · {summary.bands} bandas ·
          pico en <strong>{summary.peakHz} Hz</strong> ({summary.peakDb} dB).
          El eje vertical es frecuencia, el horizontal tiempo. Rango dinámico 70 dB
          bajo el pico.
        </p>
      )}
    </>
  );
}
