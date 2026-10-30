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

Java 17+ contract libraries are built from Protobuf and published to
[GitHub Packages](https://github.com/vigo-platform/api-contracts/packages).
Any `grpc/<name>.proto` can be built as an independent Maven artifact. There is
no contract registry, per-contract Maven module, or workflow list to maintain.
The JAR includes generated messages, client stubs, server base classes, and the
original `.proto` files. A sources JAR is also published. Transport configuration
and service implementations belong in the consuming applications.

| Name | Proto | Maven artifact | Release tag |
| --- | --- | --- | --- |
| `users` | `grpc/users.proto` | `ir.vigoapp.contracts:users-grpc-contract` | `grpc/users/v1.3.0` |
| `namex` | `grpc/namex.proto` | `ir.vigoapp.contracts:namex-grpc-contract` | `grpc/namex/v1.1.1` |

The User contract is named `users.proto` to preserve the desired
`users-grpc-contract` artifact ID. The `namex` row illustrates adding any new
Proto; it does not require configuration changes. Filenames use lowercase
letters, digits, or hyphens, start with a letter, and match the name in the tag
exactly. Java and Proto package names are defined inside each file.

### Build locally

The Maven Wrapper downloads the pinned Maven distribution; no Maven installation
is required. The first build needs internet access to download public build tools
and dependencies. No GitHub token is needed to build locally.

```bash
# Build all contracts; default local version is 0.0.0-SNAPSHOT.
python3 scripts/grpc_release.py verify-all

# Build and install only User with a specific version.
python3 scripts/grpc_release.py prepare --contract users --version 1.3.0
./mvnw -f target/grpc/users/pom.xml clean install

# Check tag resolution and publication safety rules.
python3 scripts/grpc_release.py resolve --tag grpc/users/v1.3.0
python3 -m unittest discover -s tests -v
```

Windows users can run `mvnw.cmd` instead of `./mvnw`. Build output is in
`target/grpc/users/target/`. Generated POMs, staged Protos, and Java code are not
committed. A single shared template in `build-support/grpc-pom.xml` supplies
the compiler, dependency, and publishing configuration.

Preparation stages the selected Proto and any transitive local imports from
`grpc/`, preserving their import paths. Only these files are compiled and
packaged; unrelated Protos are excluded. External imports such as
`google/protobuf/timestamp.proto` are resolved by protoc from Maven dependencies.

### Publish automatically with a tag

Commit the source and workflows before creating the tag.
Tags use `grpc/<name>/v<MAJOR.MINOR.PATCH>` and select `grpc/<name>.proto` directly.
Only stable, three-part versions
are accepted; `v` belongs in the tag, not in the Maven version.

```bash
git tag grpc/users/v1.3.0
git push origin grpc/users/v1.3.0
```

The **Publish gRPC contract** workflow checks out the tagged commit, selects only
the named Proto, generates its Maven build and Java code, and publishes:

- `ir.vigoapp.contracts:users-grpc-contract:1.3.0`: immutable numbered release.
- `ir.vigoapp.contracts:users-grpc-contract:latest-SNAPSHOT`: moving alias of the
  highest published stable version for this contract.

For example, a later `grpc/users/v1.4.0` tag publishes `1.4.0` and updates
`latest-SNAPSHOT`. Publishing a backport such as `1.3.1` after `1.4.0` publishes
the numbered version without moving latest backwards. Versions are compared
numerically (`1.10.0` is newer than `1.9.0`). Maven uses `-SNAPSHOT` for mutable
versions, so the alias is named `latest-SNAPSHOT`, not the literal release version
`latest`. There is no mutable `latest` Git tag.

Registry publications are serialized with a queue to prevent concurrent updates
from racing. A rerun for the same commit skips an already-published numbered JAR
and can finish updating latest. Reusing a numbered version from another commit
fails; create a new version instead. A partially published release fails with an
explicit error so it can be inspected rather than overwritten. The JAR manifest
records both the original contract version and source commit, including for latest.

### Build or publish manually

After this workflow is on the repository's default branch:

1. Open **Actions → Publish gRPC contract → Run workflow**.
2. Select the source branch or tag to build.
3. Enter the filename without `.proto`, such as `users` or `namex`, and a version
   such as `1.3.0`, without `v`. This is free text, not a fixed list of contracts.
4. Leave **Publish to GitHub Packages** enabled to publish both the numbered release
   and, if newest, latest. Disable it for a build without publication.

Both automatic and manual runs attach the numbered JAR, sources JAR, and resolved
POM as downloadable workflow artifacts (14-day retention). Manual publication
does not create a Git tag; the selected source commit is recorded in the JAR.

### GitHub setup

The publisher uses the built-in `GITHUB_TOKEN` with `contents: read` and
`packages: write`; no publishing PAT needs to be committed or created. GitHub
Actions must be enabled and organization/repository policies must allow the
workflow to publish packages. The endpoint defaults to
`https://maven.pkg.github.com/vigo-platform/api-contracts`; Actions automatically
uses the current repository name if this project is forked or renamed.

The separate **Verify gRPC contracts** workflow discovers all top-level
`grpc/*.proto` files, builds them, and tests
release selection on relevant pull requests and pushes to `main`.

### Consume from another Maven project

Add this repository to the consuming project's `pom.xml`. Snapshots must be
enabled to resolve the moving latest alias:

```xml
<repositories>
    <repository>
        <id>github-vigo-contracts</id>
        <url>https://maven.pkg.github.com/vigo-platform/api-contracts</url>
        <releases>
            <enabled>true</enabled>
        </releases>
        <snapshots>
            <enabled>true</enabled>
            <updatePolicy>always</updatePolicy>
        </snapshots>
    </repository>
</repositories>
```

Use a pinned version for reproducible application builds:

```xml
<dependency>
    <groupId>ir.vigoapp.contracts</groupId>
    <artifactId>users-grpc-contract</artifactId>
    <version>1.3.0</version>
</dependency>
```

Or follow the newest stable contract automatically:

```xml
<dependency>
    <groupId>ir.vigoapp.contracts</groupId>
    <artifactId>users-grpc-contract</artifactId>
    <version>latest-SNAPSHOT</version>
</dependency>
```

Use `mvn -U ...` to force a metadata refresh if a cached alias is stale. Latest may
include a new major API version; pin a numbered version when compatibility must
be controlled. Artifact versions such as `1.3.0` are independent of the Proto
package `vigo.user.v1` and Java package `ir.vigoapp.contracts.user.v1`.

GitHub's Maven registry requires authentication even for public packages. Add
the following server to the consuming machine's `~/.m2/settings.xml`, merging it
with any existing settings. Its ID must match the repository ID above:

```xml
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 https://maven.apache.org/xsd/settings-1.0.0.xsd">
    <servers>
        <server>
            <id>github-vigo-contracts</id>
            <username>${env.GITHUB_USERNAME}</username>
            <password>${env.GITHUB_PACKAGES_TOKEN}</password>
        </server>
    </servers>
</settings>
```

Set `GITHUB_USERNAME` and `GITHUB_PACKAGES_TOKEN` outside the repository. For local
consumption, use a personal access token **classic** with `read:packages`, owned
by an account that can access this repository (authorize organization SSO if
required). Do not commit the token. A workflow in a different private repository
also needs credentials authorized to read this repository; its default token
does not automatically have cross-repository access.

Applications can directly import `ir.vigoapp.contracts.user.v1.UserServiceGrpc`
and the generated message classes. They do not need to copy the Proto or run
code generation again. Choose the gRPC transport and align gRPC/Protobuf runtime
versions in the application, especially when another dependency manages them.

### Add another contract later

1. Add and commit `grpc/namex.proto` with its Proto/Java package options.
2. Push tag `grpc/namex/v1.1.1`.

The workflow automatically publishes
`ir.vigoapp.contracts:namex-grpc-contract:1.1.1` and, if newest for `namex`,
`ir.vigoapp.contracts:namex-grpc-contract:latest-SNAPSHOT`. No Maven module,
registry entry, script change, or workflow edit is needed. A tag whose matching
Proto does not exist fails with the exact missing path before building.

After publication, never renumber existing Proto fields or reuse deleted field
numbers/names; mark removed fields `reserved`. Comments describing validation,
authorization, and idempotency are implementation requirements, not generated
runtime checks.
