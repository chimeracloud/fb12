# FB12 — status

**Unit:** FB12 Dutch (both halves). **Written:** 2026-10-15 15:21 UK, by the build agent.

**State:** paper bets built through all five steps of the 9 October brief: bets
at live prices with a slip, trials for typed prices, no bets after the off
(0.7.0, live and proven on the Pride Stakes bet); settlement without clicks via
`POST /api/paper/settle-due` (0.8.0); per-runner settlement rows, the results
figures and the CSV and JSON export (0.9.0); the GUI's bet slip, entries record,
results page and download (web 0.4.0 to 0.6.0). API 0.9.0 is deployed (Cloud
Build green, read from GitHub's checks) and web 0.6.0 is built on `fb12-dutch`.
0.8.0's build had failed on a response model; 0.9.0 fixed it.

**Blocked on (from Charles):**
- Since 2026-10-15 15:19 UK: `gcloud auth login` on this Mac. The gcloud session expired, so
  the agent cannot mint operator tokens for live checks, read Cloud Build logs, or
  create the `fb12-settle-due` Cloud Scheduler job (settings in the README).
- The Racing API password rotation (since 9 October).

**Also for Charles:** a second Cloudflare Pages project named `fb12` fails on
every push; `fb12-dutch` is the one that builds and serves the subdomain. Delete
or fix `fb12`.

**Next, once gcloud is back:** create `fb12-settle-due` (every 5 minutes), check
the Pride Stakes bet settled itself, confirm the backfill from the manifests,
check the results page through the subdomain.

**Found and reported, not acted on:** see README.

**Declined:** nothing.
