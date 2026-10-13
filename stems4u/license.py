"""Acesso por senha do STEMS4U by Piradex.

Mesmo protocolo do ANALYSER, do MIXSPACE e do DELEX:

* uma senha **master** (licença completa, sem prazo) e senhas **beta** com data de validade;
* o código só guarda um *salt* aleatório e o hash PBKDF2-HMAC-SHA256 (60 000 iterações) de
  cada senha — as senhas em claro nunca entram no repositório nem na app;
* "Lembrar neste computador" grava um token ligado a este computador (não a senha);
* uma senha beta deixa de valer no fim do dia da validade (hora local), mesmo a meio da sessão.

Novas senhas beta: python3 tools/nova_senha_beta.py 2026-11-01 (actualiza este ficheiro e a
versão web).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
import platform
import subprocess
import threading
import time
import uuid
from pathlib import Path

from . import config

ITERATIONS = 60000
PRODUCT = "STEMS4U"

# >>> CHAVES (gerado por tools/nova_senha_beta.py — só salt + hash)
KEYS: list[dict] = [
    {"id": "master", "kind": "master", "salt": "e4d0c6ae252f48796a9362157c8f0ee5",
     "hash": "09775cde9c25bd6f2083e55dc55b2f09e8ae0ac163a80c65b2f39e92e92d7251", "exp": None},
    {"id": "beta-01", "kind": "trial", "salt": "a0000d6756060e9bbf4d46dc886e7c9b",
     "hash": "0da075dee600e9914c4026d6dafcdab958164aa6c77cea663add1062cbbc0d8b", "exp": "2026-11-01"},
    {"id": "beta-02", "kind": "trial", "salt": "d310eb7e3160e996f52f79cb765506c7",
     "hash": "53f9d6f6904535e5e4d94f5724ed9229d4936275a6c53a73fc3a07026e3411d7", "exp": "2026-11-01"},
    {"id": "beta-03", "kind": "trial", "salt": "557b1b4f431aa5e7094976f19c339812",
     "hash": "7c6389aea2aca53d866ca8cae37b13a1bd268dd315284d05723d1ca5e3b9f627", "exp": "2026-11-01"},
    {"id": "beta-04", "kind": "trial", "salt": "41dba5fc6687664bdf2fdf939a4820fa",
     "hash": "b13443a3d84c513b5d8a9d1e3f41801053eee21252e6d848212a8d1a59cfd96a", "exp": "2026-11-01"},
    {"id": "beta-05", "kind": "trial", "salt": "ff06021fba2ead33e067aef9df9ee6aa",
     "hash": "541ccbaccbedaac2a8351a00fed56757c3b3a3e247dd740a8be865a856d7aecd", "exp": "2026-11-01"},
    {"id": "beta-06", "kind": "trial", "salt": "ebe2fc47442bab9a8e437ac707d0484d",
     "hash": "4aca321d87fa46551b15fea908cdc1813d24284b2f876cc77ce39d6d660522c4", "exp": "2026-11-01"},
    {"id": "beta-07", "kind": "trial", "salt": "dc87b8e88d62a13e12cfdede624210de",
     "hash": "81fdeed1f950b297956d2dc4c41aef4b3f9d1c27e0283bc8421991f7804bf911", "exp": "2026-11-01"},
    {"id": "beta-08", "kind": "trial", "salt": "3c4ca91abbf65864bd7d6cc5efa29bc7",
     "hash": "7158fd608947f5c00b76ea635118a827fb372b5eb7721d7093c42a1a8eb5aa94", "exp": "2026-11-01"},
    {"id": "beta-09", "kind": "trial", "salt": "84cc033707763835dcc9b45ca3a55873",
     "hash": "6121643db9730af70ed94f2c44116f314b4c0674a999eeeda7ef4f450d3e550d", "exp": "2026-11-01"},
    {"id": "beta-10", "kind": "trial", "salt": "98e5ba0c486973afc3cca54667511e77",
     "hash": "a8b3b31a01586698852a3a5863da33341d436acbbc70ed0215cfcb1e894d853f", "exp": "2026-11-01"},
]
# <<< CHAVES


def pbkdf2_hex(password: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), ITERATIONS).hex()


def expiry_end(key: dict) -> _dt.datetime | None:
    if key.get("kind") != "trial" or not key.get("exp"):
        return None
    d = _dt.date.fromisoformat(key["exp"])
    return _dt.datetime(d.year, d.month, d.day, 23, 59, 59)


def is_expired(key: dict, now: _dt.datetime | None = None) -> bool:
    end = expiry_end(key)
    return end is not None and (now or _dt.datetime.now()) > end


def _device_id() -> str:
    """Identificador estável deste computador (não sai daqui: só entra no hash do token)."""
    ident = ""
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True,
                                 text=True, timeout=5).stdout
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    ident = line.split("=")[-1].strip().strip('"')
                    break
        elif platform.system() == "Windows":
            import winreg  # type: ignore
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
                ident = winreg.QueryValueEx(k, "MachineGuid")[0]
        else:
            for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                if os.path.exists(p):
                    ident = Path(p).read_text().strip()
                    break
    except Exception:
        ident = ""
    return ident or ("node-%012x" % uuid.getnode())


class License:
    """Estado da licença deste processo. Seguro para várias threads."""

    def __init__(self, store_path: Path | None = None, keys: list[dict] | None = None):
        self.store_path = Path(store_path) if store_path else config.DATA_DIR / "licenca.json"
        self.keys = keys if keys is not None else KEYS
        self._lock = threading.Lock()
        self._key: dict | None = None
        self._device: str | None = None
        self._try_auto_unlock()

    # ---------------------------------------------------------------- interno
    def _token_for(self, key: dict) -> str:
        if self._device is None:
            self._device = _device_id()
        s = f"{self._device}|{key['id']}|{key['hash']}|{PRODUCT}"
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    def _read_store(self) -> dict:
        try:
            return json.loads(self.store_path.read_text("utf-8"))
        except Exception:
            return {}

    def _write_store(self, data: dict | None):
        try:
            if data:
                self.store_path.parent.mkdir(parents=True, exist_ok=True)
                self.store_path.write_text(json.dumps(data), "utf-8")
            elif self.store_path.exists():
                self.store_path.unlink()
        except OSError:
            config.get_logger("stems4u.license").warning("Não foi possível gravar a licença em %s", self.store_path)

    def _try_auto_unlock(self):
        st = self._read_store()
        kid, tok = st.get("key"), st.get("token")
        if not kid or not tok:
            return
        for k in self.keys:
            if k["id"] == kid and hmac.compare_digest(tok, self._token_for(k)) and not is_expired(k):
                self._key = k
                return

    # ---------------------------------------------------------------- público
    @property
    def unlocked(self) -> bool:
        self.check_expiry()
        return self._key is not None

    def check_expiry(self):
        with self._lock:
            if self._key is not None and is_expired(self._key):
                self._key = None
                self._write_store(None)

    def try_password(self, password: str, remember: bool = True) -> str:
        """Devolve "ok", "wrong" ou "expired"."""
        pw = (password or "").strip().upper()
        found, expired = None, False
        for k in self.keys:  # calcula sempre todas: o tempo não revela qual chave existe
            if hmac.compare_digest(pbkdf2_hex(pw, k["salt"]), k["hash"]):
                if is_expired(k):
                    expired = True
                elif found is None:
                    found = k
        if found is None:
            time.sleep(0.4)  # trava tentativas em série
            return "expired" if expired else "wrong"
        with self._lock:
            self._key = found
            self._write_store({"key": found["id"], "token": self._token_for(found)} if remember else None)
        return "ok"

    def lock(self):
        with self._lock:
            self._key = None
            self._write_store(None)

    def unlock_for_tests(self):
        self._key = {"id": "teste", "kind": "master", "salt": "", "hash": "", "exp": None}

    def status(self) -> dict:
        self.check_expiry()
        k = self._key
        if k is None:
            return {"unlocked": False, "kind": None, "expires": None, "label": "Sem sessão"}
        if k["kind"] == "master":
            return {"unlocked": True, "kind": "master", "expires": None, "label": "Licença completa"}
        d = _dt.date.fromisoformat(k["exp"])
        return {"unlocked": True, "kind": "trial", "expires": k["exp"],
                "label": f"BETA · válida até {d:%d/%m/%Y}"}


def locked_error():
    return config.UserError("O STEMS4U está bloqueado.",
                            "Introduz a tua senha (master ou beta) para separar e instalar modelos.",
                            code="locked")
