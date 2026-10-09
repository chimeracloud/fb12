import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { RaceList } from "../api/types";
import ErrorBox from "../components/ErrorBox";
import { todayUk } from "../lib/format";

export default function RaceListPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const date = params.get("date") ?? todayUk();
  const gb = params.get("gb") !== "0";
  const ire = params.get("ire") !== "0";
  const patternOnly = params.get("pattern") === "1";

  const [data, setData] = useState<RaceList | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  const regions = [gb ? "gb" : null, ire ? "ire" : null].filter(Boolean).join(",");

  const load = useCallback(async () => {
    if (!regions) {
      setData(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const query = new URLSearchParams({ date, regions, pattern_only: patternOnly ? "true" : "false" });
      setData(await api<RaceList>(`/api/races?${query.toString()}`));
    } catch (e) {
      setError(e);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [date, regions, patternOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  const update = (changes: Record<string, string>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) next.set(k, v);
    setParams(next, { replace: true });
  };

  return (
    <div>
      <h1>Races</h1>
      <div className="toolbar">
        <label className="field">
          Date (UK)
          <input type="date" value={date} onChange={(e) => update({ date: e.target.value || todayUk() })} />
        </label>
        <label className="toggle">
          <input type="checkbox" checked={gb} onChange={(e) => update({ gb: e.target.checked ? "1" : "0" })} /> GB
        </label>
        <label className="toggle">
          <input type="checkbox" checked={ire} onChange={(e) => update({ ire: e.target.checked ? "1" : "0" })} /> IRE
        </label>
        <label className="toggle">
          <input type="checkbox" checked={patternOnly} onChange={(e) => update({ pattern: e.target.checked ? "1" : "0" })} /> Pattern races only
        </label>
        <button className="small" onClick={() => void load()} disabled={loading}>
          Refresh
        </button>
      </div>
      {!regions && <p className="notice">Pick at least one region.</p>}
      {error && <ErrorBox error={error} onRetry={() => void load()} />}
      {loading && !data && <p className="muted">Loading the race list from The Racing API…</p>}
      {data && (
        <div className={loading ? "dim" : ""}>
          {data.races.length === 0 ? (
            <p className="notice">
              No {patternOnly ? "pattern " : ""}races on {data.date} for {regions.toUpperCase().replace(",", " and ")} according to The Racing API.
            </p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Off (UK)</th>
                  <th>Course</th>
                  <th>Race</th>
                  <th>Grade</th>
                  <th>Class</th>
                  <th className="num">Runners</th>
                  <th>Region</th>
                </tr>
              </thead>
              <tbody>
                {data.races.map((race) => (
                  <tr key={race.race_id} className="clickable" onClick={() => navigate(`/race/${race.race_id}`)}>
                    <td className="num">{race.off_time_uk ?? "—"}</td>
                    <td>{race.course ?? "—"}</td>
                    <td>{race.race_name ?? "—"}</td>
                    <td>{race.pattern ?? "—"}</td>
                    <td>{race.race_class ?? "—"}</td>
                    <td className="num">{race.field_size ?? "—"}</td>
                    <td>{race.region ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="small muted">{data.races.length} races. Prices and fields from The Racing API.</p>
        </div>
      )}
    </div>
  );
}
