#!/usr/bin/env bash
# nicro — главный сервер с веб-панелью (установка и обновление).
#
#   curl -fsSL https://raw.githubusercontent.com/nikels522-cyber/nicro/main/install.sh | sudo bash
#
# Необязательно (переменные окружения перед bash):
#   DOMAIN=panel.example.com   свой домен панели (A-запись → IP сервера); по умолчанию <ip>.sslip.io
#   PANEL_PORT=2053            порт панели и подписок
#   NICRO_REF=main             ветка/тег репозитория
# Повторный запуск обновляет панель, сохраняя клиентов, ключи и настройки.
set -euo pipefail

REPO="${NICRO_REPO:-nikels522-cyber/nicro}"
REF="${NICRO_REF:-main}"
WORK=/opt/nicro-src
export DEBIAN_FRONTEND=noninteractive

c_ok=$'\e[32m'; c_warn=$'\e[33m'; c_err=$'\e[31m'; c_b=$'\e[1m'; c_0=$'\e[0m'
log() { echo -e "${c_ok}==>${c_0} $*"; }
warn() { echo -e "${c_warn}!!${c_0} $*"; }
die() { echo -e "${c_err}✖ $*${c_0}" >&2; exit 1; }

echo -e "${c_b}nicro · главный сервер${c_0}  (репозиторий $REPO, $REF)"

# ---------------------------------------------------------------- checks
[ "$(id -u)" = 0 ] || die "Запустите от root: curl … | sudo bash"
. /etc/os-release
case "$ID" in
  ubuntu|debian) ;;
  *) die "Поддерживаются Ubuntu 22.04/24.04 и Debian 12/13 (у вас: $PRETTY_NAME)" ;;
esac
case "$(uname -m)" in x86_64|aarch64) ;; *) die "Поддерживаются x86_64 и arm64 (у вас: $(uname -m))" ;; esac
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
[ "$MEM_MB" -ge 450 ] || die "Нужно минимум 512 МБ памяти (у вас ${MEM_MB} МБ)"
[ "$MEM_MB" -ge 900 ] || warn "Памяти ${MEM_MB} МБ — будет работать, но лучше от 1 ГБ"
for p in 443 2083 2087 8443 "${PANEL_PORT:-2053}"; do
  holder=$(ss -Hltnp "sport = :$p" 2>/dev/null | grep -oP 'users:\(\("\K[^"]+' | head -1 || true)
  if [ -n "$holder" ] && ! [[ "$holder" =~ ^(xray|caddy|haproxy)$ ]]; then
    [ "${FORCE:-0}" = 1 ] || die "Порт $p занят программой «$holder». Освободите его (или FORCE=1, если знаете, что делаете)"
  fi
done

# ---------------------------------------------------------------- source
log "Загрузка nicro"
apt-get update -qq
apt-get install -y -qq curl ca-certificates tar >/dev/null
rm -rf "$WORK" && mkdir -p "$WORK"
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" | tar -xz --strip-components=1 -C "$WORK" \
  || die "Не удалось скачать https://github.com/$REPO ($REF)"

# Prebuilt web interface from the release that GitHub Actions makes for every commit; build here otherwise.
SHA=$(curl -fsSL "https://api.github.com/repos/$REPO/commits/$REF" 2>/dev/null | grep -m1 '"sha"' | cut -d'"' -f4 || true)
FE=/tmp/nicro-frontend.tgz
if curl -fsSL -o "$FE" "https://github.com/$REPO/releases/download/frontend-$REF/nicro-frontend.tar.gz" 2>/dev/null \
   && mkdir -p "$WORK/frontend-dist" && tar -xzf "$FE" -C "$WORK/frontend-dist" \
   && { [ -z "$SHA" ] || [ "$(cat "$WORK/frontend-dist/SOURCE_SHA" 2>/dev/null)" = "$SHA" ]; }; then
  log "Веб-интерфейс: готовая сборка ${SHA:0:7}"
else
  log "Веб-интерфейс: сборка на сервере (Node.js 22, ~1–2 минуты)"
  rm -rf "$WORK/frontend-dist"
  if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
    apt-get install -y -qq nodejs >/dev/null
  fi
  (cd "$WORK/frontend" && npm ci --no-audit --no-fund --loglevel=error && npx vite build --logLevel error)
  cp -r "$WORK/frontend/dist" "$WORK/frontend-dist"
fi
rm -f "$FE"

# ---------------------------------------------------------------- install
SRC="$WORK" bash "$WORK/deploy/install.sh"
