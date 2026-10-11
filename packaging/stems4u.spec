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
             excludes=["tkinter", "matplotlib", "IPython", "pytest", "torch.utils.tensorboard", "caffe2"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="STEMS4U", console=False,
          icon=None, target_arch=None, codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, name="STEMS4U", strip=False, upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name="STEMS4U.app", bundle_identifier="com.piradex.stems4u",
                 info_plist={"CFBundleShortVersionString": "0.1.0", "LSMinimumSystemVersion": "10.15",
                             "NSHighResolutionCapable": True, "CFBundleDisplayName": "STEMS4U"})
