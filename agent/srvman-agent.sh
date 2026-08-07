#!/usr/bin/env bash
# SrvMan agent — единый серверный скрипт для деплоя/удаления проектов и сбора метрик.
# Общается по протоколу: одна JSON-команда на stdin -> одна JSON-строка ответа на stdout.
# Рассчитан на Alpine Linux + OpenRC. Требует bash, jq, git (ставятся автоматически при первом запуске).

set -u

PROJECTS_DIR="${SRVMAN_PROJECTS_DIR:-/mnt/data/projects}"
STATE_DIR="${SRVMAN_STATE_DIR:-/mnt/data/srvman}"
MANIFEST="$STATE_DIR/manifest.json"
LOG_DIR="/var/log/srvman"
INIT_DIR="/etc/init.d"
SVC_PREFIX="srv-"
FLASH_MOUNT="${SRVMAN_FLASH_MOUNT:-/mnt/data}"

mkdir -p "$PROJECTS_DIR" "$STATE_DIR" "$LOG_DIR"
[ -f "$MANIFEST" ] || echo '{"services":{}}' > "$MANIFEST"

err() {
    jq -n --arg msg "$1" '{ok:false, error:$msg}'
    exit 0
}

require_bin() {
    for b in "$@"; do
        command -v "$b" >/dev/null 2>&1 || return 1
    done
    return 0
}

ensure_packages() {
    require_bin bash jq git && return 0
    apk update >/dev/null 2>&1
    apk add --no-cache bash jq git >/dev/null 2>&1
}

svc_name() { echo "${SVC_PREFIX}$1"; }

manifest_get() {
    jq -r --arg n "$1" '.services[$n] // empty' "$MANIFEST"
}

manifest_set() {
    local name="$1" entry="$2" tmp
    tmp="$(mktemp)"
    jq --arg n "$name" --argjson e "$entry" '.services[$n] = $e' "$MANIFEST" > "$tmp" && mv "$tmp" "$MANIFEST"
}

manifest_del() {
    local name="$1" tmp
    tmp="$(mktemp)"
    jq --arg n "$name" 'del(.services[$n])' "$MANIFEST" > "$tmp" && mv "$tmp" "$MANIFEST"
}

# ---------- deploy ----------

detect_type_and_build_wrapper() {
    # $1 = project dir, $2 = name, $3 = explicit type ("" = auto), $4 = custom command
    local dir="$1" name="$2" type="$3" custom="$4"
    local wrapper="$STATE_DIR/run-$name.sh"
    local entry

    if [ -z "$type" ]; then
        if [ -f "$dir/package.json" ]; then
            type="node"
        elif [ -f "$dir/requirements.txt" ]; then
            type="python"
        elif [ -n "$custom" ]; then
            type="custom"
        else
            return 1
        fi
    fi

    case "$type" in
        node)
            require_bin node npm || { apk add --no-cache nodejs npm >/dev/null 2>&1; }
            ( cd "$dir" && npm install --omit=dev >/dev/null 2>&1 )
            entry="$(jq -r '.main // "index.js"' "$dir/package.json" 2>/dev/null)"
            [ -z "$entry" ] || [ "$entry" = "null" ] && entry="index.js"
            {
                echo "#!/bin/sh"
                echo "cd \"$dir\""
                echo "exec node \"$entry\""
            } > "$wrapper"
            ;;
        python)
            require_bin python3 || { apk add --no-cache python3 py3-pip >/dev/null 2>&1; }
            if [ ! -d "$dir/venv" ]; then
                python3 -m venv "$dir/venv" >/dev/null 2>&1
            fi
            "$dir/venv/bin/pip" install -q -r "$dir/requirements.txt" >/dev/null 2>&1
            if [ -f "$dir/main.py" ]; then entry="main.py"
            elif [ -f "$dir/app.py" ]; then entry="app.py"
            else entry="main.py"; fi
            {
                echo "#!/bin/sh"
                echo "cd \"$dir\""
                echo "exec \"$dir/venv/bin/python3\" \"$entry\""
            } > "$wrapper"
            ;;
        custom)
            [ -z "$custom" ] && return 1
            {
                echo "#!/bin/sh"
                echo "cd \"$dir\""
                echo "exec $custom"
            } > "$wrapper"
            ;;
        *)
            return 1
            ;;
    esac

    chmod +x "$wrapper"
    echo "$type|$wrapper"
    return 0
}

write_init_script() {
    local name="$1" wrapper="$2" svc dir
    svc="$(svc_name "$name")"
    cat > "$INIT_DIR/$svc" <<EOF
#!/sbin/openrc-run

name="$svc"
description="SrvMan project: $name"
command="$wrapper"
command_background="yes"
pidfile="/run/\${RC_SVCNAME}.pid"
output_log="$LOG_DIR/$name.log"
error_log="$LOG_DIR/$name.log"

depend() {
    need net
    after firewall
}
EOF
    chmod +x "$INIT_DIR/$svc"
}

do_deploy() {
    local name git_url branch type custom dir svc existing action_git result wtype wrapper

    name="$(echo "$1" | jq -r '.name // empty')"
    git_url="$(echo "$1" | jq -r '.git_url // empty')"
    branch="$(echo "$1" | jq -r '.branch // "main"')"
    type="$(echo "$1" | jq -r '.type // empty')"
    custom="$(echo "$1" | jq -r '.custom_cmd // empty')"

    [ -z "$name" ] && err "name is required"
    [ -z "$git_url" ] && err "git_url is required"
    echo "$name" | grep -qE '^[a-zA-Z0-9_-]+$' || err "invalid name (use letters, digits, - and _)"

    ensure_packages
    dir="$PROJECTS_DIR/$name"
    svc="$(svc_name "$name")"

    if [ -d "$dir/.git" ]; then
        git -C "$dir" fetch origin "$branch" >/tmp/srvman-git.log 2>&1
        git -C "$dir" checkout "$branch" >>/tmp/srvman-git.log 2>&1
        git -C "$dir" reset --hard "origin/$branch" >>/tmp/srvman-git.log 2>&1
    else
        rm -rf "$dir"
        git clone --branch "$branch" --single-branch "$git_url" "$dir" >/tmp/srvman-git.log 2>&1
    fi
    if [ ! -d "$dir/.git" ]; then
        err "git clone/pull failed: $(tail -c 500 /tmp/srvman-git.log | tr '\n' ' ')"
    fi

    result="$(detect_type_and_build_wrapper "$dir" "$name" "$type" "$custom")"
    if [ $? -ne 0 ] || [ -z "$result" ]; then
        err "could not detect project type and no custom_cmd given"
    fi
    wtype="${result%%|*}"
    wrapper="${result#*|}"

    write_init_script "$name" "$wrapper"

    rc-update add "$svc" default >/tmp/srvman-rc.log 2>&1
    rc-service "$svc" restart >>/tmp/srvman-rc.log 2>&1

    manifest_set "$name" "$(jq -n --arg n "$name" --arg u "$git_url" --arg b "$branch" \
        --arg t "$wtype" --arg d "$dir" --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{name:$n, git_url:$u, branch:$b, type:$t, dir:$d, deployed_at:$ts}')"

    jq -n --arg n "$name" --arg t "$wtype" --arg s "$svc" \
        '{ok:true, name:$n, type:$t, service:$s}'
}

do_remove() {
    local name svc dir
    name="$(echo "$1" | jq -r '.name // empty')"
    [ -z "$name" ] && err "name is required"
    svc="$(svc_name "$name")"
    dir="$PROJECTS_DIR/$name"

    rc-service "$svc" stop >/tmp/srvman-rc.log 2>&1
    rc-update del "$svc" default >>/tmp/srvman-rc.log 2>&1
    rm -f "$INIT_DIR/$svc"
    rm -f "$STATE_DIR/run-$name.sh"
    rm -f "$LOG_DIR/$name.log"
    rm -rf "$dir"
    manifest_del "$name"

    jq -n --arg n "$name" '{ok:true, name:$n, removed:true}'
}

do_service_action() {
    # start/stop/restart for an existing deployed service
    local name="$1" act="$2" svc out rc
    svc="$(svc_name "$name")"
    out="$(rc-service "$svc" "$act" 2>&1)"
    rc=$?
    jq -n --arg n "$name" --arg a "$act" --arg out "$out" --argjson rc "$rc" \
        '{ok: ($rc==0), name:$n, action:$a, output:$out}'
}

do_logs() {
    local name lines file
    name="$(echo "$1" | jq -r '.name // empty')"
    lines="$(echo "$1" | jq -r '.lines // 200')"
    [ -z "$name" ] && err "name is required"
    file="$LOG_DIR/$name.log"
    if [ ! -f "$file" ]; then
        jq -n --arg n "$name" '{ok:true, name:$n, log:""}'
        return
    fi
    jq -n --arg n "$name" --rawfile log <(tail -n "$lines" "$file") '{ok:true, name:$n, log:$log}'
}

# ---------- metrics ----------

get_uptime() {
    awk '{printf "%.0f", $1}' /proc/uptime
}

get_loadavg() {
    awk '{printf "{\"1\":%s,\"5\":%s,\"15\":%s}", $1, $2, $3}' /proc/loadavg
}

get_mem() {
    free -b | awk '
        /^Mem:/ {mt=$2; mu=$3; mf=$4}
        /^Swap:/ {st=$2; su=$3}
        END {printf "{\"mem_total\":%d,\"mem_used\":%d,\"mem_free\":%d,\"swap_total\":%d,\"swap_used\":%d}", mt+0, mu+0, mf+0, st+0, su+0}
    '
}

get_disk() {
    local root_json flash_json
    root_json="$(df -B1 / 2>/dev/null | awk 'NR==2{printf "{\"total\":%d,\"used\":%d,\"free\":%d}", $2, $3, $4}')"
    [ -z "$root_json" ] && root_json='null'
    if mountpoint -q "$FLASH_MOUNT" 2>/dev/null; then
        flash_json="$(df -B1 "$FLASH_MOUNT" 2>/dev/null | awk 'NR==2{printf "{\"total\":%d,\"used\":%d,\"free\":%d}", $2, $3, $4}')"
    else
        flash_json='null'
    fi
    [ -z "$flash_json" ] && flash_json='null'
    printf '{"root":%s,"flash":%s}' "$root_json" "$flash_json"
}

get_services() {
    jq -c '.services // {}' "$MANIFEST" | jq -c 'to_entries | map(.value)' | while read -r arr; do
        echo "$arr" | jq -c '.[]' | while read -r entry; do
            n="$(echo "$entry" | jq -r '.name')"
            svc="$(svc_name "$n")"
            status="$(rc-service "$svc" status 2>&1)"
            if echo "$status" | grep -qi "started"; then st="running"
            elif echo "$status" | grep -qi "stopped"; then st="stopped"
            else st="unknown"; fi
            echo "$entry" | jq -c --arg svc "$svc" --arg st "$st" '. + {service:$svc, status:$st}'
        done
    done | jq -cs '.'
}

do_metrics() {
    local up load mem disk services
    up="$(get_uptime)"
    load="$(get_loadavg)"
    mem="$(get_mem)"
    disk="$(get_disk)"
    services="$(get_services)"
    jq -n --argjson up "$up" --argjson load "$load" --argjson mem "$mem" \
        --argjson disk "$disk" --argjson services "$services" \
        '{ok:true, uptime_seconds:$up, load:$load, memory:$mem, disk:$disk, services:$services}'
}

# ---------- dispatch ----------

main() {
    require_bin jq || { echo '{"ok":false,"error":"jq not installed"}'; exit 0; }

    local input action
    input="$(cat)"
    [ -z "$input" ] && err "empty request"

    action="$(echo "$input" | jq -r '.action // empty' 2>/dev/null)"
    [ -z "$action" ] && err "missing action"

    case "$action" in
        metrics) do_metrics ;;
        deploy) do_deploy "$input" ;;
        remove) do_remove "$input" ;;
        logs) do_logs "$input" ;;
        start) do_service_action "$(echo "$input" | jq -r '.name')" start ;;
        stop) do_service_action "$(echo "$input" | jq -r '.name')" stop ;;
        restart) do_service_action "$(echo "$input" | jq -r '.name')" restart ;;
        ping) jq -n '{ok:true, pong:true}' ;;
        *) err "unknown action: $action" ;;
    esac
}

main
