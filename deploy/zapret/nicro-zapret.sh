#!/usr/bin/env bash
# nicro: DPI bypass (zapret / nfqws) for an entry point — only for its traffic to the main VPN server.
#
#   nicro-zapret.sh install                  download nfqws (latest zapret release) + systemd units
#   nicro-zapret.sh select [TARGETS]         test without bypass, then the strategies; keep the first that works
#   nicro-zapret.sh update [TARGETS]         fetch the newest strategy list; re-select if the current one fails
#   nicro-zapret.sh disable                  stop nfqws and remove the queue rules
#   nicro-zapret.sh status                   JSON for the panel
# TARGETS: "host:port,host:port" — TLS names served by the main server through its REALITY ports (the panel
# passes them; saved for the timer). A target works when an HTTPS request to it, sent to the main server's IP,
# completes. Fail-safe: the queue rule has "bypass", so if nfqws is not running, traffic flows as usual.
set -uo pipefail

DIR=/opt/nicro-zapret
CONF=/etc/nicro-zapret
REPO="${NICRO_REPO:-nikels522-cyber/nicro}"
QNUM=200
PORTS="443, 2083, 2087, 8443, 10443, 12083, 12087, 18443"
mkdir -p "$CONF"
UPSTREAM=$(grep -oP 'server upstream \K[0-9.]+' /etc/haproxy/haproxy.cfg 2>/dev/null | head -1)
log() { echo "$(date '+%F %T') $*" | tee -a "$CONF/log" >&2; }
state() { printf '%s' "$2" > "$CONF/$1"; }

install_nfqws() {
  [ -x "$DIR/nfqws" ] && return 0
  local arch url tmp
  case "$(uname -m)" in aarch64) arch=linux-arm64 ;; armv7l|armv6l) arch=linux-arm ;; x86_64) arch=linux-x86_64 ;; *) arch=linux-x86 ;; esac
  url=$(curl -fsSL https://api.github.com/repos/bol-van/zapret/releases/latest | grep -oP '"browser_download_url": "\K[^"]+zapret-v[0-9.]+\.tar\.gz' | head -1)
  [ -n "$url" ] || { log "cannot find the zapret release"; return 1; }
  tmp=$(mktemp -d)
  curl -fsSL "$url" | tar -xz -C "$tmp" || { log "download failed: $url"; return 1; }
  mkdir -p "$DIR"
  install -m 755 "$(find "$tmp" -path "*binaries/$arch/nfqws" | head -1)" "$DIR/nfqws" || { log "no nfqws for $arch"; return 1; }
  rm -rf "$tmp"
  cat > /etc/systemd/system/nicro-nfqws.service <<EOF
[Unit]
Description=nicro DPI bypass (nfqws) for traffic to the main server
After=network-online.target

[Service]
EnvironmentFile=$CONF/env
ExecStart=$DIR/nfqws --qnum=$QNUM \$NFQWS_ARGS
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
  cat > /etc/systemd/system/nicro-zapret-update.service <<EOF
[Unit]
Description=nicro: refresh DPI bypass strategies
[Service]
Type=oneshot
ExecStart=$DIR/nicro-zapret.sh update
EOF
  cat > /etc/systemd/system/nicro-zapret-update.timer <<EOF
[Unit]
Description=nicro: refresh DPI bypass strategies every 6 hours
[Timer]
OnBootSec=10min
OnUnitActiveSec=6h
[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  log "installed nfqws ($(basename "$url"), $arch)"
}

rules_on() {
  nft list table inet nicrozapret >/dev/null 2>&1 && return
  nft -f - <<EOF
table inet nicrozapret {
	chain post {
		type filter hook postrouting priority mangle; policy accept;
		meta mark and 0x40000000 == 0 ip daddr $UPSTREAM tcp dport { $PORTS } ct original packets 1-6 queue num $QNUM bypass
	}
}
EOF
}
rules_off() { nft delete table inet nicrozapret 2>/dev/null || true; }

apply() {  # apply "<strategy or none>"
  if [ "$1" = none ]; then
    systemctl stop nicro-nfqws 2>/dev/null; rules_off
  else
    printf 'NFQWS_ARGS="%s"\n' "$1" > "$CONF/env"
    systemctl restart nicro-nfqws && sleep 1 && rules_on
  fi
  state strategy "$1"
}

targets() { [ -n "${1:-}" ] && state targets "$1"; cat "$CONF/targets" 2>/dev/null; }

works() {  # every target answers (2 of 3 tries each)
  local t host port ok n
  for t in $(targets | tr ',' ' '); do
    host=${t%:*}; port=${t##*:}; ok=0
    for n in 1 2 3; do
      curl -s -o /dev/null --max-time 7 --resolve "$host:$port:$UPSTREAM" "https://$host:$port/" && ok=$((ok + 1))
    done
    [ $ok -ge 2 ] || return 1
  done
  return 0
}

select_strategy() {
  [ -n "$(targets "${1:-}")" ] || { log "no targets"; return 1; }
  state last_check "$(date +%s)"
  apply none
  if works; then state result "direct path works, bypass not needed"; log "direct path works"; return 0; fi
  install_nfqws || return 1
  local s
  while IFS= read -r s; do
    s="${s%%#*}"; s="$(echo "$s" | xargs)"; [ -n "$s" ] || continue
    apply "$s"
    if works; then state result "bypass active"; log "working strategy: $s"; return 0; fi
    log "no luck: $s"
  done < "$CONF/strategies.txt"
  apply none
  state result "no strategy got through"; log "no working strategy"
  return 1
}

fetch_list() {
  curl -fsSL "https://raw.githubusercontent.com/$REPO/main/deploy/zapret/strategies.txt" -o "$CONF/strategies.new" \
    && mv "$CONF/strategies.new" "$CONF/strategies.txt" && log "strategy list updated ($(grep -cv '^\s*#\|^\s*$' "$CONF/strategies.txt") entries)"
  [ -f "$CONF/strategies.txt" ] || cp "$DIR/strategies.txt" "$CONF/strategies.txt" 2>/dev/null
}

case "${1:-status}" in
  install) install_nfqws && fetch_list && systemctl enable --now nicro-zapret-update.timer >/dev/null 2>&1; state enabled 1 ;;
  select) state enabled 1; fetch_list; select_strategy "${2:-}" ;;
  update)
    [ "$(cat "$CONF/enabled" 2>/dev/null)" = 1 ] || exit 0
    fetch_list
    state last_check "$(date +%s)"
    works && { state result "$( [ "$(cat "$CONF/strategy" 2>/dev/null)" = none ] && echo 'direct path works, bypass not needed' || echo 'bypass active')"; exit 0; }
    log "current setting stopped working, selecting again"; select_strategy ;;
  try)  # diagnostics: apply strategy number N, test, restore the previous setting
    prev=$(cat "$CONF/strategy" 2>/dev/null || echo none)
    s=$(grep -v '^\s*#' "$CONF/strategies.txt" | grep -v '^\s*$' | sed -n "${2:-1}p")
    install_nfqws && apply "$s" && if works; then echo "WORKS: $s"; else echo "FAILS: $s"; fi
    nft list table inet nicrozapret >/dev/null 2>&1 && echo "queue rule: on" ; systemctl is-active nicro-nfqws
    apply "$prev" ;;
  disable) apply none; state enabled 0; systemctl disable --now nicro-zapret-update.timer >/dev/null 2>&1; state result "disabled" ;;
  status)
    python3 - "$CONF" "$DIR" <<'PY'
import json, os, sys
conf, d = sys.argv[1], sys.argv[2]
r = lambda n, dflt="": open(os.path.join(conf, n)).read().strip() if os.path.exists(os.path.join(conf, n)) else dflt
lines = r("strategies.txt").splitlines()
log = r("log").splitlines()[-8:]
print(json.dumps({"installed": os.path.exists(os.path.join(d, "nfqws")), "enabled": r("enabled") == "1",
                  "strategy": r("strategy", "none"), "result": r("result"), "last_check": int(r("last_check", "0") or 0),
                  "targets": r("targets"), "strategies": sum(1 for x in lines if x.strip() and not x.strip().startswith("#")),
                  "nfqws": os.system("systemctl is-active --quiet nicro-nfqws") == 0, "log": log}, ensure_ascii=False))
PY
    ;;
  *) echo "usage: $0 install|select [targets]|update|disable|status"; exit 1 ;;
esac
