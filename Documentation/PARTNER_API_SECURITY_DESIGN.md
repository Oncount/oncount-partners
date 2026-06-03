# Partner ↔ api Security Design — Centralizing Kommo & Wazzup

_Status: DESIGN / for review. No api code is written yet (CONTRIBUTING.md diff-only rule)._
_Date: 2026-06-03. Scope: how `oncount-partners` (the Python/FastAPI partner service)
talks to `api` (NestJS) now that all Kommo CRM and Wazzup WhatsApp access is centralized._

---

## 1. Threat model — the premise

We treat **oncount-partners as an untrusted client of api**. It is a smaller,
separately-deployed service (originally a personal repo) and we want a bug or a
full compromise of it to have a **bounded blast radius** against api, the Kommo
CRM, and our WhatsApp number.

Design principle: **authenticate, then least-privilege, then contain.** A shared
secret only answers "is this the partner app?" — it does nothing about "what can a
compromised partner app do?". So authentication is layer 1 of several.

What we are explicitly defending:

| Asset | Threat if partner app is hostile/compromised | Containment in this design |
|---|---|---|
| Kommo CRM | Arbitrary lead/contact mutation, pipeline tampering, data exfiltration | Partner can only create leads in the agent pipeline; reads return agent fields only; no admin sync/scoring routes reachable |
| Our WhatsApp number (Wazzup) | Sending arbitrary text to arbitrary numbers (spam/phishing from our brand) | **No free-text send exists.** Only typed/templated messages with api-owned bodies and api-validated recipients |
| Kommo API quota | Flooding api → api gets rate-limited by Kommo (~5 req/s) → our own sync jobs starve | Per-key rate limits on the partner surface, tighter than the global throttler |
| Login codes | Credential theft if codes flow through the less-trusted service | Code generation + verification **move into api**; partner app never handles the credential |

---

## 2. What the WhatsApp capability is actually for (audit result)

We audited every `send_wa_code` / `send_wa_text` call site in oncount-partners.
There is **no feature that lets a partner send arbitrary text to our contacts.**
Every recipient is one of:

| # | Call site | Recipient | Body | Notes |
|---|---|---|---|---|
| 1 | `POST /auth/phone/request` (`main.py:1569`) | **The partner themselves** | Login code | Recipient gated by `find_partner_by_phone` — must already be a known agent, else nothing is sent |
| 2 | `POST /account/phone/request` (`main.py:1713`) | **The partner themselves** | Verification code | Proves ownership of a number the partner is adding to their own cabinet |
| 3 | `send_notification` → `send_wa_text` (`notifications.py:262`) | **The partner (agent)** | Digest / win-push | WhatsApp only as fallback when the partner has no Telegram |
| 4 | Leadmagnet delivery (`main.py:1242`) | **A fresh inbound lead** | Corp-tax PDF link | Sent to the person who just submitted `/guide/corp-tax` seconds earlier |

Conclusion: the capability was built to message **partners** (cases 1–3) plus one
**opt-in lead** (case 4). It was never a generic sender. The design below preserves
exactly these four behaviours and nothing more.

---

## 3. Decisions locked

1. **Auth:** dedicated `PARTNER_API_KEY` via an `x-api-key` guard (not JWT, not the
   shared `ZOHO_EXPORT_API_KEY`).
2. **Surface:** a new, minimal `/api/partner/*` controller. The existing
   `/api/kommo/*` admin surface stays **off-limits** to the partner key.
3. **Wazzup:** **no free-text-to-contacts.** Typed/templated operations only; api
   owns every message body.
4. **Login codes:** **stay in the partner service** (generation, storage, and
   verification — its `PhoneLoginToken` flow is unchanged). _Revised 2026-06-03 from
   the earlier "move codes to api" idea:_ a login code authenticates the partner's
   users to the partner's own cabinet; it does not protect api or Kommo, so moving it
   buys no reduction in **api's** blast radius and would mean rewriting a live login
   path. Only the WhatsApp **send** is centralized (templated `login_code` type, §5.5)
   so a leaked partner key still can't free-text contacts.
5. **(O1) Login-code recipient:** the partner service already gates code sends to
   known partners (`find_partner_by_phone`); the templated send endpoint additionally
   refuses unknown recipients. Response stays neutral (no enumeration oracle).
6. **(O2) Network boundary:** enforced at the **EC2 Security Group** (allow api's
   port only from Railway's static egress IP `/32`), **not** in app code. The key is
   layer 1; the SG is layer 2. See §4.1/§4.2.
7. **(O3) Notifications:** digest/win **logic stays in the partner service**; only
   the **send** moves behind a templated api endpoint (recipient + body owned by api).
8. **(O4) Leadmagnet:** asset delivery requires a **correlation id** proving the
   lead just opted in; no delivery to arbitrary numbers.
9. **(O5) Code parameters:** TTL (10 min), max attempts (≤5), and request rate limit
   **stay in the partner service** (follows from #4 — the partner still owns codes).
10. **Phasing:** PR 1 centralizes **Kommo** (read endpoints + lead-create) and points
    the partner Kommo calls at `/api/partner/*`. PR 2 centralizes **Wazzup sends** via
    a single templated `/api/partner/notify` (types: `login_code`, `digest`, `win`,
    `leadmagnet`). Until PR 2 ships, the partner sends WhatsApp directly as before.

---

## 4. Authentication — `PartnerApiKeyGuard`

Reuse the existing `x-api-key` pattern (`accounting.controller.ts:253-261`) but
harden it into a reusable guard rather than an inline header check.

- New env var **`PARTNER_API_KEY`** (api side) — a long random secret, **separate**
  from `ZOHO_EXPORT_API_KEY` so partner access can be rotated/revoked independently
  and attributed in logs.
- Implemented as `PartnerApiKeyGuard` (a NestJS `CanActivate`) applied with
  `@UseGuards(PartnerApiKeyGuard)` at the **controller** level, so it cannot be
  forgotten on a newly-added route.
- Comparison uses **`crypto.timingSafeEqual`**, not `!==` (the inline accounting
  version is timing-leaky). Reject missing/short keys before comparing.
- On failure: `401`, log the route + source IP + a key *fingerprint* (never the key).

Partner side: `app/api_client.py` adds the header `x-api-key: <PARTNER_API_KEY>` to
every request, read from a new `PARTNER_API_KEY` env var on the partner service.
This is the **only** partner-side code change required for auth.

JWT was considered and rejected here: the relationship is service-to-service with
no per-user identity to carry, and a static key is simpler to rotate and reason
about than a JWT issuance/refresh flow. JWT's claims/expiry/per-user advantages buy
nothing in this single-caller relationship.

### 4.1 Network boundary — AWS Security Group, NOT an in-app IP check (O2, revised)

**Topology:** the partner service runs on **Railway**; api runs on **AWS EC2**. They
do not share a private network, so partner→api goes over the public internet. The
key is **layer 1 (who)**; the network boundary is **layer 2 (where-from)** — and the
correct place to enforce "where-from" is the **EC2 Security Group**, not NestJS.

Why not an in-app IP allowlist:
- An in-app check must read `req.ip`, which behind any proxy/ALB reflects the proxy,
  not the caller, unless Express `trust proxy` is set to exactly the right hop count.
  Get it wrong and you either block everyone or — worse — trust a forgeable
  `X-Forwarded-For` header, giving false confidence. We are NOT going to gate
  security on a header the app chooses to trust.
- A Security Group rule sees the **real TCP source address**, which cannot be spoofed
  with an HTTP header, and drops hostile packets **before they reach Node**.

**The design (two layers):**
1. **Layer 1 — `PartnerApiKeyGuard` (in api):** constant-time `PARTNER_API_KEY` check,
   scopes the caller to `/api/partner/*`. (Implemented in this slice.)
2. **Layer 2 — EC2 Security Group (in AWS):** inbound rule allowing api's port only
   from the partner service's **static Railway egress IP** (`/32`). A leaked key is
   then useless from anywhere but that one address.

`/32` is CIDR notation for a single host (one IP). If Railway ever gives a small
range instead of a single address, the rule uses the corresponding CIDR block(s).

No api code reads the IP, and **`main.ts` needs no `trust proxy` change** for this.

### 4.2 Runbook — establishing the network boundary

1. **Enable static egress on Railway** for the partner service (Railway's static
   outbound IP feature). Without it, Railway's egress rotates and is shared across
   tenants — not a boundary worth pinning.
2. **Read the assigned egress IP.** Railway shows it in the service's networking
   settings. Confirm empirically: have the partner service make one outbound call to
   an echo endpoint (e.g. `https://api.ipify.org`) and log the returned address —
   that is the IP AWS will see.
3. **Add an EC2 Security Group inbound rule:** allow api's listening port (the HTTPS
   port fronting api) **only** from `<railway-egress-IP>/32`. Keep any existing rules
   for other legitimate callers; this rule is additive and specific to partner.
4. **Set `PARTNER_API_KEY`** (a long random secret) in api's env and the same value
   in the partner service's env. Rotation: generate new → set on api → set on partner
   → remove old. Because the key is dedicated, rotation never affects other callers.
5. **Operational tripwire:** if Railway's static egress IP changes (plan change,
   region move), the SG rule must be updated or the partner service is locked out.
   Document this next to the key-rotation note.

> If api later sits behind an ALB/CloudFront where the SG can't see the true source,
> revisit: either keep the SG on the instance/origin layer, or move the allowlist to
> the ALB/WAF — still **not** into the app via `trust proxy`.

---

## 5. The `/api/partner/*` surface (proposed)

Six endpoints. All under `@UseGuards(PartnerApiKeyGuard)` and a tight `@Throttle`.
(Remember the global `/api` prefix — full paths shown.)

### 5.1 Kommo — lead create (case from quiz/masterclass/leadmagnet)

```
POST /api/partner/leads/consultation
body: { name?, phone, answers?, agent_enum_id?, utm?, ref_slug?,
        lead_prefix?, lead_tag?, note_intro?, question_titles? }
→ 200 { status: "sent"|"dry"|"failed", kommo_lead_id?: number,
        lead_correlation_id?: string, error?: string }
```

`lead_correlation_id` is a short-lived, single-use token api issues alongside a
successfully created lead; the leadmagnet flow (5.6) passes it back to authorize PDF
delivery to the same opt-in lead (O4).

Constraints enforced **server-side** (the containment, not just validation):
- Pipeline is **forced** to the agent pipeline (`11126307`) and the regular entry
  stage. The partner app **cannot** target another pipeline/status even if it sends
  one — api ignores partner-supplied pipeline fields entirely.
- Strict DTO: whitelist known fields, reject unknown ones (`forbidNonWhitelisted`).
- Contact dedup + `/leads/complex` + note attachment all happen api-side (this is
  the logic that used to live in `app/kommo_lead.py`).

### 5.2 Kommo — agent leads (read, for the hourly sync)

```
GET /api/partner/agent-leads?pipeline_id=11126307
→ 200 { leads: [ { kommo_lead_id, agent_enum_id, status, amount_aed, client_name } ] }
```

- **Flat shape** (decided earlier): api maps Kommo's `status_id` → `won|lost|in_progress`,
  extracts the `ID AGENT` enum and the display name. The Kommo wire format
  (`custom_fields_values`, raw `142/143`) never crosses to the partner service.
- Read-only; returns agent-relevant fields only — no PII beyond `client_name`.

### 5.3 Kommo — agent enums (read, for partner seeding)

```
GET /api/partner/agent-enums
→ 200 { enums: [ { id, value } ] }
```

- Returns the `ID AGENT` (field `961886`) enum list. Read-only.

### 5.4 Wazzup — login code (templated, code owned by api)

```
POST /api/partner/login-code/request
body: { phone, lang? }
→ 200 { sent: boolean }   // neutral response, anti-enumeration
```

- **api generates** the 6-digit code, **stores** its hash + TTL + attempt counter,
  and renders the templated message. The partner app never sees or stores the code.
- api resolves whether `phone` is a known partner (mirrors today's
  `find_partner_by_phone` gate). **Unknown number → api refuses to send** (O1), but
  still returns the same neutral `{ sent: true }` shape so the response is not an
  enumeration oracle. "Refuse" here means no code is generated/stored and no packet
  leaves api for non-partner numbers — only the response is made to look identical.
- Rate-limited per phone (mirror current `PHONE_RATE_LIMIT`) **and** per key.

```
POST /api/partner/login-code/verify
body: { phone, code }
→ 200 { valid: boolean }
```

- api checks hash + TTL + attempts, marks consumed on success, returns only a
  boolean. The partner app then issues its own session cookie as today (the JWT
  cookie stays a partner-app concern; only the *code credential* moves to api).
- One neutral failure for all reject paths (expired / wrong / out of attempts /
  unknown) — preserves the current anti-enumeration property.

> **Migration note (partner side, later):** this replaces the `PhoneLoginToken`
> table and `hash_login_code`/`verify_login_code` usage in `oncount-partners`. The
> auth handlers (`/auth/phone/request|verify`, `/account/phone/request|verify`)
> stop generating/storing codes and instead call these two endpoints. This is a
> follow-up change to the partner repo, tracked separately from today's work.

### 5.5 Wazzup — partner notification (templated)

```
POST /api/partner/notify
body: { partner_ref, type: "digest"|"win", params: {...} }
→ 200 { sent: boolean, channel: "wa"|"tg"|"none" }
```

**Resolved (O3): the digest/win *logic* stays in the partner service** (it owns the
adaptive weekly/monthly selection, `partner_id % 7` spreading, and the
`notification_attempts` audit). **Only the send is moved behind this templated
endpoint.** So the partner service decides *whether*, *whom*, and *which type* to
notify; api decides the *text* and performs the send.

- The partner app passes `partner_ref` (the partner's id/ref, **not** a raw phone)
  and a `type` + `params`. api resolves the recipient from the partner record and
  renders the body from api-owned templates. The partner app cannot supply a
  destination phone or message body.
- This keeps the phishing surface closed (no free text) while leaving the digest
  business logic and audit trail where they already live and are tested.
- The partner-side `NOTIFICATIONS_LIVE` guard and channel resolution
  (Telegram-first, WhatsApp-fallback) stay partner-side; api is invoked only for the
  WhatsApp leg of a notification the partner has already decided to send.

### 5.6 Wazzup — leadmagnet asset (whitelisted asset, not free text)

```
POST /api/partner/leadmagnet/deliver
body: { phone, asset_id: "corp-tax-guide", lead_correlation_id }
→ 200 { sent: boolean }
```

- `asset_id` selects from a **server-side whitelist** of assets (the corp-tax PDF
  link today). The partner app cannot supply the message body or an arbitrary URL.
- **Resolved (O4): a correlation id is required.** api will only deliver the asset
  if `lead_correlation_id` matches a consultation lead created (via 5.1) in the same
  opt-in flow, and the `phone` matches that lead. This prevents 5.6 from being used
  to blast the PDF to arbitrary numbers — delivery is bound to a real, just-created
  opt-in. The id is returned by 5.1 and passed straight through; it expires quickly
  (short TTL, single use).

**There is deliberately no `POST /api/partner/messages {phone, text}`.** Free-text
outbound is the phishing vector; it does not exist in this surface.

---

## 6. Rate limiting & quota protection

- Apply a dedicated `@Throttle` to the `/api/partner/*` controller, **tighter** than
  the global `short: 100/min`. Reads (agent-leads/enums) can be loose; the Wazzup
  sends (5.4–5.6) should be tight (e.g. single-digit per minute) since they fan out
  to our WhatsApp number and to Kommo.
- Independently, api enforces a **hard daily send cap** to WhatsApp regardless of
  what the partner requests (mirrors today's `WA_DAILY_LIMIT = 40`/channel). This
  bounds spam even if the per-minute throttle is somehow bypassed.
- Lead-create and agent-sync share api's existing Kommo client throttle (200ms /
  ~5 req/s). A partner flood is absorbed by that throttle rather than passed through
  to Kommo, protecting api's own sync jobs.

---

## 7. Network & operational hygiene

- HTTPS only. Cross-host (Railway → EC2), so the network boundary is the EC2 Security
  Group (§4.1/§4.2), not a private network.
- `PARTNER_API_KEY` stored in env on **both** services (Railway for partner, EC2/api).
  Rotation: generate new → set on api → set on partner → remove old. Because the key
  is dedicated, rotation never affects other callers.
- Log every partner call: key fingerprint, route, outcome, and (for sends) masked
  recipient — never the code, never full phone, never the key.

---

## 8. Partner-side impact summary

| Change | When | File(s) |
|---|---|---|
| Add `x-api-key: PARTNER_API_KEY` header to all calls | with this design | `app/api_client.py`, `app/config.py`, `.env.example` |
| Point client paths at `/api/partner/*` (from `/api/kommo/*`, `/api/wazzup/*`) | with this design | `app/api_client.py` |
| Move phone-login code gen/verify to api (drop `PhoneLoginToken`, call 5.4) | follow-up | `app/main.py` auth handlers, `app/auth.py`, `app/models.py` |
| Leadmagnet: send `asset_id` instead of rendered text | follow-up | `app/main.py:1242`, `app/leadmagnet_config.py` |
| Notifications: keep logic partner-side, swap WhatsApp send for templated 5.5 call (O3) | follow-up | `app/notifications.py` |

Today's already-applied partner changes (the `api_client.py` delegation) remain
valid; only the **base path** (`/partner/` vs `/kommo/`+`/wazzup/`) and the **auth
header** need to be reconciled once the api surface exists.

---

## 9. Resolved decisions (formerly open questions)

All resolved 2026-06-03.

- **O1 — Login-code recipient: REFUSE.** api does not generate, store, or send a code
  for a number that isn't a known partner. The response stays neutral (`{sent:true}`)
  so it cannot be used to enumerate which numbers are partners. See §5.4.
- **O2 — Network boundary: YES, via AWS Security Group (not in-app).** partner is on
  Railway, api on EC2. The boundary is an EC2 SG inbound rule allowing api's port only
  from Railway's **static egress IP** (`/32`) — real, unspoofable TCP source, dropped
  before the app. We deliberately do **not** do an in-app IP check (it would depend on
  forgeable `X-Forwarded-For`/`trust proxy`). `main.ts` unchanged. See §4.1 + runbook
  §4.2. (Revised from the original "in-app allowlist" idea once the cross-host topology
  was known.)
- **O3 — Notifications: keep logic in partner, move only the send.** The adaptive
  digest/win selection, channel resolution, `NOTIFICATIONS_LIVE` guard, and
  `notification_attempts` audit stay in the partner service. The WhatsApp send leg
  goes through a templated endpoint (`partner_ref` + `type` + `params`; api owns text
  and recipient). See §5.5.
- **O4 — Leadmagnet correlation id: REQUIRED.** Asset delivery (§5.6) only proceeds
  when `lead_correlation_id` matches a just-created opt-in lead (issued by §5.1) and
  the phone matches that lead. Short TTL, single use.
- **O5 — Code parameters live in api.** TTL (10 min), max attempts (≤5), and the
  per-phone request rate limit move into api config, since api now owns the
  credential. The partner service no longer holds these values.

---

## 10. Implementation order (api side, later)

1. `PartnerApiKeyGuard` + `PARTNER_API_KEY` env (constant-time compare). Unit-test the
   guard (valid key, wrong key same length, wrong length, missing key, unconfigured).
   Network boundary is the EC2 SG (§4.2), not app code — no IP logic in the guard.
2. `/api/partner` controller scaffold under the guard + a tight `@Throttle`.
3. Read endpoints first (§5.2 agent-leads flat shape, §5.3 agent-enums) — lowest risk,
   unblocks the already-built partner sync.
4. Lead create (§5.1) with forced pipeline + correlation-id issuance.
5. Login code request/verify (§5.4) with code generation/storage/TTL/attempts in api.
6. Templated notify (§5.5) and leadmagnet deliver (§5.6, correlation-id gated).
7. Reconcile partner side: repoint `app/api_client.py` paths to `/api/partner/*`, add
   the `x-api-key` header, then the follow-up auth migration (drop `PhoneLoginToken`).
