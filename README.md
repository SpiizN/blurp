# Burp Community with Reburp and MCP

This stack exposes one Streamable HTTP MCP server at `http://127.0.0.1:8765/mcp`. The server creates an isolated Burp Suite Community Edition 2026.10.1 instance with Reburp 1.1.15 for each active session. Each session has its own Burp container, private Docker network, and temporary project. No Burp container runs until an agent calls `start_burp`.

```text
Agent -> 127.0.0.1:8765/mcp -> session manager -> private relay -> Reburp -> Burp
```

Reburp listens only on `127.0.0.1:9090` inside each Burp container. A small relay shares that container's network namespace and makes Reburp reachable only on the session's private Docker network. Neither Reburp nor the relay publishes a host port. Burp uses an internal 1920 x 1080 Xvfb display, with no graphical interface exposed.

## Getting started

Requirements: Docker with Compose, access to the private GHCR packages, and approximately 4 GB of memory for each active Burp session.

1. Read the [PortSwigger license agreement](https://portswigger.net/burp/eula), especially Addendum D for Community Edition.
2. Run `docker login ghcr.io -u SpiizN` and enter a GitHub personal access token (classic) with `read:packages` access when prompted for a password. The token also needs access to these private packages.
3. Copy `.env.example` to `.env`. Set `BURP_ACCEPT_EULA=true` if you accept the agreement, and set `MCP_BEARER_TOKEN` to at least 32 random characters, such as the output of `openssl rand -hex 32`. Protect the file with `chmod 600 .env`.
4. Pull both images and start the MCP server:

   ```sh
   docker compose pull burp-image mcp
   docker compose up -d
   docker compose ps
   ```

The `burp-image` Compose service exists only for pulling or building the image. Its profile keeps it stopped during `docker compose up`. The manager starts Burp containers only when requested through MCP. `docker compose down` stops the manager and its active sessions. If the manager exits unexpectedly, its next startup removes orphaned sessions belonging to the same Compose project.

When upgrading from the earlier single-Burp stack, finish any work in that temporary project, then stop the old `burp` container before starting the new manager. The old container owns host port 8765, so the new manager cannot start until it stops. Compose may then report it as an orphan. Its `burp-home` volume is not deleted or reused by the new session containers.

Set `BLURP_IMAGE_TAG=sha-<full commit SHA>` in `.env` to run both images from a specific commit. Set `MCP_PORT` to change the host loopback port. For local image changes, set `BLURP_IMAGE_TAG=local`, then run:

```sh
docker compose build burp-image mcp
docker compose up -d --pull never
```

## Connecting an agent

Configure your MCP client to use `http://127.0.0.1:8765/mcp` with Streamable HTTP transport and the `Authorization: Bearer <MCP_BEARER_TOKEN>` header, using the token from `.env`. The `/health` endpoint requires the same header.

| Tool | Purpose |
| --- | --- |
| `start_burp` | Create a session and return its UUIDv4 ID, token, and `starting` state. |
| `burp_session_status` | Check whether the session is `starting` or `ready` and read its remaining idle time. |
| `extend_burp` | Add 1 to 3600 seconds to a ready session's idle deadline. |
| `stop_burp` | Stop a session after any active calls finish. |
| `status` | Check Burp and Reburp versions and editions in a ready session. |
| `search_operations` | Search live Reburp operations by keyword or tag, with pagination. |
| `describe_operation` | Read an operation's parameters, JSON schemas, and examples. |
| `call_operation` | Call an operation by its `operationId` with path and query parameters and a JSON body. |

Call `start_burp()`, then poll `burp_session_status(session_id=..., session_token=...)` until the state is `ready`. Pass the same `session_id` and `session_token` to every other tool. For example, call `search_operations(session_id=..., session_token=..., query="proxy history")`, then `describe_operation(operation_id="getProxyHistory", session_id=..., session_token=...)`, then `call_operation(operation_id="getProxyHistory", session_id=..., session_token=..., query_parameters={"limit": 10})`. Call `stop_burp` when finished.

The default idle timeout is five minutes after the session becomes ready. Each call moves the deadline to at least five minutes from that call. `extend_burp` adds time to the current deadline, which later calls do not shorten. Active calls are allowed to finish before a session is removed. Set `BURP_IDLE_SECONDS` and `MAX_BURP_SESSIONS` in `.env` to change the timeout and the maximum number of concurrent sessions. The default limit is two sessions. Burp startup does not count against the idle timeout.

Session tokens are returned only by `start_burp`. Treat them as credentials: they are passed in MCP tool arguments and may appear in client-side traces. The server stores only a hash of each token in memory. A manager restart invalidates all session IDs and tokens.

`call_operation` returns the HTTP status code, content type, and response body. Binary responses are Base64 encoded. Reburp HTTP errors remain visible with their status codes and bodies; transport errors identify the affected operation.

## Prebuilt images

The [publish workflow](.github/workflows/publish-images.yaml) runs on every push to `main`. It builds `linux/amd64` and `linux/arm64` variants of `ghcr.io/spiizn/blurp-burp` and `ghcr.io/spiizn/blurp-mcp`, then publishes `latest` and `sha-<full commit SHA>` tags. It uses the repository's `GITHUB_TOKEN` with `packages: write`; no publishing token needs to be stored in the repository.

New GHCR packages are private by default. The workflow requires a private repository and refuses to publish to an existing package whose visibility is not private. If a package already exists but is not linked to this repository, grant this repository write access to the package before running the workflow. The Burp Dockerfile downloads the official Burp and Reburp JARs and verifies their SHA-256 checksums.

## Limitations and access

Burp Community does not include Professional-only features. Scanner, Collaborator, and AI operations may return `403`. Community projects are temporary and held in memory. Session containers have no persistent home volume, so their traffic history and preferences disappear when the session ends.

The MCP manager needs access to the Docker socket to create and remove session containers. Docker socket access grants control over the host Docker daemon, so keep the manager on the host loopback interface with a strong bearer token. Reburp's shell executor is disabled by default. Call operations that generate traffic only against targets you are authorized to test.

Versions and specifications: [Burp 2026.10.1](https://portswigger.net/burp/releases/professional-community-2026-10-1), [Reburp 1.1.15](https://github.com/forefy/reburp/releases/tag/v1.1.15), [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/run/).
