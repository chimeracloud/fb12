import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { PaperEntry } from "../api/types";
import ErrorBox from "../components/ErrorBox";
import { money, odds, pct, pctValue, times, ukDateTime } from "../lib/format";

function signed(value: number | null | undefined): JSX.Element {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  return <span className={"num " + (value < -0.004 ? "loss" : value > 0.004 ? "gain" : "")}>{money(value)}</span>;
}

export default function PaperEntryPage() {
  const { entryId = "" } = useParams();
  const [entry, setEntry] = useState<PaperEntry | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setEntry(await api<PaperEntry>(`/api/paper/${encodeURIComponent(entryId)}`));
    } catch (e) {
      setError(e);
    }
  }, [entryId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <div>
        <p>
          <Link to="/paper">← Paper entries</Link>
        </p>
        <ErrorBox error={error} onRetry={() => void load()} />
      </div>
    );
  }
  if (!entry) {
    return (
      <div>
        <p>
          <Link to="/paper">← Paper entries</Link>
        </p>
        <p className="muted">Loading the entry…</p>
      </div>
    );
  }

  const figures = entry.figures;
  const byHorse = new Map(figures.runners.map((r) => [r.horse_id, r]));
  const s = entry.settlement;

  return (
    <div>
      <p>
        <Link to="/paper">← Paper entries</Link>
      </p>
      <h1>{entry.race.race_name ?? entry.race.race_id}</h1>
      <p className="muted">
        {entry.race.course ?? "—"} · {entry.race.pattern ?? "no grade"} · off {entry.race.off_time_uk ?? "—"} UK ·{" "}
        <span className={"badge" + (entry.kind === "TRIAL" ? " warn" : "")}>{entry.kind === "TRIAL" ? "trial: typed prices, out of the totals" : "paper bet"}</span>{" "}
        <span className={"badge" + (entry.status === "NEEDS_REVIEW" ? " warn" : "")}>{entry.status.replace("_", " ")}</span>
      </p>
      <p className="small muted">
        Placed {ukDateTime(entry.placed_at)} UK by {entry.placed_by}
        {entry.minutes_before_off !== null ? `, ${entry.minutes_before_off.toFixed(1)} minutes ${entry.minutes_before_off >= 0 ? "before" : "after"} the off` : ""} ·{" "}
        {entry.preset ? entry.preset.replace("_", " ") : "custom"} · expected profit at market odds when placed {money(entry.expected_profit_gbp)}
      </p>
      <p className="small muted">
        Card as FB12 saw it at {ukDateTime(entry.race.card_fetched_at)} UK · stake {money(entry.inputs.stake_total)} · commission {pct(entry.inputs.commission_rate)} ·{" "}
        <Link to={`/race/${entry.race.race_id}`}>open the race</Link>
      </p>

      <div className="panel">
        <h2>Figures</h2>
        {figures.message && <p className="notice">{figures.message}</p>}
        <div className="summary">
          <div className="stat">
            <span className="label">Profit per PROFIT win</span>
            <span className="value">{money(figures.profit_per_win)}</span>
          </div>
          <div className="stat">
            <span className="label">Book</span>
            <span className="value">{pctValue(figures.book_pct)}</span>
          </div>
          <div className="stat">
            <span className="label">Expected value</span>
            <span className="value">{signed(figures.expected_value_gbp)}</span>
          </div>
          <div className="stat">
            <span className="label">Expected value of stake</span>
            <span className="value">{pctValue(figures.expected_value_pct)}</span>
          </div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Horse</th>
              <th>Tier</th>
              <th className="num">Price used</th>
              <th className="num">Card price</th>
              <th className="num">Stake</th>
              <th className="num">Return if wins</th>
              <th className="num">Net if wins</th>
              <th className="num">After commission</th>
              <th className="num">Market chance</th>
              <th>Break even</th>
              <th>Wipes out</th>
            </tr>
          </thead>
          <tbody>
            {entry.inputs.runners.map((input) => {
              const f = byHorse.get(input.horse_id);
              const outOrPart = f && (f.tier === "OUT" || f.tier === "PART");
              return (
                <tr key={input.horse_id}>
                  <td>{input.horse}</td>
                  <td className={"tier-" + input.tier}>
                    {input.tier.replace("_", " ")}
                    {input.tier === "PART" && input.part_fraction !== null && <span className="small muted"> {input.part_fraction}</span>}
                  </td>
                  <td className={"num" + (input.price_edited ? " edited" : "")} title={input.price_edited ? "edited from the card price" : ""}>
                    {odds(input.price)}
                    {input.price_edited && <span className="small"> *</span>}
                  </td>
                  <td className="num muted">{odds(input.card_price)}</td>
                  <td className="num">{f ? money(f.stake) : "—"}</td>
                  <td className="num">{f ? money(f.return_if_wins) : "—"}</td>
                  <td className="num">{f ? signed(f.net_if_wins) : "—"}</td>
                  <td className="num">{f ? signed(f.net_after_commission) : "—"}</td>
                  <td className="num">{f ? pct(f.market_chance) : "—"}</td>
                  <td>{outOrPart ? (f.can_break_even === false ? <span className="loss">cannot break even</span> : pct(f.break_even_chance)) : <span className="muted">—</span>}</td>
                  <td>{outOrPart && f.wins_wiped_out !== null ? `${times(f.wins_wiped_out)} wins` : <span className="muted">—</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="small muted">* price edited from the card. Figures from the calculate function at save time.</p>
      </div>

      <div className="panel">
        <h2>Result</h2>
        {!entry.result_summary && <p className="muted">Not settled yet. Settle it from the entries page once the result is published.</p>}
        {entry.result_summary && (
          <div>
            {s && s.status === "NEEDS_REVIEW" && <p className="notice loss">Needs review: {s.review_reason}</p>}
            {s && s.status === "SETTLED" && (
              <div className="summary">
                <div className="stat">
                  <span className="label">Winner</span>
                  <span className="value">{s.winner ?? "—"}</span>
                </div>
                <div className="stat">
                  <span className="label">P&L at saved prices</span>
                  <span className="value">{signed(s.pnl)}</span>
                </div>
                <div className="stat">
                  <span className="label">After commission</span>
                  <span className="value">{signed(s.pnl_after_commission)}</span>
                </div>
                <div className="stat">
                  <span className="label">At SP {s.winner_sp_dec ? `(${odds(s.winner_sp_dec)})` : ""}</span>
                  <span className="value">{signed(s.pnl_at_sp)}</span>
                </div>
                <div className="stat">
                  <span className="label">At SP after commission</span>
                  <span className="value">{signed(s.pnl_at_sp_after_commission)}</span>
                </div>
                <div className="stat">
                  <span className="label">At BSP {s.winner_bsp ? `(${odds(s.winner_bsp)})` : ""}</span>
                  <span className="value">{s.bsp_pending ? <span className="muted">pending</span> : signed(s.pnl_at_bsp)}</span>
                </div>
                <div className="stat">
                  <span className="label">At BSP after commission</span>
                  <span className="value">{s.bsp_pending ? <span className="muted">pending</span> : signed(s.pnl_at_bsp_after_commission)}</span>
                </div>
              </div>
            )}
            <table>
              <thead>
                <tr>
                  <th className="num">Pos</th>
                  <th>Horse</th>
                  <th className="num">SP</th>
                  <th className="num">BSP</th>
                  <th className="num">Beaten by</th>
                </tr>
              </thead>
              <tbody>
                {entry.result_summary.positions.map((p, i) => (
                  <tr key={i}>
                    <td className="num">{p.position ?? "—"}</td>
                    <td>{p.horse ?? "—"}</td>
                    <td className="num">{p.sp ?? "—"}</td>
                    <td className="num">{p.bsp || "—"}</td>
                    <td className="num">{p.btn ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {entry.result_summary.non_runners && <p className="small muted">Non runners: {entry.result_summary.non_runners}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
