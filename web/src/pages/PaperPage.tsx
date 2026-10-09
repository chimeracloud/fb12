import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, describeError } from "../api/client";
import type { PaperListItem, PaperStatus, SettleResponse } from "../api/types";
import ErrorBox from "../components/ErrorBox";
import { money, ukDateTime, ukTime } from "../lib/format";

function signed(value: number | null): JSX.Element {
  if (value === null) return <span className="muted">—</span>;
  return <span className={"num " + (value < -0.004 ? "loss" : value > 0.004 ? "gain" : "")}>{money(value)}</span>;
}

export default function PaperPage() {
  const [params, setParams] = useSearchParams();
  const status = (params.get("status") ?? "") as PaperStatus | "";
  const [entries, setEntries] = useState<PaperListItem[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [settling, setSettling] = useState<string | null>(null);
  const [messages, setMessages] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const query = status ? `?status=${status}` : "";
      setEntries((await api<{ entries: PaperListItem[] }>(`/api/paper${query}`)).entries);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  const settle = async (entryId: string) => {
    setSettling(entryId);
    setMessages((m) => ({ ...m, [entryId]: "" }));
    try {
      const result = await api<SettleResponse>(`/api/paper/${encodeURIComponent(entryId)}/settle`, { method: "POST" });
      setMessages((m) => ({
        ...m,
        [entryId]: result.status === "NEEDS_REVIEW" ? `Needs review: ${result.review_reason}` : `Settled: ${result.winner ?? "no winner"} won. ${result.bsp_pending ? "BSP pending." : ""}`,
      }));
      await load();
    } catch (e) {
      const { code, message } = describeError(e);
      setMessages((m) => ({ ...m, [entryId]: `${code}: ${message}` }));
    } finally {
      setSettling(null);
    }
  };

  return (
    <div>
      <h1>Paper entries</h1>
      <div className="toolbar">
        <label className="field">
          Status
          <select value={status} onChange={(e) => setParams(e.target.value ? { status: e.target.value } : {}, { replace: true })}>
            <option value="">All</option>
            <option value="OPEN">Open</option>
            <option value="SETTLED">Settled</option>
            <option value="NEEDS_REVIEW">Needs review</option>
          </select>
        </label>
        <button className="small" onClick={() => void load()} disabled={loading}>
          Refresh
        </button>
      </div>
      {error && <ErrorBox error={error} onRetry={() => void load()} />}
      {loading && !entries && <p className="muted">Loading paper entries…</p>}
      {entries && entries.length === 0 && <p className="notice">No paper entries{status ? ` with status ${status}` : ""} yet.</p>}
      {entries && entries.length > 0 && (
        <table className={loading ? "dim" : ""}>
          <thead>
            <tr>
              <th>Race</th>
              <th>Course</th>
              <th>Off (UK)</th>
              <th>Saved (UK)</th>
              <th>Saved by</th>
              <th>Status</th>
              <th className="num">P&L</th>
              <th className="num">After commission</th>
              <th className="num">At SP</th>
              <th className="num">At BSP</th>
              <th className="num">BSP after commission</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.entry_id}>
                <td>
                  <Link to={`/paper/${entry.entry_id}`}>{entry.race_name ?? entry.race_id}</Link>
                  {entry.status === "NEEDS_REVIEW" && entry.review_reason && <div className="small loss">{entry.review_reason}</div>}
                  {messages[entry.entry_id] && <div className="small muted">{messages[entry.entry_id]}</div>}
                </td>
                <td>{entry.course ?? "—"}</td>
                <td className="num">{ukTime(entry.off_dt)}</td>
                <td className="num">{ukDateTime(entry.saved_at)}</td>
                <td>{entry.saved_by}</td>
                <td>
                  <span className={"badge" + (entry.status === "NEEDS_REVIEW" ? " warn" : "")}>{entry.status.replace("_", " ")}</span>
                  {entry.bsp_pending && <span className="badge"> BSP pending</span>}
                </td>
                <td className="num">{signed(entry.pnl)}</td>
                <td className="num">{signed(entry.pnl_after_commission)}</td>
                <td className="num">{signed(entry.pnl_at_sp)}</td>
                <td className="num">{entry.bsp_pending ? <span className="muted">pending</span> : signed(entry.pnl_at_bsp)}</td>
                <td className="num">{entry.bsp_pending ? <span className="muted">pending</span> : signed(entry.pnl_at_bsp_after_commission)}</td>
                <td>
                  {(entry.status === "OPEN" || entry.bsp_pending) && (
                    <button className="small" onClick={() => void settle(entry.entry_id)} disabled={settling === entry.entry_id}>
                      {settling === entry.entry_id ? "Settling…" : entry.status === "OPEN" ? "Settle" : "Fetch BSP"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
