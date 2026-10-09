# FB12 — Incident log

Per CHI-POL-048. Newest first. Nothing is ever deleted from this file. An
incident is recorded even when nothing was lost, and especially when it was
the agent's own defect. The detection line is the one that matters.

Form:

```
## YYYY-MM-DD — one line title
**Detected:** when, and by what
**Started:** when it actually began, or unknown with the reason
**Duration:** silent period, if it was silent
**What happened:** plainly
**What it cost:** data, money, time; unknown where unknown
**Cause:** established, or suspected and labelled as such
**Fixed:** what changed, in which commit, or NOT FIXED
**How it would be caught next time:** the detection, not the fix
**Status:** OPEN · FIXED · RECORDED NOT FIXED
```

---

## 2026-10-09 — Racing API username and password pasted into the build agent's chat
**Detected:** on receipt, by the build agent, 2026-10-09 about 12:05 UK.
**Started:** the moment of the paste.
**Duration:** none silent; the agent refused the values at once.
**What happened:** while FB12's race endpoints were failing with PermissionDenied on the Racing API secrets, the live username and password were pasted into the agent conversation. The failure was never about the values: the Cloud Run service runs as the default compute account, which has no access to the two secrets. The agent did not use, store, log or echo the values; nothing in this repository, its memory or its terminal carries them.
**What it cost:** nothing known. The values now exist in a chat transcript outside Chimera's control.
**Cause:** a permission failure read as a credential failure, under time pressure. The error message named the secret, not the identity that lacked access.
**Fixed:** NOT FIXED by the agent: rotation is a Racing API account action. Charles rotates the password in The Racing API account and adds a new version to `racingapi-password` (and `racingapi-username` if it changes); FB12 picks up the new version on its next cold start, or sooner via a redeploy. The error message is being changed to name the service identity that lacked access, so the next reader fixes the identity, not the credential.
**How it would be caught next time:** `GET /admin/status` shows `credentials` as `not loaded` and `/admin/config` names the identity; a `PermissionDenied` on a secret is an identity problem by definition. A message that says so stops the reflex to paste.
**Status:** OPEN until the password is rotated.

---

Log opened 9 October 2026 with the API shell.
