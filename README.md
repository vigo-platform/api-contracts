# api-contracts

API contracts for gRPC and REST services.

---

## REST Contracts (OpenAPI 3.0.3)

### Viewing & Inspecting `.yaml` Contracts
To view, validate, and test the OpenAPI specifications interactively:
- **Swagger Editor (Online):** Copy the contents of any `.yaml` file and paste it into **[https://editor.swagger.io/](https://editor.swagger.io/)**.
- **Multiple Outcomes per Status Code:** When an HTTP status code (such as `200 OK`) has multiple possible states (e.g., direct login vs. 2FA step), use the **Examples** dropdown inside Swagger UI to inspect each scenario.
- **IDE & API Clients:** Open directly in IntelliJ IDEA / VS Code (with the OpenAPI extension) or import the `.yaml` file into **Bruno** or **Postman**.

### Standard Response Structure
All REST endpoints return a unified JSON envelope (`snake_case` format). HTTP status codes are strictly returned via standard HTTP response headers.

```json
{
  "success": true,
  "code": "STRING_STATUS_OR_ERROR_CODE",
  "message": "English human-readable message",
  "message_fa": "پیام فارسی برای نمایش به کاربر",
  "data": {},
  "timestamp": "2026-10-18T18:30:00Z"
}
```

#### Envelope Fields & Behavior by Status Code
- **`success`** (`boolean`): `true` for `2xx` responses, `false` for `4xx` and `5xx` errors.
- **`code`** (`string`): Machine-readable identifier in `UPPER_SNAKE_CASE` (e.g., `AUTH_SUCCESS`, `VALIDATION_FAILED`, `INVALID_CREDENTIALS`) used by clients for conditional logic.
- **`message` & `message_fa`** (`string`): Localized human-readable descriptions of the result.
- **`timestamp`** (`string`): UTC response timestamp in `ISO-8601` format.
- **`data`** (`object | array | null`):
  - **`2xx` (Success):** Contains the main response payload object (or `null` for void operations like logout).
  - **`400` (Validation Error):** Contains a flat array of field-level validation errors (`[{ "field", "code", "message", "message_fa" }]`).
  - **`429` (Rate Limit / Account Locked):** Contains lock timer metadata (`retry_after_seconds` and `locked_until`).
  - **`401`, `403`, `409`, `500` (Standard Errors):** Always `null`.

---

## gRPC Contracts (Protocol Buffers)

<!-- TODO: Add .proto service definitions, package conventions, and codegen instructions -->