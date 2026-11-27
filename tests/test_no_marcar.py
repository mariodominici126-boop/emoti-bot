"""EMOTI-BOT nunca marca un número (docs/SEGURIDAD.md, «Nunca marcar»).

El robot no puede llamar y no finge haberlo hecho: muestra el número y dice
que hay que marcarlo. Esta prueba FALLA si aparece en la aplicación
cualquier forma de abrir un enlace o lanzar un proceso a partir de un
número:

- módulos para abrir enlaces o programas del sistema (webbrowser,
  os.startfile, os.system, os.popen, ShellExecute de Windows);
- esquemas de llamada o mensajería en el código (tel:, callto:, sip:,
  whatsapp:, …);
- subprocesos fuera de los tres archivos de audio y voz que ya los usaban
  (arecord/aplay y espeak), o con shell=True en cualquier sitio;
- que esos tres archivos lleguen a tocar los números (importar el
  directorio, la ruta de crisis o leer crisis.json);
- que los módulos que leen los números importen os, subprocess, ctypes,
  socket o webbrowser, o que la barra lateral haga clicables sus textos.
"""
import ast
import re
import unittest

from emotibot import rutas

PAQUETE = rutas.RAIZ / "emotibot"
CON_SUBPROCESOS = {"audio/dispositivos.py", "audio/motores.py", "voz/espeak.py"}
CON_NUMEROS = {"dialogo/directorio.py", "dialogo/seguridad.py", "dialogo/horario.py",
               "panel_directorio.py", "dialogo/gestor.py"}
PROHIBIDOS_SIEMPRE = {"webbrowser"}
LLAMADAS_PROHIBIDAS = {("os", "startfile"), ("os", "system"), ("os", "popen"),
                       ("os", "execv"), ("os", "execvp"), ("os", "spawnv")}
ESQUEMAS = re.compile(r"\b(?:tel|callto|sip|sips|whatsapp|facetime|skype|sms)\s*:",
                      re.IGNORECASE)


def _modulos():
    for ruta in sorted(PAQUETE.rglob("*.py")):
        relativo = ruta.relative_to(PAQUETE).as_posix()
        fuente = ruta.read_text(encoding="utf-8")
        yield relativo, fuente, ast.parse(fuente)


def _importados(arbol) -> set[str]:
    nombres = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level == 0 and nodo.module:
                nombres.add(nodo.module.split(".")[0])
            # Importaciones relativas: se guardan los nombres traídos.
            nombres |= {a.name for a in nodo.names}
            if nodo.module:
                nombres |= set(nodo.module.split("."))
    return nombres


class NuncaMarcarTest(unittest.TestCase):
    def test_nada_abre_enlaces_ni_programas_del_sistema(self):
        for relativo, fuente, arbol in _modulos():
            with self.subTest(modulo=relativo):
                self.assertFalse(_importados(arbol) & PROHIBIDOS_SIEMPRE)
                self.assertNotIn("ShellExecute", fuente)
                for nodo in ast.walk(arbol):
                    if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name):
                        self.assertNotIn((nodo.value.id, nodo.attr), LLAMADAS_PROHIBIDAS)

    def test_ningun_esquema_de_llamada(self):
        for relativo, fuente, _ in _modulos():
            with self.subTest(modulo=relativo):
                self.assertIsNone(ESQUEMAS.search(fuente))

    def test_subprocesos_solo_en_audio_y_voz_y_sin_shell(self):
        for relativo, _, arbol in _modulos():
            usa = "subprocess" in _importados(arbol)
            with self.subTest(modulo=relativo):
                if usa:
                    self.assertIn(relativo, CON_SUBPROCESOS,
                                  "subproceso nuevo: revisa la regla de no marcar")
                for nodo in ast.walk(arbol):
                    if isinstance(nodo, ast.keyword) and nodo.arg == "shell":
                        self.assertFalse(isinstance(nodo.value, ast.Constant)
                                         and nodo.value.value is True)

    def test_los_que_lanzan_procesos_no_tocan_los_numeros(self):
        for relativo, fuente, arbol in _modulos():
            if relativo not in CON_SUBPROCESOS:
                continue
            with self.subTest(modulo=relativo):
                self.assertFalse(_importados(arbol) & {"directorio", "seguridad",
                                                       "panel_directorio", "dialogo"})
                self.assertNotIn("crisis.json", fuente)

    def test_los_que_leen_los_numeros_no_pueden_lanzar_nada(self):
        prohibidos = {"os", "subprocess", "ctypes", "socket", "webbrowser", "urllib",
                      "http", "requests"}
        for relativo, fuente, arbol in _modulos():
            if relativo not in CON_NUMEROS:
                continue
            with self.subTest(modulo=relativo):
                self.assertFalse(_importados(arbol) & prohibidos)

    def test_la_barra_no_hace_clicables_los_numeros(self):
        fuente = (PAQUETE / "panel_directorio.py").read_text(encoding="utf-8")
        self.assertNotIn("tag_bind", fuente)
        self.assertNotIn(".bind(", fuente)

    def test_lo_dice_en_voz_alta(self):
        from emotibot.dialogo import directorio
        self.assertIn("no puedo llamar", directorio.NO_PUEDO_LLAMAR)
        self.assertIn("no puedo llamar", directorio.REMISION)


if __name__ == "__main__":
    unittest.main()
