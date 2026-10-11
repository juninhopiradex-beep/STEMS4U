#!/bin/bash
# Corre um comando no CI. Se falhar, publica as últimas linhas do output como anotação
# (aparece no resumo do Actions e na API), para se ver o erro sem abrir o log completo.
LOG=$(mktemp)
"$@" >"$LOG" 2>&1
rc=$?
cat "$LOG"
if [ $rc -ne 0 ]; then
  msg=$(tail -n 60 "$LOG" | sed -e 's/%/%25/g' -e 's/\r//g' | awk '{printf "%s%%0A", $0}')
  echo "::error title=Falhou: $1::$msg"
fi
exit $rc
