"""Asistente de perfil (D10, tanda 3): el primer arranque y «cambiar perfil».

Dos caminos desde la primera pantalla:
- ESTÁNDAR: UNA tecla (ENTER) y empieza; escribe el perfil por defecto.
- PERSONALIZABLE (P): rostro → voz → personalidad → estilo.

Este módulo es solo el MODELO: qué paso hay, qué opción está delante, qué
se ha elegido y qué perfil sale. No sabe nada de Tk ni del teclado. La
entrada llega como `Accion`; el teclado es una traducción más (`TECLAS`), y
una pantalla táctil o la voz serían otras dos que produzcan las mismas
acciones, sin tocar el modelo (no implementadas todavía).

Reglas:
- Se puede volver atrás (ATRAS) y salir (SALIR) en cualquier momento. Al
  salir a medias se queda lo ELEGIDO (lo confirmado con ACEPTAR en cada
  paso) y el resto se queda como estaba: en el primer arranque, el perfil
  por defecto. Mirar una opción sin confirmarla no la elige.
- El asistente solo produce un `PerfilUsuario`: los cinco ejes. Lo guarda
  `perfil_usuario.guardar()`, que valida con las mismas reglas que al
  cargar. No hay forma de que escriba otra cosa.
- El modelo de conversación no se elige aquí: se conserva el que hubiera
  (ESTÁNDAR lo deja en el de por defecto, como todo lo demás).
"""
from __future__ import annotations

import dataclasses
import enum
import json
from dataclasses import dataclass

from . import perfil_usuario as pu

PASOS = ("rostro", "voz", "personalidad", "estilo")
INICIO = "inicio"
HECHO = "hecho"


class Accion(enum.Enum):
    SIGUIENTE = "siguiente"        # la opción de al lado
    ANTERIOR = "anterior"
    ACEPTAR = "aceptar"            # en el inicio: estándar; en un paso: elegir
    PERSONALIZAR = "personalizar"  # solo en el inicio
    ATRAS = "atras"
    SALIR = "salir"                # guarda lo elegido y cierra


# El teclado, por ahora. keysym de Tk (en minúsculas) → acción.
TECLAS: dict[str, Accion] = {
    "return": Accion.ACEPTAR, "kp_enter": Accion.ACEPTAR,
    "right": Accion.SIGUIENTE, "down": Accion.SIGUIENTE,
    "left": Accion.ANTERIOR, "up": Accion.ANTERIOR,
    "backspace": Accion.ATRAS,
    "escape": Accion.SALIR,
    "p": Accion.PERSONALIZAR,
}


def accion_de_tecla(keysym: str) -> Accion | None:
    return TECLAS.get((keysym or "").lower())


# Nombres para la pantalla: el del archivo, con sus tildes.
_TILDES = {"estandar": "Estándar", "analitica": "Analítica", "energetica": "Energética"}


def titulo(nombre: str) -> str:
    return _TILDES.get(nombre, nombre.replace("_", " ").capitalize())


def descripcion(eje: str, nombre: str) -> str:
    """La línea de descripción de una personalidad o un estilo."""
    archivo = pu.DIRECTORIOS[eje] / f"{nombre}.json"
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        texto = datos.get("descripcion", "") if isinstance(datos, dict) else ""
    except (OSError, ValueError):
        texto = ""
    return str(texto).splitlines()[0][:90] if texto else ""


@dataclass(frozen=True)
class Efecto:
    """Lo que la interfaz tiene que hacer tras una acción."""
    rostro: str = ""          # rostro que hay que enseñar ahora
    oir: str = ""             # voz que tiene que decir su frase de muestra
    terminado: bool = False


class Asistente:
    def __init__(self, base: pu.PerfilUsuario = pu.POR_DEFECTO,
                 opciones=pu.opciones, primer_arranque: bool = False) -> None:
        self.base = base
        self.primer_arranque = primer_arranque
        self.paso = INICIO
        self.opciones = {eje: list(opciones(eje)) for eje in PASOS}
        self.indice = {eje: self._indice_de(eje, getattr(base, eje)) for eje in PASOS}
        self.elegido: dict[str, str] = {}
        self.resultado: pu.PerfilUsuario | None = None

    def _indice_de(self, eje: str, valor: str) -> int:
        lista = self.opciones[eje]
        return lista.index(valor) if valor in lista else 0

    # ------------------------------------------------------------- consulta
    @property
    def terminado(self) -> bool:
        return self.paso == HECHO

    @property
    def numero_paso(self) -> int:
        return PASOS.index(self.paso) + 1 if self.paso in PASOS else 0

    def actual(self, eje: str | None = None) -> str:
        """La opción que está delante en un paso."""
        eje = eje or self.paso
        return self.opciones[eje][self.indice[eje]]

    def perfil(self) -> pu.PerfilUsuario:
        """La base con lo elegido encima: lo que se guardaría ahora."""
        return dataclasses.replace(self.base, **self.elegido)

    def rostro_visible(self) -> str:
        """En el paso del rostro, el que está delante; fuera, el elegido."""
        if self.paso == "rostro":
            return self.actual("rostro")
        return self.elegido.get("rostro", self.base.rostro)

    # --------------------------------------------------------------- acción
    def actuar(self, accion: Accion) -> Efecto:
        if self.terminado:
            return Efecto(terminado=True)
        if accion is Accion.SALIR:
            return self._terminar(self.perfil())
        if self.paso == INICIO:
            if accion is Accion.ACEPTAR:
                return self._terminar(pu.POR_DEFECTO)
            if accion is Accion.PERSONALIZAR:
                return self._ir(PASOS[0])
            return Efecto(rostro=self.rostro_visible())
        eje = self.paso
        n = len(self.opciones[eje])
        if accion in (Accion.SIGUIENTE, Accion.ANTERIOR) and n:
            paso = 1 if accion is Accion.SIGUIENTE else -1
            self.indice[eje] = (self.indice[eje] + paso) % n
            return self._efecto_de_paso()
        if accion is Accion.ACEPTAR:
            self.elegido[eje] = self.actual()
            siguiente = PASOS.index(eje) + 1
            if siguiente == len(PASOS):
                return self._terminar(self.perfil())
            return self._ir(PASOS[siguiente])
        if accion is Accion.ATRAS:
            anterior = PASOS.index(eje) - 1
            return self._ir(PASOS[anterior] if anterior >= 0 else INICIO)
        return Efecto(rostro=self.rostro_visible())

    def _ir(self, paso: str) -> Efecto:
        self.paso = paso
        return self._efecto_de_paso()

    def _efecto_de_paso(self) -> Efecto:
        # La voz se oye al llegar a su paso y cada vez que cambia la opción.
        return Efecto(rostro=self.rostro_visible(),
                      oir=self.actual() if self.paso == "voz" else "")

    def _terminar(self, perfil: pu.PerfilUsuario) -> Efecto:
        self.resultado = perfil
        self.paso = HECHO
        return Efecto(rostro=perfil.rostro, terminado=True)
