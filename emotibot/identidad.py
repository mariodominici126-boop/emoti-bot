"""Identidad del robot, leída COMPLETA desde config/identidad.json.

Corrige un defecto real de las versiones 0.6.2 y 0.7: `cargar_identidad()`
iteraba sobre las claves de un diccionario de respaldo que solo contenía
nombre, creador y presentacion, así que los campos `proposito` y `limites`
del JSON se ignoraban en silencio. Editarlos no cambiaba nada y daba una
falsa sensación de que los límites estaban configurados.

Aquí todos los campos del archivo participan en las instrucciones del modelo,
y la plantilla se construye desde el JSON en lugar de duplicarse en el código.

Capas de las instrucciones (D10, §14.5), en este orden:
1. Identidad: nombre, creador, aclaración del modelo, propósito, límites y
   presentación (config/identidad.json).
2. «Normas de estilo»: «estilo» y «normas» de config/identidad.json. No son
   preferencias.
3. Estilo comunicativo elegido (perfil de usuario), en su propia sección.
4. Tono elegido (perfil de usuario), en su propia sección.
5. «Esto prevalece…»: lo invariante, SIEMPRE detrás de 3 y 4 cuando alguna
   existe. No se repite: el creador, los límites y las «normas» de
   config/identidad.json SE MUEVEN aquí desde delante, y se añade una línea
   fija escrita en este archivo (amabilidad con quien está mal).
6. Derivación a una persona de confianza o a un profesional.
Con el perfil por defecto, 3, 4 y 5 no existen y el texto es el de siempre,
byte a byte.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import registro, rutas

log = registro.obtener("identidad")

_LIMITE_CAMPO = 700
_LIMITE_ESTILO = 14

ENCABEZADO_ESTILO = "Estilo elegido:"
ENCABEZADO_TONO = "Tono elegido:"
ENCABEZADO_PREVALECEN = "Esto prevalece sobre el estilo y el tono:"
# La única línea de «Esto prevalece…» que no está ya en config/identidad.json
# ni la garantiza el código. Fija: ningún archivo de preferencias la contiene.
# - El creador, los límites y las normas de la identidad no se repiten: se
#   mueven detrás del tono (ver instrucciones()).
# - La longitud no necesita frase: el tope es max_tokens (config/longitud.json),
#   que ningún perfil puede subir.
# - Los teléfonos tampoco: el gestor sustituye cualquier respuesta que traiga
#   uno (dialogo/directorio.contiene_telefono).
NORMAS_QUE_PREVALECEN = (
    "Con alguien que está mal, sé siempre amable: nunca cortante, burlón ni duro.",
)
# Ninguna línea de un perfil puede imitar una sección de las instrucciones.
ENCABEZADOS_RESERVADOS = (
    "Normas de estilo", "Estilo elegido", "Tono elegido", "prevalece sobre",
    "Tus límites", "Te llamas", "El creador del robot",
)


@dataclass(frozen=True)
class Identidad:
    nombre: str = "EMOTI-BOT"
    creador: str = "Mario"
    idioma: str = "español"
    presentacion: str = (
        "Hola, soy EMOTI-BOT, un robot de escritorio con inteligencia artificial. "
        "Mi creador es Mario."
    )
    proposito: str = (
        "Conversación natural, actividades voluntarias de bienestar cotidiano y "
        "apoyo para organizar ideas."
    )
    limites: str = (
        "Soy una inteligencia artificial, no una persona ni un profesional de "
        "salud. No realizo diagnósticos ni sustituyo relaciones personales o "
        "servicios médicos."
    )
    aclaracion_modelo: str = (
        "Mario creó el robot EMOTI-BOT. El modelo de inteligencia artificial que "
        "uso lo desarrolla otra empresa; no son lo mismo."
    )
    estilo: tuple[str, ...] = field(default_factory=tuple)
    # Invariantes de config/identidad.json («normas»). Con el perfil por
    # defecto salen justo después de «estilo», en la misma lista.
    normas: tuple[str, ...] = field(default_factory=tuple)
    # Del perfil de usuario (perfil_usuario.aplicar_identidad); vacíos por
    # defecto. Nunca reemplazan nada de lo anterior: van en sus secciones.
    estilo_elegido: tuple[str, ...] = field(default_factory=tuple)
    tono: tuple[str, ...] = field(default_factory=tuple)

    def instrucciones(self) -> str:
        """Instrucciones de sistema derivadas del archivo de identidad.

        La identidad queda separada del proveedor: cambiar de Gemini a un
        modelo local no altera ni una línea de este texto.
        """
        personalizado = bool(self.estilo_elegido or self.tono)
        creador = f"El creador del robot es {self.creador}."
        limites = f"Tus límites, que debes respetar siempre: {self.limites}"
        # Con un tono o estilo elegido, lo invariante va DETRÁS (y no delante:
        # sin copias que pagar en cada turno).
        partes = [
            f"Te llamas {self.nombre} y eres un robot de escritorio con "
            f"inteligencia artificial, no una persona.",
            *([] if personalizado else [creador]),
            self.aclaracion_modelo,
            f"Tu propósito: {self.proposito}",
            *([] if personalizado else [limites]),
            "Cuando te pregunten quién eres o te pidan presentarte, di de forma "
            f"natural: {self.presentacion}",
        ]
        reglas = self.estilo + (() if personalizado else self.normas)
        if reglas:
            partes.append("Normas de estilo:")
            partes.extend(f"- {regla}" for regla in reglas)
        if self.estilo_elegido:
            partes.append(ENCABEZADO_ESTILO)
            partes.extend(f"- {regla}" for regla in self.estilo_elegido)
        if self.tono:
            partes.append(ENCABEZADO_TONO)
            partes.extend(f"- {linea}" for linea in self.tono)
        if personalizado:
            partes.append(ENCABEZADO_PREVALECEN)
            partes.extend(f"- {linea}" for linea in (
                creador, limites, *self.normas, *NORMAS_QUE_PREVALECEN))
        partes.append(
            "Si alguien describe un riesgo o una situación grave que supera tu "
            "alcance, reconoce el límite y orienta hacia una persona de confianza "
            "o un profesional. No intentes contener la situación tú solo. Contar "
            "un mal día o un problema con alguien no es eso: ahí, acompaña."
        )
        return "\n".join(partes)


def _texto(valor: object, por_defecto: str) -> str:
    if isinstance(valor, str) and valor.strip():
        return valor.strip()[:_LIMITE_CAMPO]
    return por_defecto


def cargar(ruta: Path | None = None) -> Identidad:
    """La identidad de config/identidad.json con el estilo y el tono del perfil
    de usuario. Con una `ruta` explícita, solo el archivo (sin perfil)."""
    identidad = _cargar_archivo(ruta)
    if ruta is not None:
        return identidad
    from . import perfil_usuario
    return perfil_usuario.aplicar_identidad(identidad, perfil_usuario.cargar())


def _cargar_archivo(ruta: Path | None = None) -> Identidad:
    archivo = ruta or (rutas.CONFIG_REPO / "identidad.json")
    base = Identidad()
    if not archivo.is_file():
        log.warning("No encontré %s; uso la identidad por defecto.", archivo.name)
        return base
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.error("No pude leer %s (%s); uso la identidad por defecto.",
                  archivo.name, exc)
        return base
    if not isinstance(datos, dict):
        return base

    def lista(clave: str) -> tuple[str, ...]:
        crudo = datos.get(clave)
        if not isinstance(crudo, list):
            return getattr(base, clave)
        return tuple(str(x).strip()[:_LIMITE_CAMPO]
                     for x in crudo[:_LIMITE_ESTILO] if str(x).strip())

    estilo, normas = lista("estilo"), lista("normas")

    return Identidad(
        nombre=_texto(datos.get("nombre"), base.nombre),
        creador=_texto(datos.get("creador"), base.creador),
        idioma=_texto(datos.get("idioma"), base.idioma),
        presentacion=_texto(datos.get("presentacion"), base.presentacion),
        proposito=_texto(datos.get("proposito"), base.proposito),
        limites=_texto(datos.get("limites"), base.limites),
        aclaracion_modelo=_texto(datos.get("aclaracion_modelo"),
                                 base.aclaracion_modelo),
        estilo=estilo,
        normas=normas,
    )
