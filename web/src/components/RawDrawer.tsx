import { dash } from "../lib/format";

// Every field the Racing API gave, exactly as received. A dash means missing, never zero.
export default function RawDrawer({ title, raw }: { title: string; raw: Record<string, unknown> }) {
  const keys = Object.keys(raw).sort();
  return (
    <details className="drawer">
      <summary>{title}</summary>
      <div className="raw">
        {keys.map((key) => (
          <div key={key}>
            <span className="k">{key}</span>
            <span className="v">{dash(raw[key])}</span>
          </div>
        ))}
      </div>
    </details>
  );
}
