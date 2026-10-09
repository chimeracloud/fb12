// The API contract (README, "API contract"). Field names are the API's; the GUI never
// calculates, it renders what these carry.

export type Tier = "PROFIT" | "BREAK_EVEN" | "PART" | "OUT";
export type RunnerStatus = "DECLARED" | "NON_RUNNER" | "RESERVE";

export interface RaceSummary {
  race_id: string;
  off_dt: string | null;
  off_time_uk: string | null;
  course: string | null;
  race_name: string | null;
  pattern: string | null;
  race_class: string | null;
  field_size: number | null;
  region: string | null;
}

export interface RaceList {
  date: string;
  races: RaceSummary[];
}

export interface RaceHeader {
  race_id: string;
  off_dt: string | null;
  off_time_uk: string | null;
  course: string | null;
  race_name: string | null;
  pattern: string | null;
  distance: string | null;
  going: string | null;
  field_size: number | null;
}

export interface RunnerCard {
  horse_id: string;
  horse: string;
  number: string;
  draw: number | null;
  status: RunnerStatus;
  owner: string | null;
  owner_id: string | null;
  trainer: string | null;
  trainer_id: string | null;
  jockey: string | null;
  official_rating: number | null;
  form: string | null;
  exchange_price: number | null;
  exchange_updated: string | null;
  best_bookmaker_price: number | null;
  best_bookmaker: string | null;
  same_owner_as: string[];
  same_trainer_too: boolean;
  raw: Record<string, unknown>;
}

export interface RaceCard {
  race: RaceHeader;
  fetched_at: string;
  raw_race: Record<string, unknown>;
  runners: RunnerCard[];
}

export interface CalculateRunnerIn {
  horse_id: string;
  horse: string;
  price: number | null;
  tier: Tier;
  part_fraction: number | null;
}

export interface CalculateRequest {
  stake_total: number;
  commission_rate: number;
  runners: CalculateRunnerIn[];
}

export interface CalculateRunnerOut {
  horse_id: string;
  horse: string;
  tier: Tier;
  price: number | null;
  stake: number | null;
  return_if_wins: number | null;
  net_if_wins: number | null;
  net_after_commission: number | null;
  market_chance: number | null;
  break_even_chance: number | null;
  can_break_even: boolean | null;
  wins_wiped_out: number | null;
}

export interface CalculateResponse {
  feasible: boolean;
  message: string | null;
  profit_per_win: number | null;
  book_pct: number | null;
  expected_value_gbp: number | null;
  expected_value_pct: number | null;
  runners: CalculateRunnerOut[];
}

// Admin (CHI-ADR-010), shapes as the API documents them in the README.
export interface SettingsField {
  key: string;
  label: string;
  type: "number" | "integer" | "boolean" | "string" | "list" | "secret";
  value: unknown;
  default?: unknown;
  writable: boolean;
  help?: string;
  min?: number | null;
  max?: number | null;
  step?: number | null;
  secret?: string | null;
  state?: string;
}

export interface SettingsGroup {
  id: string;
  label: string;
  fields: SettingsField[];
}

export interface SettingsForm {
  service: string;
  unit: string;
  storage: { backend: string; path: string | null };
  source: string;
  updated_at: string | null;
  updated_by: string | null;
  last_loaded_at: string | null;
  last_error: string | null;
  groups: SettingsGroup[];
}

export interface SettingsPutResponse {
  applied: string[];
  rejected: { key: string; reason: string }[];
  settings: SettingsForm;
}

export interface LogEntry {
  seq: number;
  timestamp: string;
  severity: string;
  message: string;
  [key: string]: unknown;
}

export interface LogsResponse {
  entries: LogEntry[];
  count: number;
  next_before: number | null;
}

export type Health = Record<string, unknown> & { status: string; version: string; revision: string | null; time: string };
export type Status = Record<string, unknown>;
export type Config = Record<string, unknown>;

export interface MoveResponse {
  horse_id: string;
  source: "bookmaker median" | "Betfair Exchange" | null;
  first_price: number | null;
  first_at: string | null;
  latest_price: number | null;
  latest_at: string | null;
  change_pct: number | null;
  direction: "shortened" | "drifted" | "unchanged" | null;
  note: string | null;
}

export type PaceCategory = "LED" | "PROMINENT" | "MIDFIELD" | "HELD_UP" | "UNCLASSIFIED";

export interface PaceRun {
  date: string | null;
  course: string | null;
  race_name: string | null;
  position: string | null;
  class: string | null;
  comment: string | null;
  category: PaceCategory;
}

export interface PaceResponse {
  horse_id: string;
  counts: Record<PaceCategory, number>;
  runs: PaceRun[];
}

export type PaperStatus = "OPEN" | "SETTLED" | "NEEDS_REVIEW";

export interface PaperRunnerIn {
  horse_id: string;
  price: number | null;
  card_price: number | null;
  price_edited: boolean;
  tier: Tier;
  part_fraction: number | null;
}

export interface PaperRequest {
  race_id: string;
  stake_total: number;
  commission_rate: number;
  runners: PaperRunnerIn[];
}

export interface PaperCreated {
  entry_id: string;
  status: "OPEN";
  saved_at: string;
  saved_by: string;
}

export interface PaperListItem {
  entry_id: string;
  race_id: string;
  race_name: string | null;
  course: string | null;
  off_dt: string | null;
  saved_at: string;
  saved_by: string;
  status: PaperStatus;
  pnl: number | null;
  pnl_after_commission: number | null;
  pnl_at_sp: number | null;
  pnl_at_bsp: number | null;
  pnl_at_bsp_after_commission: number | null;
  bsp_pending: boolean | null;
  review_reason: string | null;
}

export interface SettleResponse {
  entry_id: string;
  status: PaperStatus;
  winner: string | null;
  pnl: number | null;
  pnl_after_commission: number | null;
  pnl_at_sp: number | null;
  pnl_at_bsp: number | null;
  pnl_at_bsp_after_commission: number | null;
  bsp_pending: boolean | null;
  review_reason: string | null;
}

export interface PaperEntry {
  entry_id: string;
  status: PaperStatus;
  saved_at: string;
  saved_by: string;
  race: { race_id: string; race_name: string | null; course: string | null; off_dt: string | null; off_time_uk: string | null; card_fetched_at: string };
  inputs: { stake_total: number; commission_rate: number; runners: (PaperRunnerIn & { horse: string })[] };
  figures: CalculateResponse;
  settlement: (SettleResponse & { winner_tier?: string | null; winner_stake?: number | null; winner_sp_dec?: number | null; winner_bsp?: number | null; settled_at?: string; note?: string | null }) | null;
  result_summary: {
    winner: string | null;
    winners: string[];
    positions: { position: string | null; horse_id: string | null; horse: string | null; sp: string | null; sp_dec: string | null; bsp: string | null; btn: string | null }[];
    non_runners: string | null;
  } | null;
}
