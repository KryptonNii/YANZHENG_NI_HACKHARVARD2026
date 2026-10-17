import { useTranslation, translate as t } from "@/app/i18n";
import { useMemo, useState } from "react";
import { geoEqualEarth, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import type { FeatureCollection, Geometry } from "geojson";
import type { GeometryCollection, Topology } from "topojson-specification";
import world from "world-atlas/countries-110m.json";
import type { Site } from "@/app/contracts";

// Offline SVG map (no tile server, works with DEMO_OFFLINE): Natural Earth 1:110m via world-atlas.
const topo = world as unknown as Topology<{ countries: GeometryCollection }>;
const countries = feature(topo, topo.objects.countries) as unknown as FeatureCollection<Geometry>;

const W = 640;
const H = 340;

export function SiteMap({
  sites,
  excluded = [],
  onToggle,
  height = H,
}: {
  sites: Site[];
  excluded?: string[];
  onToggle?: (siteId: string) => void;
  height?: number;
}) {
  useTranslation();
  const [hover, setHover] = useState<string | null>(null);
  const located = useMemo(() => sites.filter((s) => s.lat !== null && s.lon !== null), [sites]);
  const unlocated = sites.length - located.length;

  const { path, project } = useMemo(() => {
    const projection = geoEqualEarth();
    if (located.length > 0) {
      // fit to the sites with a margin so a single-country trial is not a dot cluster
      const lons = located.map((s) => s.lon as number);
      const lats = located.map((s) => s.lat as number);
      const pad = 8;
      const [minLon, maxLon] = [Math.max(Math.min(...lons) - pad, -180), Math.min(Math.max(...lons) + pad, 180)];
      const [minLat, maxLat] = [Math.max(Math.min(...lats) - pad, -85), Math.min(Math.max(...lats) + pad, 85)];
      projection.fitExtent(
        [
          [12, 12],
          [W - 12, height - 12],
        ],
        {
          type: "Feature",
          properties: {},
          geometry: {
            type: "MultiPoint",
            coordinates: [
              [minLon, minLat],
              [maxLon, maxLat],
              [minLon, maxLat],
              [maxLon, minLat],
            ],
          },
        },
      );
    } else {
      projection.fitSize([W, height], countries);
    }
    return { path: geoPath(projection), project: (s: Site) => projection([s.lon as number, s.lat as number]) };
  }, [located, height]);

  const hovered = located.find((s) => s.id === hover);

  return (
    <figure className="relative" data-testid="site-map">
      <svg viewBox={`0 0 ${W} ${height}`} className="w-full rounded-lg bg-[#eef4f7]" role="group" aria-label={t(`Map of ${located.length} trial sites`, `${located.length} 个试验研究中心的地图`)}>
        <g>
          {countries.features.map((f, i) => (
            <path key={i} d={path(f) ?? undefined} fill="#dbe3ea" stroke="#ffffff" strokeWidth={0.6} />
          ))}
        </g>
        <g>
          {located.map((s) => {
            const p = project(s);
            if (!p) return null;
            const isExcluded = excluded.includes(s.id);
            const label = `${s.name}${s.city ? `, ${s.city}` : ""}, ${s.country} — ${isExcluded ? t("excluded", "已排除") : t("included", "已纳入")}`;
            return (
              <g
                key={s.id}
                transform={`translate(${p[0]},${p[1]})`}
                role={onToggle ? "button" : "img"}
                tabIndex={onToggle ? 0 : undefined}
                aria-label={onToggle ? t(`${label}. Press to ${isExcluded ? "include" : "exclude"}.`, `${label}。按下以${isExcluded ? "纳入" : "排除"}。`) : label}
                aria-pressed={onToggle ? !isExcluded : undefined}
                onClick={onToggle ? () => onToggle(s.id) : undefined}
                onKeyDown={
                  onToggle
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onToggle(s.id);
                        }
                      }
                    : undefined
                }
                onMouseEnter={() => setHover(s.id)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(s.id)}
                onBlur={() => setHover(null)}
                className={onToggle ? "cursor-pointer outline-none" : undefined}
              >
                <circle r={9} fill="transparent" />
                {isExcluded ? (
                  <>
                    <circle r={4.5} fill="#ffffff" stroke="#64748b" strokeWidth={1.5} />
                    <path d="M-2.5,-2.5L2.5,2.5M2.5,-2.5L-2.5,2.5" stroke="#64748b" strokeWidth={1.3} />
                  </>
                ) : (
                  <circle r={4.5} fill="#0f766e" stroke="#ffffff" strokeWidth={1.2} />
                )}
                {hover === s.id && <circle r={8} fill="none" stroke="#0f766e" strokeWidth={1.5} />}
              </g>
            );
          })}
        </g>
      </svg>
      {hovered && (
        <div className="pointer-events-none absolute left-2 top-2 max-w-[18rem] rounded-md border border-ink-200 bg-white/95 px-2.5 py-1.5 text-xs shadow-card">
          <p className="font-semibold text-ink-900">{hovered.name}</p>
          <p className="text-ink-600">
            {[hovered.city, hovered.country].filter(Boolean).join(", ")}
            {excluded.includes(hovered.id) ? t(" · excluded", " · 已排除") : ""}
          </p>
        </div>
      )}
      <figcaption className="mt-1.5 flex flex-wrap items-center justify-between gap-2 text-[11px] text-ink-500">
        <span className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <svg width="10" height="10" aria-hidden>
              <circle cx="5" cy="5" r="4" fill="#0f766e" />
            </svg>
            {t("included", "已纳入")}
          </span>
          {excluded.length > 0 && (
            <span className="flex items-center gap-1">
              <svg width="10" height="10" aria-hidden>
                <circle cx="5" cy="5" r="3.8" fill="#fff" stroke="#64748b" strokeWidth="1.3" />
              </svg>
              {t("excluded", "已排除")}
            </span>
          )}
          {unlocated > 0 && <span>{t(`${unlocated} site${unlocated === 1 ? "" : "s"} without coordinates not shown`, `${unlocated} 个无坐标的研究中心未显示`)}</span>}
        </span>
        <span>{t("Map data: Natural Earth (public domain) via world-atlas", "地图数据：Natural Earth（公共领域），由 world-atlas 提供")}</span>
      </figcaption>
    </figure>
  );
}
