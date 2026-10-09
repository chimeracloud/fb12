import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { CalculateRequest, CalculateResponse, RaceCard, RunnerCard, SettingsForm, Tier } from "../api/types";
import ErrorBox from "../components/ErrorBox";
import RawDrawer from "../components/RawDrawer";
import ResultsPanel from "../components/ResultsPanel";
import { MoveCell, PaceCell } from "../components/RunnerEvidence";
import { odds, ukDateTime } from "../lib/format";
import { useDebounced } from "../lib/useDebounce";

interface RunnerState {
  price: number | null; // the price in use: the card's exchange price, or what Charles typed
  priceText: string; // what is in the input
  edited: boolean;
  tier: Tier;
  partFraction: number;
}

interface Defaults {
  stake: number;
  commission: number;
  partFraction: number;
}

const TIERS: Tier[] = ["PROFIT", "BREAK_EVEN", "PART", "OUT"];

function settingNumber(form: SettingsForm, key: string, fallback: number): number {
  for (const group of form.groups) {
    for (const field of group.fields) {
      if (field.key === key && typeof field.value === "number") return field.value;
    }
  }
  return fallback;
}

export default function RacePage() {
  const { raceId = "" } = useParams();
  const [card, setCard] = useState<RaceCard | null>(null);
  const [cardError, setCardError] = useState<unknown>(null);
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [defaultsError, setDefaultsError] = useState<unknown>(null);
  const [stakeText, setStakeText] = useState("");
  const [commissionText, setCommissionText] = useState("");
  const [runners, setRunners] = useState<Record<string, RunnerState>>({});

  const loadCard = useCallback(async () => {
    setCardError(null);
    try {
      const data = await api<RaceCard>(`/api/races/${encodeURIComponent(raceId)}`);
      setCard(data);
      setRunners((previous) => {
        const next: Record<string, RunnerState> = {};
        for (const runner of data.runners) {
          const existing = previous[runner.horse_id];
          const cardPrice = runner.exchange_price;
          next[runner.horse_id] = existing
            ? { ...existing, price: existing.edited ? existing.price : cardPrice, priceText: existing.edited ? existing.priceText : cardPrice === null ? "" : String(cardPrice) }
            : { price: cardPrice, priceText: cardPrice === null ? "" : String(cardPrice), edited: false, tier: "OUT", partFraction: defaults?.partFraction ?? 0.5 };
        }
        return next;
      });
    } catch (e) {
      setCardError(e);
    }
  }, [raceId, defaults?.partFraction]);

  const loadDefaults = useCallback(async () => {
    setDefaultsError(null);
    try {
      const form = await api<SettingsForm>("/admin/settings");
      const next = {
        stake: settingNumber(form, "default_stake", 100),
        commission: settingNumber(form, "commission_rate", 0.02),
        partFraction: settingNumber(form, "default_part_fraction", 0.5),
      };
      setDefaults(next);
      setStakeText((current) => (current === "" ? String(next.stake) : current));
      setCommissionText((current) => (current === "" ? String(next.commission) : current));
      setRunners((previous) => {
        const updated: Record<string, RunnerState> = {};
        for (const [id, state] of Object.entries(previous)) updated[id] = { ...state, partFraction: state.tier === "PART" ? state.partFraction : next.partFraction };
        return updated;
      });
    } catch (e) {
      setDefaultsError(e);
    }
  }, []);

  useEffect(() => {
    void loadDefaults();
  }, [loadDefaults]);
  useEffect(() => {
    void loadCard();
  }, [loadCard]);

  const stake = Number(stakeText);
  const commission = Number(commissionText);
  const stakeValid = stakeText !== "" && Number.isFinite(stake) && stake > 0;
  const commissionValid = commissionText !== "" && Number.isFinite(commission) && commission >= 0 && commission < 1;

  const declared = useMemo(() => (card ? card.runners.filter((r) => r.status === "DECLARED") : []), [card]);

  const setRunner = (id: string, changes: Partial<RunnerState>) =>
    setRunners((previous) => ({ ...previous, [id]: { ...previous[id], ...changes } }));

  const onPriceInput = (runner: RunnerCard, text: string) => {
    const trimmed = text.trim();
    const value = trimmed === "" ? null : Number(trimmed);
    const price = value !== null && Number.isFinite(value) && value > 1 ? value : null;
    const state = runners[runner.horse_id];
    setRunner(runner.horse_id, {
      priceText: text,
      price,
      edited: trimmed !== (runner.exchange_price === null ? "" : String(runner.exchange_price)),
      tier: price === null && state && state.tier !== "OUT" ? "OUT" : (state?.tier ?? "OUT"),
    });
  };

  const resetPrice = (runner: RunnerCard) =>
    setRunner(runner.horse_id, {
      price: runner.exchange_price,
      priceText: runner.exchange_price === null ? "" : String(runner.exchange_price),
      edited: false,
      tier: runner.exchange_price === null ? "OUT" : runners[runner.horse_id]?.tier ?? "OUT",
    });

  const applyPreset = (profitCount: number, breakEvenCount: number) => {
    const priced = declared
      .map((r) => ({ id: r.horse_id, price: runners[r.horse_id]?.price ?? null }))
      .filter((r): r is { id: string; price: number } => r.price !== null)
      .sort((a, b) => a.price - b.price);
    setRunners((previous) => {
      const next = { ...previous };
      for (const r of declared) next[r.horse_id] = { ...next[r.horse_id], tier: "OUT" };
      priced.slice(0, profitCount).forEach((r) => (next[r.id] = { ...next[r.id], tier: "PROFIT" }));
      priced.slice(profitCount, profitCount + breakEvenCount).forEach((r) => (next[r.id] = { ...next[r.id], tier: "BREAK_EVEN" }));
      return next;
    });
  };

  // The request the results panel sends. Non runners and reserves are not in the book.
  const request: CalculateRequest | null = useMemo(() => {
    if (!card || !stakeValid || !commissionValid || declared.length === 0) return null;
    return {
      stake_total: stake,
      commission_rate: commission,
      runners: declared.map((r) => {
        const state = runners[r.horse_id];
        const tier: Tier = state?.tier ?? "OUT";
        return {
          horse_id: r.horse_id,
          horse: r.horse,
          price: state?.price ?? null,
          tier,
          part_fraction: tier === "PART" ? state?.partFraction ?? defaults?.partFraction ?? 0.5 : null,
        };
      }),
    };
  }, [card, declared, runners, stake, commission, stakeValid, commissionValid, defaults?.partFraction]);

  const debouncedRequest = useDebounced(request, 300);
  const [result, setResult] = useState<CalculateResponse | null>(null);
  const [resultError, setResultError] = useState<unknown>(null);
  const [calculating, setCalculating] = useState(false);
  const latest = useRef(0);

  const calculate = useCallback(async (body: CalculateRequest) => {
    const ticket = ++latest.current;
    setCalculating(true);
    try {
      const data = await api<CalculateResponse>("/api/calculate", { method: "POST", body: JSON.stringify(body) });
      if (ticket === latest.current) {
        setResult(data);
        setResultError(null);
      }
    } catch (e) {
      if (ticket === latest.current) setResultError(e);
    } finally {
      if (ticket === latest.current) setCalculating(false);
    }
  }, []);

  useEffect(() => {
    if (debouncedRequest) void calculate(debouncedRequest);
  }, [debouncedRequest, calculate]);

  const resultsByHorse = useMemo(() => {
    const map: Record<string, CalculateResponse["runners"][number]> = {};
    for (const r of result?.runners ?? []) map[r.horse_id] = r;
    return map;
  }, [result]);

  if (cardError) {
    return (
      <div>
        <p>
          <Link to="/races">← Races</Link>
        </p>
        <ErrorBox error={cardError} onRetry={() => void loadCard()} />
      </div>
    );
  }
  if (!card) {
    return (
      <div>
        <p>
          <Link to="/races">← Races</Link>
        </p>
        <p className="muted">Loading the race card from The Racing API…</p>
      </div>
    );
  }

  const { race } = card;
  return (
    <div>
      <p>
        <Link to="/races">← Races</Link>
      </p>
      <h1>{race.race_name ?? "—"}</h1>
      <p className="muted">
        {race.course ?? "—"} · {race.off_time_uk ?? "—"} UK · {race.pattern ?? "no grade"} · {race.distance ?? "—"} · going {race.going ?? "—"} · {race.field_size ?? "—"} runners
      </p>
      <p className="small muted">Prices from The Racing API, card fetched {ukDateTime(card.fetched_at)} UK.</p>
      <RawDrawer title="All race fields" raw={card.raw_race} />

      {defaultsError && <ErrorBox error={defaultsError} onRetry={() => void loadDefaults()} />}

      <div className="panel">
        <div className="toolbar">
          <label className="field">
            Total stake (£)
            <input className="num" type="number" min="0.01" step="1" value={stakeText} onChange={(e) => setStakeText(e.target.value)} />
          </label>
          <label className="field">
            Commission (fraction)
            <input className="num" type="number" min="0" max="0.99" step="0.005" value={commissionText} onChange={(e) => setCommissionText(e.target.value)} />
          </label>
          <button onClick={() => applyPreset(2, 0)}>Top two only</button>
          <button onClick={() => applyPreset(2, 2)}>Four horses</button>
          <button className="small" onClick={() => void loadCard()}>
            Refresh card
          </button>
        </div>
        {!stakeValid && <p className="notice">Total stake must be a number above zero.</p>}
        {!commissionValid && <p className="notice">Commission must be a fraction from 0 up to, but not including, 1 (0.02 is 2%).</p>}
      </div>

      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>Horse</th>
              <th>Exchange price</th>
              <th>Best bookmaker</th>
              <th>Move</th>
              <th>Owner</th>
              <th>Trainer</th>
              <th className="num">OR</th>
              <th>Same owner</th>
              <th>Pace</th>
              <th>Tier</th>
            </tr>
          </thead>
          <tbody>
            {card.runners.map((runner) => {
              const state = runners[runner.horse_id];
              const locked = runner.status !== "DECLARED";
              const noPrice = (state?.price ?? null) === null;
              return (
                <tr key={runner.horse_id} className={locked ? "locked" : ""}>
                  <td>
                    <div>
                      <span className="num muted">{runner.number}</span> <b>{runner.horse}</b>{" "}
                      {runner.draw !== null && <span className="small muted">(draw {runner.draw})</span>}
                    </div>
                    {locked && <span className="badge warn">{runner.status === "NON_RUNNER" ? "Non runner" : "Reserve"}</span>}
                    <div className="small muted">
                      {runner.jockey ?? "—"} · form {runner.form ?? "—"}
                    </div>
                    <RawDrawer title="All fields" raw={runner.raw} />
                  </td>
                  <td>
                    {locked ? (
                      <span className="num">{odds(runner.exchange_price)}</span>
                    ) : (
                      <div>
                        <input
                          className={"num" + (state?.edited ? " edited" : "")}
                          type="number"
                          step="0.01"
                          min="1.01"
                          value={state?.priceText ?? ""}
                          placeholder="no price"
                          onChange={(e) => onPriceInput(runner, e.target.value)}
                        />
                        <div className="small muted">
                          card {odds(runner.exchange_price)} {runner.exchange_updated ? `at ${ukDateTime(runner.exchange_updated)}` : "(none)"}
                          {state?.edited && (
                            <>
                              {" "}
                              <button className="small" onClick={() => resetPrice(runner)}>
                                reset to card
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    )}
                  </td>
                  <td>
                    <span className="num">{odds(runner.best_bookmaker_price)}</span>{" "}
                    <span className="small muted">{runner.best_bookmaker ?? ""}</span>
                  </td>
                  <td>{locked ? <span className="muted">—</span> : <MoveCell raceId={raceId} horseId={runner.horse_id} />}</td>
                  <td>{runner.owner ?? "—"}</td>
                  <td>{runner.trainer ?? "—"}</td>
                  <td className="num">{runner.official_rating ?? "—"}</td>
                  <td>
                    {runner.same_owner_as.length > 0 ? (
                      <span className="badge">
                        with {runner.same_owner_as.join(", ")}
                        {runner.same_trainer_too ? " · same trainer" : ""}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>{locked ? <span className="muted">—</span> : <PaceCell raceId={raceId} horseId={runner.horse_id} />}</td>
                  <td>
                    {locked ? (
                      <span className="muted">—</span>
                    ) : (
                      <div>
                        <select
                          value={state?.tier ?? "OUT"}
                          className={"tier-" + (state?.tier ?? "OUT")}
                          onChange={(e) => setRunner(runner.horse_id, { tier: e.target.value as Tier })}
                          disabled={noPrice}
                          title={noPrice ? "Type a price before choosing a tier" : ""}
                        >
                          {TIERS.map((tier) => (
                            <option key={tier} value={tier}>
                              {tier.replace("_", " ")}
                            </option>
                          ))}
                        </select>
                        {state?.tier === "PART" && (
                          <div className="small">
                            fraction{" "}
                            <input
                              className="num"
                              type="number"
                              min="0"
                              max="1"
                              step="0.05"
                              style={{ width: "5.5rem" }}
                              value={state.partFraction}
                              onChange={(e) => setRunner(runner.horse_id, { partFraction: Math.min(1, Math.max(0, Number(e.target.value))) })}
                            />
                          </div>
                        )}
                        {noPrice && <div className="small muted">no price: OUT until one is typed</div>}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ResultsPanel
        result={result}
        error={resultError}
        calculating={calculating}
        runners={declared}
        resultsByHorse={resultsByHorse}
        onRetry={() => debouncedRequest && void calculate(debouncedRequest)}
        pending={request === null}
      />
    </div>
  );
}
