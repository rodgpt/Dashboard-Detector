import type { Site } from "@/api/client";

/**
 * Sites come from the API, filtered by permission, never from a hardcoded table
 * (R-3.1). An operator with one site still sees the picker — hiding it would
 * make a one-site account look like a different product from a two-site one.
 */
export default function SitePicker({ sites, value, onChange }: {
  sites: Site[];
  value: string | null;
  onChange: (siteId: string) => void;
}) {
  if (sites.length === 0) {
    return (
      <span className="chip none">sin sitios asignados</span>
    );
  }
  return (
    <label className="site-picker">
      <span className="site-picker-label">Sitio</span>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {sites.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name || s.id}{s.active === false ? " (inactivo)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
