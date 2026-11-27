"""Estados expresivos del rostro.

Cada estado es un conjunto de parámetros que el rostro interpola suavemente.
Nada de saltos: las transiciones se hacen por aproximación exponencial hacia
el estado objetivo, que es lo que separa una cara simpática de una cara que
cambia a golpes.

Los nombres de estado son los que usan el gestor de diálogo y las actividades,
de modo que la expresión siempre corresponde a algo real que el sistema está
haciendo. Es también un requisito de transparencia: ESCUCHANDO significa que
el micrófono está abierto, y nunca se usa para otra cosa.
"""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Expresion:
    """Parámetros normalizados de una expresión.

    - apertura_ojos: 1.0 es el tamaño de reposo.
    - curva_boca: positivo sonríe, negativo entristece.
    - apertura_boca: 0 cerrada; la voz la modula en tiempo real.
    - ceja_alto / ceja_angulo: desplazamiento y giro de las cejas.
    - inclinacion: giro de la cabeza en grados.
    - mirada: desplazamiento de las pupilas (x, y) en fracción del ojo.
    - color: clave de color en la paleta.
    - respira: amplitud del movimiento de respiración.
    - destellos: estrellitas al lado de los ojos.
    - ojos_arco: dibuja los ojos como dos arcos «^ ^» en vez de óvalos. Es lo
      que convierte una cara neutra en una cara contenta de verdad; un óvalo
      aplastado solo parece un ojo medio cerrado.
    - escala / segundos_escala: tamaño de toda la cara al que se llega, con
      una rampa suave, en ese tiempo. Es lo que da DIRECCIÓN a la
      respiración: crecer al inhalar, mantenerse al sostener y menguar al
      exhalar. `respira` no sirve para eso: es la amplitud de una oscilación
      de periodo fijo, igual al inhalar que al exhalar.
    - boca_reposo: apertura de boca fija cuando el robot NO habla (hablando,
      la voz la sustituye). Excepción justificada para «suelta el aire».
    - vaiven: amplitud de un barrido lento de la mirada de lado a lado, «mirar
      el reloj». Solo lo usa «esperando», para distinguirse sin texto.
    - signo: «!» o «?» dibujado junto a la cara, o nada. Una marca que está o
      no está, no un valor mayor o menor: en el sondeo del 27-11-2026 las
      diferencias de pocos píxeles no se leyeron. Es un signo de dibujo
      animado, no texto de interfaz: se ve también sin carcasa.
    """

    etiqueta: str
    apertura_ojos: float = 1.0
    curva_boca: float = 0.45
    apertura_boca: float = 0.0
    ceja_alto: float = 0.0
    ceja_angulo: float = 0.0
    inclinacion: float = 0.0
    mirada: tuple[float, float] = (0.0, 0.0)
    color: str = "ojos"
    respira: float = 1.0
    destellos: bool = False
    anillo_escucha: bool = False
    parpadea: bool = True
    ojos_arco: bool = False
    escala: float = 1.0
    segundos_escala: float = 0.6
    boca_reposo: float = 0.0
    vaiven: float = 0.0
    signo: str = ""


EXPRESIONES: dict[str, Expresion] = {
    "reposo": Expresion(
        etiqueta="EN REPOSO", curva_boca=0.55, respira=1.0,
    ),
    "calibrando": Expresion(
        # Estado propio y visible: la persona NO debe hablar todavía.
        etiqueta="PREPARANDO EL MICRÓFONO", apertura_ojos=0.55,
        curva_boca=0.12, ceja_alto=0.10, inclinacion=-3.0,
        mirada=(0.0, 0.25), color="atento", respira=0.6, parpadea=False,
        # El micrófono YA está abierto (está midiendo el ruido): las barras
        # se ven desde aquí, no desde que empieza a detectar voz.
        anillo_escucha=True,
    ),
    "escuchando": Expresion(
        etiqueta="TE ESCUCHO", apertura_ojos=1.18, curva_boca=0.40,
        ceja_alto=0.26, ceja_angulo=-7.0, inclinacion=5.0,
        mirada=(0.0, 0.06), color="atento", respira=0.8,
        anillo_escucha=True,
    ),
    "pensando": Expresion(
        etiqueta="PENSANDO", apertura_ojos=0.86, curva_boca=0.18,
        ceja_alto=0.14, ceja_angulo=9.0, inclinacion=-6.0,
        mirada=(-0.34, -0.30), respira=0.7,
    ),
    "hablando": Expresion(
        etiqueta="HABLANDO", apertura_ojos=1.04, curva_boca=0.34,
        apertura_boca=0.62, respira=0.9,
    ),
    # Mientras alguien cuenta algo que le pesa (dialogo/tono.py): sin
    # sonrisa, neutra y atenta. Ni triste (eso es «preocupado», de la ruta
    # de seguridad) ni alegre.
    "acompanando": Expresion(
        etiqueta="", apertura_ojos=1.0, curva_boca=0.04, ceja_alto=0.06,
        ceja_angulo=4.0, inclinacion=4.0, respira=0.85,
    ),
    # La misma escucha de siempre (ámbar: micrófono abierto), sin sonrisa.
    "escucha_atenta": Expresion(
        etiqueta="TE ESCUCHO", apertura_ojos=1.12, curva_boca=0.04,
        ceja_alto=0.20, ceja_angulo=-4.0, inclinacion=5.0,
        mirada=(0.0, 0.06), color="atento", respira=0.8,
    ),
    "feliz": Expresion(
        etiqueta="", apertura_ojos=0.30, curva_boca=1.0, ceja_alto=0.30, color="feliz", respira=1.1, destellos=True,
        ojos_arco=True, parpadea=False,
    ),
    # «No te oí» / «no te entendí»: la cara de reposo con un «?». Sustituye a
    # «curioso» (27-11-2026): sin el ámbar era idéntica a «escuchando» y en el
    # sondeo nadie la acertó; lo que el robot necesita decir es «repítelo».
    "sin_entender": Expresion(
        etiqueta="", curva_boca=0.55, respira=1.0, signo="?",
    ),
    "preocupado": Expresion(
        # Para la ruta de seguridad y los errores: preocupación cálida, no
        # alarma. Una cara de alerta roja asusta justo cuando no toca.
        etiqueta="", apertura_ojos=0.94, curva_boca=-0.18, ceja_alto=0.16,
        ceja_angulo=26.0, inclinacion=3.0, mirada=(0.0, 0.10),
        color="preocupado", respira=0.75,
    ),
    "error": Expresion(
        etiqueta="ALGO NO FUE BIEN", apertura_ojos=0.80, curva_boca=-0.06,
        ceja_alto=0.08, ceja_angulo=20.0, color="error",
        respira=0.7, signo="!",
    ),
    "sin_conexion": Expresion(
        etiqueta="MODO SIN CONEXIÓN", apertura_ojos=0.90, curva_boca=0.30,
        ceja_alto=0.04, color="preocupado", respira=0.9,
    ),
    # Los tres estados honestos de la inteligencia (§14.4.1). PROCESANDO es
    # «pensando» (arriba). ESPERANDO, propio: párpados a media asta, boca
    # plana, cabeza recta, color base (ni ámbar, que es el micrófono, ni el
    # azul de no disponible) y la mirada barriendo de lado a lado, despacio:
    # paciencia, no esfuerzo. NO DISPONIBLE es la cara de «sin conexión» con
    # su propio rótulo: la causa puede ser la cuota o el plazo, no solo la red.
    "esperando": Expresion(
        etiqueta="UN MOMENTO", apertura_ojos=0.55, curva_boca=0.04,
        color="ojos", respira=0.5, vaiven=1.0,
    ),
    "no_disponible": Expresion(
        etiqueta="SOLO MODO LOCAL", apertura_ojos=0.90, curva_boca=0.30,
        ceja_alto=0.04, color="preocupado", respira=0.9,
    ),
    # Respiración guiada (revisada el 22-11). Antes, los cuatro estados eran
    # «feliz» con ojos «^ ^» (sonrisa constante), y inhalar y exhalar solo se
    # distinguían en 2-3 px de curva de boca. Un ejercicio de respiración no
    # tiene por qué sonreír: color base, ojos sin arco, boca casi recta. La
    # dirección la da la escala, que se interpola en el tiempo del paso:
    # inhalar crece en 4 s, sostener mantiene, exhalar mengua en 6 s (los
    # tiempos de actividades/respiracion.py).
    "respirando": Expresion(
        etiqueta="RESPIRACIÓN", apertura_ojos=0.75, curva_boca=0.20,
        color="ojos", respira=0.8, escala=1.0,
    ),
    "respirando_inhalar": Expresion(
        etiqueta="INHALA", apertura_ojos=0.95, curva_boca=0.10, ceja_alto=0.14,
        color="ojos", respira=0.2, parpadea=False,
        escala=1.08, segundos_escala=4.0,
    ),
    "respirando_sostener": Expresion(
        etiqueta="SOSTÉN", apertura_ojos=0.62, curva_boca=0.08, ceja_alto=0.08,
        color="ojos", respira=0.0, parpadea=False,
        escala=1.08, segundos_escala=0.6,
    ),
    "respirando_exhalar": Expresion(
        etiqueta="SUELTA", apertura_ojos=0.38, curva_boca=0.18,
        color="ojos", respira=0.2, parpadea=False,
        escala=0.97, segundos_escala=6.0, boca_reposo=0.26,
    ),
    "durmiendo": Expresion(
        etiqueta="", apertura_ojos=0.10, curva_boca=0.30,
        respira=1.4, parpadea=False,
    ),
}

ESTADO_POR_DEFECTO = "reposo"


def obtener(nombre: str) -> Expresion:
    return EXPRESIONES.get(nombre, EXPRESIONES[ESTADO_POR_DEFECTO])


# --------------------------------------------------------------------------
# Estado funcional + expresión (Fase 1, A1)
#
# Antes, un único nombre decía a la vez QUÉ HACE el robot y QUÉ CARA PONE.
# Resultado: hablaba con la boca cerrada en 16 de los 17 sitios que emiten
# voz, porque solo «hablando» tenía apertura de boca, y la actividad de
# ordenar ideas encendía el piloto del micrófono mientras hablaba.
#
# Ahora son dos ejes que se superponen:
#
# - el ESTADO FUNCIONAL aporta la boca (cuánto puede abrirla la voz) y el
#   indicador de escucha;
# - la EXPRESIÓN aporta ojos, cejas, inclinación, color, respiración y
#   destellos.
#
# No es una matriz de combinaciones: es una regla de composición sobre el
# catálogo de arriba, que se conserva tal cual.
# --------------------------------------------------------------------------

# Estados funcionales con el micrófono abierto de verdad: en los dos se ven
# las barras, sin excepción (escucha continua incluida).
MICROFONO_ABIERTO: tuple[str, ...] = ("calibrando", "escuchando")

FUNCIONALES: tuple[str, ...] = (
    "reposo", "calibrando", "escuchando", "pensando", "hablando", "error",
    "sin_conexion", "esperando", "no_disponible",
)

# Cuánto puede abrir la boca la voz en cada estado funcional. La apertura
# real es este valor POR la envolvente del audio que suena: con el altavoz
# en silencio la boca queda cerrada, sea cual sea el estado.
APERTURA_BOCA_FUNCIONAL: dict[str, float] = {
    "hablando": EXPRESIONES["hablando"].apertura_boca,
}


def componer(funcional: str, expresion: str) -> Expresion:
    """Expresión efectiva de un estado funcional con una expresión emocional.

    - Boca: la dicta el estado funcional. Hablando, la voz la abre igual
      con cualquier emoción. En los demás estados la amplitud es cero. La
      `apertura_boca` de las expresiones del catálogo se ignora al componer
      (antes era la causa del defecto: 0 en casi todas).
    - Indicador de escucha: SOLO si el estado funcional tiene el micrófono
      abierto de verdad («calibrando» o «escuchando», MICROFONO_ABIERTO).
      Una expresión no puede encenderlo.
    - Etiqueta: la de la expresión si es emocional («INHALA», o vacía). Si la
      expresión es a su vez un nombre funcional («escuchando» mientras se
      pronuncia una pregunta), manda la etiqueta del estado funcional real.
    """
    funcional = funcional if funcional in FUNCIONALES else ESTADO_POR_DEFECTO
    base = obtener(expresion)
    propio = EXPRESIONES[funcional]

    # Fuera de «hablando» la boca no tiene amplitud: aunque quedara un resto
    # de nivel en el altavoz, no se mueve si el robot no está hablando.
    apertura = APERTURA_BOCA_FUNCIONAL.get(funcional, 0.0)

    etiqueta = base.etiqueta
    if expresion in FUNCIONALES or expresion not in EXPRESIONES:
        etiqueta = propio.etiqueta

    return replace(
        base,
        etiqueta=etiqueta,
        apertura_boca=apertura,
        anillo_escucha=propio.anillo_escucha,
        # La boca fija de la expresión solo vale cuando NO se habla: hablando
        # manda la voz real (A1).
        boca_reposo=0.0 if funcional == "hablando" else base.boca_reposo,
    )
