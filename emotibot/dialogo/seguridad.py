"""Ruta de seguridad DETERMINISTA, sin IA y sin red.

POR QUÉ EXISTE ESTE MÓDULO
--------------------------
En las versiones 0.5, 0.6, 0.6.2 y 0.7 la gestión de una situación grave
estaba delegada al modelo mediante una línea del prompt de sistema:

    "Ante crisis graves, sugiere buscar apoyo humano o servicios de emergencia."

Eso solo funciona si el modelo responde. Con la cuota agotada —el estado real
del proyecto en noviembre de 2026— el camino que seguía el código era:

    429  →  mensaje_error()  →  "Gemini alcanzó su cuota. Revisa los límites."

Es decir: una persona que contara algo grave recibía un error de facturación.

Aquí la detección y la respuesta son código y texto fijo. No pasan por ningún
modelo, no dependen de la clave, de la cuota ni de Internet, y por eso son la
única parte del sistema con disponibilidad garantizada.

CRITERIOS DE DISEÑO
-------------------
- Solo patrones de intención explícita. La tristeza, el agobio o el enfado
  normales NO activan esta ruta: van a la conversación corriente, que es donde
  deben estar.
- Filtro de modismos ANTES de buscar: en español "me muero de risa" o "esto me
  mata" son expresiones corrientes. Se eliminan del texto y solo entonces se
  buscan los patrones de riesgo.
- La respuesta reconoce el límite, no intenta contener la situación y deriva a
  una persona de confianza y a los servicios de emergencia.
- No se formulan preguntas de evaluación de riesgo: no es papel de un robot de
  escritorio, y las guías de salud mental lo desaconsejan.
- No se nombran ni describen métodos, en ningún caso.
- El contenido de estos turnos NO se registra ni entra en la memoria de
  sesión, de modo que nunca viaja a un proveedor en el turno siguiente.
- Los números salen de config/crisis.json y de ningún otro sitio. La línea
  especializada solo se ofrece DENTRO DE SU HORARIO (hora del país de los
  números): fuera de él, la respuesta deriva a emergencias y a una persona
  de confianza. Si el país configurado no es el de los números, no se da
  ninguno.
- Esta ruta no comparte interfaz con el directorio de ayuda (directorio.py),
  que es una consulta y no una respuesta a una crisis.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .. import registro, rutas
from ..texto import normalizar
from . import horario as mod_horario

log = registro.obtener("dialogo.seguridad")

# Modismos que contienen palabras de riesgo sin ningún riesgo real.
# Se eliminan del texto antes de evaluar.
_MODISMOS = re.compile(
    r"\b(?:"
    r"me\s+muero\s+de\s+(?:risa|hambre|sueno|frio|calor|ganas|amor|aburrimiento|sed)"
    r"|muerto\s+de\s+(?:risa|hambre|sueno|frio|miedo|cansancio|aburrimiento)"
    r"|muriendo\s+de\s+(?:risa|hambre|sueno|frio|ganas)"
    r"|esto\s+me\s+mata"
    r"|me\s+mata\s+(?:la|el|los|las)\s+\w+"
    r"|me\s+matan\s+(?:la|el|los|las)\s+\w+"
    r"|matar\s+el\s+tiempo"
    r"|de\s+morirse"
    r"|para\s+morirse"
    r"|mato\s+de\s+risa"
    r"|muerto\s+de\s+la\s+risa"
    r")\b"
)

# Intención explícita. Cada patrón exige una formulación directa.
_RIESGO = (
    re.compile(r"\bme\s+quiero\s+mor(?:ir|irme)\b"),
    re.compile(r"\bquiero\s+mor(?:ir|irme)\b"),
    re.compile(r"\bganas\s+de\s+mor(?:ir|irme)\b"),
    re.compile(r"\bno\s+quiero\s+(?:seguir\s+)?viv(?:ir|iendo)\b"),
    re.compile(r"\bya\s+no\s+quiero\s+(?:seguir|viv(?:ir|iendo)|estar\s+aqui)\b"),
    re.compile(r"\bquitarme\s+la\s+vida\b"),
    re.compile(r"\bacabar\s+con\s+mi\s+vida\b"),
    re.compile(r"\bterminar\s+con\s+mi\s+vida\b"),
    re.compile(r"\bsuicid\w*\b"),
    re.compile(r"\b(?:me\s+voy\s+a\s+|quiero\s+)?matarme\b"),
    re.compile(r"\bme\s+quiero\s+matar\b"),
    re.compile(r"\bhacerme\s+dano\b"),
    re.compile(r"\blastimarme\b"),
    re.compile(r"\bautolesion\w*\b"),
    re.compile(r"\bcortarme\b"),
    re.compile(r"\bdesaparecer\s+para\s+siempre\b"),
    re.compile(r"\bmejor\s+(?:si\s+)?no\s+estar\s+(?:aqui|vivo|viva)\b"),
    re.compile(r"\bnadie\s+me\s+(?:va\s+a\s+)?extranar(?:ia)?\s+si\s+me\s+(?:voy|muero)\b"),
)

RESPUESTA_DE_RESERVA = (
    "Gracias por decírmelo. Lo que me cuentas es importante y es más grande de "
    "lo que yo puedo acompañar: soy un programa, no una persona ni un "
    "profesional. No quiero dejarte solo con esto. Busca ahora mismo a alguien "
    "de confianza que esté cerca de ti y cuéntaselo, aunque cueste. Si estás "
    "en peligro en este momento, llama a los servicios de emergencia de tu "
    "país o pide a alguien cercano que lo haga contigo."
)


@dataclass
class Recursos:
    """Recursos locales, leídos de config/crisis.json. Nunca inventados."""

    pais: str = ""
    telefono_emergencias: str = ""
    linea_especializada: str = ""
    nombre_linea_especializada: str = ""
    respuesta: str = ""
    cierre_con_emergencias: str = ""
    cierre_con_linea: str = ""
    cierre_sin_recursos: str = ""
    verificado: bool = False
    # Franja de la línea especializada y hora del país de los números.
    horario_linea: str = "24h"
    desfase_utc_horas: float | None = None
    # False si region.pais no es el país de config/crisis.json.
    pais_coincide: bool = True
    pais_configurado: str = ""

    def linea_abierta(self, hora: dt.time | None = None) -> bool:
        if hora is None:
            hora = mod_horario.hora_del_pais(self.desfase_utc_horas)
        try:
            return mod_horario.abierta(self.horario_linea, hora)
        except mod_horario.ErrorHorario:
            return False

    def mensaje(self, hora: dt.time | None = None) -> str:
        base = self.respuesta.strip()
        if not base:
            return RESPUESTA_DE_RESERVA
        partes = [base]
        # Fuera de su horario, la línea especializada NO se ofrece: a las 3:00
        # la respuesta principal es emergencias y una persona de confianza.
        if self.linea_especializada and self.nombre_linea_especializada \
                and self.cierre_con_linea and self.linea_abierta(hora):
            partes.append(
                self.cierre_con_linea.format(
                    nombre_linea=self.nombre_linea_especializada,
                    linea=self.linea_especializada,
                )
            )
        if self.telefono_emergencias and self.cierre_con_emergencias:
            partes.append(
                self.cierre_con_emergencias.format(
                    emergencias=self.telefono_emergencias
                )
            )
        elif self.cierre_sin_recursos:
            partes.append(self.cierre_sin_recursos)
        return " ".join(p.strip() for p in partes if p.strip())


def cargar_recursos(ruta: Path | None = None, pais: str | None = None) -> Recursos:
    """Recursos de config/crisis.json.

    Con `pais` (region.pais de config/ajustes.json), si no es el país de los
    números no se ofrece ninguno: fuera de su país no valen.
    """
    archivo = ruta or (rutas.CONFIG_REPO / "crisis.json")
    if not archivo.is_file():
        log.error(
            "No encontré %s. La ruta de seguridad usará el texto de reserva, "
            "sin recursos locales.", archivo.name,
        )
        return Recursos(respuesta=RESPUESTA_DE_RESERVA, verificado=False)
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.error("No pude leer %s (%s). Uso el texto de reserva.",
                  archivo.name, exc)
        return Recursos(respuesta=RESPUESTA_DE_RESERVA, verificado=False)
    if not isinstance(datos, dict):
        return Recursos(respuesta=RESPUESTA_DE_RESERVA, verificado=False)

    def campo(nombre: str, origen: dict = datos) -> str:
        valor = origen.get(nombre, "")
        return str(valor).strip() if isinstance(valor, (str, int)) else ""

    emergencias = campo("telefono_emergencias")
    especializada = campo("linea_especializada")
    nombre_especializada = campo("nombre_linea_especializada")
    horario_linea = "24h"
    # Formato con «lineas» (el del directorio): la de peligro, si es de 24 h,
    # es emergencias; la de crisis emocional es la especializada, con su
    # horario.
    for linea in datos.get("lineas") or []:
        if not isinstance(linea, dict):
            continue
        if campo("uso", linea) == "peligro" and campo("horario", linea) in ("", "24h"):
            emergencias = campo("numero", linea)
        elif campo("uso", linea) == "crisis_emocional":
            especializada = campo("numero", linea)
            nombre_especializada = campo("nombre_en_frase", linea)
            horario_linea = campo("horario", linea) or "24h"
    desfase = datos.get("desfase_utc_horas")

    pais_archivo = campo("pais")
    coincide = not pais or normalizar(pais) == normalizar(pais_archivo)
    if not coincide:
        emergencias = especializada = nombre_especializada = ""

    return Recursos(
        pais=pais_archivo,
        telefono_emergencias=emergencias,
        linea_especializada=especializada,
        nombre_linea_especializada=nombre_especializada,
        respuesta=campo("respuesta") or RESPUESTA_DE_RESERVA,
        cierre_con_emergencias=campo("cierre_con_emergencias"),
        cierre_con_linea=campo("cierre_con_linea"),
        cierre_sin_recursos=campo("cierre_sin_recursos"),
        verificado=bool(datos.get("verificado_por_responsable")),
        horario_linea=horario_linea,
        desfase_utc_horas=float(desfase) if isinstance(desfase, (int, float))
        and not isinstance(desfase, bool) else None,
        pais_coincide=coincide,
        pais_configurado=pais or "",
    )


@dataclass
class Evaluacion:
    activada: bool
    respuesta: str = ""


class Guardia:
    """Evalúa cada turno ANTES de que llegue a cualquier proveedor."""

    def __init__(self, recursos: Recursos | None = None) -> None:
        self.recursos = recursos or cargar_recursos()
        self._avisos_emitidos = False

    def advertencias_arranque(self) -> list[str]:
        """Comprobaciones que deben verse al arrancar, no descubrirse en uso."""
        avisos: list[str] = []
        if not self.recursos.pais_coincide:
            avisos.append(
                f"config/crisis.json es de {self.recursos.pais} y region.pais es "
                f"{self.recursos.pais_configurado}: no se ofrecerá ningún número."
            )
        if not self.recursos.verificado:
            avisos.append(
                "config/crisis.json tiene verificado_por_responsable=false. "
                "Confirma los recursos en una fuente oficial antes de usar "
                "EMOTI-BOT con otras personas."
            )
        if not self.recursos.linea_especializada:
            avisos.append(
                "No hay línea especializada configurada; se usará solo el "
                "teléfono de emergencias y la derivación a una persona de "
                "confianza."
            )
        if not self.recursos.telefono_emergencias:
            avisos.append(
                "No hay teléfono de emergencias configurado en "
                "config/crisis.json."
            )
        if avisos and not self._avisos_emitidos:
            self._avisos_emitidos = True
            for aviso in avisos:
                log.warning("%s", aviso)
        return avisos

    def evaluar(self, texto: str, hora: dt.time | None = None) -> Evaluacion:
        """`hora`: la del país de los números; por defecto, la actual."""
        plano = normalizar(texto)
        if not plano:
            return Evaluacion(False)
        # Primero se quitan los modismos; lo que queda es lo que se evalúa.
        filtrado = _MODISMOS.sub(" ", plano)
        for patron in _RIESGO:
            if patron.search(filtrado):
                # Se registra el hecho, nunca el contenido.
                log.warning(
                    "Ruta de seguridad activada. Respuesta local, sin modelo. "
                    "No se registra el contenido del turno."
                )
                return Evaluacion(True, self.recursos.mensaje(hora))
        return Evaluacion(False)
