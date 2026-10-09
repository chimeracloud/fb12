import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Config, Health, LogEntry, LogsResponse, SettingsForm, SettingsPutResponse, Status } from "../api/types";
import ErrorBox from "../components/ErrorBox";
import SettingsFormView from "../components/SettingsFormView";
import { ukDateTime } from "../lib/format";

function KeyValues({ data }: { data: Record<string, unknown> }) {
  return (
    <dl className="kv">
      {Object.entries(data).map(([key, value]) => (
        <Fragment key={key}>
          <dt>{key}</dt>
          <dd>{typeof value === "object" && value !== null ? JSON.stringify(value) : String(value)}</dd>
        </Fragment>
      ))}
    </dl>
  );
}


interface Loaded<T> {
  data: T | null;
  error: unknown;
}

export default function AdminPage() {
  const [health, setHealth] = useState<Loaded<Health>>({ data: null, error: null });
  const [status, setStatus] = useState<Loaded<Status>>({ data: null, error: null });
  const [config, setConfig] = useState<Loaded<Config>>({ data: null, error: null });
  const [settings, setSettings] = useState<Loaded<SettingsForm>>({ data: null, error: null });
  const [logs, setLogs] = useState<Loaded<LogEntry[]>>({ data: null, error: null });
  const [saveResult, setSaveResult] = useState<SettingsPutResponse | null>(null);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [streamState, setStreamState] = useState<string>("not connected");
  const seen = useRef<Set<number>>(new Set());

  const load = useCallback(async <T,>(path: string, set: (value: Loaded<T>) => void, pick?: (v: unknown) => T) => {
    try {
      const data = await api<unknown>(path);
      set({ data: pick ? pick(data) : (data as T), error: null });
    } catch (e) {
      set({ data: null, error: e });
    }
  }, []);

  const loadAll = useCallback(() => {
    void load<Health>("/admin/health", setHealth);
    void load<Status>("/admin/status", setStatus);
    void load<Config>("/admin/config", setConfig);
    void load<SettingsForm>("/admin/settings", setSettings);
    void load<LogEntry[]>("/admin/logs?limit=100", setLogs, (v) => {
      const entries = (v as LogsResponse).entries;
      for (const e of entries) seen.current.add(e.seq);
      return entries;
    });
  }, [load]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // Live updates: the API's SSE stream, through the Pages Function on this hostname.
  useEffect(() => {
    const source = new EventSource("/admin/stream");
    setStreamState("connecting");
    source.addEventListener("hello", () => setStreamState("live"));
    source.addEventListener("status", (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data) as { data: Status };
        setStatus({ data: payload.data, error: null });
      } catch {
        /* a malformed event is ignored; the next one replaces it */
      }
    });
    source.addEventListener("log", (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data) as { data: LogEntry };
        const entry = payload.data;
        if (seen.current.has(entry.seq)) return;
        seen.current.add(entry.seq);
        setLogs((current) => ({ data: [entry, ...(current.data ?? [])].slice(0, 300), error: null }));
      } catch {
        /* ignored */
      }
    });
    source.addEventListener("settings", () => void load<SettingsForm>("/admin/settings", setSettings));
    source.addEventListener("recorder", () => void load<Status>("/admin/status", setStatus));
    source.onerror = () => setStreamState("disconnected, reconnecting");
    return () => source.close();
  }, [load]);

  const save = async (values: Record<string, unknown>) => {
    setSaveError(null);
    setSaveResult(null);
    try {
      const response = await api<SettingsPutResponse>("/admin/settings", { method: "PUT", body: JSON.stringify({ values }) });
      setSaveResult(response);
      setSettings({ data: response.settings, error: null });
    } catch (e) {
      setSaveError(e);
    }
  };

  return (
    <div>
      <h1>Admin</h1>
      <p className="small muted">
        FB12's admin endpoints (CHI-ADR-010), rendered from what they return. Stream: {streamState}.{" "}
        <button className="small" onClick={loadAll}>
          Reload all
        </button>
      </p>

      <div className="grid-2">
        <section className="panel">
          <h3>Health</h3>
          {health.error && <ErrorBox error={health.error} onRetry={() => void load<Health>("/admin/health", setHealth)} />}
          {health.data && <KeyValues data={health.data} />}
        </section>
        <section className="panel">
          <h3>Status</h3>
          {status.error && <ErrorBox error={status.error} onRetry={() => void load<Status>("/admin/status", setStatus)} />}
          {status.data && <KeyValues data={status.data} />}
        </section>
      </div>

      <section className="panel">
        <h3>Settings</h3>
        {settings.error && <ErrorBox error={settings.error} onRetry={() => void load<SettingsForm>("/admin/settings", setSettings)} />}
        {saveError && <ErrorBox error={saveError} />}
        {saveResult && (
          <p className="notice">
            Applied: {saveResult.applied.length ? saveResult.applied.join(", ") : "nothing"}.
            {saveResult.rejected.length > 0 && <> Rejected: {saveResult.rejected.map((r) => `${r.key} (${r.reason})`).join("; ")}.</>}
          </p>
        )}
        {settings.data && <SettingsFormView form={settings.data} onSave={save} />}
      </section>

      <section className="panel">
        <h3>Config</h3>
        {config.error && <ErrorBox error={config.error} onRetry={() => void load<Config>("/admin/config", setConfig)} />}
        {config.data && <KeyValues data={config.data} />}
      </section>

      <section className="panel">
        <h3>Logs</h3>
        {logs.error && <ErrorBox error={logs.error} onRetry={loadAll} />}
        {logs.data && (
          <div className="logs">
            {logs.data.map((entry) => (
              <div key={entry.seq} className={"sev-" + entry.severity}>
                <span>{ukDateTime(entry.timestamp)}</span>
                <span>{entry.severity}</span>
                <span>
                  {entry.message}
                  {typeof entry.path === "string" ? ` ${entry.method ?? ""} ${entry.path} ${entry.status ?? ""}` : ""}
                  {typeof entry.reason === "string" ? ` — ${entry.reason}` : ""}
                  {typeof entry.error === "string" ? ` — ${entry.error}` : ""}
                </span>
              </div>
            ))}
            {logs.data.length === 0 && <p className="muted">No log entries yet on this instance.</p>}
          </div>
        )}
      </section>
    </div>
  );
}
