#!/bin/sh
set -eu

if [ "${BURP_ACCEPT_EULA:-}" != "true" ]; then
    echo "Burp cannot start: set BURP_ACCEPT_EULA=true after accepting https://portswigger.net/burp/eula" >&2
    exit 1
fi

if [ -z "${PROXPROX_PROXY_TOKEN:-}" ]; then
    echo "Burp cannot start: PROXPROX_PROXY_TOKEN is empty" >&2
    exit 1
fi
case "${PROXPROX_PROXY_HOST:-}" in
    ''|*[!a-zA-Z0-9.-]*|.*|-*)
        echo "Burp cannot start: PROXPROX_PROXY_HOST must be a DNS name" >&2
        exit 1
        ;;
esac
case "${PROXPROX_PROXY_PORT:-}" in
    ''|*[!0-9]*)
        echo "Burp cannot start: PROXPROX_PROXY_PORT must be a TCP port" >&2
        exit 1
        ;;
esac
if [ "$PROXPROX_PROXY_PORT" -lt 1 ] || [ "$PROXPROX_PROXY_PORT" -gt 65535 ]; then
    echo "Burp cannot start: PROXPROX_PROXY_PORT must be between 1 and 65535" >&2
    exit 1
fi

umask 077
jq '.user_options.connections.upstream_proxy.servers = [{
    "destination_host": "*",
    "enabled": true,
    "proxy_host": "127.0.0.1",
    "proxy_port": 18081,
    "auth_type": "basic",
    "username": "proxy",
    "password": env.PROXPROX_PROXY_TOKEN
}]' /opt/burp/user-options.json > /home/burp/user-options.json

cat > /home/burp/stunnel.conf <<EOF
foreground = yes
client = yes
pid =

[proxprox]
accept = 127.0.0.1:18081
connect = ${PROXPROX_PROXY_HOST}:${PROXPROX_PROXY_PORT}
verifyChain = yes
CAfile = /etc/ssl/certs/ca-certificates.crt
checkHost = ${PROXPROX_PROXY_HOST}
sni = ${PROXPROX_PROXY_HOST}
sslVersionMin = TLSv1.2
EOF

unset PROXPROX_PROXY_TOKEN
stunnel /home/burp/stunnel.conf &
stunnel_pid=$!

for attempt in $(seq 1 20); do
    if ! kill -0 "$stunnel_pid" 2>/dev/null; then
        echo "Burp cannot start: Proxprox TLS bridge exited" >&2
        wait "$stunnel_pid"
        exit 1
    fi
    if proxy_status=$(curl --silent --show-error --max-time 3 --output /dev/null \
        --write-out '%{http_code}' --proxy http://127.0.0.1:18081 --noproxy '' \
        http://example.com/ 2>/home/burp/proxy-check.err); then
        if [ "$proxy_status" = "407" ]; then
            break
        fi
    fi
    sleep 1
done
if [ "${proxy_status:-}" != "407" ]; then
    echo "Burp cannot start: Proxprox at ${PROXPROX_PROXY_HOST}:${PROXPROX_PROXY_PORT} did not return the expected unauthenticated 407 response (status ${proxy_status:-unknown})" >&2
    cat /home/burp/proxy-check.err >&2
    exit 1
fi

window_id() {
    xdotool search --onlyvisible --name "$1" 2>/dev/null | sed -n '1p'
}

click_percent() {
    geometry=$(xdotool getwindowgeometry --shell "$1")
    x=$(printf '%s\n' "$geometry" | awk -F= '$1 == "X" {print $2}')
    y=$(printf '%s\n' "$geometry" | awk -F= '$1 == "Y" {print $2}')
    width=$(printf '%s\n' "$geometry" | awk -F= '$1 == "WIDTH" {print $2}')
    height=$(printf '%s\n' "$geometry" | awk -F= '$1 == "HEIGHT" {print $2}')
    xdotool mousemove "$((x + width * $2 / 100))" "$((y + height * $3 / 100))" click 1
}

java -Xmx2g -jar /opt/burp/burp.jar \
    --i-accept-the-license-agreement \
    --user-config-file=/home/burp/user-options.json &
burp_pid=$!

selector_clicked=false
wizard=
for attempt in $(seq 1 240); do
    kill -0 "$burp_pid" 2>/dev/null || { wait "$burp_pid"; exit 1; }
    wizard=$(window_id '^Burp Suite Community Edition v' || true)
    [ -n "$wizard" ] && break
    if [ "$selector_clicked" = false ]; then
        selector=$(window_id '^Burp Suite$' || true)
        if [ -n "$selector" ]; then
            click_percent "$selector" 46 78
            selector_clicked=true
        fi
    fi
    sleep 0.5
done

if [ -z "$wizard" ]; then
    echo "Burp Community startup failed: project wizard did not appear" >&2
    kill "$burp_pid"
    exit 1
fi

sleep 1
temporary_files_dialog=$(window_id '^Delete old temporary files' || true)
if [ -n "$temporary_files_dialog" ]; then
    click_percent "$temporary_files_dialog" 64 92
    sleep 1
fi

click_percent "$wizard" 94 95
sleep 1
click_percent "$wizard" 92 95

for attempt in $(seq 1 180); do
    kill -0 "$burp_pid" 2>/dev/null || { wait "$burp_pid"; exit 1; }
    if curl --fail --silent --max-time 2 http://127.0.0.1:9090/api/status >/dev/null; then
        main_window=$(window_id '^Burp Suite Community Edition v.* - Temporary Project$' || true)
        if [ -z "$main_window" ]; then
            echo "Burp startup failed: the main window is missing after reburp became ready" >&2
            kill "$burp_pid"
            exit 1
        fi
        xdotool windowsize "$main_window" 1920 1080
        xdotool windowmove "$main_window" 0 0
        echo "Burp Community and reburp are ready"
        wait "$burp_pid"
        exit $?
    fi
    sleep 1
done

echo "Burp startup failed: reburp did not answer on 127.0.0.1:9090" >&2
kill "$burp_pid"
exit 1
