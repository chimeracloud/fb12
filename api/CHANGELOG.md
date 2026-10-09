# Changelog

All notable changes to FB12, both halves. Dates are UK dates. Newest first.

## [0.1.0] — 2026-10-09 — API shell

### Added
- `api/`: FastAPI shell with the seven CHI-ADR-010 admin endpoints (`/admin/health`, `/admin/status`, `GET` and `PUT /admin/settings`, `/admin/config`, `/admin/logs`, `/admin/stream`).
- The gate: every request needs a Cloudflare Access token (signature, audience, issuer, expiry against the team domain) or a Google ID token (Google's certificates, FB12's own URL or the gcloud client id as audience, verified email on the operator list). Anything else is `401` with no detail.
- Committed non-secret config `api/config/fb12.json`: team domain and audience tag (empty until prompt 2), operators `cloud@ascotwm.com` and `admin@chimerasportstrading.com`, resource and secret names.
- Credential module `core/credentials.py` (`get_credential(name)`, Secret Manager behind it, values in memory only).
- Admin settings with field definitions, validation and Firestore persistence (`fsu-admin-settings/fb12`): commission rate 2%, default stake £100, default PART fraction 0.5, past runs 5, regions GB and IRE, pace keyword lists, cache lifetimes, request rate, retries. Credentials shown masked and read only.
- Structured JSON logging (`service_name`, `trace_id`, `timestamp`, `severity`), an in-memory ring buffer for `/admin/logs`, and an event bus for the SSE stream.
- Error envelope `{"error": {"code", "message", "upstream_status"}}`; `UNAUTHENTICATED` and `INTERNAL_ERROR` added to the contract's four codes and recorded in the README.
- Tests (run as a stage of `api/Dockerfile`): 401 on every `/api` and `/admin` route without a credential or with an invalid one; both credential paths against a local signing key; every admin endpoint 200 with an operator token; settings validation, masking and persistence; logs and stream shape.
- Root: README (status, access exception, resources, pipeline, contract), this CHANGELOG, `docs/INCIDENTS.md`, `docs/status/latest.md`, `.gitignore`.

### Infrastructure (run by the build agent with gcloud, 9 October 2026, project chiops)
- `gcloud iam service-accounts create fb12-sa --display-name "FB12 Dutch API"`
- `gcloud secrets add-iam-policy-binding racingapi-username --member serviceAccount:fb12-sa@chiops.iam.gserviceaccount.com --role roles/secretmanager.secretAccessor`
- `gcloud secrets add-iam-policy-binding racingapi-password --member serviceAccount:fb12-sa@chiops.iam.gserviceaccount.com --role roles/secretmanager.secretAccessor`
- `gcloud projects add-iam-policy-binding chiops --member serviceAccount:fb12-sa@chiops.iam.gserviceaccount.com --role roles/datastore.user`
- `gcloud storage buckets create gs://chiops-fb12-paper-entries --location=europe-west2 --uniform-bucket-level-access`
- `gcloud storage buckets add-iam-policy-binding gs://chiops-fb12-paper-entries --member=serviceAccount:fb12-sa@chiops.iam.gserviceaccount.com --role=roles/storage.objectAdmin`

### Decisions recorded
- Exception to CHI-POL-004 and CHI-POL-006 approved by Charles: IAM-level unauthenticated invocation, FB12 is the gate. See README.
- ADR 010's seven admin endpoints, not CHI-POL-008's thirteen (Charles, 9 October 2026).
- Paper entries bucket in `europe-west2` per CHI-POL-009 although the service runs in `europe-west1`.

## STRATEGY NOTES

No dated notes yet. Only Claude Strategy writes here.

---

*Born from complexity. Engineered for certainty.*
