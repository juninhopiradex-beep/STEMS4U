# PyInstaller — gera STEMS4U.app (macOS) ou STEMS4U\STEMS4U.exe (Windows).
# Os modelos NÃO vão no instalador: instalam-se no Gestor de Modelos (Application Support / LOCALAPPDATA).
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
hidden = collect_submodules("demucs") + collect_submodules("webview") + ["openunmix.filtering"]
a = Analysis([str(ROOT / "packaging" / "launch.py")], pathex=[str(ROOT)],
             datas=[(str(ROOT / "ui" / "index.html"), "ui"),
                    (str(ROOT / "stems4u" / "models" / "manifest.json"), "stems4u/models"),
                    (str(ROOT / "THIRD_PARTY_NOTICES.md"), ".")],
             hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "IPython", "pytest", "torch.utils.tensorboard", "caffe2",
                       "pkg_resources", "setuptools"],  # não usados; o hook do pkg_resources falha com setuptools recente
             noarchive=False)
# As bibliotecas de áudio que o torchaudio traz (sox, ffmpeg, flac…) exigem macOS 12 e não são usadas:
# o STEMS4U lê e grava áudio com libsndfile. O torchaudio só é importado pelo filtro de Wiener do Demucs.
def _keep(entry):
    dest = entry[0].replace("\\", "/")
    return not ("torchaudio/.dylibs/" in dest or "torchaudio/__dot__dylibs/" in dest
                or "torchaudio/lib/libtorchaudio_sox" in dest or "torchaudio/lib/_torchaudio_sox" in dest
                or "torchaudio/lib/libtorio_ffmpeg" in dest or "torchaudio/lib/_torchaudio_ffmpeg" in dest)
a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="STEMS4U", console=False,
          icon=None, target_arch=None, codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, name="STEMS4U", strip=False, upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name="STEMS4U.app", bundle_identifier="com.piradex.stems4u",
                 info_plist={"CFBundleShortVersionString": "0.1.0", "LSMinimumSystemVersion": "10.15",
                             "NSHighResolutionCapable": True, "CFBundleDisplayName": "STEMS4U"})
