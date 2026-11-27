"""Franjas horarias de las líneas de ayuda y hora del país.

El horario de una línea es un REQUISITO, no un dato: una línea fuera de su
horario nunca se ofrece como principal. Formato en config/crisis.json:

- "24h"            → abierta siempre;
- "08:00-24:00"    → abierta de 8:00 (incluida) a medianoche (excluida).

La hora es la del PAÍS de los números (`desfase_utc_horas` en
config/crisis.json; República Dominicana no cambia de hora en verano), no la
del ordenador: un robot configurado en otro huso no debe abrir ni cerrar las
líneas a deshora. Sin desfase configurado se usa la hora local del equipo.
"""
from __future__ import annotations

import datetime as dt
import re

_FRANJA = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


class ErrorHorario(ValueError):
    pass


def minutos(horario: str) -> tuple[int, int] | None:
    """(inicio, fin) en minutos desde medianoche; None si es 24 h."""
    texto = (horario or "").strip().lower().replace(" ", "")
    if texto in ("24h", "24horas"):
        return None
    m = _FRANJA.match(texto)
    if not m:
        raise ErrorHorario(f"Horario no válido: {horario!r} (usa \"24h\" o \"08:00-24:00\")")
    h0, m0, h1, m1 = (int(v) for v in m.groups())
    inicio, fin = h0 * 60 + m0, h1 * 60 + m1
    if not (0 <= inicio < 24 * 60 and 0 < fin <= 24 * 60 and m0 < 60 and m1 < 60):
        raise ErrorHorario(f"Horario no válido: {horario!r}")
    return inicio, fin


def abierta(horario: str, hora: dt.time) -> bool:
    franja = minutos(horario)
    if franja is None:
        return True
    inicio, fin = franja
    ahora = hora.hour * 60 + hora.minute
    if inicio < fin:
        return inicio <= ahora < fin
    return ahora >= inicio or ahora < fin           # franja que cruza medianoche


def describir(horario: str) -> str:
    """«24 horas» o «de 8:00 a 24:00», para mostrar y para decir."""
    franja = minutos(horario)
    if franja is None:
        return "24 horas"
    inicio, fin = franja
    return f"de {inicio // 60}:{inicio % 60:02d} a {fin // 60}:{fin % 60:02d}"


def hora_del_pais(desfase_utc_horas: float | None,
                  ahora: dt.datetime | None = None) -> dt.time:
    if desfase_utc_horas is None:
        return (ahora or dt.datetime.now()).time()
    utc = ahora or dt.datetime.now(dt.timezone.utc)
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=dt.timezone.utc)
    return (utc.astimezone(dt.timezone.utc)
            + dt.timedelta(hours=desfase_utc_horas)).time()
