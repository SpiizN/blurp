#!/bin/sh
set -eu

if [ "${BURP_ACCEPT_EULA:-}" != "true" ]; then
    echo "Burp cannot start: set BURP_ACCEPT_EULA=true after accepting https://portswigger.net/burp/eula" >&2
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
    --user-config-file=/opt/burp/user-options.json &
burp_pid=$!

for attempt in $(seq 1 120); do
    kill -0 "$burp_pid" 2>/dev/null || { wait "$burp_pid"; exit 1; }
    selector=$(window_id '^Burp Suite$' || true)
    wizard=$(window_id '^Burp Suite Community Edition v' || true)
    if [ -n "$selector" ]; then
        click_percent "$selector" 46 77
        break
    fi
    [ -n "$wizard" ] && break
    sleep 0.5
done

for attempt in $(seq 1 120); do
    kill -0 "$burp_pid" 2>/dev/null || { wait "$burp_pid"; exit 1; }
    wizard=$(window_id '^Burp Suite Community Edition v' || true)
    [ -n "$wizard" ] && break
    sleep 0.5
done

if [ -z "${wizard:-}" ]; then
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
