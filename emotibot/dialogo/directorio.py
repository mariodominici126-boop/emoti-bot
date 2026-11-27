"""Directorio de ayuda: CONSULTA de números, distinta de la ruta de crisis.

La ruta de crisis (seguridad.py) es reactiva: salta sola ante una intención
explícita de riesgo y contesta con un texto fijo. El directorio es lo
contrario: alguien PIDE los números —con una tecla (A) o hablando— y se le
muestran en una barra lateral, con su situación, su número y su horario. No
comparten interfaz: la ruta de crisis nunca abre la barra, y el directorio
no pasa por la ruta de crisis.

Reglas que no se tocan:
- Los números viven en config/crisis.json. Ningún modelo los genera, los
  completa ni los corrige: este módulo es el único que los lee para mostrarlos,
  la petición hablada se resuelve aquí sin modelo, y si una respuesta de un
  modelo trae algo con forma de número de teléfono, se sustituye (ver
  `contiene_telefono` y el gestor).
- El país es configurable (`region.pais` en config/ajustes.json). Si no es el
  de los números, el directorio no los da por buenos y no muestra ninguno.
- Cada línea tiene su horario; una línea fuera de horario va al final,
  marcada, y nunca es la primera.
- El robot no puede llamar. Lo dice: muestra el número y que hay que marcarlo.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import registro, rutas
from ..texto import normalizar
from . import horario as mod_horario

log = registro.obtener("dialogo.directorio")

ARCHIVO = rutas.CONFIG_REPO / "crisis.json"
NO_PUEDO_LLAMAR = "Yo no puedo llamar: hay que marcar el número."


@dataclass(frozen=True)
class Linea:
    uso: str                 # peligro · crisis_emocional · violencia_mujer …
    etiqueta: str            # la SITUACIÓN, 3-4 palabras: «peligro ahora mismo»
    numero: str              # tal cual se marca: 911, 711, *212
    se_dice: str = ""        # cómo leerlo en voz alta: «asterisco dos uno dos»
    horario: str = "24h"
    idiomas: str = ""
    nombre_en_frase: str = ""

    def abierta(self, hora: dt.time) -> bool:
        return mod_horario.abierta(self.horario, hora)


@dataclass
class Directorio:
    pais: str = ""
    lineas: list[Linea] = field(default_factory=list)
    desfase_utc_horas: float | None = None
    motivo_vacio: str = ""          # por qué no hay números que dar

    def hora(self, ahora: dt.datetime | None = None) -> dt.time:
        return mod_horario.hora_del_pais(self.desfase_utc_horas, ahora)

    def entradas(self, hora: dt.time) -> list[tuple[Linea, bool]]:
        """Las líneas en orden: abiertas primero (en el orden del archivo) y
        las que están fuera de horario al final. Nunca es primera una cerrada."""
        abiertas = [(l, True) for l in self.lineas if l.abierta(hora)]
        cerradas = [(l, False) for l in self.lineas if not l.abierta(hora)]
        return abiertas + cerradas

    def principal(self, hora: dt.time) -> Linea | None:
        entradas = self.entradas(hora)
        return entradas[0][0] if entradas and entradas[0][1] else None

    def respuesta_hablada(self, hora: dt.time) -> str:
        if not self.lineas:
            return (f"{self.motivo_vacio} Si estás en peligro, llama a los servicios "
                    "de emergencia de tu país o pide a alguien cercano que lo haga "
                    "contigo.").strip()
        partes = [f"Te muestro en la pantalla los números de ayuda de {self.pais}."]
        for linea, abierta in self.entradas(hora):
            numero = linea.se_dice or linea.numero
            cuando = mod_horario.describir(linea.horario)
            frase = f"Para {linea.etiqueta}, el {numero}, {cuando}"
            if linea.idiomas:
                frase += f", en {linea.idiomas}"
            if not abierta:
                frase += "; ahora mismo está fuera de horario"
            partes.append(frase + ".")
        partes.append(NO_PUEDO_LLAMAR + " Márcalo tú, o pide a alguien de "
                      "confianza que lo haga contigo.")
        return " ".join(partes)

    def numeros(self) -> list[str]:
        return [l.numero for l in self.lineas]


def _texto(datos: dict, clave: str) -> str:
    valor = datos.get(clave, "")
    return str(valor).strip() if isinstance(valor, (str, int)) else ""


def cargar(pais_configurado: str | None = None, ruta: Path | None = None) -> Directorio:
    """Lee las líneas de config/crisis.json. Nunca inventa ninguna."""
    archivo = ruta or ARCHIVO
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.error("No pude leer %s (%s): el directorio queda vacío.", archivo.name, exc)
        return Directorio(motivo_vacio="No tengo números de ayuda configurados.")
    if not isinstance(datos, dict):
        return Directorio(motivo_vacio="No tengo números de ayuda configurados.")
    pais = _texto(datos, "pais")
    if pais_configurado and normalizar(pais_configurado) != normalizar(pais):
        log.warning("Los números de %s son de %s y EMOTI-BOT está configurado para %s: "
                    "no se ofrecen.", archivo.name, pais or "ningún país", pais_configurado)
        return Directorio(pais=pais_configurado, motivo_vacio=(
            f"No tengo números de ayuda comprobados para {pais_configurado}."))
    desfase = datos.get("desfase_utc_horas")
    lineas: list[Linea] = []
    for entrada in datos.get("lineas") or []:
        if not isinstance(entrada, dict) or not _texto(entrada, "numero"):
            continue
        try:
            mod_horario.minutos(_texto(entrada, "horario") or "24h")
        except mod_horario.ErrorHorario as exc:
            log.error("%s: %s. Esa línea no se ofrece.", archivo.name, exc)
            continue
        lineas.append(Linea(
            uso=_texto(entrada, "uso"), etiqueta=_texto(entrada, "etiqueta"),
            numero=_texto(entrada, "numero"), se_dice=_texto(entrada, "se_dice"),
            horario=_texto(entrada, "horario") or "24h",
            idiomas=_texto(entrada, "idiomas"),
            nombre_en_frase=_texto(entrada, "nombre_en_frase"),
        ))
    return Directorio(
        pais=pais, lineas=lineas,
        desfase_utc_horas=float(desfase) if isinstance(desfase, (int, float))
        and not isinstance(desfase, bool) else None,
        motivo_vacio="" if lineas else "No tengo números de ayuda configurados.",
    )


# --------------------------------------------------------------- petición hablada
_PIDE = tuple(re.compile(p) for p in (
    r"\b(?:numeros?|telefonos?|lineas?)\s+de\s+(?:ayuda|emergencias?|crisis|apoyo)\b",
    r"\b(?:a\s+)?(?:quien|donde|que\s+numero)\s+(?:puedo|podria|hay\s+que|debo)\s+llamar\b",
    r"\bdirectorio\s+de\s+ayuda\b",
    r"\b(?:dame|dime|ensename|muestrame|pasame)\s+(?:el|los|un)\s+(?:numeros?|telefonos?)\b",
    r"\bnumero\s+(?:para|de)\s+(?:pedir\s+)?ayuda\b",
    r"\b(?:a\s+)?que\s+numero\s+(?:marco|llamo|puedo\s+(?:marcar|llamar)"
    r"|debo\s+(?:marcar|llamar)|hay\s+que\s+(?:marcar|llamar))\b",
    r"\bnumeros?\s+de\s+(?:la\s+)?linea\s+de\s+(?:ayuda|crisis|emergencias?)\b",
))


def pide_directorio(texto: str) -> bool:
    plano = normalizar(texto or "")
    return bool(plano) and any(p.search(plano) for p in _PIDE)


# ------------------------------------------------------ números en boca de un modelo
_TELEFONO = (
    re.compile(r"\*\s?\d{2,5}\b"),                              # *212
    re.compile(r"(?<![\d.,:])\d{3}[\s.\-]\d{3}[\s.\-]\d{4}(?![\d])"),  # 809-200-1400
    re.compile(r"(?<![\d.,:])\d{10,11}(?![\d.,:])"),            # 8092001400
    re.compile(r"\b(?:1[\s.\-])?8[0-9]{2}[\s.\-]?\d{3}[\s.\-]?\d{4}\b"),
)


_DIGITO = r"(?:cero|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve)"
_PALABRA_NUMERO = (r"(?:cero|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|"
                   r"doce|trece|catorce|quince|veinti\w*|treinta|cuarenta|cincuenta|"
                   r"sesenta|setenta|ochenta|noventa|cien\w*|doscient\w*|trescient\w*|"
                   r"cuatrocient\w*|quinient\w*|seiscient\w*|setecient\w*|ochocient\w*|"
                   r"novecient\w*|mil)")
_VERBO = r"\b(?:llam\w*|marc\w*|contact\w*|comunic\w*|telefone\w*)\b"
_TELEFONO_PLANO = (
    # «llama al 112», «marca el 106»: número corto justo tras llamar o marcar.
    re.compile(_VERBO + r"\s+(?:\w+\s+){0,3}?(?<!\d)\d{3,5}(?!\d)"),
    # «llama al novecientos once», «marca el siete uno uno»: al menos dos
    # números seguidos («llama a dos amigos» no es un teléfono).
    re.compile(_VERBO + r"\s+(?:\w+\s+){0,3}?" + _PALABRA_NUMERO
               + r"(?:[\s,.\-]+(?:y\s+)?" + _PALABRA_NUMERO + r")+\b"),
    # «asterisco dos uno dos».
    re.compile(r"\basterisco\s+" + _DIGITO + r"\b"),
)


def contiene_telefono(texto: str, numeros_configurados: list[str] | tuple[str, ...] = ()) -> bool:
    """¿Trae el texto algo con forma de número de teléfono?

    Sirve para que un modelo NUNCA dé, complete ni corrija un número: si su
    respuesta trae uno —inventado o copiado—, el gestor la sustituye por la
    remisión al directorio. Se comprueban los números configurados tal cual
    (911, 711…), cualquier formato de teléfono (asterisco más dígitos, o 10
    dígitos con o sin separadores), un número —en cifras o en palabras—
    pocas palabras después de «llama» o «marca», y «asterisco» seguido de
    una cifra dicha. Las cifras normales —años, horas, cantidades— no cuentan.
    """
    if not texto:
        return False
    for numero in numeros_configurados:
        n = re.escape(numero.strip())
        if n and re.search(rf"(?<![\w*]){n}(?!\w)", texto):
            return True
    if any(p.search(texto) for p in _TELEFONO):
        return True
    plano = normalizar(texto)
    return any(p.search(plano) for p in _TELEFONO_PLANO)


REMISION = ("Los números de ayuda no los digo de memoria: los tengo en mi "
            "directorio y te los muestro en la pantalla. " + NO_PUEDO_LLAMAR)
