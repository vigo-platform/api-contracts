# Frontend integration — coach application and file uploads

Documentation only. No frontend file was added or changed for this work.

Base path: the browser calls the API Gateway, which forwards these prefixes to the
User and Storage services unchanged. Do not call the services directly.

## 1. Upload a public profile image

```http
POST /api/v1/assets/public
Authorization: Bearer <access token>
Content-Type: multipart/form-data; boundary=...

--boundary
Content-Disposition: form-data; name="file"; filename="avatar.png"
Content-Type: image/png
<binary bytes>
--boundary--
```

- Sent **before** the application form is submitted; the returned id is what the
  application references. Only the file part is required.
- Allowed: `png`, `jpg`, `jpeg`, `pdf`, `docx`, `xlsx`, `txt`, validated from the
  real bytes, max **20 MiB**.
- The route decides visibility: anything uploaded here is `PUBLIC`.

Response `201`:

```json
{
  "success": true,
  "code": "CREATED",
  "message": "File uploaded",
  "message_fa": "فایل بارگذاری شد",
  "data": {
    "asset_id": "7d1c0b1e-0000-0000-0000-000000000001",
    "owner_user_id": "9c279da3-4441-4cc3-aa46-f6fbe3293b45",
    "original_filename": "avatar.png",
    "content_type": "image/png",
    "size_bytes": 48213,
    "visibility": "PUBLIC",
    "status": "ACTIVE",
    "public_url": "/api/v1/assets/7d1c0b1e-0000-0000-0000-000000000001/content",
    "created_at": "2026-11-18T09:00:00Z",
    "updated_at": "2026-11-18T09:00:00Z"
  },
  "timestamp": "2026-11-18T09:00:00Z"
}
```

`public_url` is a stable relative path served anonymously by Storage; render it
only for assets with `visibility: "PUBLIC"`.

Errors: `400 VALIDATION_FAILED`, `401 UNAUTHORIZED`,
`413 FILE_TOO_LARGE`, `415 UNSUPPORTED_MEDIA_TYPE`,
`400 FILE_CONTENT_MISMATCH` (extension and bytes disagree).

## 2. Upload a private certificate document

```http
POST /api/v1/assets/private
Authorization: Bearer <access token>
Content-Type: multipart/form-data
```

Identical request and response shape to the public route; `visibility` is
`"PRIVATE"` and **no `public_url` is returned**. Never render this asset in the
public profile.

To display a private document to its owner or an admin, ask Storage for a
temporary link instead of storing one:

```http
GET /api/v1/assets/{asset_id}/download-url
Authorization: Bearer <access token>
```

```json
{
  "success": true, "code": "OK",
  "message": "Request completed", "message_fa": "درخواست انجام شد",
  "data": {
    "url": "https://<account>.parspack.net/<bucket>/private/<key>?X-Amz-Signature=...",
    "mode": "PRESIGNED",
    "expires_at": "2026-11-18T09:10:00Z"
  },
  "timestamp": "2026-11-18T09:00:00Z"
}
```

With the local filesystem backend `mode` is `"STREAM"` and `url` is
`/api/v1/assets/{id}/content`, which performs the same authorization check. Fetch
the URL when the user clicks; do not cache it beyond `expires_at` (default 10
minutes). An unauthorized caller receives `403`; an unknown or deleted asset `404`.

## 3. Submit the coach application

```http
POST /api/v1/coaches/applications
Content-Type: application/json
```

**No `Authorization` header.** The applicant does not need an account.

```json
{
  "first_name": "Sara",
  "last_name": "Ahmadi",
  "email": "sara@example.com",
  "phone": "+989121234567",
  "headline": "Strength coach",
  "bio": "Fifteen years coaching strength athletes.",
  "specialties": ["Strength", "Conditioning"],
  "experience_years": 12,
  "profile_image_file_id": "7d1c0b1e-0000-0000-0000-000000000001",
  "certificates": [
    {
      "category": "UNIVERSITY",
      "title": "BSc Sport Science",
      "issuer": "Tehran University",
      "field_of_study": "Physical education",
      "degree": "BSc",
      "file_id": "7d1c0b1e-0000-0000-0000-000000000002"
    },
    {
      "category": "FEDERATION",
      "title": "Level 2 coaching",
      "issuer": "National federation",
      "file_id": "7d1c0b1e-0000-0000-0000-000000000003"
    }
  ],
  "experiences": [
    {
      "title": "Strength coach",
      "organization": "City club",
      "description": "Coached adult athletes",
      "duration_months": 36
    }
  ],
  "instagram_handle": "sara.coach",
  "locale": "fa"
}
```

Rules the form must honour:

- `profile_image_file_id` must be a **PUBLIC** asset id; `file_id` on a certificate
  must be a **PRIVATE** asset id. Each certificate requires one.
- Academic fields (`field_of_study`, `degree`) are accepted **only** with
  `category: "UNIVERSITY"`; sending them with `FEDERATION` or `SKILL` is rejected.
- `email` is the address the invitation will be bound to. Show it back to the user
  and warn that registration must use exactly this address.
- Unknown JSON fields are rejected, so send only the keys above.

Success `201`:

```json
{
  "success": true, "code": "SUCCESS",
  "message": "Operation successful", "message_fa": "عملیات موفق بود",
  "data": {
    "application_id": "6a1f0a4e-0000-0000-0000-000000000010",
    "status": "PENDING",
    "lookup_token": "3fP0rQ9k8m2sVwX1yZ4aB6cD8eF0gH2iJ4kL6mN8oP0",
    "submitted_at": "2026-11-18T09:05:00Z"
  },
  "timestamp": "2026-11-18T09:05:00Z"
}
```

- Show a neutral confirmation. A duplicate submission returns the **same** `201`
  shape for the existing pending application, so never say "you already applied".
- `lookup_token` is returned only here. Keep it in `sessionStorage` if the same
  browser should be able to check status later; there is no email recovery yet.
- Status check: `GET /api/v1/coaches/applications/{lookup_token}` returns only
  `application_id`, `status`, `submitted_at`, `reviewed_at`.

Errors: `400 VALIDATION_FAILED` with `data[]` of
`{field, code, message, message_fa}`; `429 RATE_LIMITED` (5 submissions per 15
minutes per client), so show a retry message rather than a hard failure.

## 4. Upload order

Because the application references asset ids, the sequence must be:

```text
1. POST /api/v1/assets/public   -> profile_image_file_id
2. POST /api/v1/assets/private  -> one file_id per certificate
3. POST /api/v1/coaches/applications with those ids
```

Uploads require an authenticated user, while the application itself is anonymous.
If the product requires a fully anonymous form, the uploads must be moved behind a
short-lived upload grant; that is **not implemented** and needs a product decision.

## 5. After approval

The applicant registers through Auth with the **same email**. Auth verifies it by
OTP, then creates the account with role `COACH`; the invitation is consumed once.
The frontend needs no special code for this, but it should tell the applicant to
register with the email they entered.
