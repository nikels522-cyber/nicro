#!/usr/bin/env bash
# Turns a Linux box with a Russian IP into a VPN entry point (cascade relay):
# kernel-level port forwarding to the main VPN server. Encryption stays end-to-end.
# Usually run by install-relay.sh (one command from the panel). Manual use:
#   sudo UPSTREAM=1.2.3.4 AGENT_TOKEN=<from panel> MASTER=<panel url> [SSH_ALLOW=5.6.7.8] [RELAY_NAME=RU-1] bash relay-setup.sh
# (relay-agent.py next to this script is installed when AGENT_TOKEN is set)
set -euo pipefail

UPSTREAM="${UPSTREAM:?main VPN server IP}"
SSH_ALLOW="${SSH_ALLOW:-}"  # empty = SSH open to everyone (key/password as configured)
if [ -n "$SSH_ALLOW" ]; then
  SSH_RULE="ip saddr $SSH_ALLOW tcp dport 22 accept comment \"SSH only from admin\""
  COCKPIT_FROM="$SSH_ALLOW, $UPSTREAM"
else
  SSH_RULE="tcp dport 22 accept comment \"SSH\""
  COCKPIT_FROM="$UPSTREAM"
fi
AGENT_TOKEN="${AGENT_TOKEN:-}"
MASTER="${MASTER:-}"  # panel URL: the agent reports IP changes there (optional)
# Kernel DNAT: 80 = ACME for the relay's own domain, 9443/9444 = Telegram MTProto, 8388 = Shadowsocks
TCP_PORTS="${TCP_PORTS:-80, 8388, 9443, 9444}"
# HAProxy with PROXY protocol v2 (upstream sees real client IPs -> device counting / limits work):
# relay port N -> upstream port N + 10000. All VLESS keys go this way.
PROXY_PORTS="${PROXY_PORTS:-443 2083 2087 8443}"
UDP_PORTS="${UDP_PORTS:-443, 8388}"
WAN="${WAN:-$(ip -4 route show default | awk '{print $5; exit}')}"
export DEBIAN_FRONTEND=noninteractive
log() { echo -e "\e[32m==>\e[0m $*"; }

log "Packages"
apt-get update -qq
apt-get install -y -qq nftables haproxy >/dev/null

log "Kernel: forwarding, BBR, conntrack"
cat > /etc/sysctl.d/99-vpnrelay.conf <<'EOF'
net.ipv4.ip_forward=1
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.core.rmem_max=16777216
net.core.wmem_max=16777216
net.netfilter.nf_conntrack_max=262144
net.netfilter.nf_conntrack_udp_timeout_stream=180
EOF
modprobe nf_conntrack 2>/dev/null || true
sysctl -q --system || true

log "Firewall + forwarding (WAN=$WAN -> $UPSTREAM)"
cat > /etc/nftables.conf <<EOF
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
	chain input {
		type filter hook input priority filter; policy drop;
		iif lo accept
		ct state established,related accept
		ct state invalid drop
		meta l4proto { icmp, ipv6-icmp } accept
		udp dport 68 accept comment "DHCP client"
		$SSH_RULE
		ip saddr { $COCKPIT_FROM } tcp dport 9090 accept comment "Cockpit (admin + via VPN)"
		ip saddr $UPSTREAM tcp dport 9101 accept comment "metrics agent, polled by the panel"
		tcp dport { $(echo $PROXY_PORTS | tr ' ' ',') } accept comment "haproxy (PROXY protocol to upstream)"
	}
	chain forward {
		type filter hook forward priority filter; policy drop;
		ct state established,related accept
		ip daddr $UPSTREAM tcp dport { $TCP_PORTS } accept
		ip daddr $UPSTREAM udp dport { $UDP_PORTS } accept
	}
}

table ip vpnrelay {
	chain prerouting {
		type nat hook prerouting priority dstnat;
		iifname "$WAN" tcp dport { $TCP_PORTS } dnat to $UPSTREAM
		iifname "$WAN" udp dport { $UDP_PORTS } dnat to $UPSTREAM
	}
	chain postrouting {
		type nat hook postrouting priority srcnat;
		ip daddr $UPSTREAM masquerade
	}
}
EOF

# Safety net when SSH gets restricted: the rules are dropped automatically in 3 minutes unless the caller
# confirms access (systemctl stop nft-rollback.timer).
if [ -n "$SSH_ALLOW" ] && [ "${ROLLBACK:-1}" = 1 ]; then
  systemd-run --unit=nft-rollback --on-active=180 /usr/sbin/nft flush ruleset >/dev/null
fi
nft -f /etc/nftables.conf
systemctl enable nftables >/dev/null 2>&1

log "HAProxy: ports $PROXY_PORTS -> $UPSTREAM (+10000, PROXY v2)"
{
  printf 'global\n\tlog /dev/log local0 warning\n\tmaxconn 20000\n\n'
  # tcpka: TCP keepalive on both sides, so connections of vanished mobile clients don't pile up
  printf 'defaults\n\tmode tcp\n\toption tcpka\n\ttimeout connect 5s\n\ttimeout client 1h\n\ttimeout server 1h\n\n'
  for p in $PROXY_PORTS; do
    printf 'listen relay_%s\n\tbind :%s\n\tserver upstream %s:%s send-proxy-v2\n\n' "$p" "$p" "$UPSTREAM" "$((p + 10000))"
  done
} > /etc/haproxy/haproxy.cfg
haproxy -c -q -f /etc/haproxy/haproxy.cfg
systemctl enable haproxy >/dev/null 2>&1
systemctl restart haproxy

mkdir -p /etc/ssh/sshd_config.d
if [ -n "$SSH_ALLOW" ]; then
  log "sshd: allow only $SSH_ALLOW"
  printf 'AllowUsers *@%s\nMaxAuthTries 3\nLoginGraceTime 20\n' "$SSH_ALLOW" > /etc/ssh/sshd_config.d/90-vpnrelay.conf
else
  printf 'MaxAuthTries 3\nLoginGraceTime 20\n' > /etc/ssh/sshd_config.d/90-vpnrelay.conf
fi
(sshd -t && (systemctl reload ssh 2>/dev/null || systemctl reload sshd)) || true

if [ -n "$AGENT_TOKEN" ]; then
  log "Xray client for the blocking monitor (no service)"
  if ! [ -x /usr/local/bin/xray ]; then
    bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install >/dev/null 2>&1 || true
  fi
  systemctl disable --now xray >/dev/null 2>&1 || true
  log "Metrics agent (port 9101, only $UPSTREAM)"
  install -m 755 "$(dirname "$0")/relay-agent.py" /usr/local/bin/relay-agent.py
  SSHCORE="$(dirname "$0")/sshcore.py"  # SSH control from the panel (single source: backend/app/node)
  [ -f "$SSHCORE" ] || SSHCORE="$(dirname "$0")/../backend/app/node/sshcore.py"
  install -m 644 "$SSHCORE" /usr/local/bin/sshcore.py
  # DPI bypass toolkit (zapret): installed on demand from the panel (Дополнения → Обход DPI)
  ZDIR="$(dirname "$0")/zapret"; [ -d "$ZDIR" ] || ZDIR="$(dirname "$0")"
  mkdir -p /opt/nicro-zapret
  [ -f "$ZDIR/nicro-zapret.sh" ] && install -m 755 "$ZDIR/nicro-zapret.sh" /opt/nicro-zapret/nicro-zapret.sh
  [ -f "$ZDIR/strategies.txt" ] && install -m 644 "$ZDIR/strategies.txt" /opt/nicro-zapret/strategies.txt
  cat > /etc/systemd/system/relay-agent.service <<EOF
[Unit]
Description=VPN relay metrics agent
After=network-online.target

[Service]
Environment=AGENT_TOKEN=$AGENT_TOKEN
Environment=AGENT_IFACE=$WAN
Environment="AGENT_PEER_PORTS=$PROXY_PORTS"
Environment="MASTER=$MASTER"
Environment="RELAY_NAME=${RELAY_NAME:-}"
Environment="AGENT_SSH_USER=${SSH_USER:-${SUDO_USER:-root}}"
ExecStart=/usr/bin/python3 /usr/local/bin/relay-agent.py
# root: the panel turns SSH on/off and manages keys here (token auth, port open only to the panel)
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  chmod 600 /etc/systemd/system/relay-agent.service
  systemctl daemon-reload
  systemctl enable relay-agent >/dev/null 2>&1
  systemctl restart relay-agent
fi

log "Entry point ready"
