"""Los tres estados honestos de la inteligencia (§14.4.1).

- PROCESANDO: hay una consulta EN CURSO; la respuesta viene. Solo se anuncia
  justo antes de llamar a un proveedor, nunca antes: con la cuota agotada o
  el plazo vencido no se llega a anunciar.
- ESPERANDO: se topó un límite por minuto (o la pausa tras un 429) y vuelve
  sola en seguida. Dentro de un turno solo se anuncia si DE VERDAD se va a
  esperar (cabe en el plazo del turno).
- NO_DISPONIBLE: solo queda lo local: cuota del día agotada, sin conexión,
  clave que falta o rechazada, o se agotó el plazo del turno.

Todos los textos, de pantalla y hablados, son FIJOS y están aquí. Ningún
modelo los escribe ni los completa.
"""
from __future__ import annotations

PROCESANDO = "procesando"
ESPERANDO = "esperando"
NO_DISPONIBLE = "no_disponible"
DISPONIBLE = ""

# Causas de NO_DISPONIBLE (y «minuto», la de ESPERANDO).
PLAZO = "plazo"
CUOTA = "cuota"
MINUTO = "minuto"
CONEXION = "conexion"
CLAVE = "clave"
CAUSAS = (PLAZO, CUOTA, MINUTO, CONEXION, CLAVE)

# Estado del rostro para cada estado de la inteligencia.
ROSTRO = {PROCESANDO: "pensando", ESPERANDO: "esperando", NO_DISPONIBLE: "no_disponible"}

TEXTO_PROCESANDO = "Pensando la respuesta…"
TEXTO_ESPERANDO = "Un momento: llegué a mi límite por minuto y enseguida sigo."

# Con carcasa, en pantalla.
TEXTOS_PANTALLA = {
    PLAZO: "Tardaba demasiado: te contesto en modo local.",
    CUOTA: "Se acabó mi cuota de hoy: te contesto en modo local.",
    MINUTO: "Llegué a mi límite por un momento: te contesto en modo local.",
    CONEXION: "Mi modelo no responde ahora: te contesto en modo local.",
    CLAVE: "Falta la clave de mi modelo o no es válida (tecla K): modo local.",
}

# Hablados. NO_DISPONIBLE se dice siempre, antes de la respuesta local: si no,
# la persona espera algo que no llega.
FRASES_HABLADAS = {
    PLAZO: "Mi modelo tardaba demasiado, así que te contesto en modo local.",
    CUOTA: "Hoy ya no me queda cuota, así que te contesto en modo local.",
    MINUTO: "He llegado a mi límite por un momento; te contesto en modo local "
            "y enseguida vuelvo a la normalidad.",
    CONEXION: "Mi modelo no me responde ahora, así que te contesto en modo local.",
    CLAVE: "Me falta la clave de mi modelo, así que te contesto en modo local.",
}
# ESPERANDO es solo visual, salvo que se alargue: entonces, UNA vez por turno.
FRASE_ESPERA = "Un momento, enseguida sigo."
SEGUNDOS_PARA_HABLAR_ESPERA = 4.0
