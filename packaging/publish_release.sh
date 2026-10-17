#!/bin/bash
# Envia um instalador para o release "ultima-build" (cria-o se ainda não existir)
# e também para o release da versão actual (v2.0.0, lida de stems4u/__init__.py).
set -e
FILE="$1"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' stems4u/__init__.py)
NOTES="As apps não estão assinadas: no Mac, a primeira vez abre com botão direito → Abrir. Interface em Português e English (selector PT | EN; a escolha é partilhada com os plugins Piradex)."
ensure() {  # tag título prerelease(0/1)
  gh release view "$1" >/dev/null 2>&1 && return 0
  if [ "$3" = 1 ]; then gh release create "$1" --prerelease --title "$2" --notes "Gerado automaticamente pelo GitHub Actions a cada alteração no código. $NOTES" || sleep 5
  else gh release create "$1" --title "$2" --notes "STEMS4U by Piradex $VERSION. $NOTES" || sleep 5; fi   # outro job pode tê-lo criado ao mesmo tempo
}
upload() { for i in 1 2 3; do gh release upload "$1" "$FILE" --clobber && return 0; sleep 5; done; return 1; }
ensure ultima-build "STEMS4U — última build" 1
upload ultima-build
if [ -n "$VERSION" ] && [ "${GITHUB_REF:-refs/heads/main}" = "refs/heads/main" ]; then
  ensure "v$VERSION" "STEMS4U $VERSION" 0
  upload "v$VERSION"
fi
