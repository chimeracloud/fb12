# FB12 — status

**Unit:** FB12 Dutch (both halves). **Written:** 2026-10-09 14:09 UK, by the build agent.

**State:** every API endpoint of the contract is deployed (0.6.0) and checked live
except settlement against a published result, which waits for the Challenge
Stakes result (off 14:25 UK today): paper entry `pe_20261009T130900_dcfa61` is
saved and answers NO_RESULT_YET until then. The recorder is live and the backfill
starts 00:00 UK. The GUI (web 0.3.0: races, race page with move, pace and the
results panel, paper entries, admin) is pushed and deploys when Charles creates
the Pages project.

**Waiting for (from Charles):**
- The Cloudflare Pages project (proposed `fb12-dutch`; settings in the README),
  then the subdomain, the Access application and its audience tag.
- The Racing API password rotation and new secret version (since 12:05 UK).

**Next:** settle the live entry once the result is published; confirm tonight's
backfill from the manifests tomorrow; set the team domain and audience tag when
they arrive; check the GUI through the subdomain.

**Found and reported, not acted on:** see README (deploy-time double instance;
only `cloud@ascotwm.com` in gcloud here). Earlier status timestamps today were
written from an estimate rather than the clock and ran up to three hours fast;
from this entry they come from the clock.

**Declined:** nothing.
