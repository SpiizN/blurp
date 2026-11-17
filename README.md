# BlurP

BlurP exposes Burp Suite Community Edition 2026.10.1 through a Streamable HTTP MCP server. Each `start_burp` call creates a temporary Burp instance with Reburp 1.1.15 in a dedicated Docker-in-Docker daemon. Sessions do not share Burp settings, traffic history, or project files.

Burp sends outgoing HTTP and HTTPS requests through Proxprox. Inside each Burp container, a local HTTP proxy bridge carries traffic over verified TLS to the Proxprox HTTPS endpoint. Proxprox then selects the VPN and upstream proxy from its scope rules. The manager checks Burp's loaded upstream rule before marking a session ready. Reburp listens only on the Burp container's loopback interface; a private relay lets the MCP server reach it.

## Start

Requirements: Docker with Compose, Bash, a reachable Proxprox HTTPS proxy, and about 4 GB of memory per active Burp session. Read the [PortSwigger license agreement](https://portswigger.net/burp/eula) before setting `BURP_ACCEPT_EULA=true`. The repository contains build instructions but no Burp or Reburp JARs.

1. Copy `.env.example` to `.env`. Set `BURP_ACCEPT_EULA=true` after accepting the license, generate an `MCP_BEARER_TOKEN` of at least 32 characters, and set `PROXPROX_PROXY_HOST` to your proxy's DNS name and `PROXPROX_PROXY_TOKEN` to its password. Keep `.env` private with `chmod 600 .env`.
2. Run `./start.sh --local`. The example configuration names the locally built images `blurp-burp:local` and `blurp-mcp:local`. The script loads them into Docker-in-Docker and starts the MCP server. Check it with `docker compose ps`.

The default `PROXPROX_PROXY_PORT` is 18443. The endpoint must be reachable from the Burp containers with a trusted TLS certificate. Burp sessions fail to start if the endpoint is unavailable or Burp does not load the required upstream rule. A wrong Proxprox password causes proxy authentication failures when Burp sends requests.

For an operator with access to the existing private GHCR packages, set `BLURP_IMAGE_PREFIX=ghcr.io/spiizn/blurp` and `BLURP_IMAGE_TAG=latest` in `.env`, log in with `docker login ghcr.io -u <username>`, and run `./start.sh`. Set `BLURP_IMAGE_TAG=sha-<full commit SHA>` to pin both private images to one release. The default `./start.sh` pulls the image names configured in `.env`; public source users should use `--local`.

## Caddy

The MCP server binds to `127.0.0.1:8765` on the host. To expose it through an existing Caddy container on the `proxprox-proxy` Docker network, add these lines to `.env`:

```dotenv
COMPOSE_FILE=compose.yaml:compose.caddy.yaml
CADDY_NETWORK=proxprox-proxy
MCP_PUBLIC_ORIGIN=https://blurp.example.com
```

The overlay attaches only the MCP container to that network as `blurp-mcp`. Add this site to the existing Caddyfile and reload Caddy:

```caddyfile
blurp.example.com {
    reverse_proxy blurp-mcp:8765
}
```

Point your chosen hostname at the server. MCP clients use `https://blurp.example.com/mcp` with `Authorization: Bearer <MCP_BEARER_TOKEN>`. `MCP_PUBLIC_ORIGIN` must match the HTTPS origin exactly, without a trailing slash. The `/health` endpoint requires the same bearer token.

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

## Source and image access

The public repository does not publish images. The Burp Dockerfile downloads the official Burp and Reburp JARs during a local build and verifies their SHA-256 checksums. Existing GHCR images must stay private. Before making the repository public, check both `blurp-burp` and `blurp-mcp` [package access settings](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility): keep visibility private, disable inherited access from the repository, and remove the public repository from Actions access. If you need to update those private images later, build and publish them from a separate private environment.

No reuse license is granted for this source at present.

Only the MCP port is published on the host, on loopback. The manager reaches Docker-in-Docker over TLS without mounting the host Docker socket. Docker-in-Docker runs privileged; use a separate VM or host if you need a stronger isolation boundary. Burp's Proxprox password is passed through container environments and stored in each temporary Burp user configuration. Agents that can export Burp settings through Reburp can read it, so restrict MCP access accordingly. Reburp's shell executor is disabled by default. Send testing traffic only to authorized targets.
