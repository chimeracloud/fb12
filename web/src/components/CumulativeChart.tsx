import { useMemo, useState } from "react";
import type { CumulativePoint } from "../api/types";
import { money, ukDateTime } from "../lib/format";

// Cumulative profit after commission, one point per settled bet in off-time order. One series,
// so no legend: the title names it. Thin 2px line, a zero baseline, a crosshair with a tooltip
// on hover, and the final value labelled directly. Text uses the page's text tokens.
export default function CumulativeChart({ points }: { points: CumulativePoint[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 760;
  const height = 260;
  const pad = { top: 18, right: 64, bottom: 34, left: 56 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;

  const series = useMemo(() => points.map((p, i) => ({ ...p, i, y: p.cumulative ?? 0 })), [points]);
  const ys = [0, ...series.map((p) => p.y)];
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const span = maxY - minY || 1;
  const yPad = span * 0.12;
  const lo = minY - yPad;
  const hi = maxY + yPad;
  const x = (i: number) => pad.left + (series.length <= 1 ? innerW / 2 : (i / (series.length - 1)) * innerW);
  const y = (v: number) => pad.top + ((hi - v) / (hi - lo)) * innerH;

  if (series.length === 0) {
    return <p className="muted">No settled bets yet, so nothing to chart.</p>;
  }

  const path = series.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join(" ");
  const ticks = 4;
  const tickValues = Array.from({ length: ticks + 1 }, (_, k) => lo + ((hi - lo) * k) / ticks);
  const last = series[series.length - 1];
  const active = hover !== null ? series[hover] : null;

  const onMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * width;
    let best = 0;
    let bestDist = Infinity;
    series.forEach((_, i) => {
      const d = Math.abs(x(i) - px);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    setHover(best);
  };

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        role="img"
        aria-label="Cumulative profit after commission by bet"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        style={{ maxWidth: width, display: "block", touchAction: "none" }}
      >
        {tickValues.map((v, k) => (
          <g key={k}>
            <line x1={pad.left} x2={width - pad.right} y1={y(v)} y2={y(v)} stroke="var(--line)" strokeWidth={1} />
            <text x={pad.left - 8} y={y(v) + 4} textAnchor="end" fontSize={11} fill="var(--cream-dim)" fontFamily="var(--font-mono)">
              {money(v)}
            </text>
          </g>
        ))}
        <line x1={pad.left} x2={width - pad.right} y1={y(0)} y2={y(0)} stroke="var(--cream-dim)" strokeWidth={1} strokeDasharray="3 3" />
        <text x={pad.left} y={height - 10} fontSize={11} fill="var(--cream-dim)" fontFamily="var(--font-ui)">
          bet 1
        </text>
        <text x={width - pad.right} y={height - 10} textAnchor="end" fontSize={11} fill="var(--cream-dim)" fontFamily="var(--font-ui)">
          bet {series.length}
        </text>
        <path d={path} fill="none" stroke="var(--gold)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={x(last.i)} cy={y(last.y)} r={4} fill="var(--gold)" stroke="var(--bg-raised)" strokeWidth={2} />
        <text x={x(last.i) + 8} y={y(last.y) + 4} fontSize={12} fill="var(--cream)" fontFamily="var(--font-mono)">
          {money(last.y)}
        </text>
        {active && (
          <g>
            <line x1={x(active.i)} x2={x(active.i)} y1={pad.top} y2={height - pad.bottom} stroke="var(--cream-dim)" strokeWidth={1} />
            <circle cx={x(active.i)} cy={y(active.y)} r={5} fill="var(--gold)" stroke="var(--bg-raised)" strokeWidth={2} />
          </g>
        )}
        <rect x={pad.left} y={pad.top} width={innerW} height={innerH} fill="transparent" />
      </svg>
      <div className="small" style={{ minHeight: "2.4rem" }}>
        {active ? (
          <span>
            Bet {active.i + 1} · {active.race_name ?? "—"} ({active.course ?? "—"}) · off {ukDateTime(active.off_dt)} UK · winner {active.winner ?? "—"} · this bet{" "}
            <span className={(active.pnl ?? 0) < -0.004 ? "loss" : (active.pnl ?? 0) > 0.004 ? "gain" : ""}>{money(active.pnl)}</span> · cumulative{" "}
            <b>{money(active.cumulative)}</b>
            {active.expected !== null ? ` · expected ${money(active.expected)}` : ""}
          </span>
        ) : (
          <span className="muted">Hover a point for the bet behind it.</span>
        )}
      </div>
    </div>
  );
}
