# Burp Community with Reburp and MCP

This stack runs Burp Suite Community Edition 2026.10.1, loads Reburp 1.1.15, and exposes a Streamable HTTP MCP server at `http://127.0.0.1:8765/mcp`. Docker Compose pulls prebuilt private images from GHCR. The server reads Reburp's live OpenAPI specification and provides access to all 206 operations through four MCP tools.

```text
Agent -> 127.0.0.1:8765/mcp -> MCP server -> 127.0.0.1:9090/api -> Burp Community
```

The MCP container shares the Burp container's network because Reburp listens only on `127.0.0.1:9090`. Port 9090 is not published to the host. Burp uses an internal 1920 x 1080 Xvfb display, with no graphical interface exposed. Its window fills the virtual display, so `/api/ui/screenshot` returns 1920 x 1080 captures.

## Getting started

Requirements: Docker with Compose, access to the private GHCR packages, and approximately 4 GB of memory available for the stack.

1. Read the [PortSwigger license agreement](https://portswigger.net/burp/eula), especially Addendum D for Community Edition.
2. Run `docker login ghcr.io -u SpiizN` and enter a GitHub personal access token (classic) with `read:packages` access when prompted for a password. The token also needs access to these private packages.
3. Copy `.env.example` to `.env`. Set `BURP_ACCEPT_EULA=true` if you accept the agreement, and set `MCP_BEARER_TOKEN` to at least 32 random characters, such as the output of `openssl rand -hex 32`. Protect the file with `chmod 600 .env`.
4. Start the stack:

   ```sh
   docker compose up -d
   ```

5. Check both services:

   ```sh
   docker compose ps
   docker compose exec burp curl -fsS http://127.0.0.1:9090/api/status
   ```

The first startup can take several dozen seconds. `docker compose down` stops the stack and retains Burp preferences in the `burp-home` volume. Set `BLURP_IMAGE_TAG=sha-<full commit SHA>` in `.env` to run both images from a specific commit instead of `latest`.

## Prebuilt images

The [publish workflow](.github/workflows/publish-images.yaml) runs on every push to `main`. It builds `linux/amd64` and `linux/arm64` variants of `ghcr.io/spiizn/blurp-burp` and `ghcr.io/spiizn/blurp-mcp`, then publishes `latest` and `sha-<full commit SHA>` tags. It uses the repository's `GITHUB_TOKEN` with `packages: write`; no publishing token needs to be stored in the repository.

New GHCR packages are private by default. The workflow requires a private repository and refuses to publish to an existing package whose visibility is not private. If a package already exists but is not linked to this repository, grant this repository write access to the package before running the workflow.

For local image changes, run `docker compose up -d --build --pull never`. The Burp Dockerfile downloads the official Burp and Reburp JARs and verifies their SHA-256 checksums.

## Connecting an agent

Configure your MCP client to use `http://127.0.0.1:8765/mcp` with Streamable HTTP transport and the `Authorization: Bearer <MCP_BEARER_TOKEN>` header, using the token from `.env`. The `/health` endpoint requires the same header. The available tools are:

| Tool | Purpose |
| --- | --- |
| `status` | Check the Burp and Reburp versions and editions. |
| `search_operations` | Search operations by keyword or tag, with pagination. |
| `describe_operation` | Read an operation's parameters, JSON schemas, and examples. |
| `call_operation` | Call an operation by its `operationId` with path and query parameters and a JSON body. |

Start by searching for an operation, read its description, then call it with the fields specified by OpenAPI. For example, use `search_operations(query="proxy history")`, then `describe_operation(operation_id="getProxyHistory")`, then `call_operation(operation_id="getProxyHistory", query_parameters={"limit": 10})`.

`call_operation` returns the HTTP status code, content type, and response body. Binary responses are Base64 encoded. Reburp HTTP errors remain visible with their status codes and bodies; transport errors identify the affected operation.

## Limitations and access

Burp Community does not include Professional-only features. Scanner, Collaborator, and AI operations may return `403`. Community projects are temporary and held in memory: Burp preferences persist in the volume, but traffic history does not survive a restart.

MCP requires a bearer token and is published only on the host loopback interface. Keep the token secret and the local-only binding in place. Call operations that generate traffic only against targets you are authorized to test. Reburp's shell executor is disabled by default.

Versions and specifications: [Burp 2026.10.1](https://portswigger.net/burp/releases/professional-community-2026-10-1), [Reburp 1.1.15](https://github.com/forefy/reburp/releases/tag/v1.1.15), [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/run/).
