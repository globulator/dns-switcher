#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$SCRIPT_DIR/dist"
mkdir -p "$DIST_DIR"

OUTPUT_ZIP="$DIST_DIR/DNS-Switcher-Linux-GNOME.zip"
rm -f "$OUTPUT_ZIP"

echo "Упаковка расширения GNOME Shell в $OUTPUT_ZIP..."

cd "$SCRIPT_DIR"

FILES_TO_PACK=(
    metadata.json
    extension.js
    stylesheet.css
    dns_backend.py
    core/
    platforms/
)

for f in dns_presets.json targets_list.txt dns_list.txt; do
    if [ -f "$f" ]; then
        FILES_TO_PACK+=("$f")
    fi
done

zip -r "$OUTPUT_ZIP" "${FILES_TO_PACK[@]}" \
    -x "*.pyc" -x "*__pycache__*" -x "*.tmp*"

echo "Готово! Расширение упаковано: $OUTPUT_ZIP"
