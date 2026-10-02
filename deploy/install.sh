#!/usr/bin/env bash
# nicro panel installer (called by ../install.sh, which downloads the code). Can also be run from a
# directory containing backend/ and frontend-dist/ (SRC=... overrides it).
# Idempotent: re-running updates the code and keeps secrets, users and keys.
set -euo pipefail

SRC="${SRC:-$(cd "$(dirname "$0")" && pwd)}"
APP=/opt/vpnpanel
ENV_FILE=/etc/vpnpanel.env
PANEL_PORT="${PANEL_PORT:-2053}"
export DEBIAN_FRONTEND=noninteractive

log() { echo -e "\e[32m==>\e[0m $*"; }

log "Packages"
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip curl openssl ufw fail2ban rclone debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null

if ! command -v caddy >/dev/null; then
  log "Caddy"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi

log "Kernel tuning (BBR, UDP buffers)"
cat > /etc/sysctl.d/99-vpnpanel.conf <<'EOF'
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.core.rmem_max=16777216
net.core.wmem_max=16777216
net.ipv4.tcp_fastopen=3
net.ipv4.tcp_mtu_probing=1
net.ipv4.ip_forward=1
fs.file-max=1000000
EOF
sysctl -q --system || true

log "Xray-core"
bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install >/dev/null
log "Hysteria2"
bash <(curl -fsSL https://get.hy2.sh/) >/dev/null
mkdir -p /etc/hysteria
if [ ! -f /etc/hysteria/server.crt ]; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 3650 \
    -keyout /etc/hysteria/server.key -out /etc/hysteria/server.crt -subj "/CN=www.apple.com" 2>/dev/null
fi
chown -R hysteria:hysteria /etc/hysteria 2>/dev/null || true
chmod 640 /etc/hysteria/server.key
for svc in xray hysteria-server; do
  mkdir -p /etc/systemd/system/$svc.service.d
  # GOMEMLIMIT: soft memory limit, the Go GC works harder instead of growing on small servers
  printf '[Unit]\nStartLimitIntervalSec=0\n[Service]\nRestart=always\nRestartSec=3\nEnvironment=GOMEMLIMIT=200MiB\n' > /etc/systemd/system/$svc.service.d/20-vpnpanel.conf
done
systemctl daemon-reload
systemctl enable xray hysteria-server >/dev/null 2>&1

log "Telegram proxy (mtg, MTProto Fake-TLS on :9443)"
MTG_VER=2.2.8
MTG_ARCH=$(case "$(uname -m)" in aarch64) echo arm64 ;; *) echo amd64 ;; esac)
if ! /usr/local/bin/mtg --version 2>/dev/null | grep -q "$MTG_VER"; then
  curl -fsSL "https://github.com/9seconds/mtg/releases/download/v$MTG_VER/mtg-$MTG_VER-linux-$MTG_ARCH.tar.gz" | tar -xz -C /tmp
  install -m 755 /tmp/mtg-$MTG_VER-linux-$MTG_ARCH/mtg /usr/local/bin/mtg
fi
if [ ! -f /etc/mtg.toml ]; then
  printf 'secret = "%s"\nbind-to = "0.0.0.0:9443"\nprefer-ip = "prefer-ipv4"\n' \
    "$(/usr/local/bin/mtg generate-secret --hex www.google.com)" > /etc/mtg.toml
fi
cat > /etc/systemd/system/mtg.service <<'EOF'
[Unit]
Description=Telegram MTProto proxy (mtg)
After=network-online.target

[Service]
ExecStart=/usr/local/bin/mtg run /etc/mtg.toml
DynamicUser=yes
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable mtg >/dev/null 2>&1
systemctl restart mtg

log "Panel code"
mkdir -p $APP/data
rm -rf $APP/app $APP/frontend
cp -r "$SRC/backend/app" $APP/app
cp -r "$SRC/frontend-dist" $APP/frontend
cp "$SRC/backend/requirements.txt" $APP/
[ -d $APP/venv ] || python3 -m venv $APP/venv
$APP/venv/bin/pip install -q --upgrade pip
$APP/venv/bin/pip install -q -r $APP/requirements.txt

PUBLIC_IP="$(curl -4 -fsS https://api.ipify.org || hostname -I | awk '{print $1}')"
DOMAIN="${DOMAIN:-$(echo "$PUBLIC_IP" | tr . -).sslip.io}"
FIRST_RUN=0
if [ ! -f $ENV_FILE ]; then
  FIRST_RUN=1
  cat > $ENV_FILE <<EOF
PANEL_PATH=$(openssl rand -hex 8)
JWT_SECRET=$(openssl rand -hex 32)
INTERNAL_SECRET=$(openssl rand -hex 24)
PUBLIC_HOST=$PUBLIC_IP
SUB_BASE_URL=https://$DOMAIN:$PANEL_PORT
VPNPANEL_DATA=$APP/data
FRONTEND_DIST=$APP/frontend
LISTEN_PORT=8000
EOF
  chmod 600 $ENV_FILE
fi
set -a; . $ENV_FILE; set +a

cat > /etc/systemd/system/vpnpanel.service <<EOF
[Unit]
Description=nicro VPN panel
After=network-online.target xray.service
Wants=network-online.target

[Service]
EnvironmentFile=$ENV_FILE
WorkingDirectory=$APP
ExecStart=$APP/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

log "Caddy (HTTPS for $DOMAIN:$PANEL_PORT)"
cat > /etc/caddy/Caddyfile <<EOF
$DOMAIN:$PANEL_PORT {
	@internal path /internal/*
	respond @internal 404
	encode zstd gzip
	@assets path */assets/*
	header @assets Cache-Control "public, max-age=31536000, immutable"
	reverse_proxy 127.0.0.1:8000
	header -Server
}

# camouflage site for self-steal REALITY, managed by the panel
import /etc/caddy/sites/*.caddy
EOF
mkdir -p /etc/caddy/sites
[ -e /etc/caddy/sites/steal.caddy ] || : > /etc/caddy/sites/steal.caddy

log "Firewall"
ufw allow 22/tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow $PANEL_PORT/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
ufw allow 8443/tcp >/dev/null
ufw allow 8388 >/dev/null
ufw allow 9443/tcp >/dev/null
ufw allow 9444/tcp >/dev/null
ufw allow 2083/tcp >/dev/null
ufw allow 2087/tcp >/dev/null
for p in 10443 12083 12087 18443; do  # VLESS from relays (PROXY protocol twins, port + 10000)
  ufw allow $p/tcp >/dev/null
done
ufw --force enable >/dev/null
systemctl enable --now fail2ban >/dev/null 2>&1 || true

ADMIN_PASS=""
if [ $FIRST_RUN = 1 ]; then
  ADMIN_PASS="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-16)"
  (cd $APP && $APP/venv/bin/python -m app.cli admin admin "$ADMIN_PASS")
fi

systemctl daemon-reload
systemctl enable vpnpanel caddy >/dev/null 2>&1
systemctl restart vpnpanel caddy

for i in $(seq 1 20); do  # wait for the panel to answer (it generates keys on the first start)
  curl -fsS -o /dev/null "http://127.0.0.1:8000/$PANEL_PATH/" 2>/dev/null && break
  sleep 1
done
RELAY_CMD=$(cd $APP && $APP/venv/bin/python -m app.cli info 2>/dev/null | sed -n 's/^RELAY_COMMAND=//p')

B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; N=$'\e[0m'
cat <<EOF

${G}════════════════════════════════════════════════════════════════════${N}
${B} nicro установлен${N}
${G}════════════════════════════════════════════════════════════════════${N}

 ${B}Панель:${N}  https://$DOMAIN:$PANEL_PORT/$PANEL_PATH/
EOF
if [ -n "$ADMIN_PASS" ]; then
  cat <<EOF
 ${B}Логин:${N}   admin
 ${B}Пароль:${N}  $ADMIN_PASS      ${Y}← сохраните, больше не покажется${N}
EOF
else
  echo " Логин и пароль прежние (обновление). Сброс: cd $APP && set -a && . $ENV_FILE && set +a && venv/bin/python -m app.cli admin admin <новый>"
fi
cat <<EOF

 ${B}Что сделать дальше${N}
  1. Откройте панель, войдите, смените пароль и включите 2FA (Безопасность → Мой аккаунт).
  2. Создайте клиента (Клиенты → Создать) — ссылка для него появится в карточке, кнопка «Поделиться».
  3. Желательно: свой домен для маскировки — A-запись → $PUBLIC_IP, затем
     Настройки → «Свой домен для маскировки». Ключи «🛡 свой домен» работают у мобильных операторов.
  4. Telegram-бот (напоминания, оплата, поддержка): @BotFather → /newbot → токен в Дополнения → Telegram-бот.
  5. Приложение на телефон: в панели кнопка «📱 Приложение на телефон» (QR + установка).

 ${B}Точка входа с российским IP${N} (Raspberry Pi или VPS в РФ — помогает на мобильном интернете).
 Выполните на той машине:
   $RELAY_CMD
 ${B}Узел-выход в другой стране${N}: панель → Серверы → «Узел-выход» — там одноразовая команда.

 Обновление панели: та же команда установки ещё раз.
${G}════════════════════════════════════════════════════════════════════${N}
EOF
