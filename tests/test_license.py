"""Acesso por senha: mesmo protocolo do ANALYSER / MIXSPACE / DELEX (PBKDF2 60 000, só salt + hash)."""
import datetime as dt
import hashlib
import re
import secrets

from stems4u import license as L


def _entry(ident, kind, pw, exp):
    salt = secrets.token_bytes(16)
    return {"id": ident, "kind": kind, "salt": salt.hex(), "exp": exp,
            "hash": hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, L.ITERATIONS).hex()}


def make_keys():
    today = dt.date.today()
    pw = {"master": "STEMS4U-TEST-MAST-ER00-0001", "beta": "S4U-TEST-BETA-0001", "expired": "S4U-TEST-OLDX-0001"}
    keys = [_entry("master", "master", pw["master"], None),
            _entry("beta-01", "trial", pw["beta"], (today + dt.timedelta(days=30)).isoformat()),
            _entry("beta-00", "trial", pw["expired"], (today - dt.timedelta(days=1)).isoformat())]
    return keys, pw


def test_password_flow(tmp_path):
    keys, pw = make_keys()
    store = tmp_path / "lic.json"
    lic = L.License(store_path=store, keys=keys)
    assert not lic.unlocked and lic.status()["label"] == "Sem sessão"
    assert lic.try_password("S4U-NADA-NADA-NADA") == "wrong" and not lic.unlocked
    assert lic.try_password(pw["expired"]) == "expired" and not lic.unlocked
    assert lic.try_password("  " + pw["beta"].lower() + " ") == "ok" and lic.unlocked
    assert lic.status()["kind"] == "trial" and lic.status()["label"].startswith("BETA · válida até ")
    # o ficheiro guardado nunca contém a senha
    assert pw["beta"] not in store.read_text() and "token" in store.read_text()
    # outra sessão no mesmo computador entra sozinha
    assert L.License(store_path=store, keys=keys).unlocked
    lic.lock()
    assert not lic.unlocked and not store.exists()
    assert not L.License(store_path=store, keys=keys).unlocked
    assert lic.try_password(pw["master"], remember=False) == "ok"
    assert lic.status() == {"unlocked": True, "kind": "master", "expires": None, "label": "Licença completa"}
    assert not store.exists()


def test_token_is_tied_to_this_computer(tmp_path, monkeypatch):
    keys, pw = make_keys()
    store = tmp_path / "lic.json"
    assert L.License(store_path=store, keys=keys).try_password(pw["beta"]) == "ok"
    monkeypatch.setattr(L, "_device_id", lambda: "outro-computador")
    assert not L.License(store_path=store, keys=keys).unlocked


def test_beta_expires_mid_session(tmp_path):
    keys, pw = make_keys()
    lic = L.License(store_path=tmp_path / "lic.json", keys=keys)
    assert lic.try_password(pw["beta"]) == "ok"
    keys[1]["exp"] = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    assert not lic.unlocked and lic.status()["unlocked"] is False


def test_expiry_is_end_of_day():
    k = {"kind": "trial", "exp": "2026-11-01"}
    assert not L.is_expired(k, dt.datetime(2026, 11, 1, 23, 59, 0))
    assert L.is_expired(k, dt.datetime(2026, 11, 2, 0, 0, 1))
    assert not L.is_expired({"kind": "master", "exp": None}, dt.datetime(2099, 1, 1))


def test_shipped_keys_have_only_salt_and_hash():
    assert sum(k["kind"] == "master" for k in L.KEYS) == 1
    for k in L.KEYS:
        assert re.fullmatch(r"[0-9a-f]{32}", k["salt"]) and re.fullmatch(r"[0-9a-f]{64}", k["hash"])
        assert set(k) == {"id", "kind", "salt", "hash", "exp"}
        if k["kind"] == "trial":
            dt.date.fromisoformat(k["exp"])


def test_web_keys_match_python_keys():
    """A versão web (ui/index.html e index.html) usa exactamente as mesmas chaves."""
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for f in ("ui/index.html", "index.html"):
        s = (root / f).read_text("utf-8")
        m = re.search(r"const S4U_KEYS = (\[.*?\]); // <<< CHAVES", s, re.S)
        assert m, f
        assert json.loads(m.group(1)) == L.KEYS, f
