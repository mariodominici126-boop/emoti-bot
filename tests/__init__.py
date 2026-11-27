"""Pruebas de EMOTI-BOT. Ejecuta: python -m unittest discover -s tests -t ."""
import atexit
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# Las pruebas no leen ni escriben la configuración de ESTA máquina: con un
# perfil propio elegido en el asistente (tanda 3), las pruebas del perfil por
# defecto verían el de la persona. Carpetas vacías, antes de importar nada.
_AISLADO = Path(tempfile.mkdtemp(prefix="emotibot-pruebas-"))
os.environ["EMOTI_CONFIG_DIR"] = str(_AISLADO / "config")
os.environ["EMOTI_STATE_DIR"] = str(_AISLADO / "estado")
atexit.register(shutil.rmtree, _AISLADO, True)

# Las pruebas no escriben en logs/emotibot.log: ese archivo es el registro de
# uso real y mezclarlo con el ruido de las pruebas —rutas de seguridad
# simuladas, rechazos de cuota inventados, identidades inválidas a propósito—
# hace imposible diagnosticar nada en él.
from emotibot import registro  # noqa: E402

registro.configurar(a_archivo=False)
logging.getLogger("emotibot").setLevel(logging.CRITICAL)
