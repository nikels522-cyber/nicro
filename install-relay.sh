#!/usr/bin/env bash
# nicro — точка входа (машина с российским IP: Raspberry Pi, мини-ПК или VPS в РФ).
# Пересылает подключения клиентов на главный сервер; шифрование сквозное, ключи и трафик — на главном.
# Помогает там, где мобильные операторы режут зарубежные адреса.
#
# Готовая команда с вашими данными — в панели: Серверы → «Точка входа». Вид:
#   curl -fsSL https://raw.githubusercontent.com/nikels522-cyber/nicro/main/install-relay.sh \
#     | sudo bash -s -- --master https://<панель>:2053 --token <токен точек входа>
#
# Параметры:
#   --master URL      адрес панели (Базовый URL подписок, без секретного пути)
#   --token TOKEN     токен точек входа из панели
#   --name NAME       как точка будет называться у клиентов (по умолчанию RU-<номер>)
#   --ssh-allow IP    пускать по SSH только с этого IP (по умолчанию SSH открыт)
#   --ssh-user USER   чьи SSH-ключи управляются из панели (по умолчанию пользователь sudo или root)
# Без параметров скрипт спросит всё сам.
set -euo pipefail

REPO="${NICRO_REPO:-nikels522-cyber/nicro}"
REF="${NICRO_REF:-main}"
RAW="https://raw.githubusercontent.com/$REPO/$REF"
DIR=/opt/nicro-relay
c_ok=$'\e[32m'; c_warn=$'\e[33m'; c_err=$'\e[31m'; c_b=$'\e[1m'; c_0=$'\e[0m'
log() { echo -e "${c_ok}==>${c_0} $*"; }
die() { echo -e "${c_err}✖ $*${c_0}" >&2; exit 1; }
has_tty() { { : </dev/tty; } 2>/dev/null; }
ask() {  # ask "prompt" default -> reads from the terminal even when the script comes from curl | bash
  local a=""
  if has_tty; then read -r -p "$1${2:+ [$2]}: " a </dev/tty || true; fi
  echo "${a:-$2}"
}

MASTER="" TOKEN="" NAME="" SSH_ALLOW="" SSH_USER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --master) MASTER="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --ssh-allow) SSH_ALLOW="$2"; shift 2 ;;
    --ssh-user) SSH_USER="$2"; shift 2 ;;
    *) die "Неизвестный параметр $1" ;;
  esac
done

echo -e "${c_b}nicro · точка входа${c_0}"
[ "$(id -u)" = 0 ] || die "Запустите от root: curl … | sudo bash -s -- …"
. /etc/os-release
case "$ID" in ubuntu|debian|raspbian) ;; *) die "Поддерживаются Debian, Ubuntu, Raspberry Pi OS (у вас: $PRETTY_NAME)" ;; esac

[ -n "$MASTER" ] || MASTER=$(ask "Адрес панели (например https://1-2-3-4.sslip.io:2053)" "")
[ -n "$TOKEN" ] || TOKEN=$(ask "Токен точек входа (панель → Серверы → Точка входа)" "")
[ -n "$MASTER" ] && [ -n "$TOKEN" ] || die "Нужны адрес панели и токен — скопируйте готовую команду из панели"
MASTER="${MASTER%/}"
[ -n "$NAME" ] || NAME=$(ask "Название для клиентов" "")
SSH_USER="${SSH_USER:-${SUDO_USER:-root}}"

HOST=$(echo "$MASTER" | sed -E 's#^https?://##; s#[:/].*$##')
apt-get update -qq && apt-get install -y -qq curl ca-certificates python3 iproute2 >/dev/null
if [[ "$HOST" =~ ^([0-9]+)-([0-9]+)-([0-9]+)-([0-9]+)\.sslip\.io$ ]]; then
  UPSTREAM="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.${BASH_REMATCH[3]}.${BASH_REMATCH[4]}"
else
  UPSTREAM=$(getent ahostsv4 "$HOST" | awk 'NR==1 {print $1}')
fi
[ -n "$UPSTREAM" ] || die "Не удалось определить IP главного сервера из $MASTER"

log "Проверка связи с панелью ($MASTER)"
code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$MASTER/cluster/relay-check" || true)
case "$code" in
  200) ;;
  403) die "Токен не подходит — скопируйте команду заново из панели (Серверы → Точка входа)" ;;
  000) die "Панель $MASTER недоступна с этой машины" ;;
  *) die "Панель ответила HTTP $code — проверьте адрес (без секретного пути панели)" ;;
esac

log "Загрузка файлов точки входа"
mkdir -p "$DIR"
for f in deploy/relay-setup.sh deploy/relay-agent.py backend/app/node/sshcore.py deploy/zapret/nicro-zapret.sh deploy/zapret/strategies.txt; do
  curl -fsSL "$RAW/$f" -o "$DIR/$(basename "$f")" || die "Не удалось скачать $f"
done

ROLLBACK=0
if [ -n "$SSH_ALLOW" ] && has_tty; then  # without a terminal nobody could confirm: no auto-rollback then
  ROLLBACK=1
  echo -e "${c_warn}SSH будет открыт только для $SSH_ALLOW. Если через 3 минуты вход не подтвердить, правила откатятся сами.${c_0}"
fi
ROLLBACK="$ROLLBACK" UPSTREAM="$UPSTREAM" SSH_ALLOW="$SSH_ALLOW" AGENT_TOKEN="$TOKEN" MASTER="$MASTER" RELAY_NAME="$NAME" SSH_USER="$SSH_USER" \
  bash "$DIR/relay-setup.sh"

if [ "$ROLLBACK" = 1 ]; then
  ok=$(ask "Откройте НОВОЕ SSH-подключение с $SSH_ALLOW. Получилось войти? (y/n)" "n")
  if [ "$ok" = y ] || [ "$ok" = Y ]; then
    systemctl stop nft-rollback.timer 2>/dev/null || true
    log "Правила закреплены"
  else
    echo -e "${c_warn}Через 3 минуты правила откатятся — запустите установку снова без --ssh-allow или с правильным IP.${c_0}"
  fi
fi

sleep 3
systemctl is-active --quiet relay-agent || die "Агент не запустился: journalctl -u relay-agent -n 30"
MYIP=$(curl -4 -fsS https://api.ipify.org 2>/dev/null || echo "?")

G=$'\e[32m'; B=$'\e[1m'; N=$'\e[0m'
cat <<EOF

${G}════════════════════════════════════════════════════════════════════${N}
${B} Точка входа готова${N}   внешний IP: $MYIP → главный сервер $UPSTREAM
${G}════════════════════════════════════════════════════════════════════${N}

 Через минуту точка появится в панели (Серверы → «Точки входа») и её ключи
 «через ${NAME:-RU-…}» сами добавятся в подписки всех клиентов. Владельцу придёт сообщение в Telegram.

 ${B}Что проверить в панели${N}
  1. Серверы → карточка точки: «онлайн», нагрузка, температура (у Raspberry Pi).
  2. Обзор → «Проверка из РФ» → «Проверить»: ключи через точку должны быть зелёными.
  3. Рекомендуется свой домен для точки (мобильные операторы пропускают лучше):
     A-запись, например ru.example.com → $MYIP; затем Серверы → точка → «изменить» → «Свой домен».
  4. Если IP точки меняется (домашний интернет) — панель обновит ключи сама; для домена укажите
     доступ к API reg.ru в Настройки → «Свой домен и DNS».

 ${B}Важно${N}
  • Если машина дома за роутером, пробросьте на неё TCP 80, 443, 2083, 2087, 8443, 9443, 9444
    и UDP 443, 8388; порт 9101 должен быть доступен главному серверу ($UPSTREAM).
  • SSH этой машины включается/выключается из панели: Серверы → точка → «SSH».
  • Повторный запуск команды обновляет точку входа.
${G}════════════════════════════════════════════════════════════════════${N}
EOF
