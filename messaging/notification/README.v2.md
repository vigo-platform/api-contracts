# NotificationRequested v2 — PROPOSED

Review proposal, not an approved production rollout. The [v2 schema](notification-requested.v2.schema.json)
is a separate contract; [approved v1](README.md) remains EMAIL/OTP-only and unchanged.
This directory changes no Auth or Notification implementation.

## Command and recipients

`event_type: NotificationRequested` is a delivery command, not a business event.
`event_version: 2` is mandatory. A logical request contains one or two `deliveries`,
at most one per channel: EMAIL, IN_APP, or both, in either order. No SMS or PUSH.
Fan-out to multiple users requires separate commands and event IDs.

EMAIL requires exactly `recipient.destination`, a single conventional ASCII
mailbox (same syntax and length limits as v1). IN_APP requires exactly
`recipient.user_id`, User's internal positive int64 ID from `grpc/users.proto`,
encoded as a decimal string to preserve precision in JSON clients. No UUID,
email, username, leading zeroes, or number coercion. The consumer must additionally
check user existence and authorization. Do not infer a user
from an email address. With both channels, the producer must resolve and authorize
both destinations for the same intended person; the schema cannot prove ownership.

**Team-confirmed identity (Taha):** IN_APP ownership uses User's internal positive
numeric ID. Auth JWT `sub` already carries this same ID as a decimal string.
Canonical validation is ASCII digits only, no leading zeros, and inclusive range
`1..9223372036854775807` (positive signed int64). The schema enforces this range
on the string itself; do not round through floating-point JSON numbers. Notification
must authorize ownership against the validated, authenticated internal-ID subject.
Public user UUIDs and anonymous coach application IDs are separate identifiers and
must never be substituted for `recipient.user_id`, even if an application ID is
numeric. Anonymous applicants without a user account remain EMAIL-only.

The public-UUID JWT-sub wording in `rest/user.yaml` conflicts with this confirmed
team decision and needs separate documentation reconciliation by its owners; it
does not reopen the notification identity choice. No existing User, Auth or Gateway
contract is changed here, and no live JWT behavior was inspected in this task.

The shared locale, template, parameters and optional expiration apply to both
channels. Delivery entries contain only channel and recipient, with no
producer-supplied read status. Notification persists IN_APP history and initializes
it unread; only Notification's authorized read/unread workflow changes that state.
EMAIL-only commands do not create IN_APP history. Delivery bookkeeping is distinct
from user-visible history. No OTP may enter v2 or persistent notification history;
existing Auth OTP requests continue through v1 with transient processing only.

## Producer integration

1. Register an authenticated publisher and its allowed templates/channels/recipient
   scope. `producer` is a stable service name, not an arbitrary caller-supplied claim.
   Use Kafka ACLs and a trusted ingress/publishing boundary that binds the payload
   identity to the authenticated publisher; a shared topic record does not itself
   prove which principal authored its `producer` field. Never trust that field alone.
2. Register an immutable template ID with Notification, including channel-specific
   renderers for `fa` and `en`, a closed parameter allowlist with semantic validators,
   authorized producers and whether expiration is required. Unknown template,
   locale, parameter, or unsupported channel/locale combination means reject;
   never silently fall back to another language or send only the valid subset.
3. Generate a lowercase UUID `event_id` once per logical request. Use a stable UUID
   `correlation_id` for tracing, never deduplication. `occurred_at` is creation time,
   unchanged on retries. Publish from a durable outbox where the business change
   and delivery intent need atomicity. Store and retry the original command.
4. Populate destinations explicitly and choose channels. Send only template data,
   never subject, HTML, rendered body, template source, or read/unread fields.
   Select `fa` or `en` explicitly. Use `expires_at` for time-sensitive notices.
5. Validate with Draft 2020-12 **and enabled uuid/date-time/email format assertions**,
   then perform catalog, authorization and semantic checks. Publish only after the
   v2 consumer is ready. Kafka key is `producer:event_id` (PROPOSED); headers contain
   tracing/version metadata only, no recipient, parameters, credentials or PII.
6. Broker acknowledgment means durable enqueue, not delivery. Do not retry a failed
   channel by creating a new event ID; Notification owns channel retries. A deliberate
   new notice or resend requires a new event ID and may create new history.

The schema accepts service-name syntax to support multiple authorized producers
without editing an enum. `user-service`, `order-service`, and `payment-service`
are PROPOSED publisher registrations, not granted permissions. Future User and
Order/Payment scenarios use the same envelope with separately reviewed templates.
No new final domain event names are introduced here. The aligned `rest/user.yaml`
already mentions `CoachApplicationApproved` / `CoachApplicationRejected` for
anonymous applications and `CoachApproved` / `CoachRejected` for existing users.
Their mapping into these notification templates remains PROPOSED; this contract
does not define their event payloads or silently equate the two application flows.

### Coach Approved / Rejected integration example

Anonymous applications create no user account, including at approval. Their
ordinary status notice must be EMAIL-only. Approval's separate invitation and
lookup tokens/secret links must never enter v2; secure invitation delivery requires
a separate approved contract, not extending the approved OTP-only v1 contract.
The combined and IN_APP fixtures model an already registered applicant with an
authorized internal user ID. They are not examples
of an anonymous application magically acquiring an IN_APP recipient.

The following pseudocode builds either non-sensitive notice. `user-service`, both
template IDs, topic and key remain PROPOSED. UUID/time functions are placeholders;
the persisted outbox command, not this builder, is reused on retries.

```python
template_by_outcome = {
    "APPROVED": "notification.coach_application.approved.v1",
    "REJECTED": "notification.coach_application.rejected.v1",
}
command = {
    "event_id": new_lowercase_uuid(),  # once per logical notice
    "event_type": "NotificationRequested",
    "event_version": 2,
    "occurred_at": utc_now_rfc3339(),
    "producer": "user-service",
    "correlation_id": correlation_uuid,
    "data": {
        "locale": "fa",  # or en, explicitly chosen
        "template_id": template_by_outcome[outcome],
        "template_parameters": {},
        "deliveries": [
            {"channel": "EMAIL", "recipient": {"destination": "coach@example.invalid"}}
        ],
    },
}
# Validate schema + approved catalog/authorization, then persist the command
# with the business transition in the outbox. Use a real authorized destination
# at integration time; this example address is synthetic.
# Publish the saved command to PROPOSED notification.commands.v2,
# key = command["producer"] + ":" + command["event_id"].
```

For registered applicants only, select
IN_APP alone or add `{"channel": "IN_APP", "recipient": {"user_id": "12345"}}`
using an authorized internal ID (the number here is synthetic).
Both outcomes accept exactly `{}` parameters in the proposed catalog: no names,
rejection reasons, application details, passwords, invitation links or tokens.

## Templates, localization and privacy

The following catalog entries are **PROPOSED**, not business event identifiers:

| Template | Required parameters | Channels / locales |
| --- | --- | --- |
| `notification.coach_application.approved.v1` | None (`{}`) | EMAIL, IN_APP / fa, en |
| `notification.coach_application.rejected.v1` | None (`{}`) | EMAIL, IN_APP / fa, en |

Approved copy could be “Your coach application was approved.” / “درخواست مربیگری شما تأیید شد.”
Rejected copy could be “Your coach application was rejected.” / “درخواست مربیگری شما رد شد.”
Notification owns final localized copy and versioned channel renderers. No rejection
reason or personal application details are transported in these examples.

`template_parameters` is the only intentionally extensible object: at most 16 named
plain-text strings, each 1–256 characters. Nested objects/arrays, control characters
and angle brackets are rejected. Common secret field names are rejected as defense
in depth, **not a secret detector**. A secret under `message` could pass the schema.
The template catalog must reject unknown keys and validate values by meaning;
ordinary notifications must contain no passwords, OTPs, tokens, credentials, API
keys, secret links or secret values under any name. No free-form reason/body field.
Render values as data, with contextual escaping for HTML/text; never execute or
re-interpret parameters as templates, markup, URLs or header fragments.

Do not log full payloads, destination, user IDs, parameters or rendered content.
Log opaque command IDs, channel, status and redacted error codes. Apply the same
rules to traces, retries and DLQ tooling. Protect Kafka and operational storage
with access controls and bounded retention. V1 OTP payloads must never be copied
to persistent history or an ordinary-notification DLQ.

## Idempotency, partial failure and retries

PROPOSED transport: separate `notification.commands.v2`, isolating closed v1
consumers on `notification.commands`. At-least-once processing is assumed.

- Logical command identity is `(producer, event_id)`; channel identity is
  `(producer, event_id, channel)`. Topic/version are not extra deduplication axes:
  never reuse an ID for another payload or version. A changed destination,
  template, locale, expiration or channel set under the same identity is a
  permanent conflict, not an update. Compare the full parsed payload, ignoring
  object member order and sorting deliveries by channel; all values, including
  correlation ID and timestamp strings, must remain unchanged. Do not normalize
  email case, Unicode, timestamps or omitted fields during replay. UUIDs are lowercase.
- Validate the entire command, publisher and catalog before any side effect.
  Invalid/unauthorized commands are terminal rejections, not partial deliveries.
  A timeout/unavailable authorization or catalog dependency is not proof of an
  invalid request: defer without side effects and retry within the agreed bounds.
- Persist accepted intent and per-channel states durably before committing the
  Kafka offset (or after atomic completion). Crash recovery must resume pending
  work; concurrent duplicate claims need a durable uniqueness constraint.
- IN_APP creation and channel success must be atomic and unique by channel
  identity. Replays must not create a second history entry or reset an entry to
  unread. Keep a deduplication tombstone if history is deleted during the replay
  window. EMAIL success is recorded independently.
- EMAIL failure after IN_APP success leaves the IN_APP history intact. Retry only
  EMAIL. Conversely, do not resend a successful email when IN_APP creation fails.
  Track pending, succeeded, retryable failure, permanent failure, exhausted and
  expired per channel. Complete means all channels are terminal; it does not mean
  all succeeded. Report partial success distinctly, without compensating a success.
- Retry transient provider/storage failures with bounded exponential backoff and
  jitter. Invalid recipients or permanent provider rejection are terminal. Exhausted
  retries become terminal exhausted and require restricted dead-letter/operator
  handling. Automatic Kafka redelivery cannot reset attempt counters or deadlines.
  An explicitly authorized replay may reopen only exhausted/transient work with
  an audited, bounded additional budget; never reopen succeeded, permanently failed
  or expired channels. Replay preserves identity, payload and successful states.
  Consume duplicate records after expiry without new side effects; suppress
  remaining work, rather than repeatedly failing the Kafka record.
- Use the channel identity as a provider idempotency key when supported. A crash
  after provider acceptance but before recording success can cause duplicate email;
  exactly-once external delivery is not guaranteed. Reconcile ambiguous outcomes
  with the provider where possible before retrying.

Check recorded outcomes before scheduling delivery. A duplicate arriving after
success or expiry cannot revive work or erase history/read state. Keep immutable
template revisions available for accepted pending work; a retry must not pick up
different copy under the same template ID. If authorization is revoked, stop
remaining delivery without undoing prior success; reauthorization policy needs
owner approval. Persist terminal rejections safely before acknowledging poison
records so they cannot block a partition, without retaining rejected secret payloads.

Deduplication retention must cover Kafka retention, retries, DLQ/manual replay and
outbox replay windows. Until durations are agreed, do not enable unrestricted
replay or prune deduplication records. Keys distribute by command, so there is no
per-user ordering guarantee. Do not use arrival order to reconstruct business state.

## Expiration

UTC timestamps use the same application profile as v1: RFC 3339, `Z`/`+00:00`,
seconds 00–59, lowercase `t`/`z` permitted. Schema validates syntax/calendar dates,
not wall-clock time or cross-field ordering. Runtime must require
`expires_at > occurred_at` when present. Time-sensitive templates must require
expiration via their catalog policy; omission on an ordinary template means no
business deadline, not unlimited infrastructure retries.

Check `now >= expires_at` before each first attempt/retry for each channel: do not
hand off EMAIL or create IN_APP history at/after expiry. No clock-skew extension.
Expiry is a dispatch deadline, not history TTL: an IN_APP entry already created
remains in history and keeps its read state. Already handed-off email cannot be
recalled and may arrive later. No cancellation/supersession protocol is proposed.

## Compatibility and deployment order

V2 does not validate as v1; neither schema is a substitute for the other. Preserve
the v1 schema, fixture, tests, topic and Auth flow byte-for-byte. Envelope and
delivery objects are closed: optional field additions and enum expansions can
break existing validators. Use a new explicit contract version for incompatible
wire changes; never mutate published meanings. Template version is independent
of `event_version`; new catalog entries within existing syntax require coordinated
consumer rollout, even if no schema change is needed. Pin contract revisions.

1. Approve the unresolved decisions below; provision the separate topic, ACLs,
   retention, monitoring and schema routing. No registry is assumed by this repo.
2. Deploy v2-capable Notification validation, catalog/renderers, durable per-channel
   processing, history and deduplication while continuing v1 consumption unchanged.
3. Verify synthetic traffic, expiry, replay/concurrency and partial-failure behavior
   in integration tests before enabling authorized v2 producers gradually.
4. Roll back by pausing v2 publishers and safely retaining/draining v2 work with a
   capable consumer. Never route v2 to v1 or dual-publish the same logical notice.
   Auth OTP stays on v1 throughout; no Auth migration is required by this proposal.

## Examples and focused checks

`examples/v2/valid/` contains EMAIL-only, IN_APP-only and combined commands for the
two proposed scenarios. `examples/v2/invalid/` contains structurally invalid commands;
filenames identify the violation. All addresses/IDs are synthetic. Historical
timestamps are intentional: structural validity is not present dispatchability.

```sh
py -m pip install -r tests/messaging/requirements.txt
py -m unittest discover -s tests/messaging -v
```

Tests validate both versions, exercise negative cases and guard existing v1
artifact hashes. They do not claim to test service behavior. Runtime-only rejection
examples: an unregistered but syntactically valid producer/template;
an unknown user; a secret hidden under an innocent
parameter name; an already-expired request; or expiration preceding creation.

## Explicit unresolved decisions

- Approve the separate topic/key proposal, authenticated publisher binding, initial
  producer ACLs and template/channel/recipient authorization matrix.
- Approve history authorization and user deletion/email ownership policy using
  the confirmed internal ID; reconcile stale REST identity documentation separately.
- Approve Coach template IDs/copy and the owning business event mappings (all
  PROPOSED). Define future User/Order/Payment catalog entries separately.
- Choose history retention/deletion, deduplication/replay windows, retry limits,
  backoff, DLQ retention/redaction and operational ownership; no numbers invented.
- Define which future templates are time-sensitive and their deadlines, provider
  idempotency/reconciliation capability and metrics/alerts for partial outcomes.
- Define Notification-owned history/read APIs and rendering snapshot policy so
  old history remains stable across template changes; no REST contract added here.
- Confirm registry/version publication and rollout approval, and separately assign
  secure anonymous-coach invitation delivery outside this ordinary notice contract.

## Review baseline and minimum Notification handoff

Initially prepared at `7e3a792d97863c75df4a338570ccd81161f6b3a4`. Remote refs were
subsequently fetched and the working proposal aligned to main
`1132a0c76ff1f0d8c9024e3513f7955dc65e69d2` on `codex/notification-v2-review`,
without merge or commit. The three intervening commits change only `rest/user.yaml`.
All 18 local files were backed up and their byte hashes verified after alignment,
before these review clarifications. V1 artifacts and Auth's contract remain unchanged.

Before implementing a production v2 consumer, hand off:

1. A reviewed, pinned schema revision using the confirmed internal ID; approved
   topic/key, publisher binding/ACL matrix and consumer version routing.
2. The approved immutable template catalog (both channels/locales, closed parameter
   definitions, deadline policy) and owning producer mappings. Anonymous Coach
   notices are EMAIL-only; invitation secrets need a separate approved path.
3. Durable command/channel uniqueness and conflict rules, attempt budgets, replay
   permissions, deduplication/retention windows, provider idempotency/reconciliation,
   redacted failure handling and consumer offset/recovery design.
4. Notification-owned history/read authorization, deletion/tombstone and rendering
   retention policy, plus acceptance tests for concurrent duplicates, changed-payload
   conflicts, both partial-failure directions, crash-after-provider-acceptance,
   exhausted/replayed work, expiry at the exact boundary and no read-state reset.
5. A consumer-first rollout and rollback plan preserving v1, plus proof that no OTP,
   credentials or anonymous application tokens enter v2 or persistent history.

The contract tests check wire structure and v1 preservation, not distributed
delivery behavior or deployed JWT semantics. This is reviewable as a local proposal;
remaining transport, authorization, catalog and operational decisions still need approval.

Prior review validation on Windows after alignment: messaging regressions passed all
20 tests (9 v1, 11 v2). Repository release tests passed 23 of 25; unchanged tests
failed on Windows symlink privilege (`WinError 1314`) and a POSIX-only expected
path (`grpc/storage.proto` versus `grpc\storage.proto`). `verify-all` was attempted
but the existing Windows Maven wrapper invocation failed on the `&` in the checkout
path before compilation. These checks need a supported runner (CI uses Ubuntu);
no unrelated test/build workaround is included in this proposal.
