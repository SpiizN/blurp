#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

case "${1:-}" in
    "")
        docker compose pull burp-image mcp
        ;;
    --local)
        docker compose build burp-image mcp
        ;;
    *)
        printf 'Usage: %s [--local]\n' "$0" >&2
        exit 2
        ;;
esac

burp_image=
mcp_image=
while IFS= read -r image; do
    case "$image" in
        ghcr.io/spiizn/blurp-burp:*) burp_image=$image ;;
        ghcr.io/spiizn/blurp-mcp:*) mcp_image=$image ;;
    esac
done < <(docker compose --profile image config --images)

if [[ -z "$burp_image" || -z "$mcp_image" ]]; then
    printf 'Failed to find the Burp and MCP images in the Compose configuration\n' >&2
    exit 1
fi

docker compose up -d --wait dind

for image in "$burp_image" "$mcp_image"; do
    host_id=$(docker image inspect --format '{{.Id}}' "$image")
    if ! nested_id=$(docker compose exec -T dind docker -H unix:///var/run/docker.sock image inspect --format '{{.Id}}' "$image" 2>/dev/null); then
        nested_id=
    fi
    if [[ "$host_id" != "$nested_id" ]]; then
        docker image save "$image" | docker compose exec -T dind docker -H unix:///var/run/docker.sock image load
    fi
done

docker compose up -d --wait --pull never mcp
