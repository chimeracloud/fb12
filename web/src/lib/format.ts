// Formats: prices as decimal odds to two decimals; money in pounds to two decimals with
// losses in brackets, for example (£50.00); chances as percents to two decimals; all race
// times in UK time. A dash means missing, never zero.

const UK = "Europe/London";

export function money(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value).toFixed(2);
  return value < -0.004 ? `(£${abs})` : `£${abs}`;
}

export function odds(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

export function pct(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return "—";
  return (fraction * 100).toFixed(2) + "%";
}

export function pctValue(percent: number | null | undefined): string {
  if (percent === null || percent === undefined || Number.isNaN(percent)) return "—";
  return percent.toFixed(2) + "%";
}

export function times(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

export function ukTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: UK }).format(date);
}

export function ukDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: UK }).format(date);
}

export function todayUk(): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: UK, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export function dash(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value.trim() === "" ? "—" : value;
  if (Array.isArray(value)) return value.length === 0 ? "—" : JSON.stringify(value);
  if (typeof value === "object") return Object.keys(value as object).length === 0 ? "—" : JSON.stringify(value);
  return String(value);
}
