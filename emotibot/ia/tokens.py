"""Estimación de tokens ANTES de llamar al proveedor (Fase 1, A3, §13.4).

Los tokens de entrada se conocen antes de llamar, porque el prompt ya está
construido. Lo único incierto es la salida, y está acotada por `max_tokens`.
Por eso la reserva previa es:

    reserva = entrada estimada AL ALZA + max_tokens

No hay tokenizador en el proyecto: añadirlo sería una dependencia más en la
Raspberry y, además, cada proveedor usa el suyo. Se estima por caracteres y
se sobreestima a propósito, porque el error tiene que ir hacia arriba:

- quedarse corto provoca un 429, que cuesta el turno más 120 s de pausa;
- pasarse solo cuesta un turno de margen.

Método y error esperado
-----------------------
- Medido con tokens REALES de Qwen (22-11-2026, `logs/latencia.csv`): la
  primera vuelta de sesión con las instrucciones de hoy (3.278 caracteres)
  costó 783 tokens de entrada. Son ~4,25 caracteres por token. La cifra
  anterior (3,6, de 2.447 caracteres y ~680 tokens) era una estimación.
- Se cuentan 4,0 caracteres por token (6 % de margen sobre lo medido), 4
  tokens de envoltorio por mensaje y 3 fijos, y se multiplica todo por 1,10.
- La estimación queda en torno a un 17 % por ENCIMA del consumo real. Antes,
  con 3,0, quedaba un 42 % por encima: el robot reservaba más de lo que
  gastaba y se frenaba antes de lo necesario (ver bitácora, D10).
- Puede quedarse corta con texto muy denso en cifras, símbolos o alfabetos
  no latinos, que se tokenizan casi carácter a carácter. En una conversación
  hablada eso es raro, y el margen del 10 % lo cubre en parte. La
  reconciliación posterior con el `usage` real corrige el contador igual.

No predice el consumo exacto de una respuesta que todavía no existe: acota
el peor caso razonable.
"""
from __future__ import annotations

import math
from typing import Iterable

CARACTERES_POR_TOKEN = 4.0          # medido: ~4,25 (Qwen, 22-11-2026)
SOBRECOSTE_POR_MENSAJE = 4
SOBRECOSTE_FIJO = 3
MARGEN = 1.10


def estimar_entrada(textos: Iterable[str]) -> int:
    """Tokens de entrada estimados al alza para una lista de mensajes."""
    caracteres = 0
    mensajes = 0
    for texto in textos:
        caracteres += len(texto or "")
        mensajes += 1
    bruto = (caracteres / CARACTERES_POR_TOKEN
             + SOBRECOSTE_POR_MENSAJE * mensajes + SOBRECOSTE_FIJO)
    return int(math.ceil(bruto * MARGEN))
