#!/usr/bin/env python3
"""
Gera uma nova senha BETA para o STEMS4U by Piradex (mesmo protocolo do ANALYSER, MIXSPACE e DELEX).

Uso:  python3 tools/nova_senha_beta.py 2026-11-01  [id]
  -> imprime a senha (para dar ao tester) e acrescenta o salt + hash às chaves da app
     (stems4u/license.py) e da versão web (ui/index.html e index.html).
     Depois é só fazer push: o GitHub testa, compila e publica.

A senha nunca vai para o repositório: só o salt e o hash PBKDF2-HMAC-SHA256 (60 000 iterações).
"""
import datetime
import hashlib
import json
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ITER = 60000                     # tem de ser igual a stems4u.license.ITERATIONS
ALFA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

if len(sys.argv) < 2:
    sys.exit(__doc__)
data = datetime.date.fromisoformat(sys.argv[1])
sys.path.insert(0, str(ROOT))
from stems4u.license import KEYS  # noqa: E402

ident = sys.argv[2] if len(sys.argv) > 2 else f"beta-{len([k for k in KEYS if k['kind'] == 'trial']) + 1:02d}"
if any(k["id"] == ident for k in KEYS):
    sys.exit(f"Já existe uma chave com o id {ident}.")
senha = "S4U-" + "-".join("".join(secrets.choice(ALFA) for _ in range(4)) for _ in range(3))
salt = secrets.token_bytes(16)
entry = {"id": ident, "kind": "trial", "salt": salt.hex(),
         "hash": hashlib.pbkdf2_hmac("sha256", senha.encode(), salt, ITER).hex(), "exp": data.isoformat()}
keys = KEYS + [entry]

# app (Python)
py = ROOT / "stems4u" / "license.py"
lines = "\n".join(
    f'    {{"id": "{k["id"]}", "kind": "{k["kind"]}", "salt": "{k["salt"]}",\n'
    f'     "hash": "{k["hash"]}", "exp": {json.dumps(k["exp"]) if k["exp"] else "None"}}},' for k in keys)
src = py.read_text("utf-8")
src, n = re.subn(r"(KEYS: list\[dict\] = \[\n).*?(\n\]\n# <<< CHAVES)", lambda m: m.group(1) + lines + m.group(2), src, flags=re.S)
if n != 1:
    sys.exit("Não encontrei as chaves em stems4u/license.py.")
py.write_text(src, "utf-8")

# versão web (as duas cópias da página)
for f in ("ui/index.html", "index.html"):
    p = ROOT / f
    s = p.read_text("utf-8")
    s, n = re.subn(r"const S4U_KEYS = \[.*?\]; // <<< CHAVES",
                   lambda m: "const S4U_KEYS = " + json.dumps(keys) + "; // <<< CHAVES", s, flags=re.S)
    if n != 1:
        sys.exit(f"Não encontrei as chaves em {f}.")
    p.write_text(s, "utf-8")

print(f"\nSenha beta do STEMS4U (válida até {data:%d/%m/%Y}, id {ident}):  {senha}\n")
print("Chave acrescentada à app e à versão web. Guarda a senha: não fica escrita em lado nenhum.")
