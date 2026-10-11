#!/bin/bash
# Envia um instalador para o release "ultima-build" (cria-o se ainda não existir).
set -e
TAG=ultima-build
FILE="$1"
if ! gh release view "$TAG" >/dev/null 2>&1; then
  gh release create "$TAG" --prerelease --title "STEMS4U — última build" \
    --notes "Gerado automaticamente pelo GitHub Actions a cada alteração no código. As apps não estão assinadas: no Mac, a primeira vez abre com botão direito → Abrir." \
    || sleep 5   # outro job pode tê-lo criado ao mesmo tempo
fi
for i in 1 2 3; do gh release upload "$TAG" "$FILE" --clobber && exit 0; sleep 5; done
exit 1
