"""Perfil de rostro: proporciones y colores del dibujo, como DATOS.

Todo lo que define cómo se ve la cara —tamaños, posiciones, grosores y
colores— vive en un archivo `config/rostro/<nombre>.json`. El código de
`cara.py` solo sabe dibujar; no lleva ni una proporción escrita.

Así, una variante de diseño (D10) es un archivo de datos y no código nuevo:
se copia `hybrid_balanced.json`, se cambian los valores y se pone su nombre
en `rostro.perfil` de `config/ajustes.json`.

La carga es estricta: si falta un valor, sobra uno o tiene un tipo que no
toca, el perfil se rechaza con un mensaje que dice cuál. Un perfil a medias
dibujaría una cara rota sin avisar.

Unidades (ver cada sección del JSON):
- `cabeza`: fracciones de la ventana (`*_ventana`, `centro_bloque_y`) o de
  min(ancho, alto) (`*_escala`, `marco`, `oreja_ancho`); `tamano` multiplica
  la cabeza entera.
- `sin_carcasa`: el reparto del área cuando no se dibuja la cabeza.
- `rasgos`, `ojos`, `boca`, `onda`…: fracciones de la «cabeza equivalente»
  (ver cara.py) o de la medida del propio rasgo; los grosores, de la unidad
  de trazo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path

from .. import rutas
from .paleta import Paleta

DIRECTORIO = rutas.CONFIG_REPO / "rostro"
POR_DEFECTO = "hybrid_balanced"


class ErrorPerfil(ValueError):
    pass


@dataclass(frozen=True)
class Cabeza:
    ancho_max_ventana: float
    ancho_max_escala: float
    alto_max_ventana: float
    alto_max_escala: float
    tamano: float
    centro_bloque_y: float
    marco: float
    radio: float
    pantalla_sobre_cabeza_ancho: float
    pantalla_sobre_cabeza_alto: float
    aspecto: float
    alto_sobre_unidad: float
    oreja_ancho: float
    oreja_alto: float
    oreja_solape: float


@dataclass(frozen=True)
class SinCarcasa:
    margen: float
    extension_v: float
    anisotropia: float
    lado_rasgo: float
    escala_max: float
    centro_v: float


@dataclass(frozen=True)
class Rasgos:
    separacion_ojos: float
    ojo_ancho: float
    ojo_alto: float
    y_ojos: float
    y_ceja: float
    y_boca: float
    boca_ancho: float


@dataclass(frozen=True)
class Ojos:
    radio: float
    borde: float
    alto_minimo: float
    mirada_x: float
    mirada_y: float
    brillo_radio: float
    brillo_x: float
    brillo_y: float
    punto_radio: float
    punto_x: float
    punto_y: float


@dataclass(frozen=True)
class Alegria:
    umbral_apertura: float
    altura: float
    altura_cierre: float
    bajada: float
    ancho: float
    grosor: float


@dataclass(frozen=True)
class Cejas:
    """`ceno`: cuánto del ángulo NEGATIVO de estados.py (extremo interior
    abajo) se dibuja como inclinación. 1 lo dibuja entero; 0, nada. El
    interior abajo es la ceja del enfado: en rejilla de píxeles se vuelve un
    escalón que se lee como rabia (sondeo del 27-11-2026, tele)."""
    largo: float
    grosor: float
    curva: float
    subida: float
    giro: float
    intensidad: float
    ceno: float


@dataclass(frozen=True)
class SinCejas:
    """Un rostro SIN cejas tiene un canal de expresión menos. Lo que la ceja
    decía (`ceja_angulo` de estados.py, el mismo dato para todos) se dice
    con la forma del ojo, para que «preocupado» y «curioso» se sigan
    distinguiendo entre sí y del reposo:
    - ángulo POSITIVO (interior arriba: preocupación): un párpado del color
      de la pantalla tapa la parte de arriba del ojo, más por fuera que por
      dentro (ojo caído), y el ojo se achata;
    - ángulo NEGATIVO (curiosidad): un ojo crece y el otro mengua, hacia
      donde mira. Solo a partir de `umbral_curiosidad` grados, para que la
      atención de «te escucho» (−7°) no se lea como curiosidad.
    Fracciones del alto del ojo, en el ángulo pleno."""
    angulo_pleno: float
    parpado_exterior: float
    parpado_interior: float
    achatado: float
    umbral_curiosidad: float
    curiosidad_plena: float
    asimetria: float


@dataclass(frozen=True)
class Boca:
    apertura: float
    grosor: float
    ensanche_sonrisa: float
    curva: float
    radio: float
    arriba: float
    abajo: float
    interior_hacia_fondo: float
    borde: float


@dataclass(frozen=True)
class Barras:
    """Barras del micrófono. Tamaños en unidades de trazo; colores, nombres
    de la paleta (degradado del centro a los extremos)."""
    numero: int
    ancho: float
    separacion: float
    alto_minimo: float
    alto_maximo: float
    hueco: float
    escala_sin_carcasa: float
    margen_inferior_sin_carcasa: float
    color_centro: str
    color_extremos: str


@dataclass(frozen=True)
class Destellos:
    tamano: float
    carcasa_radio_x: float
    carcasa_radio_y: float
    ojo_radio_x: float
    ojo_radio_y: float


TIPOS_MUEBLE = ("cabeza", "tele", "capsula")
ESTILOS_TRAZO = ("lineas", "pixeles", "redondo")


@dataclass(frozen=True)
class Mueble:
    """Lo que rodea a la pantalla con carcasa. «cabeza» es la de
    hybrid_balanced, que gira y respira con la cara; «tele» y «capsula» son
    muebles ESTÁTICOS (rostro/muebles.py): se dibujan al crear la cara y no
    se vuelven a tocar. Fracciones del mueble (ancho y alto) salvo `radio`,
    `antena` y `zocalo`, que son fracciones del alto del mueble, y
    `radio_pantalla`, del alto de la pantalla."""
    tipo: str
    proporcion: float           # ancho / alto del mueble
    pantalla_x0: float
    pantalla_x1: float
    pantalla_y0: float
    pantalla_y1: float
    radio: float
    radio_pantalla: float
    bandas: int                 # franjas del degradado del mueble
    antena: float               # lo que asoman las antenas por encima
    zocalo: float               # lo que baja el zócalo por debajo


@dataclass(frozen=True)
class Trazo:
    """Cómo se dibujan ojos, cejas y boca. La GRAMÁTICA (qué significa cada
    ángulo, apertura y curva) es la misma en los tres; esto es solo aspecto.
    - lineas: contorno suave (hybrid_balanced);
    - pixeles: bloques en una rejilla de lado `pixel` × alto de referencia,
      con el brillo del ojo cuadrado (tele);
    - redondo: ojos macizos y boca de guion redondeado (cápsula)."""
    estilo: str
    pixel: float


@dataclass(frozen=True)
class PerfilRostro:
    nombre: str
    descripcion: str
    colores: Paleta
    cabeza: Cabeza
    sin_carcasa: SinCarcasa
    rasgos: Rasgos
    ojos: Ojos
    alegria: Alegria
    cejas: Cejas | None         # None: rostro sin cejas (canal ausente)
    sin_cejas: SinCejas | None  # cómo se dice la ceja sin ella; solo si cejas es None
    boca: Boca
    barras: Barras
    destellos: Destellos
    mueble: Mueble
    trazo: Trazo


def _construir(tipo, datos, donde: str):
    if not isinstance(datos, dict):
        raise ErrorPerfil(f"{donde}: se esperaba una sección, no {type(datos).__name__}")
    # Las claves que empiezan por «_» son notas para personas.
    datos = {k: v for k, v in datos.items() if not k.startswith("_")}
    esperados = {f.name: f for f in fields(tipo)}
    faltan = sorted(set(esperados) - set(datos))
    sobran = sorted(set(datos) - set(esperados))
    if faltan or sobran:
        raise ErrorPerfil(f"{donde}: faltan {faltan or 'ninguno'}; sobran {sobran or 'ninguno'}")
    valores = {}
    for nombre, campo in esperados.items():
        valor, sitio = datos[nombre], f"{donde}.{nombre}"
        tipo_campo = campo.type
        if isinstance(tipo_campo, str) and tipo_campo.endswith(" | None"):
            # Sección opcional: tiene que estar, pero puede valer null.
            if valor is None:
                valores[nombre] = None
                continue
            tipo_campo = tipo_campo[:-len(" | None")].strip()
        subtipo = tipo_campo if not isinstance(tipo_campo, str) else _TIPOS.get(tipo_campo)
        if subtipo is not None and is_dataclass(subtipo):
            valores[nombre] = _construir(subtipo, valor, sitio)
        elif campo.type in ("int", int):
            if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
                raise ErrorPerfil(f"{sitio}: debe ser un entero positivo")
            valores[nombre] = valor
        elif campo.type in ("float", float):
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                raise ErrorPerfil(f"{sitio}: debe ser un número")
            valores[nombre] = float(valor)
        else:
            if not isinstance(valor, str) or not valor:
                raise ErrorPerfil(f"{sitio}: debe ser un texto")
            if tipo is Paleta and not (valor.startswith("#") and len(valor) in (4, 7)):
                raise ErrorPerfil(f"{sitio}: debe ser un color #rrggbb")
            if nombre.startswith("color_") and valor not in {f.name for f in fields(Paleta)}:
                raise ErrorPerfil(f"{sitio}: debe ser un color de la paleta del perfil")
            valores[nombre] = valor
    return tipo(**valores)


_TIPOS = {c.__name__: c for c in (Paleta, Cabeza, SinCarcasa, Rasgos, Ojos, Alegria,
                                  Cejas, SinCejas, Boca, Barras, Destellos, Mueble, Trazo)}


def ruta(nombre: str) -> Path:
    if not nombre or any(c in nombre for c in "/\\.") :
        raise ErrorPerfil(f"Nombre de perfil no válido: {nombre!r}")
    return DIRECTORIO / f"{nombre}.json"


def leer(archivo: Path) -> PerfilRostro:
    try:
        datos = json.loads(Path(archivo).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErrorPerfil(f"No existe el perfil de rostro {archivo}") from None
    except json.JSONDecodeError as exc:
        raise ErrorPerfil(f"{archivo}: JSON no válido ({exc})") from None
    perfil = _construir(PerfilRostro, datos, Path(archivo).stem)
    m, t, sitio = perfil.mueble, perfil.trazo, Path(archivo).stem
    if m.tipo not in TIPOS_MUEBLE:
        raise ErrorPerfil(f"{sitio}.mueble.tipo: {m.tipo!r}; vale {', '.join(TIPOS_MUEBLE)}")
    if t.estilo not in ESTILOS_TRAZO:
        raise ErrorPerfil(f"{sitio}.trazo.estilo: {t.estilo!r}; vale {', '.join(ESTILOS_TRAZO)}")
    if not (0 <= m.pantalla_x0 < m.pantalla_x1 <= 1 and 0 <= m.pantalla_y0 < m.pantalla_y1 <= 1):
        raise ErrorPerfil(f"{sitio}.mueble: la pantalla va dentro del mueble (fracciones 0-1)")
    if t.estilo == "pixeles" and t.pixel <= 0:
        raise ErrorPerfil(f"{sitio}.trazo.pixel: debe ser positivo con estilo «pixeles»")
    if (perfil.cejas is None) == (perfil.sin_cejas is None):
        raise ErrorPerfil(f"{sitio}: o hay «cejas» o hay «sin_cejas» (la otra, null)")
    return perfil


_cache: dict[str, PerfilRostro] = {}


def cargar(nombre: str = POR_DEFECTO) -> PerfilRostro:
    """El perfil `config/rostro/<nombre>.json`, validado (se carga una vez)."""
    if nombre not in _cache:
        _cache[nombre] = leer(ruta(nombre))
    return _cache[nombre]
