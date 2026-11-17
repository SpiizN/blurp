# BlurP

BlurP exposes Burp Suite Community Edition 2026.10.1 through a Streamable HTTP MCP server. Each `start_burp` call creates a temporary Burp instance with Reburp 1.1.15 in a dedicated Docker-in-Docker daemon. Sessions do not share Burp settings, traffic history, or project files.

Burp sends outgoing HTTP and HTTPS requests through Proxprox. Inside each Burp container, a local HTTP proxy bridge carries traffic over verified TLS to the Proxprox HTTPS endpoint. Proxprox then selects the VPN and upstream proxy from its scope rules. The manager checks Burp's loaded upstream rule before marking a session ready. Reburp listens only on the Burp container's loopback interface; a private relay lets the MCP server reach it.

## Start

Requirements: Docker with Compose, Bash, access to the private GHCR images, and about 4 GB of memory per active Burp session. Read the [PortSwigger license agreement](https://portswigger.net/burp/eula) before setting `BURP_ACCEPT_EULA=true`.

1. Log in to GHCR with a GitHub token that can read the private `blurp-burp` and `blurp-mcp` packages: `docker login ghcr.io -u SpiizN`.
2. Copy `.env.example` to `.env`, set `BURP_ACCEPT_EULA=true`, generate an `MCP_BEARER_TOKEN` of at least 32 characters, and set `PROXPROX_PROXY_TOKEN` to the `PROXY_TOKEN` from Proxprox. Keep `.env` private with `chmod 600 .env`.
3. Run `./start.sh`. It pulls both GHCR images, loads changed images into Docker-in-Docker, and starts the MCP server. Check it with `docker compose ps`.

The defaults use `proxy.proxprox.spiizn.xyz:18443` for Proxprox. Change `PROXPROX_PROXY_HOST` and `PROXPROX_PROXY_PORT` in `.env` if needed. The endpoint must be reachable from the Burp containers with a trusted TLS certificate. Burp sessions fail to start if the endpoint is unavailable or Burp does not load the required upstream rule. A wrong Proxprox password causes proxy authentication failures when Burp sends requests.

Set `BLURP_IMAGE_TAG=sha-<full commit SHA>` to pin both images to one release. For unpublished source changes, set `BLURP_IMAGE_TAG=local` and run `./start.sh --local`. The default `./start.sh` pulls from GHCR; it does not build local source.

## Caddy

The MCP server binds to `127.0.0.1:8765` on the host. To expose it through an existing Caddy container on the `proxprox-proxy` Docker network, add these lines to `.env`:

```dotenv
COMPOSE_FILE=compose.yaml:compose.caddy.yaml
CADDY_NETWORK=proxprox-proxy
MCP_PUBLIC_ORIGIN=https://blurp.spiizn.xyz
```

The overlay attaches only the MCP container to that network as `blurp-mcp`. Add this site to the existing Caddyfile and reload Caddy:

```caddyfile
blurp.spiizn.xyz {
    reverse_proxy blurp-mcp:8765
}
```

Point `blurp.spiizn.xyz` at the VPS. MCP clients use `https://blurp.spiizn.xyz/mcp` with `Authorization: Bearer <MCP_BEARER_TOKEN>`. `MCP_PUBLIC_ORIGIN` must match the HTTPS origin exactly, without a trailing slash. The `/health` endpoint requires the same bearer token.

## MCP sessions

Call `start_burp`, then poll `burp_session_status` until the state is `ready`. Pass its `session_id` and `session_token` to every other tool. Use `search_operations` and `describe_operation` to find the live Reburp API contract before calling `call_operation`. Call `stop_burp` when finished.

| Tool | Purpose |
| --- | --- |
| `start_burp` | Start an isolated Burp session. |
| `burp_session_status` | Read startup state, errors, and idle time. |
| `extend_burp` | Add 1 to 3600 seconds to the idle deadline. |
| `stop_burp` | Stop a session after active calls finish. |
| `status` | Read Burp and Reburp versions. |
| `search_operations` | Search Reburp operations. |
| `describe_operation` | Read an operation's parameters and schemas. |
| `call_operation` | Call a Reburp operation and return its HTTP status and body. |

Sessions expire after five idle minutes by default. Calls extend the deadline, and startup does not count against it. Configure `BURP_IDLE_SECONDS` and `MAX_BURP_SESSIONS` in `.env`; the default session limit is two. A manager restart removes abandoned containers and invalidates session tokens. Session tokens are credentials and may appear in MCP client traces.

Burp Community projects are temporary, so session history disappears when a session stops. Professional-only Scanner, Collaborator, and AI operations may return `403`.

## Images and access

The [publish workflow](.github/workflows/publish-images.yaml) publishes private `linux/amd64` and `linux/arm64` images to GHCR on pushes to `main`, tagged `latest` and `sha-<full commit SHA>`. The Burp image downloads the official Burp and Reburp JARs and verifies their SHA-256 checksums.

Only the MCP port is published on the host, on loopback. The manager reaches Docker-in-Docker over TLS without mounting the host Docker socket. Docker-in-Docker runs privileged; use a separate VM or host if you need a stronger isolation boundary. Burp's Proxprox password is passed through container environments and stored in each temporary Burp user configuration. Agents that can export Burp settings through Reburp can read it, so restrict MCP access accordingly. Reburp's shell executor is disabled by default. Send testing traffic only to authorized targets.
