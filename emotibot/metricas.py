"""Instrumentación de latencia por etapas.

Motivo: el número que el usuario siente es el tiempo desde que deja de hablar
hasta que oye el primer sonido. Las versiones 0.5–0.6.2 imprimían
"respuesta disponible", medido ANTES de sintetizar, y marcaban el rostro como
HABLANDO antes de que `aplay` recibiera un solo byte. El tramo de síntesis no
se medía en ningún punto, así que la pantalla reportaba siempre menos de lo
que el usuario percibía.

Aquí cada etapa se marca por separado y `t_primer_sonido` se toma en el
instante real en que el altavoz recibe el primer bloque de PCM.

PRIVACIDAD: este módulo guarda únicamente marcas de tiempo, el proveedor y el
modelo. Nunca escribe transcripciones ni texto de las respuestas.
"""
from __future__ import annotations

import csv
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import registro, rutas

log = registro.obtener("metricas")

COLUMNAS = (
    "marca_tiempo",
    "modo_captura",
    "t_captura",
    "t_primera_voz",
    "t_voz_util",
    "t_stt",
    "t_ia",
    "t_sintesis",
    "t_primer_sonido",
    "t_total",
    "bytes_audio",
    "proveedor",
    "modelo",
    "resultado",
    # Fase 1, A2/A3. Columnas añadidas AL FINAL: un CSV de la v1.7 se migra
    # rellenándolas vacías (ver Bitacora._migrar_cabecera).
    "motivo_fin",
    "recortada",
    "tokens_entrada",
    "tokens_salida",
    # Fase 1, B5: ruta de longitud y número de palabras (nunca el texto).
    "papel",
    "palabras_respuesta",
)


@dataclass
class Medicion:
    """Marcas de una interacción. Todos los tiempos en segundos."""

    modo_captura: str = "automatico"
    t_captura: float = 0.0        # duración total de la grabación
    t_primera_voz: float = 0.0    # desde abrir el micrófono hasta detectar voz
    t_voz_util: float = 0.0       # duración del audio tras recortar silencios
    t_stt: float = 0.0            # reconocimiento de voz
    t_ia: float = 0.0             # consulta al proveedor
    t_sintesis: float = 0.0       # hasta tener el primer bloque de audio listo
    t_primer_sonido: float = 0.0  # desde la última voz hasta el primer sonido
    t_total: float = 0.0          # desde la última voz hasta terminar de hablar
    bytes_audio: int = 0
    proveedor: str = ""
    modelo: str = ""
    resultado: str = "ok"
    motivo_fin: str = ""            # completa | truncada | filtrada | otro | ""
    recortada: bool = False
    tokens_entrada: int | None = None
    tokens_salida: int | None = None
    papel: str = ""
    palabras_respuesta: int = 0

    _origen: float = field(default_factory=time.monotonic, repr=False)
    _ultima_voz: float | None = field(default=None, repr=False)

    def marcar_ultima_voz(self, instante: float | None = None) -> None:
        self._ultima_voz = instante if instante is not None else time.monotonic()

    def desde_ultima_voz(self) -> float:
        if self._ultima_voz is None:
            return 0.0
        return time.monotonic() - self._ultima_voz

    def registrar_primer_sonido(self) -> None:
        if self.t_primer_sonido == 0.0:
            self.t_primer_sonido = self.desde_ultima_voz()

    def cerrar(self) -> None:
        if self.t_total == 0.0:
            self.t_total = self.desde_ultima_voz()

    def resumen_corto(self) -> str:
        return (
            f"voz {self.t_voz_util:.1f}s · STT {self.t_stt:.1f}s · "
            f"IA {self.t_ia:.1f}s · voz {self.t_sintesis:.1f}s · "
            f"1.er sonido {self.t_primer_sonido:.1f}s"
        )

    def como_fila(self) -> dict[str, object]:
        return {
            "marca_tiempo": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "modo_captura": self.modo_captura,
            "t_captura": round(self.t_captura, 3),
            "t_primera_voz": round(self.t_primera_voz, 3),
            "t_voz_util": round(self.t_voz_util, 3),
            "t_stt": round(self.t_stt, 3),
            "t_ia": round(self.t_ia, 3),
            "t_sintesis": round(self.t_sintesis, 3),
            "t_primer_sonido": round(self.t_primer_sonido, 3),
            "t_total": round(self.t_total, 3),
            "bytes_audio": self.bytes_audio,
            "proveedor": self.proveedor,
            "modelo": self.modelo,
            "resultado": self.resultado,
            "motivo_fin": self.motivo_fin,
            "recortada": "1" if self.recortada else "",
            "tokens_entrada": "" if self.tokens_entrada is None else self.tokens_entrada,
            "tokens_salida": "" if self.tokens_salida is None else self.tokens_salida,
            "papel": self.papel,
            "palabras_respuesta": self.palabras_respuesta or "",
        }


class Bitacora:
    """Escribe las mediciones a CSV para poder comparar antes y después."""

    def __init__(self, ruta: Path | None = None) -> None:
        self.ruta = ruta or rutas.ARCHIVO_LATENCIA
        self._cabecera_revisada = False

    def _migrar_cabecera(self) -> None:
        """Si el CSV tiene la cabecera de una versión anterior, la amplía.

        Sin esto, las filas nuevas (con más columnas) quedarían desalineadas
        bajo la cabecera vieja. Se reescribe el archivo conservando todas las
        filas, con las columnas nuevas vacías. Se hace una sola vez.
        """
        self._cabecera_revisada = True
        if not self.ruta.is_file():
            return
        with self.ruta.open(newline="", encoding="utf-8") as origen:
            lector = csv.DictReader(origen)
            cabecera = tuple(lector.fieldnames or ())
            if cabecera == COLUMNAS or not cabecera:
                return
            filas = list(lector)
        temporal = self.ruta.with_suffix(".csv.migrando")
        with temporal.open("w", newline="", encoding="utf-8") as destino:
            escritor = csv.DictWriter(destino, fieldnames=list(COLUMNAS),
                                      extrasaction="ignore")
            escritor.writeheader()
            for fila in filas:
                escritor.writerow({c: fila.get(c, "") or "" for c in COLUMNAS})
        temporal.replace(self.ruta)
        log.info("latencia.csv migrado a la cabecera de la Fase 1 (%d filas).",
                 len(filas))

    def anotar(self, medicion: Medicion) -> None:
        try:
            rutas.asegurar_directorio(self.ruta.parent)
            if not self._cabecera_revisada:
                self._migrar_cabecera()
            nuevo = not self.ruta.exists()
            with self.ruta.open("a", newline="", encoding="utf-8") as destino:
                escritor = csv.DictWriter(destino, fieldnames=list(COLUMNAS))
                if nuevo:
                    escritor.writeheader()
                escritor.writerow(medicion.como_fila())
        except OSError as exc:
            log.warning("No pude anotar la medición: %s", exc)


def _percentil(valores: list[float], fraccion: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    indice = min(len(ordenados) - 1, max(0, round(fraccion * (len(ordenados) - 1))))
    return ordenados[indice]


def resumir(filas: Iterable[dict[str, str]]) -> str:
    """Mediana y p90 por etapa, que es la forma honesta de reportar latencia."""
    datos: dict[str, list[float]] = {}
    total = 0
    truncadas = recortadas = con_motivo = 0
    for fila in filas:
        total += 1
        motivo = (fila.get("motivo_fin") or "").strip()
        if motivo:
            con_motivo += 1
        if motivo == "truncada":
            truncadas += 1
        if (fila.get("recortada") or "").strip() == "1":
            recortadas += 1
        for columna in COLUMNAS:
            if not columna.startswith("t_"):
                continue
            try:
                datos.setdefault(columna, []).append(float(fila[columna]))
            except (KeyError, TypeError, ValueError):
                continue
    if not total:
        return "Sin mediciones todavía."

    lineas = [f"Interacciones medidas: {total}", "", 
              f"{'etapa':<18}{'mediana':>10}{'p90':>10}"]
    for columna, valores in datos.items():
        if not valores:
            continue
        lineas.append(
            f"{columna:<18}{statistics.median(valores):>9.2f}s"
            f"{_percentil(valores, 0.9):>9.2f}s"
        )
    lineas.append("")
    if con_motivo:
        lineas.append(
            f"Truncadas: {truncadas} de {con_motivo} respuestas con motivo de "
            f"fin conocido ({recortadas} recortadas a la última frase).")
    lineas.append("t_primer_sonido es la única que el usuario percibe.")
    return "\n".join(lineas)


def leer_csv(ruta: Path | None = None) -> list[dict[str, str]]:
    archivo = ruta or rutas.ARCHIVO_LATENCIA
    if not archivo.is_file():
        return []
    try:
        with archivo.open(newline="", encoding="utf-8") as origen:
            return list(csv.DictReader(origen))
    except OSError as exc:
        log.warning("No pude leer %s: %s", archivo.name, exc)
        return []
