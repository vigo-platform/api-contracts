# Order integration — proposed contract (pending Order team confirmation)

No Order or Payment service exists in this organization yet: there is no
repository and no contract in this repository. The User Service therefore
implements only its **side** of the boundary, disabled by default, so that the
platform is not left with an invented dependency.

## What User does today

- `POST /api/v1/plans/{plan_id}/purchase` (ATHLETE) validates the plan, records a
  `PENDING_PAYMENT` subscription, then calls Order synchronously.
- The request body is empty. **User never forwards a client price** and never
  stores an authoritative amount; `amount_due` in the response is always `null`.
- If Order fails or is unconfigured, the pending subscription is deleted and the
  caller receives `503 ORDER_UNAVAILABLE`. Nothing is activated.
- `GET /api/v1/plans/subscriptions/me` returns the caller's subscriptions.
- A payment-success event activates access. Activation is a conditional update
  from `PENDING_PAYMENT`, and `consumed_events` deduplicates by `event_id`, so a
  redelivery or duplicate cannot extend access twice.

## Contract Order must confirm

### Synchronous: create order

```http
POST {ORDER_BASE_URL}/api/v1/orders
Content-Type: application/json

{
  "plan_id": "uuid",
  "coach_id": "uuid",
  "athlete_id": "uuid",
  "duration_days": 30,
  "currency": "IRR"
}
```

Response `201`/`200`:

```json
{ "order_id": "uuid", "status": "PENDING" }
```

Order owns the price snapshot, order persistence and payment initiation. User
sends `duration_days` only so Order can validate the plan window; it is not a
price.

### Asynchronous: payment success

Topic `order.events` (override with `ORDER_PAYMENT_TOPIC`), keyed by the order id,
using the existing Vigo envelope:

```json
{
  "event_id": "uuid",
  "event_type": "OrderPaid",
  "event_version": 1,
  "occurred_at": "2026-11-18T10:00:00Z",
  "producer": "order-service",
  "aggregate_id": "order uuid",
  "aggregate_version": 1,
  "data": {
    "order_id": "uuid",
    "athlete_id": "uuid",
    "plan_id": "uuid",
    "amount": 500000,
    "currency": "IRR"
  }
}
```

User reads only `event_id`, `order_id` and `occurred_at`. `amount` and `currency`
are not copied into User state because Order remains the source of truth; they are
present so that future reconciliation can compare records without a synchronous
call.

### Enabling it

```dotenv
ORDER_BASE_URL=https://order.internal
ORDER_PAYMENT_EVENTS_ENABLED=true
ORDER_PAYMENT_TOPIC=order.events
```

`ORDER_BASE_URL` must be HTTPS unless `ORDER_ALLOW_HTTP=true` is set for local
development. Until these are set the listener is not registered and purchases
return `503`, so enabling the feature is an explicit deployment decision.

### Open questions for the Order owner

1. Is `POST /api/v1/orders` the agreed path and is `order_id` returned immediately?
2. Is `order.events` the agreed topic, and is `OrderPaid` the agreed event name?
3. Does Order guarantee that `OrderPaid` is published only after a settled payment?
4. What identifies a refunded or failed order, and should User revoke access on it?
