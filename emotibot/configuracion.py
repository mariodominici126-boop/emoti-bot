"""Pestaña de configuración: QUÉ se puede cambiar y cómo se navega.

Lo que NO es configurable no se impide con una comprobación al guardar: no
existe en el catálogo. `guardar()` solo escribe un campo de `PERMITIDOS` con
uno de los valores de su lista, en el `ajustes.json` de la máquina; el
modelo de conversación va al perfil por `perfil_usuario.guardar()`, que
valida igual que al cargar. Fuera del catálogo, por construcción: la ruta
de seguridad, el directorio de crisis (números y horarios),
`verificado_por_responsable`, la autoría, los topes de longitud, consumo y
plazo (ninguna opción los sube), el prompt de seguridad, el indicador del
micrófono y las claves completas. La memoria persistente no existe (D4) y
no aparece.

El perfil (rostro, voz, personalidad, estilo) lo decide el asistente de D10:
aquí solo hay un botón que lo abre.

Este módulo no sabe de Tk: `Menu` recibe acciones (teclado o toque) y
devuelve un `Efecto` que aplica la aplicación.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from typing import Any

from . import ajustes as mod_ajustes
from . import perfil_usuario as pu

SI_NO = ((True, "Sí"), (False, "No"))

# Los ÚNICOS campos de ajustes.json que escribe esta pestaña.
PERMITIDOS: frozenset[tuple[str, str]] = frozenset({
    ("dialogo", "saludo_inicial"),
    ("rostro", "pantalla_completa"),
    ("rostro", "mostrar_boton_menu"),
    ("rostro", "mostrar_controles"),
    ("audio", "volumen"),
    ("voz", "ajuste_velocidad"),
    ("audio", "dispositivo_captura"),
    ("audio", "factor_umbral"),
    ("audio", "silencio_final_s"),
    ("dialogo", "activacion_por_voz"),
    ("dialogo", "conversacion_continua"),
    ("dialogo", "turnos_seguidos_max"),
    ("dialogo", "max_turnos_memoria"),
    ("ia", "longitud_respuesta"),
    ("rostro", "carcasa"),
    ("rostro", "tamano_rostro"),
    ("rostro", "animaciones"),
    ("rostro", "parpadeo"),
    ("dialogo", "actividades"),
    ("dialogo", "respiracion_ritmo"),
})

FRASES_ACTIVACION = "«Hola Emoti», «Buenos días, Emoti», «Buenas tardes, Emoti»"

QUE_SE_GUARDA = (
    "Se guarda en este equipo: tus ajustes y tu perfil, las claves de los",
    "proveedores solo si eliges guardarlas, los contadores de consumo y los",
    "tiempos de cada turno. Todo son números o nombres: nada de lo hablado.",
    "",
    "No se guarda: lo que dices ni lo que contesto. La conversación vive en",
    "memoria durante la sesión (los turnos elegidos) y se borra al salir o",
    "con «Borrar la conversación». No hay memoria entre sesiones.",
    "",
    "El audio no se guarda. Con la activación por voz, lo que se oye se",
    "transcribe en el equipo y se descarta.",
    "",
    "Sale del equipo: el texto de tu pregunta (no el audio) hacia el modelo,",
    "para contestarte. {remoto}",
)


@dataclass(frozen=True)
class Ajuste:
    clave: str
    etiqueta: str
    opciones: tuple[tuple[Any, str], ...]
    seccion: str = ""             # de ajustes.json; vacío = va al perfil
    campo: str = ""
    reinicio: bool = False        # se aplica al reiniciar, y se dice


@dataclass(frozen=True)
class Accion:
    clave: str
    etiqueta: str
    texto_boton: str = "Abrir"


@dataclass(frozen=True)
class Info:
    """Solo lectura. Con `ver`, abre una página de texto."""
    clave: str
    etiqueta: str
    ver: bool = False


def secciones(microfonos: tuple[tuple[str, str], ...],
              modelos: tuple[str, ...]) -> list[tuple[str, list]]:
    """El catálogo. Las listas que dependen del equipo (micrófonos y modelos
    configurados) llegan de fuera."""
    return [
        ("General", [
            Info("idioma", "Idioma"),
            # El país decide qué números de ayuda se ofrecen: cambiarlo aquí
            # podría quitarlos de la ruta de seguridad. Solo se muestra.
            Info("pais", "País"),
            Ajuste("saludo_inicial", "Saludo al arrancar", SI_NO,
                   "dialogo", "saludo_inicial"),
            Ajuste("pantalla_completa", "Pantalla completa", SI_NO,
                   "rostro", "pantalla_completa"),
            Ajuste("boton_menu", "Botón ☰", ((True, "Visible"), (False, "Oculto")),
                   "rostro", "mostrar_boton_menu"),
            Ajuste("fila_teclas", "Fila de teclas", ((True, "Visible"), (False, "Oculta")),
                   "rostro", "mostrar_controles"),
            Accion("depuracion", "Ver la transcripción (T)", "Cambiar"),
        ]),
        ("Voz y audio", [
            Ajuste("volumen", "Volumen", ((0.25, "25 %"), (0.5, "50 %"), (0.75, "75 %"),
                                          (1.0, "100 %")), "audio", "volumen"),
            Ajuste("ritmo", "Velocidad de habla", ((1.15, "Lenta"), (1.0, "Normal"),
                                                   (0.87, "Rápida")),
                   "voz", "ajuste_velocidad"),
            Ajuste("microfono", "Micrófono", ((None, "Predeterminado"),)
                   + tuple(microfonos), "audio", "dispositivo_captura"),
            Ajuste("sensibilidad", "Sensibilidad", ((1.8, "Alta"), (2.2, "Normal"),
                                                    (2.8, "Baja")),
                   "audio", "factor_umbral"),
            Ajuste("silencio", "Silencio antes de responder",
                   ((0.7, "0,7 s"), (1.0, "1,0 s"), (1.4, "1,4 s")),
                   "audio", "silencio_final_s"),
            Accion("prueba_audio", "Prueba de audio", "Empezar"),
        ]),
        ("Conversación", [
            Ajuste("activacion", "Activación por voz", SI_NO,
                   "dialogo", "activacion_por_voz"),
            Info("frases", "Frases"),
            Ajuste("continua", "Conversación seguida", SI_NO,
                   "dialogo", "conversacion_continua"),
            Ajuste("turnos_seguidos", "Turnos seguidos, como mucho",
                   ((3, "3"), (6, "6"), (10, "10")), "dialogo", "turnos_seguidos_max"),
            Ajuste("memoria", "Turnos de memoria", ((0, "0"), (4, "4"), (8, "8"), (12, "12")),
                   "dialogo", "max_turnos_memoria"),
            Ajuste("longitud", "Longitud de respuesta", (("normal", "Normal"),
                                                        ("breve", "Breve")),
                   "ia", "longitud_respuesta"),
            Accion("borrar", "Reiniciar la conversación", "Borrar"),
        ]),
        ("Personalización", [
            Accion("asistente", "Rostro, voz, personalidad y estilo"),
            Ajuste("carcasa", "Carcasa", SI_NO, "rostro", "carcasa"),
            Ajuste("tamano", "Tamaño del rostro", ((1.0, "Grande"), (0.9, "Mediano"),
                                                   (0.8, "Pequeño")),
                   "rostro", "tamano_rostro"),
            Ajuste("animaciones", "Animaciones", SI_NO, "rostro", "animaciones"),
            Ajuste("parpadeo", "Parpadeo", SI_NO, "rostro", "parpadeo"),
        ]),
        ("Inteligencia", [
            Ajuste("modelo", "Modelo", tuple((m, m) for m in modelos), reinicio=True),
            Info("estado_ia", "Estado"),
            Info("cuota", "Cuota de hoy", ver=True),
        ]),
        ("Bienestar", [
            Ajuste("actividades", "Respiración y ordenar ideas", SI_NO,
                   "dialogo", "actividades"),
            Ajuste("respiracion_ritmo", "Ritmo de respiración",
                   (("4-4-6", "4-4-6"), ("3-3-5", "3-3-5 (corto)"), ("5-5-7", "5-5-7 (lento)")),
                   "dialogo", "respiracion_ritmo"),
        ]),
        ("Privacidad y sistema", [
            Accion("borrar", "Borrar la conversación", "Borrar"),
            Info("que_se_guarda", "Qué se guarda y qué no", ver=True),
            Info("version", "Versión"),
            Info("conexion", "Conexión"),
            Info("diagnostico", "Diagnóstico", ver=True),
        ]),
    ]


class ErrorConfiguracion(ValueError):
    pass


def guardar(ajuste: Ajuste, valor: Any, valores_actuales: dict[str, Any]) -> dict[str, Any]:
    """Escribe UN ajuste del catálogo. Devuelve los ajustes que cambian (a
    veces dos: ver el botón ☰). Lo que no está en `PERMITIDOS` o no es una
    de sus opciones no se escribe."""
    if not isinstance(ajuste, Ajuste):
        raise ErrorConfiguracion("Solo se guardan ajustes del catálogo.")
    if valor not in [v for v, _ in ajuste.opciones]:
        raise ErrorConfiguracion(f"{ajuste.etiqueta}: {valor!r} no es una opción.")
    if not ajuste.seccion:                           # el modelo: va al perfil
        if ajuste.clave != "modelo":
            raise ErrorConfiguracion(f"{ajuste.clave}: sin destino.")
        pu.guardar(replace(pu.cargar(), modelo=valor))
        return {ajuste.clave: valor}
    if (ajuste.seccion, ajuste.campo) not in PERMITIDOS:
        raise ErrorConfiguracion(f"{ajuste.seccion}.{ajuste.campo} no es configurable.")
    cambios = {ajuste.clave: valor}
    escribir = {ajuste.seccion: {ajuste.campo: valor}}
    # Nunca inaccesible: el botón ☰ solo se oculta si queda la voz, y si se
    # apaga la voz con el botón oculto, el botón vuelve.
    if ajuste.clave == "boton_menu" and valor is False and not valores_actuales.get("activacion"):
        raise ErrorConfiguracion("Para ocultar el botón ☰, activa antes la activación "
                                 "por voz: si no, no habría cómo volver aquí.")
    if ajuste.clave == "activacion" and valor is False and not valores_actuales.get(
            "boton_menu", True):
        escribir["rostro"] = {"mostrar_boton_menu": True}
        cambios["boton_menu"] = True
    mod_ajustes._guardar_usuario(escribir)
    return cambios


def valores_de(config, perfil) -> dict[str, Any]:
    """Valor actual de cada ajuste del catálogo, leído de los ajustes y del
    perfil cargados."""
    valores: dict[str, Any] = {"modelo": perfil.modelo}
    for _, filas in secciones((), ()):
        for fila in filas:
            if isinstance(fila, Ajuste) and fila.seccion:
                valores[fila.clave] = getattr(getattr(config, fila.seccion), fila.campo)
    return valores


# ------------------------------------------------------------- navegación
class Accion_(enum.Enum):
    ARRIBA = "arriba"
    ABAJO = "abajo"
    MENOS = "menos"           # opción anterior
    MAS = "mas"               # opción siguiente
    ACEPTAR = "aceptar"
    ATRAS = "atras"
    SALIR = "salir"


TECLAS = {
    "up": Accion_.ARRIBA, "down": Accion_.ABAJO, "left": Accion_.MENOS,
    "right": Accion_.MAS, "return": Accion_.ACEPTAR, "kp_enter": Accion_.ACEPTAR,
    "backspace": Accion_.ATRAS, "escape": Accion_.SALIR,
}

INICIO, SECCION, TEXTO = "inicio", "seccion", "texto"


@dataclass
class Efecto:
    cambio: tuple[Ajuste, Any] | None = None   # guardar este valor
    accion: str = ""                           # ejecutar esta acción
    ver: str = ""                              # abrir el texto de esta info
    cerrar: bool = False


@dataclass
class Menu:
    catalogo: list[tuple[str, list]]
    valores: dict[str, Any]
    pagina: str = INICIO
    seccion: int = 0
    fila: int = 0
    texto: tuple[str, tuple[str, ...]] = ("", ())
    nota: str = ""
    _pila: list = field(default_factory=list)

    @property
    def filas(self) -> list:
        return self.catalogo[self.seccion][1] if self.pagina == SECCION else []

    def valor_texto(self, ajuste: Ajuste) -> str:
        actual = self.valores.get(ajuste.clave)
        for valor, texto in ajuste.opciones:
            if valor == actual:
                return texto
        return str(actual)

    def _otra_opcion(self, ajuste: Ajuste, paso: int):
        valores = [v for v, _ in ajuste.opciones]
        if not valores:
            return None
        actual = self.valores.get(ajuste.clave)
        i = valores.index(actual) if actual in valores else 0
        return valores[(i + paso) % len(valores)]

    def mostrar_texto(self, titulo: str, lineas) -> None:
        self._pila.append((self.pagina, self.seccion, self.fila))
        self.pagina, self.texto = TEXTO, (titulo, tuple(lineas))

    def actuar(self, accion: Accion_) -> Efecto:
        self.nota = ""
        if accion is Accion_.SALIR:
            return Efecto(cerrar=True)
        if accion is Accion_.ATRAS:
            if self.pagina == TEXTO:
                self.pagina, self.seccion, self.fila = self._pila.pop() if self._pila \
                    else (INICIO, 0, 0)
            elif self.pagina == SECCION:
                self.pagina, self.fila = INICIO, self.seccion
            else:
                return Efecto(cerrar=True)
            return Efecto()
        if self.pagina == INICIO:
            n = len(self.catalogo)
            if accion in (Accion_.ABAJO, Accion_.MAS):
                self.fila = (self.fila + 1) % n
            elif accion in (Accion_.ARRIBA, Accion_.MENOS):
                self.fila = (self.fila - 1) % n
            elif accion is Accion_.ACEPTAR:
                self.pagina, self.seccion, self.fila = SECCION, self.fila, 0
            return Efecto()
        if self.pagina == TEXTO:
            return Efecto()
        filas = self.filas
        if accion is Accion_.ABAJO:
            self.fila = (self.fila + 1) % len(filas)
            return Efecto()
        if accion is Accion_.ARRIBA:
            self.fila = (self.fila - 1) % len(filas)
            return Efecto()
        fila = filas[self.fila]
        if isinstance(fila, Ajuste) and accion in (Accion_.MAS, Accion_.MENOS, Accion_.ACEPTAR):
            valor = self._otra_opcion(fila, -1 if accion is Accion_.MENOS else 1)
            return Efecto(cambio=(fila, valor))
        if isinstance(fila, Accion) and accion is Accion_.ACEPTAR:
            return Efecto(accion=fila.clave)
        if isinstance(fila, Info) and fila.ver and accion is Accion_.ACEPTAR:
            return Efecto(ver=fila.clave)
        return Efecto()

    def tocar(self, objetivo: tuple) -> Efecto:
        """Un toque (o clic) sobre lo que la vista dibujó."""
        tipo = objetivo[0]
        if tipo == "cerrar":
            return self.actuar(Accion_.SALIR)
        if tipo == "volver":
            return self.actuar(Accion_.ATRAS)
        if tipo == "seccion":
            self.pagina, self.seccion, self.fila = SECCION, objetivo[1], 0
            return Efecto()
        if tipo in ("menos", "mas", "fila"):
            self.fila = objetivo[1]
            return self.actuar({"menos": Accion_.MENOS, "mas": Accion_.MAS,
                                "fila": Accion_.ACEPTAR}[tipo])
        return Efecto()
