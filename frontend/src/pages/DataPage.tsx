import { useCallback, useEffect, useState } from "react";
import { Download, RefreshCw, Upload } from "lucide-react";
import type { PageProps } from "../App";
import { SignInHint } from "../components/Toasts";
import { Button, Callout, Field, KeyValues, Panel, Spinner, cx, inputClass } from "../components/ui";
import { api, downloadBlob, type IngestResult } from "../lib/api";
import { fmtInt, fmtNum, fmtUtc, timeAgo } from "../lib/format";
import { errorMessage, useApp } from "../lib/store";
import { DATA_SOURCE_LABELS } from "../lib/taxonomy";
import type { GisLayers, IngestionRun } from "../lib/types";

function GisPanel() {
  const { notify, summary } = useApp();
  const [info, setInfo] = useState<GisLayers | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api.gisLayers().then(setInfo).catch((e) => notify("error", errorMessage(e)));
  }, [notify, summary?.generated_at]);

  async function download(key: string, load: () => Promise<Blob>, filename: string) {
    setBusy(key);
    try {
      downloadBlob(await load(), filename);
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Panel
      title="GIS layer store"
      subtitle="Every analysis is also written to an OGC GeoPackage in WGS 84 that opens directly in QGIS, ArcGIS Pro or GDAL. Single layers download as GeoJSON."
      actions={
        <Button variant="primary" icon={Download} loading={busy === "geopackage"} onClick={() => download("geopackage", api.geopackage, "geothermal_sentinel.gpkg")}>
          Download GeoPackage
        </Button>
      }
      bodyClassName="p-0"
    >
      {!info ? (
        <Spinner label="Reading GIS layers" />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-[14px]">
              <thead className="bg-sunk text-left text-[12.5px] uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Layer</th>
                  <th className="px-2 py-2 font-medium">Geometry</th>
                  <th className="px-2 py-2 text-right font-medium">Features</th>
                  <th className="px-2 py-2 font-medium">Contents</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {info.layers.map((layer) => (
                  <tr key={layer.name}>
                    <td className="px-4 py-2">
                      <div className="font-medium text-ink">{layer.title}</div>
                      <code className="text-[13px] text-muted">{layer.name}</code>
                    </td>
                    <td className="px-2 py-2 text-ink-2">{layer.geometry_type.toLowerCase()}</td>
                    <td className="num px-2 py-2 text-right">{fmtInt(layer.features)}</td>
                    <td className="px-2 py-2 text-ink-2">{layer.description}</td>
                    <td className="px-4 py-2 text-right">
                      <Button size="sm" icon={Download} loading={busy === layer.name} disabled={layer.features === 0} onClick={() => download(layer.name, () => api.layerGeojson(layer.name), `${layer.name}.geojson`)}>
                        GeoJSON
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-line px-4 py-2.5 text-[13.5px] text-muted">
            {info.store.exists ? `Store: ${info.store.format}, ${fmtNum((info.store.size_bytes ?? 0) / 1048576, 1)} MB, updated ${fmtUtc(info.store.updated_at)}` : "The store is written after the next analysis"}
            {info.store.last_write?.error ? ` · last write failed: ${info.store.last_write.error}` : ""} · {info.crs} · open with {info.open_with}
          </div>
        </>
      )}
    </Panel>
  );
}

function IngestSummary({ result }: { result: IngestResult }) {
  return (
    <div className="mt-3 flex flex-col gap-2">
      <Callout tone={result.records_inserted > 0 ? "success" : "info"}>{result.message}</Callout>
      <KeyValues
        rows={[
          ["Rows received", fmtInt(result.records_received)],
          ["Valid", fmtInt(result.records_valid)],
          ["New detections stored", fmtInt(result.records_inserted)],
          ["Already stored", fmtInt(result.records_duplicate)],
          ["Outside India", fmtInt(result.records_outside_india)],
          ["Rejected", fmtInt(result.records_rejected)],
        ]}
      />
      {result.details?.landcover && (
        <div className="text-[13.5px] text-muted">
          Land cover fetched for {fmtInt(result.details.landcover.fetched)} new footprints
          {result.details.landcover.failed ? `, ${result.details.landcover.failed} not reachable (retried on the next ingest)` : ""}.
        </div>
      )}
      {result.rejected_sample?.length > 0 && (
        <div className="max-h-48 overflow-y-auto rounded-lg border border-line">
          <table className="w-full text-[13.5px]">
            <thead className="bg-sunk text-left text-muted">
              <tr>
                <th className="px-3 py-1.5 font-medium">CSV row</th>
                <th className="px-3 py-1.5 font-medium">Why it was rejected</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {result.rejected_sample.map((r) => (
                <tr key={r.row}>
                  <td className="num px-3 py-1.5">{r.row}</td>
                  <td className="px-3 py-1.5">{r.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function DataPage(_props: PageProps) {
  const { can, health, summary, facilities, refresh, notify } = useApp();
  const staticDataset = Boolean(health?.dataset?.static);
  const [mode, setMode] = useState("auto");
  const [window, setWindow] = useState("24h");
  const [dayRange, setDayRange] = useState(2);
  const [syncBusy, setSyncBusy] = useState(false);
  const [syncResult, setSyncResult] = useState<IngestResult | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadResult, setUploadResult] = useState<IngestResult | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [runs, setRuns] = useState<IngestionRun[]>([]);

  const loadRuns = useCallback(() => {
    api.runs().then((r) => setRuns(r.items)).catch((e) => notify("error", errorMessage(e)));
  }, [notify]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  async function sync() {
    setSyncBusy(true);
    setSyncResult(null);
    try {
      const result = await api.sync({ mode, window, day_range: dayRange });
      setSyncResult(result);
      await refresh();
      loadRuns();
    } catch (e) {
      notify("error", errorMessage(e));
      loadRuns();
    } finally {
      setSyncBusy(false);
    }
  }

  async function upload() {
    if (!file) return;
    setUploadBusy(true);
    setUploadResult(null);
    setUploadError(null);
    try {
      const result = await api.upload(file);
      setUploadResult(result);
      await refresh();
      loadRuns();
    } catch (e) {
      setUploadError(errorMessage(e));
      loadRuns();
    } finally {
      setUploadBusy(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-5 p-4 md:p-6">
      {staticDataset && <Callout tone="info">This server shows a fixed archive dataset: FIRMS sync and uploads are off. Use the live server to add detections.</Callout>}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Fetch NASA FIRMS detections" subtitle="The public near-real-time feed needs no key. With a MAP_KEY (Settings) the FIRMS area API can fetch up to 10 days.">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Source">
              <select className={inputClass} value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="auto">Automatic (API if a key is set)</option>
                <option value="public_feed">Public NRT feed (no key)</option>
                <option value="map_key_api">FIRMS area API (MAP_KEY)</option>
              </select>
            </Field>
            {mode !== "map_key_api" ? (
              <Field label="Public feed window">
                <select className={inputClass} value={window} onChange={(e) => setWindow(e.target.value)}>
                  <option value="24h">Last 24 hours</option>
                  <option value="48h">Last 48 hours</option>
                  <option value="7d">Last 7 days</option>
                </select>
              </Field>
            ) : (
              <Field label="API day range">
                <input className={inputClass} type="number" min={1} max={10} value={dayRange} onChange={(e) => setDayRange(Math.min(10, Math.max(1, Number(e.target.value) || 1)))} />
              </Field>
            )}
            <div className="flex items-end">
              <Button variant="primary" icon={RefreshCw} loading={syncBusy} disabled={!can("sync_feed") || staticDataset} onClick={sync} className="w-full">
                Fetch now
              </Button>
            </div>
          </div>
          <div className="mt-3">
            <SignInHint permission="sync_feed" action="fetch FIRMS data" />
          </div>
          <p className="mt-2 text-[13.5px] text-muted">Sensors: VIIRS on Suomi NPP, NOAA-20 and NOAA-21 (375 m) and MODIS on Terra and Aqua (1 km). Land cover is fetched for new locations and the full analysis re-runs.</p>
          {syncResult && <IngestSummary result={syncResult} />}
        </Panel>

        <Panel title="Upload a FIRMS CSV" subtitle="Archive downloads from firms.modaps.eosdis.nasa.gov or your own exports in the FIRMS format.">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="CSV file" className="min-w-[240px] flex-1">
              <input className={inputClass} type="file" accept=".csv,text/csv" disabled={staticDataset} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </Field>
            <Button variant="primary" icon={Upload} loading={uploadBusy} disabled={!file || !can("upload_data") || staticDataset} onClick={upload}>
              Upload and analyse
            </Button>
          </div>
          <div className="mt-3">
            <SignInHint permission="upload_data" action="upload data" />
          </div>
          <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
            Required columns: <code>latitude, longitude, frp, acq_date, acq_time, daynight</code> plus <code>bright_ti4, bright_ti5</code> (VIIRS) or <code>brightness, bright_t31</code> (MODIS). Optional:{" "}
            <code>satellite, confidence, scan, track, version</code>. Rows with missing or impossible values are rejected with a reason; nothing is filled in.
          </p>
          {uploadError && (
            <Callout tone="error" className="mt-3">
              {uploadError}
            </Callout>
          )}
          {uploadResult && <IngestSummary result={uploadResult} />}
        </Panel>
      </div>

      <Panel
        title="Ingestion history"
        actions={
          <Button size="sm" icon={RefreshCw} onClick={loadRuns}>
            Refresh
          </Button>
        }
        bodyClassName="p-0"
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-[14px]">
            <thead className="bg-sunk text-left text-[12.5px] uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Started</th>
                <th className="px-2 py-2 font-medium">Source</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 text-right font-medium">Received</th>
                <th className="px-2 py-2 text-right font-medium">Outside India</th>
                <th className="px-2 py-2 text-right font-medium">Rejected</th>
                <th className="px-2 py-2 text-right font-medium">Duplicates</th>
                <th className="px-4 py-2 text-right font-medium">New</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {runs.map((run) => (
                <tr key={run.id} title={run.message ?? undefined}>
                  <td className="px-4 py-2">
                    {fmtUtc(run.started_at)}
                    <div className="text-[13px] text-muted">{timeAgo(run.started_at)}</div>
                  </td>
                  <td className="px-2 py-2">{run.source}</td>
                  <td className={cx("px-2 py-2 font-medium", run.status === "failed" ? "text-crit" : run.status === "succeeded" ? "text-good" : "text-warn")}>
                    {run.status}
                    {run.status === "failed" && <div className="max-w-[260px] truncate text-[13px] font-normal text-crit">{run.message}</div>}
                  </td>
                  <td className="num px-2 py-2 text-right">{fmtInt(run.records_received)}</td>
                  <td className="num px-2 py-2 text-right">{fmtInt(run.records_outside_india)}</td>
                  <td className="num px-2 py-2 text-right">{fmtInt(run.records_rejected)}</td>
                  <td className="num px-2 py-2 text-right">{fmtInt(run.records_duplicate)}</td>
                  <td className="num px-4 py-2 text-right font-semibold">{fmtInt(run.records_inserted)}</td>
                </tr>
              ))}
              {runs.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-5 text-muted">
                    No ingestion runs recorded.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <GisPanel />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Reference data">
          <KeyValues
            rows={[
              ["Industrial context", `${fmtInt(health?.reference_data.osm_features)} OpenStreetMap features (refineries, flares, wells, power plants, steel, cement, kilns, mines), ODbL`],
              ["Catalog facilities", `${facilities.length} (${facilities.filter((f) => f.osm_element_id).length} matched to an OSM element)`],
              ["Land cover", `ESA WorldCover 10 m 2021 v200 for ${fmtInt(health?.reference_data.landcover_cache.cells_with_data)} footprints (Microsoft Planetary Computer)`],
              ["India boundary", "Natural Earth 1:10m admin-0, India point of view (public domain)"],
              ["Classifier", health?.model.available ? `v${health.model.version} - ${health.model.training_data}` : "not trained"],
            ]}
          />
        </Panel>
        <Panel title="What is stored">
          <KeyValues
            rows={[
              ...Object.entries(summary?.data_sources ?? {}).map(([k, v]) => [DATA_SOURCE_LABELS[k] ?? k, `${fmtInt(v)} detections`] as [string, string]),
              ...Object.entries(summary?.satellites ?? {}).map(([k, v]) => [`Satellite ${k}`, `${fmtInt(v)} detections`] as [string, string]),
              ["Day / night", `${fmtInt(summary?.daynight?.D)} day, ${fmtInt(summary?.daynight?.N)} night`],
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
