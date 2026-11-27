"""Dónde van los textos de la aplicación, sin salirse ni pisarse.

Antes cada texto tenía una altura fija. Medido en Tk real, con el detalle a
dos líneas y todos los textos visibles, se pisaban en todos los tamaños, y a
800 px de ancho la fila de teclas ocupaba dos líneas y tapaba las métricas.

Ahora se colocan con su tamaño REAL (el `bbox` del lienzo):
- arriba, el nombre y el creador, de arriba abajo, sin bajar del borde
  superior del rostro;
- abajo, apilados desde el borde inferior hacia arriba: controles, métricas,
  privacidad, depuración, detalle y estado, sin subir del borde inferior del
  rostro (las barras del micrófono incluidas).

Si una pila no cabe en su franja, sus letras se reducen poco a poco. Si ni
así cabe, se dejan de mostrar primero las métricas y después la fila de
teclas. El estado, el detalle, la privacidad y la depuración (B2: tiene que
verse que está activa) no se quitan nunca. Sin la fila de teclas
(`rostro.mostrar_controles: false`), lo demás baja hasta el borde: no queda
franja muerta.

Los límites del rostro los da `Cara.limites_verticales()`, que es fija para
cada tamaño de ventana: los textos no saltan cuando la cabeza se inclina ni
cuando aparecen las barras.
"""
from __future__ import annotations

ARRIBA = ("nombre", "creador")
ABAJO = ("estado", "detalle", "depuracion", "privacidad", "metricas", "controles")
# Tamaño de letra (fracción de min(ancho, alto)) y ancho máximo (del ancho).
TAMANO = {"nombre": 0.042, "creador": 0.019, "estado": 0.024, "detalle": 0.021,
          "depuracion": 0.018, "privacidad": 0.018, "metricas": 0.015,
          "controles": 0.015}
ANCHO_MAXIMO = {"nombre": 0.9, "creador": 0.9, "estado": 0.9, "detalle": 0.86,
                "depuracion": 0.9, "privacidad": 0.9, "metricas": 0.9,
                "controles": 0.96}
PRESCINDIBLES = ("controles", "metricas")      # en este orden, si no cabe
# Hasta dónde se reduce la letra antes de quitar la fila de teclas, antes de
# quitar las métricas (donde va el aviso de crisis.json) y como último recurso.
PISO_LETRA = (0.75, 0.6, 0.45)
MARGEN = 0.012                                 # del alto, en cada borde
HUECO = 0.006                                  # del alto, entre textos y con el rostro
LETRA_MINIMA = 8
FUENTE = "DejaVu Sans"


def _colocar_pila(lienzo, items, contenidos, claves, ancho, alto, escala, desde_abajo,
                  limite, factor):
    """Coloca una pila; devuelve {clave: bbox} y el borde alcanzado."""
    cajas = {}
    y = alto * (1 - MARGEN) if desde_abajo else alto * MARGEN
    for clave in (reversed(claves) if desde_abajo else claves):
        texto, color = contenidos[clave]
        item = items[clave]
        lienzo.coords(item, ancho / 2, y)
        lienzo.itemconfigure(
            item, text=texto, fill=color, state="normal",
            anchor="s" if desde_abajo else "n", justify="center",
            font=(FUENTE, max(LETRA_MINIMA, int(escala * TAMANO[clave] * factor))),
            width=int(ancho * ANCHO_MAXIMO[clave]))
        caja = lienzo.bbox(item)
        cajas[clave] = caja
        y = (caja[1] - alto * HUECO) if desde_abajo else (caja[3] + alto * HUECO)
    borde = y + alto * HUECO if desde_abajo else y - alto * HUECO
    return cajas, borde


def colocar(lienzo, items: dict, contenidos: dict, ancho: int, alto: int,
            limites: tuple[float, float] | None) -> dict:
    """Coloca los textos visibles y oculta el resto.

    `contenidos`: {clave: (texto, color)} de los textos que deben verse; los
    vacíos no ocupan sitio. `limites`: (arriba, abajo) del rostro, o None sin
    carcasa (entonces solo puede haber depuración, arriba del todo).
    Devuelve {clave: bbox} de lo que quedó visible.
    """
    escala = min(ancho, alto)
    visibles = {k: v for k, v in contenidos.items() if v[0]}
    for clave, item in items.items():
        if clave not in visibles:
            lienzo.itemconfigure(item, state="hidden")
    if limites is None:
        cajas, _ = _colocar_pila(lienzo, items, visibles, [k for k in ARRIBA + ABAJO
                                                         if k in visibles],
                                 ancho, alto, escala, False, alto, 1.0)
        return cajas

    arriba, abajo = limites
    resultado = {}
    for claves_base, desde_abajo, limite in (
            ([k for k in ARRIBA if k in visibles], False, arriba - alto * HUECO),
            ([k for k in ABAJO if k in visibles], True, abajo + alto * HUECO)):
        claves = list(claves_base)
        # Primero se reduce la letra hasta un suelo legible; si no basta, se
        # quita lo prescindible (teclas, luego métricas) y se vuelve a probar
        # desde el tamaño completo, con un suelo algo más bajo.
        for fase, suelo in enumerate(PISO_LETRA):
            if fase > 0:
                quitables = [k for k in PRESCINDIBLES if k in claves]
                if quitables:
                    claves.remove(quitables[0])
                    lienzo.itemconfigure(items[quitables[0]], state="hidden")
            factor = 1.0
            while True:
                cajas, borde = _colocar_pila(lienzo, items, visibles, claves, ancho, alto,
                                             escala, desde_abajo, limite, factor)
                cabe = borde >= limite if desde_abajo else borde <= limite
                if cabe or factor * 0.95 < suelo:
                    break
                factor *= 0.95
            if cabe:
                break
        resultado.update(cajas)
    return resultado
