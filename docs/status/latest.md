# FB12 — status

**Unit:** FB12 Dutch (both halves). **Written:** 2026-10-09 16:20 UK, by the build agent.

**State:** API 0.4.2 deployed and recording; backfill changes (7-day BSP rule, one
try a night, 150 s calls) live and proven on 2010-06-05. GUI web 0.1.0 pushed:
shell, races, race page with results panel, admin. It deploys when Charles creates
the Pages project.

**Waiting for (from Charles):**
- Since 16:20 UK: the Cloudflare Pages project (proposed name `fb12-dutch`) with
  root `web`, build `npm run build`, output `dist`, `NODE_VERSION=22`, watch path
  include `web/*`. Then the subdomain, the Access application and its audience tag.
- Since 12:05 UK: the Racing API password rotation and new secret version.

**Last did:** backfill changes, the GUI's first four steps.

**Next:** move and pace in the API with their GUI columns; then paper entries with
SP and BSP settlement and their page. Confirm tonight's backfill from the manifests
tomorrow morning.

**Found and reported, not acted on:** see README (deploy-time double instance; only
`cloud@ascotwm.com` in gcloud here).

**Declined:** nothing.
