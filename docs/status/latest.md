# FB12 — status

**Unit:** FB12 Dutch (both halves). **Written:** 2026-10-09 14:41 UK, by the build agent.

**State:** the API is finished for prompt 1: every contract endpoint deployed
(0.6.1) and checked live, including paper entry `pe_20261009T130900_dcfa61`
settled against the Challenge Stakes result at 14:39 UK (Never So Brave won,
£0.00 at the saved prices, BSP pending). The GUI is live at
https://fb12.chimerasportstrading.com behind Cloudflare Access; the Cloudflare
path on the API opened at 14:45 UK with the team domain and audience tag in the
committed config. The recorder is live; the backfill starts 00:00 UK.

**Waiting for (from Charles):**
- A reload of the GUI to confirm data shows through the subdomain.
- The Racing API password rotation and new secret version (since 12:05 UK).

**Next:** confirm the GUI shows data through the subdomain; fetch BSP on the
settled entry tomorrow; confirm tonight's backfill from the manifests tomorrow.

**Found and reported, not acted on:** see README (deploy-time double instance;
only `cloud@ascotwm.com` in gcloud here). Earlier status timestamps today were
written from an estimate rather than the clock and ran up to three hours fast;
from this entry they come from the clock.

**Declined:** nothing.
