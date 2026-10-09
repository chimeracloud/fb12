import { Link } from "react-router-dom";
import type { CalculateResponse, CalculateRunnerOut, PaperCreated, RunnerCard } from "../api/types";
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
}

function signed(value: number | null): JSX.Element {
  if (value === null) return <span className="muted">—</span>;
  return <span className={value < -0.004 ? "loss" : value > 0.004 ? "gain" : ""}>{money(value)}</span>;
}

// Every figure here comes from POST /api/calculate. The GUI never calculates.
export default function ResultsPanel({ result, error, calculating, runners, resultsByHorse, onRetry, pending, onSave, saving, saved, saveError }: Props) {
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
            <button className="primary" onClick={onSave} disabled={saving || calculating || !result.feasible}>
              {saving ? "Saving…" : "Save as paper entry"}
            </button>
            {saved && (
              <span>
                Saved as <span className="mono">{saved.entry_id}</span> by {saved.saved_by}. <Link to={`/paper/${saved.entry_id}`}>Open it</Link> ·{" "}
                <Link to="/paper">all entries</Link>
              </span>
            )}
          </div>
          {saveError && <ErrorBox error={saveError} onRetry={onSave} />}
        </div>
      )}
    </div>
  );
}
