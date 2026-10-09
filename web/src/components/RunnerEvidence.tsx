import { useCallback, useEffect, useState } from "react";
import { api, describeError } from "../api/client";
import type { MoveResponse, PaceResponse } from "../api/types";
import { odds, pctValue, ukTime } from "../lib/format";

// Move and pace load per runner: each row fills as its own call returns, and neither blocks
// the tiers or the results. A failed call shows in its own row only, with a retry.

interface Loaded<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
}

function useEvidence<T>(path: string): [Loaded<T>, () => void] {
  const [state, setState] = useState<Loaded<T>>({ data: null, error: null, loading: true });
  const load = useCallback(async () => {
    setState({ data: null, error: null, loading: true });
    try {
      setState({ data: await api<T>(path), error: null, loading: false });
    } catch (e) {
      setState({ data: null, error: e, loading: false });
    }
  }, [path]);
  useEffect(() => {
    void load();
  }, [load]);
  return [state, () => void load()];
}

function RowError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { code, message } = describeError(error);
  return (
    <span className="small loss" title={message}>
      {code}: {message.length > 90 ? message.slice(0, 90) + "…" : message}{" "}
      <button className="small" onClick={onRetry}>
        retry
      </button>
    </span>
  );
}

export function MoveCell({ raceId, horseId }: { raceId: string; horseId: string }) {
  const [state, retry] = useEvidence<MoveResponse>(`/api/races/${encodeURIComponent(raceId)}/runners/${encodeURIComponent(horseId)}/move`);
  if (state.loading) return <span className="small muted">loading…</span>;
  if (state.error) return <RowError error={state.error} onRetry={retry} />;
  const move = state.data;
  if (!move || move.first_price === null || move.latest_price === null) {
    return <span className="small muted">{move?.note ?? "no price history"}</span>;
  }
  const arrow = move.direction === "shortened" ? "▼" : move.direction === "drifted" ? "▲" : "▶";
  const cls = move.direction === "shortened" ? "gain" : move.direction === "drifted" ? "loss" : "";
  return (
    <div>
      <span className="num">{odds(move.first_price)}</span> <span className="muted">→</span> <span className="num">{odds(move.latest_price)}</span>{" "}
      <span className={"num " + cls}>
        {arrow} {pctValue(move.change_pct)}
      </span>
      <div className="small muted">
        {move.direction ?? "—"} · {move.source ?? "—"} · {ukTime(move.first_at)} to {ukTime(move.latest_at)} UK
      </div>
      {move.note && <div className="small muted">{move.note}</div>}
    </div>
  );
}

const LABELS: Record<string, string> = { LED: "led", PROMINENT: "prominent", MIDFIELD: "midfield", HELD_UP: "held up", UNCLASSIFIED: "unclassified" };

export function PaceCell({ raceId, horseId }: { raceId: string; horseId: string }) {
  const [state, retry] = useEvidence<PaceResponse>(`/api/races/${encodeURIComponent(raceId)}/runners/${encodeURIComponent(horseId)}/pace`);
  if (state.loading) return <span className="small muted">loading…</span>;
  if (state.error) return <RowError error={state.error} onRetry={retry} />;
  const pace = state.data;
  if (!pace) return <span className="small muted">—</span>;
  const total = pace.runs.length;
  if (total === 0) return <span className="small muted">no past runs before this race</span>;
  const parts = (["LED", "PROMINENT", "MIDFIELD", "HELD_UP", "UNCLASSIFIED"] as const)
    .filter((c) => pace.counts[c] > 0)
    .map((c) => `${LABELS[c]} ${pace.counts[c]}`);
  return (
    <details className="drawer">
      <summary>
        <span className="num">{pace.counts.LED}</span> of {total} led · {parts.join(", ")}
      </summary>
      <table className="small">
        <thead>
          <tr>
            <th>Date</th>
            <th>Course</th>
            <th>Race</th>
            <th>Pos</th>
            <th>Class</th>
            <th>Pace</th>
            <th>Comment</th>
          </tr>
        </thead>
        <tbody>
          {pace.runs.map((run, i) => (
            <tr key={i}>
              <td className="num">{run.date ?? "—"}</td>
              <td>{run.course ?? "—"}</td>
              <td>{run.race_name ?? "—"}</td>
              <td className="num">{run.position ?? "—"}</td>
              <td>{run.class ?? "—"}</td>
              <td>{LABELS[run.category] ?? run.category}</td>
              <td>{run.comment ?? <span className="muted">no comment</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
