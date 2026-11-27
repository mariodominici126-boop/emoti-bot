"""Lógica común de los instrumentos de medición de la Fase 1 (B1 y B3).

Aquí solo hay cálculo puro, comprobable sin micrófono. Los scripts de `bin/`
ponen la interacción con la persona y el hardware.

PRIVACIDAD. Los instrumentos guardan cifras, categorías y el identificador
de la frase del guion, nunca el texto reconocido ni audio. Las frases del
guion son fijas, inocuas y están escritas aquí, así que una comparación con
ellas no expone nada de nadie.
"""
from __future__ import annotations

import math
import random
from array import array
from dataclasses import dataclass

from .audio import senal
from .audio.captura import PRE_VOZ_S
from .audio.vad import DetectorVoz, Fase
from .texto import normalizar

# ------------------------------------------------------------------ B1: STT
CATEGORIAS_STT = (
    "correcta",              # reconocida sin errores de palabra
    "error_reconocimiento",  # se entendió algo, pero con palabras mal
    "transcripcion_vacia",   # el motor devolvió texto vacío
    "fallo_motor",           # el motor STT lanzó un error técnico
    "corte_prematuro",       # el audio se cerró antes de acabar la frase
    "fallo_captura",         # el micrófono o el dispositivo falló
    "sin_voz",               # el detector no oyó voz
)

# 30 frases inocuas, de longitud y dificultad variadas: números, nombres
# propios, preguntas, y frases con pausa natural en medio. Las 5 últimas son
# de las que una persona suele decir con una pausa interna.
GUION_STT: tuple[str, ...] = (
    "Hola, ¿cómo estás hoy?",
    "Quiero hacer una respiración corta.",
    "Ayúdame a ordenar mis ideas, por favor.",
    "¿Qué hora es en Madrid?",
    "Mañana tengo una reunión a las diez y media.",
    "Me gusta mucho el café con leche.",
    "¿Cuántos planetas hay en el sistema solar?",
    "Hoy he dormido bastante mal.",
    "Mi hermana se llama Lucía y vive en Valencia.",
    "Cuéntame algo curioso sobre los pulpos.",
    "Necesito comprar pan, huevos y tomates.",
    "¿Por qué el cielo es azul?",
    "El tren sale a las siete y cuarto.",
    "No sé si ir al cine o quedarme en casa.",
    "¿Puedes repetir lo último que dijiste?",
    "Tengo que estudiar para el examen del jueves.",
    "Ayer caminé casi cinco kilómetros.",
    "¿Quién te creó?",
    "Estoy un poco cansado, pero bien.",
    "La película empieza a las nueve de la noche.",
    "Me cuesta concentrarme por las tardes.",
    "Quiero preparar una sopa de verduras.",
    "¿Qué puedes hacer por mí?",
    "Mi número favorito es el veintitrés.",
    "Hace frío y está lloviendo bastante.",
    "Estaba pensando… que quizá mañana salga a correr.",
    "Primero quiero contarte algo, y luego te pregunto.",
    "No sé muy bien… cómo empezar esto.",
    "Bueno, a ver, lo que quería decir es que estoy bien.",
    "Creo que sí, pero déjame pensarlo un momento.",
)


def errores_de_palabra(referencia: str, hipotesis: str) -> tuple[int, int]:
    """(errores, palabras de la referencia): distancia de edición por palabras.

    Sobre texto normalizado (minúsculas, sin acentos ni puntuación), para no
    contar como error una tilde o una coma que Whisper puso distinta.
    """
    ref = normalizar(referencia).split()
    hip = normalizar(hipotesis).split()
    anterior = list(range(len(hip) + 1))
    for i, palabra_ref in enumerate(ref, 1):
        actual = [i] + [0] * len(hip)
        for j, palabra_hip in enumerate(hip, 1):
            actual[j] = min(
                anterior[j] + 1,                       # borrado
                actual[j - 1] + 1,                     # inserción
                anterior[j - 1] + (palabra_ref != palabra_hip),  # sustitución
            )
        anterior = actual
    return anterior[-1], len(ref)


def parece_cortada(referencia: str, hipotesis: str, minimo_faltan: int = 2) -> bool:
    """La hipótesis es el principio de la referencia y le falta el final.

    Es una SOSPECHA de corte prematuro, que el operador confirma: Whisper
    también puede omitir palabras finales por otros motivos.
    """
    ref = normalizar(referencia).split()
    hip = normalizar(hipotesis).split()
    if not hip or len(ref) - len(hip) < minimo_faltan:
        return False
    coinciden = sum(1 for a, b in zip(ref, hip) if a == b)
    return coinciden >= max(1, int(len(hip) * 0.7))


def clasificar_stt(referencia: str, hipotesis: str | None, *,
                   error_motor: bool = False, error_captura: bool = False,
                   sin_voz: bool = False) -> str:
    """Categoría automática de una intervención (el operador puede corregirla)."""
    if error_captura:
        return "fallo_captura"
    if sin_voz:
        return "sin_voz"
    if error_motor:
        return "fallo_motor"
    if hipotesis is None or not hipotesis.strip():
        return "transcripcion_vacia"
    errores, _ = errores_de_palabra(referencia, hipotesis)
    if errores == 0:
        return "correcta"
    if parece_cortada(referencia, hipotesis):
        return "corte_prematuro"
    return "error_reconocimiento"


def intervalo_wilson(exitos: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confianza del 95 % de una proporción.

    Es la respuesta a «30 sin errores demuestran fiabilidad perfecta»: con
    0 fallos en 30, la tasa real de fallo puede llegar a ~11 %.
    """
    if total <= 0:
        return 0.0, 1.0
    p = exitos / total
    denominador = 1 + z * z / total
    centro = (p + z * z / (2 * total)) / denominador
    margen = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) \
        / denominador
    return max(0.0, centro - margen), min(1.0, centro + margen)


# ------------------------------------------------------------------ B3: VAD
PAUSAS_B3 = (0.3, 0.5, 0.8, 1.2)
# Umbrales de cierre que se comparan con las mismas grabaciones: el vigente
# (0,6 s) y tres alternativas. Elegir entre ellos es lo que la tabla permite.
SILENCIOS_B3 = (0.6, 0.8, 1.0, 1.2)
# Cinco frases partidas en dos mitades: 5 frases × 4 pausas = 20
# intervenciones controladas por cada umbral.
GUION_VAD: tuple[tuple[str, str], ...] = (
    ("Estaba pensando", "que quizá mañana salga a correr."),
    ("Primero quiero contarte algo", "y luego te pregunto una cosa."),
    ("No sé muy bien", "cómo empezar a contarte esto."),
    ("Bueno, lo que quería decir", "es que hoy estoy bastante bien."),
    ("Creo que sí", "pero déjame pensarlo un momento."),
)
SEGUNDOS_BLOQUE = 0.05   # el mismo bloque que usa la captura real


@dataclass
class ResultadoPausa:
    pausa_s: float
    silencio_final_s: float
    corte_prematuro: bool       # se cerró el turno DURANTE la pausa
    intervencion_completa: bool  # se cerró después del final de la 2.ª parte
    cierre_desde_ultima_voz_s: float | None  # solo si quedó completa
    sin_voz: bool = False
    # Lo que habría llegado al STT, en memoria y solo para transcribir.
    pcm_recortado: bytes = b""


def _bloques(pcm: bytes, frecuencia: int) -> list[bytes]:
    tam = int(frecuencia * SEGUNDOS_BLOQUE) * senal.ANCHO_MUESTRA
    return [pcm[i:i + tam] for i in range(0, len(pcm) - tam + 1, tam)]


def _repetir_hasta(pcm: bytes, segundos: float, frecuencia: int) -> bytes:
    necesarios = int(segundos * frecuencia) * senal.ANCHO_MUESTRA
    if not pcm:
        return b"\x00" * necesarios
    veces = necesarios // len(pcm) + 1
    return (pcm * veces)[:necesarios]


def simular_pausa(voz_a: bytes, voz_b: bytes, ruido: bytes, pausa_s: float,
                  frecuencia: int, ajustes_audio,
                  silencio_final_s: float | None = None) -> ResultadoPausa:
    """Pasa por el detector real una intervención con una pausa exacta.

    La señal es: ruido (asentamiento + calibración + 0,5 s) · voz A · ruido
    durante `pausa_s` · voz B · ruido 3 s. Como la verdad es conocida —B es
    la continuación de A—, cualquier cierre durante la pausa es un corte
    prematuro y no una intervención nueva. Es lo que la métrica rechazada
    («volvió a hablar en menos de 1,5 s») no podía distinguir.

    El ruido de la pausa es ruido real de la sala, no ceros: un silencio
    digital perfecto haría el detector más fácil de lo que es.
    """
    silencio = (ajustes_audio.silencio_final_s if silencio_final_s is None
                else silencio_final_s)
    detector = DetectorVoz(
        segundos_bloque=SEGUNDOS_BLOQUE,
        ms_asentamiento=ajustes_audio.ms_asentamiento,
        ms_calibracion=ajustes_audio.ms_calibracion,
        factor_umbral=ajustes_audio.factor_umbral,
        piso_umbral_rms=float(ajustes_audio.piso_umbral_rms),
        histeresis=ajustes_audio.histeresis,
        bloques_confirmacion=ajustes_audio.bloques_confirmacion,
        silencio_final_s=silencio,
    )
    previo_s = (ajustes_audio.ms_asentamiento + ajustes_audio.ms_calibracion) \
        / 1000.0 + 0.5
    tramos = [
        _repetir_hasta(ruido, previo_s, frecuencia),
        voz_a,
        _repetir_hasta(ruido, pausa_s, frecuencia),
        voz_b,
        _repetir_hasta(ruido, 3.0, frecuencia),
    ]
    bloques_tramo = [len(_bloques(t, frecuencia)) for t in tramos]
    # Se alinean los tramos a bloques enteros para que los índices cuadren.
    pcm = b"".join(t[:n * int(frecuencia * SEGUNDOS_BLOQUE) * senal.ANCHO_MUESTRA]
                   for t, n in zip(tramos, bloques_tramo))
    inicio_b = sum(bloques_tramo[:3])
    fin_b = inicio_b + bloques_tramo[3]

    bloques = _bloques(pcm, frecuencia)
    cierre: int | None = None
    for indice, bloque in enumerate(bloques):
        if detector.procesar(bloque, indice * SEGUNDOS_BLOQUE):
            cierre = indice
            break

    if not detector.detecto_voz:
        return ResultadoPausa(pausa_s, silencio, False, False, None, sin_voz=True)

    if cierre is None:            # nunca cerró: se trata como fin de grabación
        cierre = len(bloques) - 1
    corte = cierre < inicio_b
    completa = cierre >= fin_b
    desde = None
    if completa and detector.indice_ultima_voz is not None:
        desde = (cierre - detector.indice_ultima_voz) * SEGUNDOS_BLOQUE

    pre = max(0, round(PRE_VOZ_S / SEGUNDOS_BLOQUE))
    cola = max(0, round(ajustes_audio.margen_cola_s / SEGUNDOS_BLOQUE))
    primera = detector.indice_primera_voz or 0
    ultima = detector.indice_ultima_voz if detector.indice_ultima_voz is not None \
        else cierre
    recortado = b"".join(bloques[max(0, primera - pre):ultima + cola + 1])
    return ResultadoPausa(pausa_s, silencio, corte, completa, desde,
                          pcm_recortado=recortado)


def recortar_a_voz(pcm: bytes, frecuencia: int, ruido_rms: float,
                   piso_rms: float = 120.0, factor: float = 1.5) -> bytes:
    """Recorta el silencio inicial y final de una grabación por energía.

    Deliberadamente independiente del detector que se evalúa: si el corte de
    las mitades lo hiciera el propio VAD, se mediría con la misma vara que se
    quiere medir. Umbral: el mayor entre el piso y `factor` × ruido de sala.
    Así la pausa insertada entre dos mitades es exactamente la pedida.
    """
    umbral = max(piso_rms, ruido_rms * factor)
    bloques = _bloques(pcm, frecuencia)
    con_voz = [i for i, b in enumerate(bloques) if senal.rms(b) >= umbral]
    if not con_voz:
        return b""
    return b"".join(bloques[con_voz[0]:con_voz[-1] + 1])


def tabla_pausas(resultados: list[ResultadoPausa]) -> list[dict]:
    """Agrega por (silencio_final_s, pausa): n, cortes, tasa e IC 95 %."""
    grupos: dict[tuple[float, float], list[ResultadoPausa]] = {}
    for r in resultados:
        grupos.setdefault((r.silencio_final_s, r.pausa_s), []).append(r)
    filas = []
    for (silencio, pausa), lista in sorted(grupos.items()):
        validos = [r for r in lista if not r.sin_voz]
        cortes = sum(r.corte_prematuro for r in validos)
        cierres = [r.cierre_desde_ultima_voz_s for r in validos
                   if r.cierre_desde_ultima_voz_s is not None]
        bajo, alto = intervalo_wilson(cortes, len(validos))
        filas.append({
            "silencio_final_s": silencio,
            "pausa_s": pausa,
            "n": len(validos),
            "sin_voz": len(lista) - len(validos),
            "cortes": cortes,
            "tasa_corte": cortes / len(validos) if validos else 0.0,
            "ic95_bajo": bajo,
            "ic95_alto": alto,
            "cierre_mediano_s": sorted(cierres)[len(cierres) // 2] if cierres else None,
        })
    return filas


def voz_sintetica(segundos: float, frecuencia: int = 16000,
                  semilla: int = 7, amplitud: int = 2500) -> bytes:
    """Señal de prueba con forma de habla: sílabas de ruido modulado.

    SOLO para comprobar que el instrumento funciona. No es voz humana y lo
    que se mida con ella no dice nada de cómo habla una persona.
    Incluye microcaídas entre sílabas (~60 ms), como el habla real.
    """
    azar = random.Random(semilla)
    total = int(segundos * frecuencia)
    muestras = array("h")
    t = 0
    while t < total:
        silaba = int(frecuencia * azar.uniform(0.12, 0.22))
        hueco = int(frecuencia * azar.uniform(0.02, 0.06))
        for k in range(min(silaba, total - t)):
            envolvente = math.sin(math.pi * k / silaba)
            muestras.append(int(azar.gauss(0, 1) * amplitud * envolvente))
        t += silaba
        for _ in range(min(hueco, max(0, total - t))):
            muestras.append(int(azar.gauss(0, 40)))
        t += hueco
    return muestras[:total].tobytes()


def ruido_sintetico(segundos: float, frecuencia: int = 16000,
                    semilla: int = 3, amplitud: float = 40.0) -> bytes:
    azar = random.Random(semilla)
    return array("h", (int(azar.gauss(0, amplitud))
                       for _ in range(int(segundos * frecuencia)))).tobytes()


__all__ = [
    "CATEGORIAS_STT", "GUION_STT", "PAUSAS_B3", "ResultadoPausa",
    "clasificar_stt", "errores_de_palabra", "intervalo_wilson",
    "parece_cortada", "recortar_a_voz", "ruido_sintetico", "simular_pausa",
    "tabla_pausas", "GUION_VAD",
    "voz_sintetica", "Fase",
]
