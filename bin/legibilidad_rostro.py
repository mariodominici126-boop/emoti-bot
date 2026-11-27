#!/usr/bin/env python3
"""C4 — Prueba de legibilidad de expresiones con personas ajenas al proyecto.

INSTRUMENTO. La prueba la organiza el responsable; este script no produce
ningún resultado sin participantes.

Diseño (27-11-2026, con los tres rostros actuales):
- Láminas de hybrid_balanced, tele y capsula, SIN etiqueta, con códigos
  neutrales. Cada participante ve UN solo rostro, asignado por turnos según
  su código (P01 → el primero, P02 → el segundo, P03 → el tercero, P04 →
  otra vez el primero…): así nadie compara rostros entre sí.
- Seis expresiones por rostro (siete hasta el 27-11-2026: «curioso» se
  quitó y el criterio de c4_umbral.json se lee sobre seis). «hablando» y las de respiración NO entran:
  hablar es la boca moviéndose con el audio y la respiración es la cara
  creciendo y menguando en el tiempo; en una imagen quieta no se ve ninguna
  de las dos y se acertarían o fallarían por otra cosa.
- Las respuestas son palabras corrientes («tranquilo», «algo va mal»…), no
  los nombres internos, y hay MÁS opciones que láminas: las seis, dos que
  no están en el set («enfadado» y «triste», para ver si se lee de más) y
  «no sé». Se pueden repetir: así no se resuelve por eliminación.

  preparar   Láminas, clave aparte, página local (prueba.html) que asigna el
             rostro por el código y descarga las respuestas en CSV, y hoja
             para hacerlo en papel.
  analizar   Comprueba que el umbral (config/c4_umbral.json, §13.8c) se fijó
             ANTES de la primera respuesta y lo aplica JUNTANDO los tres
             rostros por expresión (la gramática es común); además compara
             rostro contra rostro y cuenta las lecturas de más.

Todo en logs/legibilidad/tres_rostros/. La página no usa Internet ni guarda
nada por su cuenta. A cada participante se le identifica con un código,
nunca con su nombre.

Uso:
    .venv\\Scripts\\python.exe bin\\legibilidad_rostro.py preparar
    .venv\\Scripts\\python.exe bin\\legibilidad_rostro.py analizar
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import importlib.util
import io
import json
import math
import re
import secrets
import sys
import time
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
try:  # consola de Windows en cp1252: que se vean tildes y símbolos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from emotibot import rutas  # noqa: E402
from prototipos.rostro_pillow import legibilidad  # noqa: E402  (solo lectura)

DIRECTORIO = rutas.LOGS / "legibilidad" / "tres_rostros"
CLAVE = DIRECTORIO / "clave_NO_MIRAR.json"
RESPUESTAS = DIRECTORIO / "respuestas"
UMBRAL = rutas.CONFIG_REPO / "c4_umbral.json"

ROSTROS = ("hybrid_balanced", "tele", "capsula")
# Lo que se ve → (estado funcional, expresión) del robot, y su palabra.
EXPRESIONES: dict[str, tuple[tuple[str, str], str]] = {
    "reposo": (("reposo", "reposo"), "tranquilo"),
    "escuchando": (("escuchando", "escuchando"), "escuchando"),
    "pensando": (("pensando", "pensando"), "pensando"),
    "feliz": (("reposo", "feliz"), "contento"),
    "preocupado": (("reposo", "preocupado"), "preocupado"),
    "error": (("error", "error"), "algo va mal"),
}
FUERA = {"hablando": "es la boca moviéndose con el audio: quieta no se ve",
         "curioso": "se quitó el 27-11-2026 (sin el ámbar era «escuchando»); el conjunto pasa de 7 a 6",
         "respirando_inhalar/sostener/exhalar": "es la cara creciendo y menguando en el tiempo"}
DISTRACTORES = ("enfadado", "triste")
NO_SE = "no sé"
OPCIONES = tuple(etiqueta for _, etiqueta in EXPRESIONES.values()) + DISTRACTORES + (NO_SE,)


def rostro_de(participante: str) -> str:
    """El rostro que le toca, por turnos según el número de su código."""
    numero = re.search(r"\d+", participante or "")
    if not numero:
        raise ValueError(f"Código sin número: {participante!r} (se esperan P01, P02…)")
    return ROSTROS[(int(numero.group()) - 1) % len(ROSTROS)]


def hacer_clave() -> dict[str, dict]:
    """Un código neutral por lámina: no dice ni el rostro ni la expresión."""
    clave = {}
    for rostro in ROSTROS:
        for expresion, (_, etiqueta) in EXPRESIONES.items():
            codigo = f"L-{secrets.token_hex(2).upper()}"
            while codigo in clave:
                codigo = f"L-{secrets.token_hex(2).upper()}"
            clave[codigo] = {"rostro": rostro, "expresion": expresion, "correcta": etiqueta}
    return clave


# ------------------------------------------------------------------ análisis
def wilson(aciertos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = aciertos / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centro - margen), min(1.0, centro + margen)


def _resumen(respuestas: list[str], correcta: str, umbral: dict) -> dict:
    n = len(respuestas)
    cuenta = Counter(respuestas)
    aciertos = cuenta.get(correcta, 0)
    erroneas = [(r, c) for r, c in cuenta.most_common() if r != correcta]
    principal, veces = erroneas[0] if erroneas else ("", 0)
    acierto = aciertos / n if n else 0.0
    confusion = veces / n if n else 0.0
    return {
        "n": n, "acierto": acierto, "ic95": wilson(aciertos, n),
        "confusion_principal": principal, "confusion_principal_pct": confusion,
        "de_mas": {d: cuenta.get(d, 0) / n if n else 0.0 for d in DISTRACTORES},
        "no_se": cuenta.get(NO_SE, 0) / n if n else 0.0,
        "respuestas": dict(cuenta),
        "pasa": bool(n) and acierto >= umbral["acierto_minimo_por_expresion"]
        and confusion <= umbral["confusion_maxima_con_otra"],
    }


def analizar(filas: list[dict], clave: dict, umbral: dict) -> dict:
    """Junta por expresión (decide) y compara por rostro (informa)."""
    minimo = umbral["participantes_minimos"]
    avisos = []
    por_expresion: dict[str, list[str]] = {e: [] for e in EXPRESIONES}
    por_rostro: dict[str, dict[str, list[str]]] = {r: {e: [] for e in EXPRESIONES}
                                                   for r in ROSTROS}
    participantes: dict[str, set] = {r: set() for r in ROSTROS}
    for fila in filas:
        lamina = clave.get(fila["lamina"])
        if lamina is None:
            avisos.append(f"{fila['participante']}: lámina desconocida {fila['lamina']}")
            continue
        try:
            asignado = rostro_de(fila["participante"])
        except ValueError as exc:
            avisos.append(str(exc))
            continue
        if lamina["rostro"] != asignado:
            avisos.append(f"{fila['participante']} respondió una lámina de otro rostro: "
                          "se descarta (cada participante ve uno solo).")
            continue
        respuesta = fila["respuesta"].strip().lower()
        por_expresion[lamina["expresion"]].append(respuesta)
        por_rostro[lamina["rostro"]][lamina["expresion"]].append(respuesta)
        participantes[lamina["rostro"]].add(fila["participante"])
    total = sum(len(p) for p in participantes.values())
    juntas = {e: _resumen(r, EXPRESIONES[e][1], umbral) for e, r in por_expresion.items()}
    rostros = {}
    for rostro, expresiones in por_rostro.items():
        resumenes = {e: _resumen(r, EXPRESIONES[e][1], umbral) for e, r in expresiones.items()}
        n = sum(x["n"] for x in resumenes.values())
        aciertos = sum(round(x["acierto"] * x["n"]) for x in resumenes.values())
        rostros[rostro] = {"participantes": len(participantes[rostro]),
                           "suficientes": len(participantes[rostro]) >= minimo,
                           "acierto_global": aciertos / n if n else 0.0,
                           "ic95_global": wilson(aciertos, n), "expresiones": resumenes}
    # Rostro contra rostro: por expresión, la mayor diferencia de acierto y si
    # los intervalos de los extremos se separan (diferencia clara).
    comparacion = {}
    for expresion in EXPRESIONES:
        datos = {r: rostros[r]["expresiones"][expresion] for r in ROSTROS
                 if rostros[r]["expresiones"][expresion]["n"]}
        if len(datos) < 2:
            continue
        mejor = max(datos, key=lambda r: datos[r]["acierto"])
        peor = min(datos, key=lambda r: datos[r]["acierto"])
        comparacion[expresion] = {
            "acierto": {r: d["acierto"] for r, d in datos.items()},
            "mejor": mejor, "peor": peor,
            "diferencia": datos[mejor]["acierto"] - datos[peor]["acierto"],
            "clara": datos[peor]["ic95"][1] < datos[mejor]["ic95"][0]}
    suficientes = total >= minimo
    return {"participantes": total, "suficientes": suficientes,
            "umbral_provisional": bool(umbral.get("provisional")),
            "por_expresion": juntas,
            "pasan_todas": suficientes and all(e["pasa"] for e in juntas.values()),
            "por_rostro": rostros, "rostro_contra_rostro": comparacion,
            "fuera_del_set": FUERA, "avisos": avisos}


# ------------------------------------------------------------------ página
PAGINA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prueba de expresiones</title>
<style>
 :root {{ --fondo:#f3f6f9; --tinta:#1a2430; --boton:#ffffff; --borde:#c9d3de; --acento:#2b6cb0; }}
 body {{ margin:0; font:18px/1.4 system-ui,sans-serif; background:var(--fondo); color:var(--tinta); }}
 main {{ max-width:860px; margin:0 auto; padding:16px; }}
 img {{ width:100%; height:auto; border-radius:10px; display:block; }}
 .opciones {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:8px; margin-top:12px; }}
 button {{ font:inherit; padding:12px; border:1px solid var(--borde); border-radius:8px; background:var(--boton); cursor:pointer; }}
 button:hover {{ border-color:var(--acento); }}
 .oculto {{ display:none; }} .tenue {{ color:#5b6b7c; font-size:15px; }}
</style></head><body><main>
<section id="inicio">
 <h1>¿Qué expresa la cara?</h1>
 <p>Verás {n} imágenes de la cara de un robot, una a una. En cada una, elige la
 palabra que mejor describa lo que expresa. Puedes usar la misma palabra varias
 veces, y puede que alguna no sirva para ninguna imagen. No hay respuestas
 buenas ni malas: lo que se evalúa es el dibujo, no a ti. Si no lo tienes
 claro, elige «no sé».</p>
 <p><label>Código de participante (te lo dan; no pongas tu nombre):
 <input id="codigo" maxlength="8" size="8" autocomplete="off"></label></p>
 <button id="empezar">Empezar</button>
</section>
<section id="prueba" class="oculto">
 <p class="tenue" id="progreso"></p>
 <img id="lamina" alt="Cara del robot">
 <div class="opciones" id="opciones"></div>
</section>
<section id="fin" class="oculto">
 <h1>¡Gracias!</h1>
 <p>Pulsa el botón para descargar tus respuestas y entrégale el archivo a
 quien te pidió hacer la prueba.</p>
 <button id="descargar">Descargar respuestas</button>
</section>
</main>
<script>
const LAMINAS = {laminas};       // por rostro: {{rostro: {{codigo: imagen}}}}
const ROSTROS = {rostros};
const OPCIONES = {opciones};
let orden = [], i = 0, respuestas = [], t0 = 0, codigo = "", mias = {{}};
function barajar(a) {{ for (let k = a.length - 1; k > 0; k--) {{ const j = Math.floor(Math.random() * (k + 1)); [a[k], a[j]] = [a[j], a[k]]; }} return a; }}
function mostrar() {{
  if (i >= orden.length) {{ document.getElementById("prueba").classList.add("oculto"); document.getElementById("fin").classList.remove("oculto"); return; }}
  document.getElementById("progreso").textContent = `Imagen ${{i + 1}} de ${{orden.length}}`;
  document.getElementById("lamina").src = mias[orden[i]];
  t0 = performance.now();
}}
document.getElementById("empezar").onclick = () => {{
  codigo = document.getElementById("codigo").value.trim().replace(/[^A-Za-z0-9_-]/g, "");
  const numero = (codigo.match(/\\d+/) || [""])[0];
  if (!numero) {{ alert("Escribe el código que te dieron (P01, P02…)."); return; }}
  mias = LAMINAS[ROSTROS[(parseInt(numero, 10) - 1) % ROSTROS.length]];   // un solo rostro
  orden = barajar(Object.keys(mias));
  document.getElementById("inicio").classList.add("oculto");
  document.getElementById("prueba").classList.remove("oculto");
  const caja = document.getElementById("opciones");
  barajar(OPCIONES.slice(0, -1)).concat(OPCIONES.slice(-1)).forEach(o => {{
    const b = document.createElement("button"); b.textContent = o;
    b.onclick = () => {{ respuestas.push([codigo, orden[i], o, ((performance.now() - t0) / 1000).toFixed(1), i + 1]); i++; mostrar(); }};
    caja.appendChild(b); }});
  mostrar();
}};
document.getElementById("descargar").onclick = () => {{
  const csv = "participante,lamina,respuesta,segundos,posicion\\n" + respuestas.map(r => r.join(",")).join("\\n") + "\\n";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["\\ufeff" + csv], {{type: "text/csv"}}));
  a.download = `respuestas_${{codigo}}.csv`; a.click();
}};
</script></body></html>
"""


def _capturas():
    spec = importlib.util.spec_from_file_location("capturas_rostro",
                                                  RAIZ / "bin" / "capturas_rostro.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def preparar(argumentos, capturar=None) -> int:
    if CLAVE.exists() and not argumentos.sobrescribir:
        print(f"Ya hay una prueba preparada ({CLAVE}). Usa --sobrescribir para "
              "rehacerla, pero no a mitad de una ronda: los códigos cambiarían.")
        return 1
    if capturar is None:
        if sys.platform == "win32":
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                pass
        capturas = _capturas()
        ancho, alto = (int(v) for v in argumentos.tamano.lower().split("x"))

        def capturar(rostro, expresion):
            return capturas.captura_a(expresion, ancho, alto, not argumentos.sin_carcasa,
                                      rostro, estado=EXPRESIONES[expresion][0])
    clave = hacer_clave()
    laminas_dir = DIRECTORIO / "laminas"
    laminas_dir.mkdir(parents=True, exist_ok=True)
    incrustadas: dict[str, dict[str, str]] = {r: {} for r in ROSTROS}
    for codigo, destino in clave.items():
        imagen = capturar(destino["rostro"], destino["expresion"])
        imagen.save(laminas_dir / f"{codigo}.png")
        memoria = io.BytesIO()
        imagen.save(memoria, format="PNG", optimize=True)
        incrustadas[destino["rostro"]][codigo] = (
            "data:image/png;base64," + base64.b64encode(memoria.getvalue()).decode())
        print(f"  {codigo}")
    huella = hashlib.sha256(UMBRAL.read_bytes()).hexdigest() if UMBRAL.is_file() else ""
    legibilidad.guardar_json(CLAVE, {
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"), "tamano": argumentos.tamano,
        "carcasa": not argumentos.sin_carcasa, "rostros": list(ROSTROS),
        "opciones": list(OPCIONES), "umbral_sha256_al_preparar": huella, "clave": clave})
    (DIRECTORIO / "prueba.html").write_text(PAGINA.format(
        n=len(EXPRESIONES), laminas=json.dumps(incrustadas), rostros=json.dumps(ROSTROS),
        opciones=json.dumps(list(OPCIONES), ensure_ascii=False)), encoding="utf-8")
    # En papel: cada participante, solo las láminas de su rostro.
    lineas = ["participante,lamina,respuesta"]
    for numero in range(1, argumentos.participantes + 1):
        codigo_p = f"P{numero:02d}"
        lineas += [f"{codigo_p},{c}," for c, d in sorted(clave.items())
                   if d["rostro"] == rostro_de(codigo_p)]
    (DIRECTORIO / "hoja_registro_papel.csv").write_text(
        "﻿" + "\n".join(lineas) + "\n", encoding="utf-8")
    (DIRECTORIO / "opciones_papel.txt").write_text(
        "Opciones (se pueden repetir; alguna puede no servir para ninguna imagen):\n"
        + "\n".join(f"- {o}" for o in OPCIONES) + "\n", encoding="utf-8")
    RESPUESTAS.mkdir(parents=True, exist_ok=True)
    print(f"\nPágina de la prueba: {DIRECTORIO / 'prueba.html'}")
    print(f"Clave (no la mires hasta cerrar la prueba): {CLAVE}")
    print(f"Respuestas: deja los CSV descargados en {RESPUESTAS}")
    print("Fuera del set: " + "; ".join(f"{k} ({v})" for k, v in FUERA.items()))
    return 0


def analizar_orden(argumentos) -> int:
    if not CLAVE.is_file():
        print("Primero: preparar.")
        return 1
    hojas = sorted(RESPUESTAS.glob("*.csv"))
    valido, motivo = legibilidad.umbral_valido(UMBRAL, hojas)
    if not valido:
        print(f"No analizo: {motivo}")
        return 2
    datos_clave = json.loads(CLAVE.read_text(encoding="utf-8"))
    huella = hashlib.sha256(UMBRAL.read_bytes()).hexdigest()
    if datos_clave.get("umbral_sha256_al_preparar") not in ("", huella):
        print("AVISO: el umbral es distinto del que había al preparar la prueba.")
    if not hojas:
        print(f"No hay respuestas en {RESPUESTAS}.")
        return 1
    umbral = json.loads(UMBRAL.read_text(encoding="utf-8"))
    r = analizar(legibilidad.leer_respuestas(hojas), datos_clave["clave"], umbral)
    print(f"Participantes: {r['participantes']} ("
          + ", ".join(f"{k} {v['participantes']}" for k, v in r["por_rostro"].items()) + ")"
          + ("" if r["suficientes"] else
             f"  — menos de {umbral['participantes_minimos']}: se informa, no decide"))
    if r["umbral_provisional"]:
        print("Umbral PROVISIONAL (§13.8c pendiente del responsable).")
    print(f"\nPor expresión, los tres rostros juntos: "
          f"{'PASAN todas' if r['pasan_todas'] else 'NO pasan todas'}")
    for expresion, e in r["por_expresion"].items():
        etiqueta = EXPRESIONES[expresion][1]
        confusion = (f"confunde con «{e['confusion_principal']}» "
                     f"{e['confusion_principal_pct']:.0%}" if e["confusion_principal"] else "")
        de_mas = " ".join(f"{d} {p:.0%}" for d, p in e["de_mas"].items() if p)
        print(f"  {etiqueta:<12} {e['acierto']:>5.0%}  IC95 {e['ic95'][0]:.0%}–{e['ic95'][1]:.0%}"
              f"  n={e['n']:<3} {'✓' if e['pasa'] else '✗'}  {confusion}"
              + (f"  · se lee de más: {de_mas}" if de_mas else ""))
    print("\nRostro contra rostro (informa; con pocos por rostro, no decide):")
    for rostro, d in r["por_rostro"].items():
        print(f"  {rostro:<16} {d['acierto_global']:>5.0%}  IC95 {d['ic95_global'][0]:.0%}–"
              f"{d['ic95_global'][1]:.0%}  ({d['participantes']} personas"
              + ("" if d["suficientes"] else ", pocas") + ")")
    for expresion, c in r["rostro_contra_rostro"].items():
        print(f"  {EXPRESIONES[expresion][1]:<12} "
              + "  ".join(f"{k} {v:.0%}" for k, v in c["acierto"].items())
              + (f"  ← diferencia clara: {c['peor']} peor" if c["clara"] else ""))
    for aviso in r["avisos"]:
        print(f"AVISO: {aviso}")
    legibilidad.guardar_json(DIRECTORIO / "resultados.json", r)
    print(f"\nResultados: {DIRECTORIO / 'resultados.json'}")
    return 0


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = analizador.add_subparsers(dest="orden", required=True)
    p = sub.add_parser("preparar")
    p.add_argument("--tamano", default="800x480")
    p.add_argument("--sin-carcasa", action="store_true")
    p.add_argument("--participantes", type=int, default=24,
                   help="Filas de la hoja en papel (P01…).")
    p.add_argument("--sobrescribir", action="store_true")
    sub.add_parser("analizar")
    argumentos = analizador.parse_args()
    return {"preparar": preparar, "analizar": analizar_orden}[argumentos.orden](argumentos)


if __name__ == "__main__":
    sys.exit(main())
