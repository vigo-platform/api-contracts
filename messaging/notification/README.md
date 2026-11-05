# Notification command contract v1

Approved contract for SCRUM-108. This is an asynchronous delivery **command**,
not a domain event or a REST request. No Notification REST endpoint is introduced;
history and read/unread REST APIs are future work.

## Transport and identity

- Topic: `notification.commands`; logical command type: `NotificationRequested`.
- Kafka key: `event_id`. Producer: `auth-service`; `event_version`: `1`.
- Processing is at-least-once. Logical duplicate identity is `(producer, event_id)`.
- `event_id` is a UUID identifying one logical delivery request; UUID v4 is
  recommended. A resend is a new command with a new `event_id`.
- `correlation_id` is a UUID for tracing only, never a deduplication key.
- The required envelope also includes `occurred_at` and `data`. `aggregate_id`,
  `aggregate_version`, `user_id`, and a separate `idempotency_key` are omitted.

## Payload and rendering

All seven data fields are mandatory: `channel`, `purpose`, `locale`, `recipient`,
`template_id`, `template_parameters`, and `expires_at`. Channel is `EMAIL` only.
Locale must be `fa` or `en`: unknown or unsupported locales mean **no delivery**,
with no silent fallback. Notification owns localized rendering.

| Purpose | Template ID |
| --- | --- |
| `LOGIN_OTP` | `auth.login_otp.email.v1` |
| `REGISTRATION_OTP` | `auth.registration_otp.email.v1` |
| `PASSWORD_CHANGE_OTP` | `auth.password_change_otp.email.v1` |
| `PASSWORD_RESET_OTP` | `auth.password_reset_otp.email.v1` |

`PASSWORD_RESET_NOTICE` is not in v1. Each template accepts exactly one parameter:
`otp_code`, a string matching `^[0-9]{6}$`. Preserve leading zeroes.
`recipient` contains exactly `destination`: one conventional ASCII email address
with a standard dot-atom local part and a DNS-style domain name. This is an explicit
v1 MVP/application constraint, not full RFC mailbox support. Local-part atoms are
separated by single dots, with no leading, trailing, or consecutive dots; domain
labels contain ASCII letters, digits, and interior hyphens.
The local part is at most 64 characters, each DNS label at most 63 characters,
and the complete mailbox at most 254 characters (including `@` and dots).

V1 intentionally excludes display names, address lists, CC/BCC, IP-literal domains,
SMTPUTF8 / Unicode local parts, and quoted or obsolete RFC mailbox forms. The
schema checks this syntax, not deliverability, and adds no provider-specific rules.
Auth must not supply HTML, subject, rendered body, template source, or provider
credentials. All objects are closed to additional properties.

## Time and runtime obligations

`occurred_at` and `expires_at` use the Vigo messaging v1 application timestamp
profile: RFC 3339, UTC only (`Z` or `+00:00`), and seconds from `00` through `59`.
Lowercase `t`/`z` are also accepted. Leap seconds are outside this application
profile. `expires_at` is the actual Auth challenge
expiration, not a hardcoded five-minute policy.

At dispatch time, **`now >= expires_at` means do not dispatch**. No positive
clock-skew grace period may extend validity. Auth remains authoritative for OTP
validity and verification. Schema validation cannot evaluate current wall-clock
time, determine challenge validity, enforce uniqueness, or enforce dispatch
behavior. Consumers must enforce these runtime obligations separately.

## Privacy

Never log OTP values, destination, the recipient object, `template_parameters`,
rendered subject/body, authentication tokens, or the full command payload.
Kafka keys and headers must contain no PII or OTP. Validation errors must not
expose command values in production logs.

## Known limitations

- Login challenge replacement can invalidate an older OTP while its old email
  command remains queued. No cancellation/supersession protocol exists in v1.
- Only the currently valid Auth challenge can verify successfully.
- Provider handoff before `expires_at` does not guarantee inbox delivery before
  expiration.
- No per-recipient ordering guarantee exists.
- Duplicate external email delivery remains theoretically possible under
  at-least-once processing and ambiguous provider outcomes. There is no
  exactly-once external email delivery guarantee.

## Compatibility and versioning

Breaking changes require a new `event_version` and schema version; existing
published versions must be preserved. Adding enum values is not automatically
backward compatible. Supporting consumers must exist before producers emit new
versions or enum values. Optional additive fields are compatible only when
existing consumers can safely ignore them; v1's closed objects reject unknown
fields. Published identifiers and their meanings must never be repurposed.

## Validation

The schema uses JSON Schema Draft 2020-12. Enable format assertions for `uuid`,
`date-time`, and `email`; format annotations alone are insufficient. The test
runner uses `Draft202012Validator` with an explicit `FormatChecker`.

From the repository root (on Windows, use `py` instead of `python3`):

```sh
python3 -m pip install -r tests/messaging/requirements.txt
python3 -m unittest discover -s tests/messaging -v
python3 -m unittest discover -s tests -v
python3 scripts/grpc_release.py verify-all
```

Messaging tests live separately so existing gRPC CI and publishing do not acquire
messaging dependencies. The dedicated messaging workflow runs structural tests
and validates the checked-in synthetic example. Its historical timestamps are
intentional: structurally valid does not mean currently dispatchable.

This directory defines contracts only. Kafka producers/consumers, email transport,
SMTP/provider integration, persistence, retries/DLQ, idempotency storage, REST
business endpoints, JWT/security, and deployment infrastructure are out of scope.
