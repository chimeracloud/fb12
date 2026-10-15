import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { PaperListItem, PaperStats, SplitRow, StatValue } from "../api/types";
import CumulativeChart from "../components/CumulativeChart";
import ErrorBox from "../components/ErrorBox";
import { money, pctValue, ukDateTime, ukTime } from "../lib/format";

function signed(value: number | null | undefined): JSX.Element {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  return <span className={value < -0.004 ? "loss" : value > 0.004 ? "gain" : ""}>{money(value)}</span>;
}

function Tile({ label, stat, format }: { label: string; stat: StatValue | undefined; format: (v: number | null) => JSX.Element | string }) {
  return (
    <div className="stat">
      <span className="label">{label}</span>
      <span className="value">{stat ? format(stat.value) : "—"}</span>
      <span className="small muted">{stat ? `${stat.n} bet${stat.n === 1 ? "" : "s"}` : ""}</span>
    </div>
  );
}

function SplitTable({ title, rows }: { title: string; rows: SplitRow[] }) {
  return (
    <div>
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <p className="muted small">No settled bets.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Split</th>
              <th className="num">Bets</th>
              <th className="num">Staked</th>
              <th className="num">Profit</th>
              <th className="num">Return on stake</th>
              <th className="num">Made money</th>
              <th className="num">Expected</th>
              <th className="num">At SP</th>
              <th className="num">At BSP</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td>{row.key.replace("_", " ")}</td>
                <td className="num">{row.n}</td>
                <td className="num">{money(row.staked)}</td>
                <td className="num">{signed(row.profit)}</td>
                <td className="num">{pctValue(row.return_on_stake_pct)}</td>
                <td className="num">{pctValue(row.win_rate_pct)}</td>
                <td className="num">{signed(row.expected_profit)}</td>
                <td className="num">{signed(row.profit_at_sp)}</td>
                <td className="num">{signed(row.profit_at_bsp_after_commission)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function ResultsPage() {
  const [params, setParams] = useSearchParams();
  const kind = params.get("kind") === "TRIAL" ? "TRIAL" : "BET";
  const [stats, setStats] = useState<PaperStats | null>(null);
  const [bets, setBets] = useState<PaperListItem[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, list] = await Promise.all([
        api<PaperStats>(`/api/paper/stats?kind=${kind}`),
        api<{ entries: PaperListItem[] }>(`/api/paper?kind=${kind}`),
      ]);
      setStats(s);
      setBets(list.entries);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [kind]);

  useEffect(() => {
    void load();
  }, [load]);

  const totals = stats?.totals;
  return (
    <div>
      <h1>Results</h1>
      <div className="toolbar">
        <label className="field">
          Showing
          <select value={kind} onChange={(e) => setParams(e.target.value === "TRIAL" ? { kind: "TRIAL" } : {}, { replace: true })}>
            <option value="BET">Paper bets (live prices)</option>
            <option value="TRIAL">Trials (typed prices)</option>
          </select>
        </label>
        <a className="badge" href={`/api/paper/export.csv?kind=${kind}`} download>
          Download CSV (one row per runner per bet)
        </a>
        <button className="small" onClick={() => void load()} disabled={loading}>
          Refresh
        </button>
      </div>
      {error && <ErrorBox error={error} onRetry={() => void load()} />}
      {loading && !stats && <p className="muted">Loading the results…</p>}
      {stats && (
        <div className={loading ? "dim" : ""}>
          <p className="small muted">
            Totals are over settled {kind === "BET" ? "bets" : "trials"}: {stats.scope.settled} settled, {stats.scope.open} open, {stats.scope.needs_review} needing review
            {kind === "BET" ? `, ${stats.scope.trials} trials kept out` : ""}
            {stats.scope.bsp_pending ? `, ${stats.scope.bsp_pending} awaiting BSP` : ""}. Profit is after commission at the prices taken unless the tile says otherwise.
          </p>
          <div className="panel">
            <div className="summary">
              <Tile label="Bets" stat={totals?.bets} format={(v) => (v === null ? "—" : String(v))} />
              <Tile label="Total staked" stat={totals?.staked} format={money} />
              <Tile label="Profit" stat={totals?.profit} format={signed} />
              <Tile label="Return on stake" stat={totals?.return_on_stake_pct} format={pctValue} />
              <Tile label="Bets that made money" stat={totals?.win_rate_pct} format={pctValue} />
              <Tile label="Expected profit" stat={totals?.expected_profit} format={signed} />
              <Tile label="Expected minus actual" stat={totals?.expected_minus_actual} format={signed} />
              <Tile label="Profit at SP" stat={totals?.profit_at_sp} format={signed} />
              <Tile label="Profit at BSP after commission" stat={totals?.profit_at_bsp_after_commission} format={signed} />
            </div>
          </div>
          <div className="panel">
            <h2>Cumulative profit</h2>
            <CumulativeChart points={stats.cumulative} />
          </div>
          <div className="panel">
            <h2>Splits</h2>
            <SplitTable title="By preset" rows={stats.splits.preset} />
            <SplitTable title="By pattern race" rows={stats.splits.pattern} />
            <SplitTable title="By time before the off" rows={stats.splits.minutes_before_off} />
          </div>
          <div className="panel">
            <h2>Every {kind === "BET" ? "bet" : "trial"}</h2>
            {bets && bets.length === 0 && <p className="muted">None yet.</p>}
            {bets && bets.length > 0 && (
              <table>
                <thead>
                  <tr>
                    <th>Race</th>
                    <th>Off (UK)</th>
                    <th>Placed (UK)</th>
                    <th className="num">Before off</th>
                    <th>Preset</th>
                    <th>Status</th>
                    <th>Outcome</th>
                    <th className="num">Staked</th>
                    <th className="num">Expected</th>
                    <th className="num">Profit</th>
                    <th className="num">At SP</th>
                    <th className="num">At BSP</th>
                  </tr>
                </thead>
                <tbody>
                  {bets.map((b) => (
                    <tr key={b.entry_id}>
                      <td>
                        <Link to={`/paper/${b.entry_id}`}>{b.race_name ?? b.race_id}</Link>
                        <div className="small muted">
                          {b.course ?? "—"}
                          {b.pattern ? ` · ${b.pattern}` : ""}
                        </div>
                      </td>
                      <td className="num">{ukTime(b.off_dt)}</td>
                      <td className="num">{ukDateTime(b.placed_at)}</td>
                      <td className="num">{b.minutes_before_off === null ? "—" : `${b.minutes_before_off.toFixed(0)} min`}</td>
                      <td>{(b.preset ?? "custom").replace("_", " ")}</td>
                      <td>
                        <span className={"badge" + (b.status === "NEEDS_REVIEW" ? " warn" : "")}>{b.status.replace("_", " ")}</span>
                        {b.bsp_pending && <span className="badge"> BSP pending</span>}
                      </td>
                      <td>{b.status === "SETTLED" ? `${b.winner ?? "—"} won` : b.status === "NEEDS_REVIEW" ? <span className="small loss">{b.review_reason}</span> : <span className="muted">awaiting result</span>}</td>
                      <td className="num">{money(b.stake_total)}</td>
                      <td className="num">{signed(b.expected_profit_gbp)}</td>
                      <td className="num">{signed(b.pnl_after_commission)}</td>
                      <td className="num">{signed(b.pnl_at_sp)}</td>
                      <td className="num">{b.bsp_pending ? <span className="muted">pending</span> : signed(b.pnl_at_bsp_after_commission)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
