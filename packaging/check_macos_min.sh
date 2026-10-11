#!/bin/bash
# Falha se algum binário dentro da app exigir macOS mais recente do que o alvo (ex.: 10.15 Catalina).
APP="$1"; TARGET="${2:-10.15}"; BAD=0
ver_gt() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$1" ] && [ "$1" != "$2" ]; }
while IFS= read -r -d '' f; do
  file -b "$f" | grep -q "Mach-O" || continue
  MIN=$(otool -l "$f" 2>/dev/null | awk '/LC_BUILD_VERSION/{b=1} b&&/minos/{print $2; exit} /LC_VERSION_MIN_MACOSX/{v=1} v&&/version/{print $2; exit}')
  [ -z "$MIN" ] && continue
  if ver_gt "$MIN" "$TARGET"; then echo "INCOMPATÍVEL ($MIN > $TARGET): ${f#$APP/}"; BAD=1; fi
done < <(find "$APP" -type f \( -perm -u+x -o -name "*.so" -o -name "*.dylib" \) -print0)
[ $BAD = 0 ] && echo "OK: todos os binários correm em macOS $TARGET" || { echo "Há binários que não correm em macOS $TARGET"; exit 1; }
