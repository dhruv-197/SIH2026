import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import { api } from "../lib/api";
import { fmtUtc } from "../lib/format";
import { CLASS_META, CONTEXT_CATEGORY_META, reviewLabel, subtypeLabel } from "../lib/taxonomy";
import type { DetectionSummary, Facility, ThermalSource } from "../lib/types";
import { escapeHtml } from "./ui";

export type Basemap = "light" | "satellite" | "viirs";
export interface MapFocus {
  lat: number;
  lon: number;
  zoom: number;
  key: string;
  bounds?: [[number, number], [number, number]];
}

interface Props {
  detections: DetectionSummary[];
  sources: ThermalSource[];
  facilities: Facility[];
  layers: { sources: boolean; facilities: boolean; osm: boolean };
  basemap: Basemap;
  imageryDate?: string;
  focus: MapFocus | null;
  selectedId: string | null;
  regionBox?: [number, number, number, number] | null;
  onSelectDetection: (id: string) => void;
  onSelectSource?: (id: number) => void;
  onSelectFacility?: (id: string) => void;
}

const OSM_MIN_ZOOM = 8;
const INK = "#0f172a";
const CRITICAL = "#c0262d";
const HIGH = "#c2410c";

function tileLayer(basemap: Basemap, date?: string): L.TileLayer {
  if (basemap === "satellite") {
    return L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 19,
      attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
    });
  }
  if (basemap === "viirs" && date) {
    return L.tileLayer(
      `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/${date}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`,
      { maxZoom: 9, maxNativeZoom: 9, attribution: `NASA GIBS · VIIRS Suomi NPP true colour ${date}` },
    );
  }
  return L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    maxZoom: 19,
    subdomains: "abcd",
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>',
  });
}

/** The Leaflet map. Filters, legend, layer menu and detection list are drawn over it by the Map page. */
export function MapView(props: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const rendererRef = useRef<L.Canvas | null>(null);
  const baseRef = useRef<L.TileLayer | null>(null);
  const regionLayer = useRef<L.LayerGroup | null>(null);
  const detectionLayer = useRef<L.LayerGroup | null>(null);
  const sourceLayer = useRef<L.LayerGroup | null>(null);
  const facilityLayer = useRef<L.LayerGroup | null>(null);
  const osmLayer = useRef<L.LayerGroup | null>(null);
  const selectedLayer = useRef<L.LayerGroup | null>(null);
  const handlers = useRef(props);
  const [osmStatus, setOsmStatus] = useState<string | null>(null);

  useEffect(() => {
    handlers.current = props;
  });

  // Create the map once. The zoom buttons sit top right, clear of the filter card.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { center: [22.8, 80.5], zoom: 5, preferCanvas: true, zoomControl: false });
    L.control.zoom({ position: "topright" }).addTo(map);
    rendererRef.current = L.canvas({ padding: 0.5 });
    regionLayer.current = L.layerGroup().addTo(map);
    osmLayer.current = L.layerGroup().addTo(map);
    facilityLayer.current = L.layerGroup().addTo(map);
    sourceLayer.current = L.layerGroup().addTo(map);
    detectionLayer.current = L.layerGroup().addTo(map);
    selectedLayer.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (baseRef.current) map.removeLayer(baseRef.current);
    baseRef.current = tileLayer(props.basemap, props.imageryDate).addTo(map);
    baseRef.current.bringToBack();
  }, [props.basemap, props.imageryDate]);

  const regionKey = props.regionBox ? props.regionBox.join(",") : "";
  useEffect(() => {
    const layer = regionLayer.current;
    if (!layer) return;
    layer.clearLayers();
    if (!regionKey) return;
    const [west, south, east, north] = regionKey.split(",").map(Number);
    L.rectangle(
      [
        [south, west],
        [north, east],
      ],
      { color: "#2453c9", weight: 1.8, dashArray: "6 4", fill: false, interactive: false },
    ).addTo(layer);
  }, [regionKey]);

  useEffect(() => {
    const layer = detectionLayer.current;
    const renderer = rendererRef.current;
    if (!layer || !renderer) return;
    layer.clearLayers();
    for (const d of props.detections) {
      const meta = CLASS_META[d.class_code];
      const critical = d.severity === "CRITICAL";
      const high = d.severity === "HIGH";
      const marker = L.circleMarker([d.latitude, d.longitude], {
        renderer,
        radius: Math.max(4, Math.min(12, 3 + Math.sqrt(d.frp))),
        color: critical ? CRITICAL : high ? HIGH : "#ffffff",
        weight: critical || high ? 2.6 : 1,
        fillColor: meta?.color ?? "#64748b",
        fillOpacity: 0.9,
        dashArray: d.verification_required && !d.review_label ? "3 2" : undefined,
      });
      marker.bindTooltip(
        `<b>${escapeHtml(meta?.short)}</b>${d.verification_required && !d.review_label ? " · needs verification" : ""}<br/>` +
          `FRP ${d.frp.toFixed(1)} MW · ${fmtUtc(d.acq_datetime, false)}` +
          (d.severity !== "NORMAL" ? `<br/><b>${d.severity}</b>` : "") +
          (d.review_label ? `<br/>Analyst label: ${escapeHtml(reviewLabel(d.review_label))}` : "") +
          (d.place ? `<br/><span style="color:#64748b">${escapeHtml(d.place)}</span>` : ""),
        { direction: "top", sticky: true },
      );
      marker.on("click", () => handlers.current.onSelectDetection(d.detection_id));
      layer.addLayer(marker);
    }
  }, [props.detections]);

  useEffect(() => {
    const layer = sourceLayer.current;
    if (!layer) return;
    layer.clearLayers();
    if (!props.layers.sources) return;
    for (const s of props.sources) {
      const meta = CLASS_META[s.class_code];
      const ring = L.circle([s.latitude, s.longitude], {
        radius: Math.max(500, s.extent_km * 1000 + 300),
        color: meta?.color ?? "#333",
        weight: 1.8,
        fill: false,
        dashArray: s.verification_required ? "4 3" : undefined,
      });
      ring.bindTooltip(
        `<b>Persistent source</b> · ${escapeHtml(meta?.short)}<br/>${s.active_days} of ${s.observation_days} days · ${s.detection_count} detections<br/>median FRP ${s.frp_median.toFixed(1)} MW`,
        { direction: "top", sticky: true },
      );
      ring.on("click", () => handlers.current.onSelectSource?.(s.id));
      layer.addLayer(ring);
    }
  }, [props.sources, props.layers.sources]);

  useEffect(() => {
    const layer = facilityLayer.current;
    const renderer = rendererRef.current;
    if (!layer || !renderer) return;
    layer.clearLayers();
    if (!props.layers.facilities) return;
    for (const f of props.facilities) {
      const alert = f.status === "ALERT";
      const tooltip =
        `<b>${escapeHtml(f.name)}</b><br/>${escapeHtml(f.sector)} · ${f.detections} detections` +
        `<br/><span style="color:#64748b">${f.osm_element_id ? `OSM ${escapeHtml(f.osm_element_id)}` : "catalog location (not matched in OSM)"}</span>`;
      let shape: L.Layer;
      if (f.geometry) {
        shape = L.geoJSON(f.geometry as GeoJSON.GeoJsonObject, {
          style: { color: alert ? CRITICAL : INK, weight: alert ? 2.2 : 1.3, fillColor: INK, fillOpacity: 0.05, dashArray: "5 3" },
        });
      } else {
        shape = L.circleMarker([f.latitude, f.longitude], { renderer, radius: 6.5, color: alert ? CRITICAL : INK, weight: 2.2, fillColor: "#ffffff", fillOpacity: 1 });
      }
      (shape as L.Path).bindTooltip(tooltip, { direction: "top", sticky: true });
      shape.on("click", () => handlers.current.onSelectFacility?.(f.id));
      layer.addLayer(shape);
    }
  }, [props.facilities, props.layers.facilities]);

  // OpenStreetMap industrial features for the current view (only when zoomed in).
  useEffect(() => {
    const map = mapRef.current;
    const layer = osmLayer.current;
    const renderer = rendererRef.current;
    if (!map || !layer || !renderer) return;
    if (!props.layers.osm) {
      layer.clearLayers();
      setOsmStatus(null);
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    const load = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(async () => {
        if (map.getZoom() < OSM_MIN_ZOOM) {
          layer.clearLayers();
          setOsmStatus(`Zoom in to level ${OSM_MIN_ZOOM} to see mapped industrial features`);
          return;
        }
        const b = map.getBounds();
        setOsmStatus("Loading OpenStreetMap features…");
        try {
          const data = await api.osmFeatures(`${b.getWest().toFixed(4)},${b.getSouth().toFixed(4)},${b.getEast().toFixed(4)},${b.getNorth().toFixed(4)}`);
          if (cancelled) return;
          layer.clearLayers();
          L.geoJSON(data, {
            style: (feature) => {
              const color = CONTEXT_CATEGORY_META[feature?.properties?.category]?.color ?? "#555";
              return { color, weight: 1.2, fillColor: color, fillOpacity: 0.15 };
            },
            pointToLayer: (feature, latlng) => {
              const color = CONTEXT_CATEGORY_META[feature.properties?.category]?.color ?? "#555";
              return L.circleMarker(latlng, { renderer, radius: 3.5, color: "#fff", weight: 1, fillColor: color, fillOpacity: 0.95 });
            },
            onEachFeature: (feature, lyr) => {
              const p = feature.properties ?? {};
              (lyr as L.Path).bindTooltip(
                `<b>${escapeHtml(p.name ?? subtypeLabel(p.subtype))}</b><br/>${escapeHtml(subtypeLabel(p.subtype))} · ${escapeHtml(p.feature_id)}`,
                { sticky: true },
              );
            },
          }).addTo(layer);
          setOsmStatus(`${data.features.length} mapped features in view${data.truncated ? " (truncated)" : ""} · © OpenStreetMap contributors`);
        } catch {
          if (!cancelled) setOsmStatus("Could not load OpenStreetMap features");
        }
      }, 350);
    };
    load();
    map.on("moveend", load);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      map.off("moveend", load);
    };
  }, [props.layers.osm]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !props.focus) return;
    if (props.focus.bounds) map.fitBounds(props.focus.bounds, { padding: [24, 24] });
    else map.setView([props.focus.lat, props.focus.lon], props.focus.zoom, { animate: true });
    // Move the map only when a new focus target is set (its key changes), not whenever the parent re-renders.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [props.focus?.key]);

  useEffect(() => {
    const layer = selectedLayer.current;
    if (!layer) return;
    layer.clearLayers();
    const selected = props.detections.find((d) => d.detection_id === props.selectedId);
    if (selected) {
      L.circleMarker([selected.latitude, selected.longitude], { radius: 17, color: INK, weight: 2.4, fill: false, interactive: false }).addTo(layer);
    }
  }, [props.selectedId, props.detections]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
      {osmStatus && (
        <div className="pointer-events-none absolute left-1/2 top-[76px] z-[1000] max-w-[calc(100%-2rem)] -translate-x-1/2 rounded-full border border-line bg-panel/95 px-3.5 py-1.5 text-[13.5px] text-ink-2 shadow-float">
          {osmStatus}
        </div>
      )}
    </div>
  );
}
