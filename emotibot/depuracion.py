"""Modo de depuración de la transcripción (Fase 1, B2).

Para que el desarrollador compare lo que dijo con lo que entendió Whisper.
La transcripción no se registra en ningún sitio (decisión de privacidad), así
que hasta ahora nadie podía verla.

Reglas, todas comprobadas en `tests/test_medicion.py`:

- Desactivado al arrancar, siempre. No hay ajuste que lo deje encendido: se
  activa con una tecla (T) en cada sesión y se ve en pantalla que está activo.
- El texto vive solo en la memoria de este objeto y en la pantalla, y caduca
  a los pocos segundos. No se escribe en disco, no pasa por el registro y no
  sale del dispositivo.
- La ruta de seguridad queda fuera: si el turno fue de seguridad, no se
  muestra nada, ni siquiera que hubo texto.
- Desactivarlo borra al instante lo que hubiera en pantalla.
- No cambia nada del comportamiento del robot: solo muestra.
"""
from __future__ import annotations

import time

SEGUNDOS_VISIBLE = 10.0
MAX_CARACTERES = 160
AVISO_ACTIVO = "DEPURACIÓN STT ACTIVA · T para apagar"


class DepuracionStt:
    def __init__(self, segundos_visible: float = SEGUNDOS_VISIBLE) -> None:
        self.activa = False
        self.segundos_visible = segundos_visible
        self._texto = ""
        self._caduca = 0.0

    def alternar(self) -> bool:
        self.activa = not self.activa
        if not self.activa:
            self.borrar()
        return self.activa

    def borrar(self) -> None:
        self._texto = ""
        self._caduca = 0.0

    def mostrar(self, texto: str, es_seguridad: bool,
                ahora: float | None = None) -> bool:
        """Guarda el texto para mostrarlo. Devuelve si se mostrará."""
        if not self.activa or es_seguridad:
            # Un turno de seguridad borra también lo anterior: no debe quedar
            # en pantalla nada que se lea junto a esa respuesta.
            self.borrar()
            return False
        ahora = time.monotonic() if ahora is None else ahora
        limpio = " ".join((texto or "").split())
        self._texto = limpio[:MAX_CARACTERES] if limpio else "(vacía)"
        self._caduca = ahora + self.segundos_visible
        return True

    def linea(self, ahora: float | None = None) -> str:
        """Lo que hay que pintar ahora mismo, o "" si nada."""
        if not self.activa:
            return ""
        ahora = time.monotonic() if ahora is None else ahora
        if self._texto and ahora >= self._caduca:
            self.borrar()
        if not self._texto:
            return AVISO_ACTIVO
        return f"{AVISO_ACTIVO} · Whisper oyó: «{self._texto}»"
