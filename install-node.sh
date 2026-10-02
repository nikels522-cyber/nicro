#!/usr/bin/env bash
# nicro — узел-выход (дополнительный сервер в другой стране).
# Получает клиентов и настройки с главного сервера; его ключи сами появляются в подписках клиентов;
# трафик, лимиты и устройства считаются общими для всего кластера.
#
# Одноразовая команда (токен действует 1 час) — в панели: Серверы → «Узел-выход». Вид:
#   curl -fsSL https://raw.githubusercontent.com/nikels522-cyber/nicro/main/install-node.sh \
#     | sudo bash -s -- --master https://<панель>:2053 --token nkl_join_...
#
# Параметры:
#   --master URL     адрес панели (без секретного пути)
#   --token TOKEN    одноразовый токен из панели
#   --domain DOMAIN  свой домен узла (A-запись → IP узла); по умолчанию <ip>.sslip.io
# Требования: чистый VPS с Ubuntu 22.04/24.04 или Debian 12/13, свободные порты 80, 443, 8443.
set -euo pipefail

c_ok=$'\e[32m'; c_err=$'\e[31m'; c_b=$'\e[1m'; c_0=$'\e[0m'
log() { echo -e "${c_ok}==>${c_0} $*"; }
die() { echo -e "${c_err}✖ $*${c_0}" >&2; exit 1; }
has_tty() { { : </dev/tty; } 2>/dev/null; }
ask() {
  local a=""
  if has_tty; then read -r -p "$1${2:+ [$2]}: " a </dev/tty || true; fi
  echo "${a:-$2}"
}

MASTER="" TOKEN="" DOMAIN=""
while [ $# -gt 0 ]; do
  case "$1" in
    --master) MASTER="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    *) die "Неизвестный параметр $1" ;;
  esac
done

echo -e "${c_b}nicro · узел-выход${c_0}"
[ "$(id -u)" = 0 ] || die "Запустите от root: curl … | sudo bash -s -- …"
. /etc/os-release
case "$ID" in ubuntu|debian) ;; *) die "Поддерживаются Ubuntu и Debian (у вас: $PRETTY_NAME)" ;; esac
[ -n "$MASTER" ] || MASTER=$(ask "Адрес панели (например https://1-2-3-4.sslip.io:2053)" "")
[ -n "$TOKEN" ] || TOKEN=$(ask "Одноразовый токен (панель → Серверы → Узел-выход)" "")
[ -n "$MASTER" ] && [ -n "$TOKEN" ] || die "Нужны адрес панели и токен — скопируйте готовую команду из панели"
MASTER="${MASTER%/}"
for p in 80 443 8443; do
  holder=$(ss -Hltnp "sport = :$p" 2>/dev/null | grep -oP 'users:\(\("\K[^"]+' | head -1 || true)
  if [ -n "$holder" ] && ! [[ "$holder" =~ ^(xray|caddy)$ ]]; then die "Порт $p занят программой «$holder» — нужен чистый сервер"; fi
done

apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null
log "Установка узла с главного сервера ($MASTER)"
curl -fsSL "$MASTER/cluster/node-install.sh" -o /tmp/nicro-node-install.sh || die "Панель $MASTER недоступна с этого сервера"
bash /tmp/nicro-node-install.sh "$MASTER" "$TOKEN" ${DOMAIN:+--domain "$DOMAIN"}
rm -f /tmp/nicro-node-install.sh
MYIP=$(curl -4 -fsS https://api.ipify.org 2>/dev/null || echo "?")

G=$'\e[32m'; B=$'\e[1m'; N=$'\e[0m'
cat <<EOF

${G}════════════════════════════════════════════════════════════════════${N}
${B} Узел-выход подключён${N}   IP: $MYIP
${G}════════════════════════════════════════════════════════════════════${N}

 Узел уже в панели (Серверы → «Узлы-выходы») и через несколько секунд получит всех клиентов.
 Его ключи «🛡» сами добавятся в подписки — клиентам достаточно обновить подписку в приложении.

 ${B}Что проверить в панели${N}
  1. Серверы → карточка узла: «онлайн», нагрузка, версия Xray.
  2. Обзор → «Проверка из РФ» → «Проверить» — ключи узла должны пройти (если есть точка входа).
  3. Название и флаг страны — Серверы → нажмите на имя узла, чтобы переименовать.
  4. Временно убрать узел у клиентов — кнопка «Вывести из подписок».

 ${B}Свой домен${N} (маскировка лучше, чем <ip>.sslip.io): A-запись → $MYIP, затем запустите
 установку заново с --domain ваш.домен и новым токеном из панели.

 ${B}Обслуживание${N}
  • Агент: systemctl status nicro-node · журнал: journalctl -u nicro-node -f
  • Обновление Xray на всех узлах — кнопка в панели (Настройки → Обновление Xray).
  • SSH узла включается/выключается из панели: Серверы → узел → «SSH».
${G}════════════════════════════════════════════════════════════════════${N}
EOF
