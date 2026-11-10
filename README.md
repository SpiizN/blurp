# Burp Community with Reburp and MCP

This stack runs Burp Suite Community Edition 2026.10.1, loads Reburp 1.1.15, and exposes a Streamable HTTP MCP server at `http://127.0.0.1:8765/mcp`. The server reads Reburp's live OpenAPI specification and provides access to all 206 operations through four MCP tools.

```text
Agent -> 127.0.0.1:8765/mcp -> MCP server -> 127.0.0.1:9090/api -> Burp Community
```

The MCP container shares the Burp container's network because Reburp listens only on `127.0.0.1:9090`. Port 9090 is not published to the host. Burp uses an internal 1920 x 1080 Xvfb display, with no graphical interface exposed. Its window fills the virtual display, so `/api/ui/screenshot` returns 1920 x 1080 captures.

## Getting started

Requirements: Docker with Compose and approximately 4 GB of memory available for the stack.

1. Read the [PortSwigger license agreement](https://portswigger.net/burp/eula), especially Addendum D for Community Edition.
2. Copy `.env.example` to `.env`. Set `BURP_ACCEPT_EULA=true` if you accept the agreement, and set `MCP_BEARER_TOKEN` to at least 32 random characters, such as the output of `openssl rand -hex 32`. Protect the file with `chmod 600 .env`.
3. Start the stack:

   ```sh
   docker compose up -d --build
   ```

4. Check both services:

   ```sh
   docker compose ps
   docker compose exec burp curl -fsS http://127.0.0.1:9090/api/status
   ```

The first build downloads the official Burp and Reburp JARs and verifies their SHA-256 checksums. The first startup can take several dozen seconds. `docker compose down` stops the stack and retains Burp preferences in the `burp-home` volume.

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
