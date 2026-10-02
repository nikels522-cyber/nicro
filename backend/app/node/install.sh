#!/usr/bin/env bash
# nicro cluster node installer. Get the exact command in the panel: Servers -> Add server.
#   curl -fsSL <master>/cluster/node-install.sh | bash -s -- <master-url> <join-token> [--domain example.com]
# Installs Xray + Caddy (camouflage site with a real certificate for own-domain REALITY) and the
# node agent, joins the cluster with the one-time token. Re-running with a new token re-joins.
set -euo pipefail

MASTER="${1:?master url}"; TOKEN="${2:?join token}"; shift 2
DOMAIN=""
while [ $# -gt 0 ]; do case "$1" in --domain) DOMAIN="$2"; shift 2 ;; *) shift ;; esac; done
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
export DEBIAN_FRONTEND=noninteractive
log() { echo -e "\e[32m==>\e[0m $*"; }

log "Packages"
apt-get update -qq
apt-get install -y -qq python3-grpcio >/dev/null 2>&1 || true  # agent: stats over gRPC instead of `xray api`
apt-get install -y -qq curl python3 ufw debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi

log "Joining the cluster"
IP="$(curl -4 -fsS https://api.ipify.org)"
RESP="$(curl -fsS -X POST "$MASTER/cluster/join" -H 'Content-Type: application/json' \
  -d "{\"token\":\"$TOKEN\",\"ip\":\"$IP\",\"hostname\":\"$(hostname)\",\"domain\":\"$DOMAIN\"}")" \
  || { echo "join failed: token invalid/expired? Create a new one in the panel."; exit 1; }
field() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)" <<<"$RESP"; }
SECRET="$(field "['secret']")"; DOMAIN="$(field "['domain']")"; NAME="$(field "['name']")"
PORT_V="$(field "['ports']['vision']")"; PORT_X="$(field "['ports']['xhttp']")"
install -d -m 700 /etc/nicro-node
printf 'MASTER=%s\nSECRET=%s\n' "$MASTER" "$SECRET" > /etc/nicro-node/env
chmod 600 /etc/nicro-node/env
log "Joined as \"$NAME\", domain $DOMAIN"

log "Kernel tuning (BBR)"
cat > /etc/sysctl.d/99-nicro-node.conf <<'EOF'
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.ipv4.tcp_fastopen=3
fs.file-max=1000000
EOF
sysctl -q --system || true

log "Xray-core"
bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install >/dev/null
mkdir -p /etc/systemd/system/xray.service.d
printf '[Unit]\nStartLimitIntervalSec=0\n[Service]\nRestart=always\nRestartSec=3\nEnvironment=GOMEMLIMIT=200MiB\n' > /etc/systemd/system/xray.service.d/20-nicro.conf

log "Camouflage site for $DOMAIN (Caddy, real certificate)"
install -d /var/www/nicro
cat > /var/www/nicro/index.html <<EOF
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>$(hostname)</title><style>body{margin:0;font:16px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;background:#fafafa;color:#333}</style>
</head><body><main><h1>Welcome</h1><p>This site is under construction.</p></main></body></html>
EOF
cat > /etc/caddy/Caddyfile <<EOF
https://$DOMAIN:8444 {
	bind 127.0.0.1
	root * /var/www/nicro
	file_server
	header -Server
}
http://$DOMAIN {
	root * /var/www/nicro
	file_server
	header -Server
}
EOF
systemctl enable caddy >/dev/null 2>&1; systemctl restart caddy

log "Firewall"
for p in 22/tcp 80/tcp "$PORT_V/tcp" "$PORT_X/tcp"; do ufw allow "$p" >/dev/null; done
ufw --force enable >/dev/null

log "Node agent"
install -d /opt/nicro-node
curl -fsSL "$MASTER/cluster/node-agent.py" -o /opt/nicro-node/agent.py
curl -fsSL "$MASTER/cluster/node-sshcore.py" -o /opt/nicro-node/sshcore.py  # SSH control from the panel
cat > /etc/systemd/system/nicro-node.service <<'EOF'
[Unit]
Description=nicro cluster node agent
After=network-online.target xray.service
Wants=network-online.target

[Service]
EnvironmentFile=/etc/nicro-node/env
ExecStart=/usr/bin/python3 /opt/nicro-node/agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable xray nicro-node >/dev/null 2>&1
systemctl restart nicro-node
sleep 8
journalctl -u nicro-node --no-pager -n 5 | sed 's/^/   /'
log "Готово: сервер \"$NAME\" в кластере. Он появится в панели → Серверы."
