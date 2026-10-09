import { useState } from "react";
import { Link } from "react-router-dom";
import type { CalculateResponse, CalculateRunnerOut, PaperCreated, Preset, RunnerCard } from "../api/types";
import ErrorBox from "./ErrorBox";
import { money, pct, pctValue, times } from "../lib/format";

interface Props {
  result: CalculateResponse | null;
  error: unknown;
  calculating: boolean;
  runners: RunnerCard[];
  resultsByHorse: Record<string, CalculateRunnerOut>;
  onRetry: () => void;
  pending: boolean;
  onSave: () => void;
  saving: boolean;
  saved: PaperCreated | null;
  saveError: unknown;
  trial: boolean;
  offDt: string | null;
  preset: Preset;
  stakeTotal: number | null;
}

const PRESET_LABEL: Record<Preset, string> = { top_two: "Top two only", four_horses: "Four horses", custom: "Custom tiers" };

function signed(value: number | null): JSX.Element {
  if (value === null) return <span className="muted">—</span>;
  return <span className={value < -0.004 ? "loss" : value > 0.004 ? "gain" : ""}>{money(value)}</span>;
}

// Every figure here comes from POST /api/calculate. The GUI never calculates.
export default function ResultsPanel({ result, error, calculating, runners, resultsByHorse, onRetry, pending, onSave, saving, saved, saveError, trial, offDt, preset, stakeTotal }: Props) {
  const [slipOpen, setSlipOpen] = useState(false);
  const afterOff = offDt !== null && new Date(offDt).getTime() <= Date.now();
  const backed = runners.map((r) => resultsByHorse[r.horse_id]).filter((r): r is CalculateRunnerOut => Boolean(r) && (r as CalculateRunnerOut).tier !== "OUT");
  return (
    <div className="panel">
      <h2>Results</h2>
      {pending && !result && <p className="muted">Set a valid stake and commission to see the figures.</p>}
      {error && <ErrorBox error={error} onRetry={onRetry} />}
      {result && (
        <div className={calculating ? "dim" : ""}>
          {result.message && <p className="notice">{result.message}</p>}
          <div className="summary">
            <div className="stat">
              <span className="label">Profit per PROFIT win</span>
              <span className="value">{result.feasible ? money(result.profit_per_win) : "—"}</span>
            </div>
            <div className="stat">
              <span className="label">Book</span>
              <span className="value">{pctValue(result.book_pct)}</span>
            </div>
            <div className="stat">
              <span className="label">Expected value</span>
              <span className="value">{result.expected_value_gbp === null ? "—" : <>{signed(result.expected_value_gbp)}</>}</span>
            </div>
            <div className="stat">
              <span className="label">Expected value of stake</span>
              <span className="value">{pctValue(result.expected_value_pct)}</span>
            </div>
          </div>
          <table>
            <thead>
              <tr>
                <th>Horse</th>
                <th>Tier</th>
                <th className="num">Price</th>
                <th className="num">Stake</th>
                <th className="num">Return if wins</th>
                <th className="num">Net if wins</th>
                <th className="num">Net after commission</th>
                <th className="num">Market chance</th>
                <th>Break even chance</th>
                <th>One loss wipes out</th>
              </tr>
            </thead>
            <tbody>
              {runners.map((runner) => {
                const r = resultsByHorse[runner.horse_id];
                if (!r) return null;
                const outOrPart = r.tier === "OUT" || r.tier === "PART";
                return (
                  <tr key={runner.horse_id}>
                    <td>{r.horse}</td>
                    <td className={"tier-" + r.tier}>{r.tier.replace("_", " ")}</td>
                    <td className="num">{r.price === null ? "—" : r.price.toFixed(2)}</td>
                    <td className="num">{result.feasible ? money(r.stake) : "—"}</td>
                    <td className="num">{result.feasible ? money(r.return_if_wins) : "—"}</td>
                    <td className="num">{result.feasible ? signed(r.net_if_wins) : "—"}</td>
                    <td className="num">{result.feasible ? signed(r.net_after_commission) : "—"}</td>
                    <td className="num">{pct(r.market_chance)}</td>
                    <td>
                      {!outOrPart ? (
                        <span className="muted">—</span>
                      ) : r.can_break_even === false ? (
                        <span className="loss">cannot break even</span>
                      ) : (
                        <span className="num">{pct(r.break_even_chance)}</span>
                      )}
                    </td>
                    <td>{outOrPart && r.wins_wiped_out !== null ? <span className="num">{times(r.wins_wiped_out)} wins</span> : <span className="muted">—</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="small muted">{calculating ? "Recalculating…" : "Figures from POST /api/calculate."}</p>
          <div className="toolbar">
            <button className="primary" onClick={() => setSlipOpen(true)} disabled={saving || calculating || !result.feasible || slipOpen || (afterOff && !trial)}>
              {trial ? "Save trial" : "Place paper bet"}
            </button>
            {afterOff && !trial && <span className="small loss">The race is off: bets are refused after the off. Typed prices save as a trial.</span>}
            {trial && <span className="badge warn">trial: typed prices, kept out of the totals</span>}
            {saved && (
              <span>
                {saved.kind === "BET" ? "Bet placed" : "Trial saved"} as <span className="mono">{saved.entry_id}</span> by {saved.saved_by}
                {saved.minutes_before_off !== null ? `, ${saved.minutes_before_off.toFixed(1)} min before the off` : ""}.{" "}
                <Link to={`/paper/${saved.entry_id}`}>Open it</Link> · <Link to="/paper">all entries</Link>
              </span>
            )}
          </div>
          {slipOpen && (
            <div className="panel" style={{ borderColor: "var(--gold)" }}>
              <h3>{trial ? "Trial slip" : "Bet slip"}</h3>
              <p className="small muted">
                {PRESET_LABEL[preset]} · total stake {money(stakeTotal)} · {trial ? "typed prices (trial)" : "live exchange prices as shown now"} ·{" "}
                {offDt ? `off ${new Date(offDt).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" })} UK` : "no off time"}
              </p>
              <table>
                <thead>
                  <tr>
                    <th>Horse</th>
                    <th>Tier</th>
                    <th className="num">Price</th>
                    <th className="num">Stake</th>
                    <th className="num">Return if wins</th>
                    <th className="num">Net if wins</th>
                  </tr>
                </thead>
                <tbody>
                  {backed.map((r) => (
                    <tr key={r.horse_id}>
                      <td>{r.horse}</td>
                      <td className={"tier-" + r.tier}>{r.tier.replace("_", " ")}</td>
                      <td className="num">{r.price === null ? "—" : r.price.toFixed(2)}</td>
                      <td className="num">{money(r.stake)}</td>
                      <td className="num">{money(r.return_if_wins)}</td>
                      <td className="num">{signed(r.net_if_wins)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="small muted">
                Profit per PROFIT win {money(result.profit_per_win)} · book {pctValue(result.book_pct)} · expected value {money(result.expected_value_gbp)}.
                {runners.length - backed.length > 0 ? ` ${runners.length - backed.length} runners OUT with no stake.` : ""}
              </p>
              <div className="toolbar">
                <button
                  className="primary"
                  disabled={saving}
                  onClick={() => {
                    setSlipOpen(false);
                    onSave();
                  }}
                >
                  {saving ? "Placing…" : trial ? "Confirm trial" : "Confirm paper bet"}
                </button>
                <button onClick={() => setSlipOpen(false)} disabled={saving}>
                  Cancel
                </button>
              </div>
            </div>
          )}
          {saveError && <ErrorBox error={saveError} onRetry={onSave} />}
        </div>
      )}
    </div>
  );
}
