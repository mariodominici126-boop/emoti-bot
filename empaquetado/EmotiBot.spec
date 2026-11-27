# -*- mode: python ; coding: utf-8 -*-
# PyInstaller --onedir de EMOTI-BOT para Windows. Ver empaquetado/LEEME.md.
#   .venv\Scripts\python.exe -m PyInstaller --noconfirm empaquetado\EmotiBot.spec
# Dentro: config/, la voz «claude» (Apache-2.0) y Whisper «small».
# Fuera: la voz «daniela» (CC BY-SA 4.0) y Whisper «base» (se bajan a
# petición), PyAV (sustituto vacío) y los datos de hebreo y árabe de Piper.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

RAIZ = Path(SPECPATH).parent
EMPAQUETADO = RAIZ / "empaquetado"

# Whisper «small» de la caché de Hugging Face (tiene que estar bajado).
from faster_whisper.utils import download_model
SMALL = Path(download_model("small", local_files_only=True))

# Voz «claude»: donde la busca la app desde el código (~/emoti-voices).
VOCES = Path(os.environ.get("EMOTI_VOCES", Path.home() / "emoti-voices"))
VOZ = "es_MX-claude-high.onnx"

datas = [
    (str(RAIZ / "config"), "config"),
    (str(VOCES / VOZ), "voces"),
    (str(VOCES / (VOZ + ".json")), "voces"),
    (str(EMPAQUETADO / "LICENCIA_VOZ_CLAUDE.txt"), "voces"),
]
datas += [(str(SMALL / f), "modelos/whisper-small")
          for f in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")]
binaries, hiddenimports = [], []
for paquete in ("faster_whisper", "ctranslate2", "piper", "onnxruntime"):
    d, b, h = collect_all(paquete)
    datas += d
    binaries += b
    hiddenimports += h

# Hebreo (nakdimon.onnx, 21 MB) y árabe (tashkeel, 4,6 MB): Piper solo los
# carga con voces de esas lenguas. El código se queda; los modelos, fuera.
FUERA = ("nakdimon.onnx", os.path.join("tashkeel", "model.onnx"))
datas = [(src, dst) for src, dst in datas if not src.endswith(FUERA)]

a = Analysis(
    [str(EMPAQUETADO / "lanzador.py")],
    pathex=[str(RAIZ), str(EMPAQUETADO / "sustitutos")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "tests", "torch", "onnx", "av.audio", "av.container",
              "av.video", "av.codec", "av.filter"],
    noarchive=False,
)
# PyAV real fuera, con sus DLL de FFmpeg (av.libs): entra el sustituto.
a.binaries = [b for b in a.binaries if "av.libs" not in b[0] and not b[0].startswith("av" + os.sep)]
a.datas = [d for d in a.datas if not d[0].startswith("av.libs")]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="EmotiBot",
          console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="EmotiBot")
