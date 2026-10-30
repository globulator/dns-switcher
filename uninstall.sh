#!/bin/bash
set -e

UUID="dns-switcher@globulator"
OLD_UUID="dns-switcher@mcperchik"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dns-switcher"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/dns-switcher"
EXT_DIR="$HOME/.local/share/gnome-shell/extensions"

echo "=================================================="
echo "    Удаление DNS Switcher (Linux / GNOME)"
echo "=================================================="
echo ""

# 1. Безопасный сброс DNS в NetworkManager обратно на DHCP
echo "[1/4] Сброс параметров DNS сетевого адаптера на DHCP (по умолчанию)..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/main.py" ]; then
    python3 "$SCRIPT_DIR/main.py" set DEFAULT >/dev/null 2>&1 || true
elif [ -f "$SCRIPT_DIR/dns_backend.py" ]; then
    python3 "$SCRIPT_DIR/dns_backend.py" set DEFAULT >/dev/null 2>&1 || true
fi

# 2. Отключение расширения в GNOME
echo "[2/4] Отключение расширения в GNOME Shell..."
gnome-extensions disable "$UUID" >/dev/null 2>&1 || true
gnome-extensions disable "$OLD_UUID" >/dev/null 2>&1 || true

# 3. Удаление файлов расширения из каталога GNOME
echo "[3/4] Удаление файлов расширения..."
if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions uninstall "$UUID" >/dev/null 2>&1 || true
fi
rm -rf "$EXT_DIR/$UUID"
rm -rf "$EXT_DIR/$OLD_UUID"

# 4. Очистка конфигураций и кэша
echo "[4/4] Очистка пользовательских данных..."
read -r -p "Удалить сохранённые серверы и кэш ($CONFIG_DIR)? [y/N]: " answer
case "$answer" in
    [yY][eE][sS]|[yY]|"д"|"Д")
        rm -rf "$CONFIG_DIR" "$CACHE_DIR"
        echo "Конфигурации и кэш удалены."
        ;;
    *)
        echo "Конфигурации сохранены в $CONFIG_DIR."
        ;;
esac

echo ""
echo "=================================================="
echo "  DNS Switcher успешно удалён!"
echo "  Сетевые настройки возвращены к автоматическим."
echo "=================================================="
