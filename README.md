# FB12 Dutch

**Chimera Sports Trading · First Build 12 · graded dutch, paper only.**

Strategy concept: Mark Insley. Architecture and build: Charles Duckitt.

FB12 backs several horses in one race with stakes sized so each horse gives a
chosen result if it wins: a profit (PROFIT), the stake back (BREAK_EVEN), part
of the stake back (PART) or the whole stake lost (OUT). It works out every
outcome at current prices, the expected value at the market's own odds, and the
pacemaker and price movement evidence per runner. It logs paper entries and
settles them against the result. It never places a bet and never connects to
Betfair. Every number comes from The Racing API.

The repo holds both halves: the API in `api/` and the GUI in `web/`. One README
and one CHANGELOG at the root cover both.

## Status

| Part | State | Where |
| --- | --- | --- |
| API shell (admin endpoints, both credential paths) | Deployed and checked, 9 October 2026 (revision `fb12-dutch-api-00003-ztd`, version 0.1.1) | `api/` |
| **Cloud Run URL** | **https://fb12-dutch-api-jptjmb2mfq-ew.a.run.app** (also answers at `https://fb12-dutch-api-991649774709.europe-west1.run.app`). Prompt 2 puts this in the Pages Function's config | europe-west1 |
| Race list and race card (`GET /api/races`, `GET /api/races/{race_id}`) | Deployed (0.2.0). Live check blocked until the service identity is fb12-sa: the default compute account cannot read the Racing API secrets | `api/services/races.py` |
| Calculate (`POST /api/calculate`) | Deployed and checked live against the brief's figures (0.3.0) | `api/services/dutch.py` |
| Recorder (`POST /api/record`) | Deployed and recording: 8 October 2026 and 17 March 2025 recorded live; Cloud Scheduler jobs created, backfill starts 00:00 UK | `api/services/recorder.py` |
| Move and pace (`.../move`, `.../pace`) | Deployed and checked live (0.5.0): Holguin's move from the median of 26 bookmakers, his last five runs classified | `api/services/move.py`, `api/services/pace.py` |
| Paper entries with SP and BSP settlement | Next | — |
| GUI shell, race list, race page with grid and results panel, admin page | Pushed (web 0.1.0); deploys to pages.dev once Charles creates the Pages project; shows data once the subdomain and Access exist and the audience tag is set | `web/` |
| GUI move and pace columns | Pushed (web 0.2.0) | `web/src/components/RunnerEvidence.tsx` |
| GUI paper entries page and "Save as paper entry" | Follow their endpoints; no placeholders in the meantime | `web/` |

Open items for Charles:
- Rotate the Racing API password (it was pasted into a chat on 9 October 2026) and add it as a new version of `racingapi-password`. See docs/INCIDENTS.md.

Current state in detail: [docs/status/latest.md](docs/status/latest.md).
Incidents: [docs/INCIDENTS.md](docs/INCIDENTS.md).

## Standalone, and the access exception

FB12 is a First Build kept outside the Chimera ecosystem by Charles's decision
of 9 October 2026: no CST portal, no portal proxy, no Pub/Sub, no FSU wiring.
The Bible governs how it is built, not what it connects to.

**Exception to CHI-POL-004 and CHI-POL-006, approved by Charles on 9 October
2026.** FB12's Cloud Run service accepts unauthenticated invocation at the IAM
level and FB12 itself is the gate. Reason: the GUI reaches the API through a
Cloudflare Pages Function carrying a Cloudflare Access token, and Cloudflare
cannot present a Google identity, so an IAM invoker binding cannot be the
boundary. Every `/api` and `/admin` request must carry one of two credentials;
anything else gets `401` with no detail.

## Access

| Path | Header | Checked against | Who uses it |
| --- | --- | --- | --- |
| Cloudflare Access token | `Cf-Access-Jwt-Assertion` | Signature against the team domain's published keys, audience against the FB12 Access application's audience tag, issuer against the team domain, expiry | The GUI's Pages Function (prompt 2) |
| Google ID token | `Authorization: Bearer` | Google's published certificates; audience is FB12's own URL (the host the request was sent to) or the gcloud client id that user tokens carry; email verified and on the operator list | Charles and the build agent, before the GUI exists |

Team domain, audience tag and operator list are non-secret config in
`api/config/fb12.json`. Until the team domain and audience tag are set, the
Cloudflare path rejects everything. `saved_by` on paper entries is the email in
the verified credential. No CORS: the browser never calls FB12 directly.

Operators: `cloud@ascotwm.com`, `admin@chimerasportstrading.com`.

Checking an endpoint with an operator token, from a machine where gcloud is
logged in as an operator:

```bash
TOKEN=$(gcloud auth print-identity-token)
curl -s -H "Authorization: Bearer $TOKEN" https://fb12-dutch-api-jptjmb2mfq-ew.a.run.app/admin/health
curl -s -o /dev/null -w "%{http_code}\n" https://fb12-dutch-api-jptjmb2mfq-ew.a.run.app/admin/health   # 401
```

## Resources

| Resource | Name |
| --- | --- |
| GCP project | `chiops` |
| Cloud Run service | `fb12-dutch-api`, region `europe-west1` (Belgium) |
| Service account | `fb12-sa@chiops.iam.gserviceaccount.com` |
| Racing API credentials | Secret Manager `racingapi-username`, `racingapi-password` (fb12-sa has `secretAccessor` on these two only) |
| Admin settings | Firestore `(default)`, collection `fsu-admin-settings`, document `fb12` (fb12-sa has `roles/datastore.user`) |
| Paper entries | GCS `gs://chiops-fb12-paper-entries`, `europe-west2` per CHI-POL-009, uniform access (fb12-sa has `objectAdmin`) |
| GitHub | `chimeracloud/fb12`, branch `main` only |

## Pipeline

Code is written into this repo and never run locally. A push to `main` is the
only path to production. Charles owns the Cloud Run service, its repository
connection and the Cloud Build trigger; the agent uses gcloud only for the
bucket and IAM bindings, and read-only for build status and logs.

The build is `api/Dockerfile`, context `api/`. Stage `test` runs the suite;
stage `runtime` copies a marker from it, so a failing test fails the build and
nothing deploys. The runtime image carries no tests and no dev dependencies.

Cloud Run wizard settings ("Continuously deploy from a repository"):

| Setting | Value |
| --- | --- |
| Repository | GitHub `chimeracloud/fb12` |
| Branch | `^main$` |
| Build type | Dockerfile |
| Source location (Dockerfile) | `/api/Dockerfile`, build context `api` |
| Included files filter (on the Cloud Build trigger) | `api/**` so GUI pushes do not rebuild the API |
| Service name | `fb12-dutch-api` |
| Region | `europe-west1` (Belgium) |
| Authentication | Allow unauthenticated invocations (FB12 is the gate, see above) |
| Service account | `fb12-sa@chiops.iam.gserviceaccount.com` |
| Container port | `8080` |

No environment variables are set on the service: all non-secret config is in
the committed file, and credentials are read from Secret Manager at runtime.

**One instance, always.** The service runs with max instances 1 and a 900 second
request timeout (set with `gcloud run services update ... --max-instances 1
--timeout 900 --service-account fb12-sa@chiops.iam.gserviceaccount.com` on
9 October 2026). The Racing API throttle, the response cache and the recorder's
run lock live in memory, so a second instance would double the request rate
against a shared account and run two recordings at once. Do not raise it.

## The GUI

A standalone React, Vite and TypeScript app in `web/`, on Cloudflare Pages, on a
chimerasportstrading.com subdomain behind Cloudflare Access. Paper only. It
never calculates: every stake, profit, chance and expected value on screen comes
from `POST /api/calculate`. Theme: background `#06060a`, gold `#b8924a`, cream
`#e8e0d0`; Cormorant Garamond for headings, Rajdhani for the UI, JetBrains Mono
for figures. Header "Chimera Sports Trading | FB12 Dutch", footer "Born from
complexity. Engineered for certainty."

The browser never sees FB12's Cloud Run URL. Every `/api` and `/admin` call goes
to a Pages Function on the same hostname (`web/functions/api/[[path]].ts`,
`web/functions/admin/[[path]].ts`), which forwards method, path, query and body
to the API with the `Cf-Access-Jwt-Assertion` header Cloudflare adds, drops any
`Authorization` header or cookie the browser sends, and returns the API's status
and body unchanged, streams included. The API URL is the committed constant in
`web/functions/_config.ts`, built by Pages, never by Vite.

Pages project settings (Charles creates the project; the first push after that
deploys the shell to its pages.dev address):

| Setting | Value |
| --- | --- |
| Repository, production branch | `chimeracloud/fb12`, `main` |
| Root directory | `web` |
| Build command | `npm run build` |
| Build output directory | `dist` |
| Environment variable | `NODE_VERSION` = `22` |
| Build watch paths | Include `web/*` (Cloudflare's `*` matches nested paths), so API pushes do not rebuild the GUI |

Until the subdomain and its Access application exist, calls through the pages.dev
address carry no Access token and the API answers 401; the GUI shows that error
as returned. That is expected.

Access (Charles creates it after the first deploy): a self-hosted Access
application covering the whole subdomain, the same policy as the CST portal, no
bypass rules. Its audience tag and the team domain
(`chimerasportstrading.cloudflareaccess.com` per the June inventory) then go into
`api/config/fb12.json` under `access.cloudflare` and are pushed; the trigger
redeploys the API and the Cloudflare path opens.

Pages: Races (date in UK time, GB and IRE toggles, pattern races only; a row opens
the race), Race (header; total stake and commission from FB12's settings; presets
"Top two only" and "Four horses" on the prices in use; the runner grid with an
editable exchange price beside the card price and its updated time, best
bookmaker, owner, trainer, official rating, same-owner marker, tier with a PART
fraction, and an "all fields" drawer per runner and for the race; the results
panel, recalculated 300 ms after every change with the last figures dimmed while
a call is in flight; Move and Pace columns that load per runner and show their
own error with a retry), Admin (health, status, the settings form built from the
field definitions, config, logs, live stream). The paper entries page arrives
with its endpoints.

## Repository layout

```
api/
  main.py              FastAPI app factory; middleware order; routers
  config/fb12.json     committed non-secret config (team domain, audience tag, operators, resource and secret names)
  core/config.py       config loader (Pydantic v2, extra="forbid"); Cloud Run identity env
  core/auth.py         the gate: Cloudflare Access token and Google ID token verification
  core/credentials.py  get_credential(name): Secret Manager behind one interface (CHI-POL-040)
  core/settings.py     admin settings: field definitions, validation, Firestore persistence
  core/logging.py      JSON logging (service_name, trace_id, timestamp, severity) + ring buffer
  core/events.py       event bus for the SSE stream
  core/errors.py       the error envelope
  core/middleware.py   trace id, timing, counters, one log line per request
  routers/admin.py     the seven ADR 010 endpoints
  models/schemas.py    request models
  services/            Racing API client, dutch maths, pace, paper entries (steps 2 to 5)
  tests/               runs inside the Docker build
  Dockerfile           base -> test -> runtime
docs/INCIDENTS.md      incident log (CHI-POL-048)
docs/status/latest.md  where the unit is now (CHI-POL-053)
web/
  package.json         React 18, Vite 5, TypeScript, react-router
  index.html           the shell; Google Fonts for the three typefaces
  functions/_config.ts the API's Cloud Run URL (committed, never in the bundle)
  functions/_lib/proxy.ts  the forwarding logic
  functions/api/[[path]].ts, functions/admin/[[path]].ts  the Pages Functions
  src/api/client.ts    same-origin fetch with the error envelope
  src/api/types.ts     the contract as TypeScript types
  src/lib/format.ts    money with losses in brackets, odds, percents, UK time
  src/pages/           RaceListPage, RacePage, AdminPage
  src/components/      ResultsPanel, SettingsFormView, RawDrawer, ErrorBox
  src/theme.css        the Chimera dark theme
```

## Configuration

`api/config/fb12.json` ships with every push. Fields: `unit`, `service_name`,
`gcp_project`, `region`, `firestore` (database, collection, document),
`paper_entries_bucket`, `racing_api.base_url`, `credentials` (logical name to
secret id, names only), `access.cloudflare` (`team_domain`, `audience_tag`),
`access.google` (`operators`, `extra_audiences`).

Settings live in Firestore and are edited through `PUT /admin/settings`. The
stored value governs; the code default only applies until something is stored.

| Key | Default | Meaning |
| --- | --- | --- |
| `commission_rate` | 0.02 | Betfair commission on net market winnings |
| `default_stake` | 100 | Total stake the GUI starts with (£) |
| `default_part_fraction` | 0.5 | Share of the stake a PART runner returns |
| `past_runs` | 5 | Previous runs the pace endpoint reads |
| `regions` | gb, ire | Racing API region codes for the race list |
| `request_rate_per_second` | 3 | FB12's own ceiling (the account allows 5 and may be shared) |
| `retry_on_429_max` | 3 | Retries with backoff on a 429 |
| `cache_race_list_seconds` | 300 | |
| `cache_race_card_seconds` | 60 | |
| `cache_odds_seconds` | 60 | |
| `cache_past_runs_seconds` | 86400 | |
| `pace_led`, `pace_prominent`, `pace_held_up`, `pace_midfield` | the lists in the brief | Matched in that order, first match wins; anything else is UNCLASSIFIED |
| `racing_api_username`, `racing_api_password` | masked | Read only; values never leave the credential module |

The service must run as `fb12-sa`. `GET /admin/status` and `GET /admin/config`
report the identity the service actually runs as against the expected one, and a
secret permission failure names that identity in its message. A `PermissionDenied`
on a secret is an identity problem; the credential values are never the answer
and are never needed anywhere.

Credentials: `core/credentials.py` is the one place FB12 reads a credential.
Secret Manager sits behind `get_credential(name)` today (interim, per
CHI-POL-040); values live in memory for the life of the process and are never
logged, stored or returned by an endpoint.

## API contract

JSON throughout. Operational routes under `/api`, admin routes under `/admin`.
Every request needs a valid credential.

Units: money in pounds to two decimals; prices as decimal odds; chances as
fractions from 0 to 1; `book_pct`, `change_pct` and `expected_value_pct` as
percents (for example 103.03); times in ISO 8601 with offset. Tiers: `PROFIT`,
`BREAK_EVEN`, `PART`, `OUT`.

Errors: any failure returns an HTTP error status with
`{"error": {"code": "...", "message": "...", "upstream_status": 429}}`.
Codes: `UPSTREAM_ERROR`, `NOT_FOUND`, `INVALID_INPUT`, `NO_RESULT_YET`. Three more
exist in practice: `UNAUTHENTICATED` (401, body `{"error": {"code":
"UNAUTHENTICATED", "message": "Not authenticated."}}`, no detail),
`INTERNAL_ERROR` (500, an unexpected exception) and `RECORDER_BUSY` (409, a
recording run is already in progress). The message is written to be shown as is.

### Operational endpoints

1. `GET /api/races?date=&regions=gb,ire&pattern_only=false` →
   `{"date", "races": [{"race_id", "off_dt", "off_time_uk", "course", "race_name", "pattern", "race_class", "field_size", "region"}]}`
2. `GET /api/races/{race_id}` →
   `{"race": {"race_id", "off_dt", "off_time_uk", "course", "race_name", "pattern", "distance", "going", "field_size"}, "fetched_at", "runners": [{"horse_id", "horse", "number", "draw", "status" (DECLARED, NON_RUNNER or RESERVE), "owner", "owner_id", "trainer", "trainer_id", "jockey", "official_rating", "form", "exchange_price", "exchange_updated", "best_bookmaker_price", "best_bookmaker", "same_owner_as", "same_trainer_too"}]}`.
   Plus, since 0.4.0: `"raw_race"` (the race object exactly as the Racing API card gives it, without `runners`) and on each runner `"raw"` (the runner object exactly as received, `odds` included). The GUI shows these in an "all fields" drawer per runner; a dash or empty string means missing, never zero. The provider removed `rpr`, `ts`, `tsr`, `spotlight`, `quotes`, `stable_tour` and `betting_forecast` in June 2026: they are always present and always empty, and FB12 passes them through untouched and builds nothing on them. `medical` and `breeder` were not removed and can carry data.
   `exchange_price` is null when the card has no Betfair Exchange price.
   How it is built: from `GET /racecards/{race_id}/pro`. Number `NR` is `NON_RUNNER`, numbers starting `R` are `RESERVE`. `exchange_price` is the card's Betfair Exchange entry with its `updated` time; the API gives that time without an offset and FB12 reads it as UK time. `best_bookmaker_price` is the highest decimal among bookmakers, leaving out Betfair Exchange, Smarkets and Matchbook. `same_owner_as` lists the other declared runners with the same `owner_id`; `same_trainer_too` is true when one of them shares the `trainer_id`. `fetched_at` is when FB12 fetched the card from the API (a cached card keeps its fetch time).
   Race list: from `GET /racecards/pro?date=&region_codes=`; `date` defaults to today in UK time, `regions` to the setting; `pattern_only` keeps races with a pattern. Sorted by off time.
3. `GET /api/races/{race_id}/runners/{horse_id}/move` →
   `{"horse_id", "source" ("bookmaker median", "Betfair Exchange" or null), "first_price", "first_at", "latest_price", "latest_at", "change_pct", "direction" ("shortened", "drifted", "unchanged" or null), "note"}`
   Source order (decided 9 October 2026): the bookmaker median first, Betfair Exchange only when no bookmaker has history. Movement comes from `/odds/{race_id}/{horse_id}` (minute level, every bookmaker, from the evening before to the off); the card's one price per bookmaker shows no movement. "SP" and dash entries are skipped. Exchange prices outside that minute's bookmaker range are dropped (thin early books show 1.1 while bookmakers are at 16/1); the range is each bookmaker's last price at that minute, or its current price when it has no history. The first price is the price at 00:00 UK on race day with each bookmaker's evening price carried forward (or the first price of the day when nothing came before); the latest is the newest price; the median is taken across bookmakers at each of those times. `note` says why fields are null or how the figure was reached ("median of 12 bookmakers with history", "no price history", ...). Race day comes from the race card. Live since 0.5.0.
4. `GET /api/races/{race_id}/runners/{horse_id}/pace?runs=5` →
   `{"horse_id", "counts": {"LED", "PROMINENT", "MIDFIELD", "HELD_UP", "UNCLASSIFIED"}, "runs": [{"date", "course", "race_name", "position", "class", "comment", "category"}]}`, runs newest first, comment raw. Since 0.5.0 each run also carries `category`, the class its comment fell into, so the GUI can show it beside the raw comment.
   How it is built: the horse's last N runs before the race date from `GET /horses/{horse_id}/results?start_date=2000-01-01&end_date=<day before>&limit=N` (N from `runs`, default the `past_runs` setting). The horse's own comment in each run is normalised (lower case, hyphens and punctuation to spaces) and matched against the `pace_*` keyword lists as whole phrases on word boundaries, in the order LED, PROMINENT, HELD_UP, MIDFIELD, first match wins. Anything else is UNCLASSIFIED; "settled just behind the leader" stays unclassified rather than guessed. Live since 0.5.0.
5. `POST /api/calculate` body `{"stake_total", "commission_rate", "runners": [{"horse_id", "horse", "price", "tier", "part_fraction"}]}` →
   `{"feasible", "message", "profit_per_win", "book_pct", "expected_value_gbp", "expected_value_pct", "runners": [{"horse_id", "horse", "tier", "price", "stake", "return_if_wins", "net_if_wins", "net_after_commission", "market_chance", "break_even_chance", "can_break_even", "wins_wiped_out"}]}`.
   No Racing API call, nothing stored. The only place figures are worked out (`services/dutch.py`); paper entries call the same function.
   The maths: T total stake, q = 1 / price. Targets: PROFIT T + P, BREAK_EVEN T, PART part_fraction × T, OUT 0; stake = target / price, so the stakes sum to T. P = T × (1 − Σq over PROFIT and BREAK_EVEN − Σ part_fraction × q over PART) / Σq over PROFIT. No PROFIT runner or P ≤ 0: `feasible` false with the reason in `message`, and stakes, returns, nets, the profit and the expected value are null; nothing is forced. `book_pct` is Σq over every runner (every runner needs a price; if one lacks it, `message` names it and `book_pct`, `market_chance` and the expected value are null). `market_chance` = q / book. Expected value = Σ market_chance × net_if_wins, in pounds and as a percent of T. For OUT and PART runners: `break_even_chance` = E / (E + L) where E is the expected net if that runner does not win (the others' chances rescaled to sum to 1) and L the loss if it does; `can_break_even` is false and the chance null when E ≤ 0; `wins_wiped_out` = L / P. `net_after_commission` reduces a positive net by the commission rate; a loss is unchanged. Rounding: money 2 dp, chances 4 dp, percents 2 dp; the unrounded stakes sum to T exactly.
   Validation (`400 INVALID_INPUT`, every problem listed): stake_total > 0; 0 ≤ commission_rate < 1; price required unless OUT and always above 1.0; part_fraction required for PART, 0 to 1, and only for PART; no horse_id twice.
6. `POST /api/paper` body `{"race_id", "stake_total", "commission_rate", "runners": [{"horse_id", "price", "card_price", "price_edited", "tier", "part_fraction"}]}` → `201 {"entry_id", "status": "OPEN", "saved_at", "saved_by"}`
7. `GET /api/paper?status=` → `{"entries": [{"entry_id", "race_id", "race_name", "course", "off_dt", "saved_at", "saved_by", "status" (OPEN, SETTLED or NEEDS_REVIEW), "pnl", "pnl_after_commission", "pnl_at_sp", "pnl_at_bsp", "pnl_at_bsp_after_commission", "bsp_pending", "review_reason"}]}`
8. `GET /api/paper/{entry_id}` → the entry without the raw API responses, with the same four settlement fields.
9. `POST /api/paper/{entry_id}/settle` → `{"entry_id", "status", "winner", "pnl", "pnl_after_commission", "pnl_at_sp", "pnl_at_bsp", "pnl_at_bsp_after_commission", "bsp_pending", "review_reason"}`; `409 NO_RESULT_YET` when the result is not published.
   Settlement (contract change of 9 October 2026 for 7, 8 and 9): settle pays the winner at the saved prices with the saved stakes, in every case. SP is in the result straight away, so `pnl_at_sp` (bookmaker SP, no commission) is set at once, using the same saved stakes. BSP lands the next day: until then `bsp_pending` is true and `pnl_at_bsp` and `pnl_at_bsp_after_commission` are null; a later settle call fills them. The GUI shows SP and BSP columns and a pending marker. Paper entries keep the card exactly as FB12 saw it at save time. Not yet built.
10. `POST /api/record?date=` (operator only: a Google ID token from the operator list; the GUI's Cloudflare path is refused) → records one day of raw Racing API responses into the recordings bucket. `date` is `YYYY-MM-DD`, `yesterday` or `backfill` (default). Returns `{"mode", "date", "skipped", "reason", "complete", "attempts", "calls", "duration_seconds", "cards", "results", "odds", "errors", "counts": {...}, "manifest", "retried" (yesterday mode), "remaining_estimate" (backfill mode)}`. `409 RECORDER_BUSY` while a run is in progress. See The recorder.

### Admin endpoints (CHI-ADR-010, live in the shell)

| Endpoint | Returns |
| --- | --- |
| `GET /admin/health` | `{"status": "ok", "service", "unit", "version", "revision", "time", "uptime_seconds", "settings_source"}` |
| `GET /admin/status` | `{"service", "unit", "version", "revision", "mode": "paper", "time", "started_at", "uptime_seconds", "requests": {"total", "errors", "error_rate", "by_status"}, "access": {"accepted": {"cloudflare_access", "google_id_token"}, "rejected", "cloudflare_configured", "operators"}, "settings": {"source", "updated_at", "updated_by", "last_error"}, "credentials": {name: "loaded" or "not loaded"}, "identity": {"runs_as", "expected", "matches"}, "racing_api" (counters, see The Racing API below), "stream": {"subscribers", "events_published", "events_dropped"}}` |
| `GET /admin/settings` | The form: `{"service", "unit", "storage": {"backend", "path"}, "source", "updated_at", "updated_by", "last_loaded_at", "last_error", "groups": [{"id", "label", "fields": [{"key", "label", "type", "value", "default", "writable", "help", "min", "max", "step"}]}]}`. Field types: `number`, `integer`, `boolean`, `string`, `list`, `secret`. A `secret` field has `value` masked, `writable` false, plus `secret` (the Secret Manager name) and `state`. Read from Firestore on every call. |
| `PUT /admin/settings` | Body `{"values": {key: value}}`. Returns `{"applied": [keys], "rejected": [{"key", "reason"}], "settings": the form}`. Persisted to Firestore before anything is applied in memory; a failed write returns `502 UPSTREAM_ERROR` and changes nothing. `updated_by` is the credential's email. |
| `GET /admin/config` | Deployment reference: project, region, Cloud Run service and revision, the identity the service runs as against the one expected (`cloud_run.identity`), Python version, Racing API base URL, bucket, Firestore path, access config (team domain, audience tag, operators, audience rule), credential secret names with masked values, pipeline. |
| `GET /admin/logs?limit=100&before=&severity=` | `{"entries": [...newest first], "count", "limit", "newest_seq", "oldest_seq", "next_before", "buffer_size"}`. Each entry: `timestamp`, `severity`, `service_name`, `trace_id`, `logger`, `message`, `seq`, plus the structured fields of that line. In-memory ring buffer of the last 1000 entries of this instance. |
| `GET /admin/stream` | Server-Sent Events. First event `hello` carries the status snapshot. Then `log` (each log entry, `id` = its seq), `settings` (keys changed, by whom) and a `status` heartbeat every 15 seconds of silence. Every event's data is `{"event", "time", "data"}`. Cloud Run closes long requests at its timeout; the client reconnects. |

## The Racing API

Base URL `https://api.theracingapi.com/v1`, HTTP Basic Auth. Field names were
checked against the live OpenAPI document and live responses on 9 October 2026.
FB12 throttles itself to `request_rate_per_second` (default 3; the account
allows 5 and may be shared), backs off and retries on 429 (waiting for
`Retry-After`, else exponential, `retry_on_429_max` times), and caches per
endpoint kind with the `cache_*_seconds` settings. Keep the 3 a second: the
account is capped at 50 calls per 10 seconds at the network edge, and more than
100 calls in 10 seconds from one IP triggers a 5 minute lockout. The racecards
list endpoint itself allows 2 a second; the race list is cached 5 minutes.

A failure comes back as `UPSTREAM_ERROR` (or `NOT_FOUND` for a 404) with the
Racing API's status in `upstream_status` and its body, as is, in the message. A
401 can mean wrong credentials, a plan that does not cover the endpoint, or an
overdue invoice; the message says so. On a 401 FB12 re-reads the two secrets
from Secret Manager once and retries, so a rotated password is picked up
without a restart; a new revision is still rolled on rotation as belt and
braces. Counters are in `GET /admin/status` under `racing_api`.

## The recorder

FB12 owns its history, so every decision can be replayed and scored later.
`POST /api/record` stores The Racing API's responses raw and untouched
(gzip-compressed, served as JSON) in their own bucket, one object per response,
with a manifest per day. Regions GB and IRE by default (French races carry no
exchange prices and no running comments).

What this plan gives, as documented by The Racing API on 9 October 2026, and
what the recorder therefore asks for and nothing more:

| Data | Available | Setting |
| --- | --- | --- |
| Pro racecards (`/racecards/pro?date=`) | from 2023-01-23 | `cards_history_from` |
| Results (`/results?start_date=&end_date=`) | back to 2005-01-01: the historical add-on is active on this account, confirmed 9 October 2026 with a call for 2025-03-17 (35 races, every runner with a BSP) | `results_history_days` (8000) |
| Odds history (`/odds/{race_id}/{horse_id}`) | from 2025-03-17 | `odds_history_from` |

Layout in `gs://chiops-fb12-racingapi-raw` (created 9 October 2026, europe-west2,
uniform access, fb12-sa objectAdmin, the paper entries bucket's settings):

```
cards/{date}.json.gz                      the day's racecards response
results/{date}/page-NN.json.gz            the day's results, one object per page
odds/{date}/{race_id}/{horse_id}.json.gz  one object per runner
manifest/{date}.json                      counts, completeness, fetch times, errors, runs
manifest/_index.json                      per-day summary used to skip complete days
manifest/_state.json                      availability boundaries learned from the API
```

Completeness: a day in the last `bsp_required_within_days` (7) is complete only
when every result carries BSP, plus the cards and every runner's odds history
where the plan offers them. An older day is complete once its results are
stored, with the runners lacking BSP listed in the manifest under
`results.runners_without_bsp` (BSP did not exist in 2005, and even recent days
can have runners that never get one). Incomplete days are retried: the daily run
retries the last `recorder_retry_days` days, and the backfill picks the newest
incomplete day first, so a day the morning run leaves without BSP is picked up
that night. The backfill tries an incomplete day at most once a night, then
moves on. Every run on a day counts towards `recorder_max_attempts` (8); after
that the day is left as it is and its manifest says why. Odds that the API
answers 404 for are recorded as missing, not failed. A results page with no
races on a day whose card has races means the plan does not reach that day: the
day stays incomplete and older days are not asked for results. Days before
2023-01-23 are results only (no card, no odds); the backfill runs back to
`backfill_earliest_date` (2005-01-01).

Overlap: one run at a time, enforced by an in-process lock on the single
instance. A call that arrives while a run is in progress returns `409
RECORDER_BUSY` at once and the next scheduled call picks up. A big day (around
800 runners) takes longer than the 3 minute gap; that is expected. The one gap:
during a deploy Cloud Run can briefly run two instances, so a run on the old
one and a call to the new one could record the same day; the writes are
idempotent raw objects, so nothing is lost or corrupted, and the manifest's
`runs` list shows both.

Modes: `date=YYYY-MM-DD` records that day at any time. `date=yesterday` records
yesterday (UK) and retries recent incomplete days. `date=backfill` records the
newest day not yet complete, newest first, only inside the night window
(`backfill_window_start_hour` to `backfill_window_end_hour`, 00:00 to 06:00 UK),
and answers `skipped` outside it. A backfill call keeps recording days, newest
first, until it has used `backfill_call_budget_seconds` (150); the day in
progress always finishes, so a big day can run past the budget but stays under
the 900 s timeout. A day with odds is about 450 calls and 160 seconds
(8 October 2026 took 471 calls in 160 s); a results-only day before 2023 is two
or three calls. The backfill is about 275,000 calls over about six nights: the
571 odds days in about five, the 7,400 results-only days behind them in about
one. The backfill answer lists every day it recorded (`days`), `days_recorded`,
`calls`, `elapsed_seconds`, `stopped_because` (budget, window or nothing left)
and `remaining_estimate`.

GUI calls go first: recorder calls are background calls that wait while any
foreground request is in flight and share the same `request_rate_per_second`
budget. One run at a time (`409 RECORDER_BUSY`). Progress is in
`GET /admin/status` under `recorder` and on the stream as `recorder` events.

Cloud Scheduler (created with gcloud on 9 October 2026; region europe-west1, HTTP
target, method POST, OIDC token, service account
`fb12-recorder-scheduler@chiops.iam.gserviceaccount.com`, audience
`https://fb12-dutch-api-jptjmb2mfq-ew.a.run.app`, attempt deadline 900 s,
retries 0, time zone Europe/London):

| Job | Schedule | URL |
| --- | --- | --- |
| `fb12-record-daily` | `0 7 * * *` | `https://fb12-dutch-api-jptjmb2mfq-ew.a.run.app/api/record?date=yesterday` |
| `fb12-record-backfill` | `*/3 0-5 * * *` | `https://fb12-dutch-api-jptjmb2mfq-ew.a.run.app/api/record?date=backfill` |

The scheduler account is on the operator list in the committed config; it holds
no roles. A backfill call that finds a run still in progress gets 409 and the
next one three minutes later picks up.

Rotation: when the Racing API password changes, the old one stops working at
once. Add the new value as a new version of `racingapi-password`; FB12 re-reads
the secrets on the first 401 and carries on, and a new revision is rolled as
well. Rotate outside 00:00 to 07:00 UK so the backfill is not running.

## Policies honoured

- CHI-POL-008 Shell First: the shell is the first push; content follows only once the shell is deployed and checked.
- CHI-POL-040: one credential module behind `get_credential(name)`.
- CHI-POL-047: STRATEGY NOTES sections below and in the CHANGELOG; only Claude Strategy writes into them.
- CHI-POL-048: `docs/INCIDENTS.md`.
- CHI-POL-053: `docs/status/latest.md`, overwritten whenever the unit reports.
- CHI-POL-004 / CHI-POL-006: exception recorded above.

## STRATEGY NOTES

No notes yet. Only Claude Strategy writes into this section; the build agent
reads it, acts on it and records what it did in the CHANGELOG.

---

*Born from complexity. Engineered for certainty.*
