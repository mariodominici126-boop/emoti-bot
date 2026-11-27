# Fase 1C — Prototipo visual Hybrid Balanced

Estado: **prototipo ejecutable y medido en PC. No sustituye al rostro de
producción.** Faltan dos cosas que solo puede hacer el responsable: medir en
la Raspberry Pi y la prueba de legibilidad C4 con personas.

```powershell
.venv\Scripts\python.exe -m prototipos.rostro_pillow
```

Teclas: 1–7 expresiones · **B** alterna A (producción) / B (prototipo) en el
mismo Canvas · **V** voz de demostración · **S** supermuestreo ×1/×2.

## 1. Qué hay y dónde

| Pieza | Archivo |
|---|---|
| Renderizador B (Pillow) | `prototipos/rostro_pillow/render.py` |
| Animación compartida con A (sin reimplementar) | `prototipos/rostro_pillow/animador.py` |
| Ventana A/B interactiva | `prototipos/rostro_pillow/ventana.py` |
| Banco de rendimiento | `bin/banco_rostro.py` |
| Capturas comparables | `bin/capturas_rostro.py` → `docs/fase1/capturas/` |
| Prueba de legibilidad C4 | `bin/legibilidad_rostro.py` + `prototipos/rostro_pillow/legibilidad.py` |
| Umbral C4 (provisional) | `config/c4_umbral.json` |

La aplicación no importa nada de `prototipos/` ni de Pillow; una prueba lo
comprueba. Pillow 13.0.0 está instalado en el `.venv` y figura en
`requirements.txt` como opcional y experimental.

## 2. Motor y diseño: dos decisiones separadas

**Motor (C3).** Cada fotograma se dibuja en una imagen RGBA con Pillow y se
muestra en el mismo `tk.Canvas`, reutilizando un único `PhotoImage`
(`paste`). Se conservan la ventana, el bucle de eventos y toda la lógica de
animación. Esto da bordes suavizados (supermuestreo ×2 reducido con
`reduce()`), degradados reales, transparencia y halo.

**Diseño (C2).** Las proporciones y los rasgos son una decisión aparte. Las
mejoras de legibilidad (ojos, cejas, curva de la boca) podrían llevarse
también al motor Tkinter si Pillow no rindiera en la Pi.

### Registro de decisiones artísticas

| Elemento | Antes (A) | Prototipo (B) | Motivo |
|---|---|---|---|
| Ojos | 13,2 % × 27 % de la cabeza, solo contorno | 16,5 % × 34 %, borde luminoso grueso, interior con degradado, iris y dos brillos | Más adorables y legibles de lejos. Conservan el ojo redondeado con borde y brillo, que es la identidad |
| Separación ocular | 18,5 % | 20 % | Compensa el ojo más grande sin que se junten |
| Cejas | Arco fino | Cápsula gruesa de extremos redondos | El ángulo (preocupación, curiosidad) se lee mejor |
| Boca cerrada | Curva invertida (ver §4; ya corregida en A) | Sonrisa con el centro hacia abajo; preocupación hacia arriba | Corrección de legibilidad |
| Boca abierta | Banda maciza del color de los ojos | Interior oscuro con borde de color y lengua al abrirse mucho | Se lee como boca que habla, no como un rectángulo |
| Alegría | Ojos «^ ^» y destellos ✦ de texto | Los mismos, más gruesos con halo, rubor suave y estrellas dibujadas | Más expresiva sin cambiar el código visual |
| Carcasa | Color plano | Luz cenital (degradado), filo de luz y sombra bajo la cabeza | Profundidad («futurista») sin perder la silueta |
| Pantalla | Plana con banda de reflejo | Viñeta radial y reflejo diagonal difuminado | Aspecto de cristal |
| Orejas | Rectángulos | Cápsulas con degradado | Coherentes con el resto |
| Barbilla / piloto del micrófono | Igual | Igual, con halo solo al escuchar | Sigue siendo el indicador de captura; no se toca su función |
| Paleta | — | La misma de `paleta.py` | Identidad reconocible |

No se ha tomado de ningún robot existente. La silueta, la paleta y los
rasgos siguen siendo los de EMOTI-BOT.

Capturas: `docs/fase1/capturas/comparativa_A_B.png`, y un PNG por expresión
y motor. A se capturó de una ventana Tkinter real; es lo que se ve hoy.

## 3. Rendimiento (medido en PC, 21-11-2026)

Equipo: Windows 11, AMD Zen 3 (familia 25), 8 núcleos, Python 3.13.15,
Pillow 13.0.0. Objetivo: 30 FPS, 8 s por caso, cambiando de expresión cada
segundo y hablando la mitad del tiempo. «CPU» es el porcentaje de un núcleo.

| Resolución | Motor | FPS | ms mediana | ms p95 | CPU | RSS |
|---|---|---|---|---|---|---|
| 800×480 | A Tkinter | 30,0 | 1,65 | 2,05 | 6 % | 41 MB |
| 800×480 | B Pillow ×1 | 30,0 | 9,95 | 24,9 | 35 % | 89 MB |
| 800×480 | B Pillow ×2 | 30,0 | 13,5 | 29,6 | 47 % | 93 MB |
| 1280×720 | A Tkinter | 30,0 | 1,83 | 2,27 | 6 % | 43 MB |
| 1280×720 | B Pillow ×1 | 27,3 | 18,5 | 52,5 | 66 % | 125 MB |
| 1280×720 | B Pillow ×2 | 26,5 | 28,3 | 63,0 | 88 % | 136 MB |
| 1920×1080 | A Tkinter | 30,0 | 2,21 | 2,85 | 7 % | 43 MB |
| 1920×1080 | B Pillow ×1 | 17,5 | 40,7 | 115 | 100 % | 143 MB |
| 1920×1080 | B Pillow ×2 | 12,1 | 62,3 | 141 | 99 % | 160 MB |

- Con un núcleo ocupado en paralelo (`--carga`, imitando a Whisper), las
  cifras a 800×480 y 1280×720 no cambian de forma apreciable. En un equipo
  de 8 núcleos era lo esperable; **en la Pi (4 núcleos) puede no ser así**.
- B cuesta entre 6 y 18 veces más CPU que A. A tamaño de pantalla pequeño
  sostiene 30 FPS en PC; a 1080p no.
- El p95 de B duplica o triplica la mediana. Las causas son el giro de la
  carcasa cuando no está en caché (cambios de expresión) y la subida de la
  textura a Tk. La caché de giros está limitada a 64 MB.
- El RSS es del proceso completo y crece entre casos de la misma ejecución:
  orientativo.
- Optimización ya hecha: reducir con `reduce()` en lugar de LANCZOS pasó de
  23 a 11,5 ms por fotograma (headless, 800×480).

**No medido:** la Raspberry Pi 5. Ninguna cifra de esta tabla dice cómo irá
allí. Instrucciones:

```bash
python bin/banco_rostro.py --resoluciones 800x480 --carga
```

Usa la resolución real de la pantalla del robot.

## 4. Defecto encontrado en producción (fuera del alcance de C)

**La curva de la boca cerrada está invertida en `emotibot/rostro/cara.py`.**
`_dibujar_boca` pasa `altura = desplazamiento` a `arco()`, y una altura
positiva sube el centro. Resultado: una `curva_boca` positiva (sonrisa)
dibuja ∩ y una negativa dibuja ∪. Medido sobre el código actual: en
«feliz» el centro queda 5,4 px por encima de los extremos (boca triste) y en
«preocupado» 1 px por debajo (sonrisa leve).

- **Impacto:** el robot pone «cara contenta» (ojos ^ ^) con la boca triste.
  Es justo el tipo de fallo de legibilidad que mide C4, y perjudicaría al
  diseño A en esa prueba por un error y no por su diseño.
- **CORREGIDO** el 21-11-2026, con autorización del responsable.
  `_dibujar_boca` pasa ahora `-desplazamiento` como altura y centra la boca
  en `cy`. La curvatura medida queda simétrica a la anterior: reposo +2,95
  px, feliz +5,36 y preocupado −0,96 (positivo = sonrisa). Hay una prueba de
  regresión: `test_la_curva_de_la_boca_va_en_el_sentido_correcto`.
- Las capturas de A y las 14 láminas de C4 se regeneraron después de la
  corrección, sin ninguna respuesta recogida todavía. La prueba C4 compara,
  por tanto, A ya corregido con B.

## 5. Prueba de legibilidad C4

Estado: *instrumento entregado, medición pendiente del responsable.*

1. **Antes de ver nada**, el responsable fija el umbral en
   `config/c4_umbral.json`: pone `"provisional": false` y su nombre en
   `decidido_por`. Mientras tanto rige el provisional conservador:
   - ≥ 70 % de acierto por expresión;
   - ninguna confusión concreta > 25 %;
   - un diseño pasa si pasan las siete;
   - mínimo 8 participantes para decidir.
   El análisis se niega a ejecutarse si el umbral se modificó después de la
   primera hoja de respuestas.
2. `bin/legibilidad_rostro.py preparar` genera, en `logs/legibilidad/`:
   - 14 láminas sin etiqueta (7 expresiones × A/B) con códigos neutrales;
   - `prueba.html`, una página local sin Internet que funciona con doble
     clic, muestra las láminas en orden aleatorio y descarga las respuestas;
   - la clave aparte;
   - una hoja para hacer la prueba en papel.
   Ya está generado una vez, a 800×480.
3. Participantes **ajenos al proyecto**, identificados con un código (P01…).
   Cada uno ve las 14 láminas; las opciones son las 7 expresiones y «no sé».
4. `bin/legibilidad_rostro.py analizar` da, por diseño y expresión, el
   acierto, el IC 95 %, la confusión principal y si pasa.

Limitación: cada persona ve los dos diseños y puede aprender del primero.
El orden aleatorio reparte ese efecto, pero no lo elimina.

## 6. Reversión

- Prototipo: borrar `prototipos/`, `bin/banco_rostro.py`,
  `bin/capturas_rostro.py`, `bin/legibilidad_rostro.py`,
  `config/c4_umbral.json`, `docs/fase1/capturas/` y
  `tests/test_prototipo_rostro.py`. Nada de la aplicación depende de ellos.
- Pillow: `.venv\Scripts\python.exe -m pip uninstall pillow` y quitar su
  línea de `requirements.txt`. Las pruebas del prototipo se saltan solas.
- `.claude/launch.json` solo sirve para abrir `prueba.html` desde el
  navegador integrado de Claude; se puede borrar.

## 7. Recomendación

**No adoptar todavía el motor Pillow. Sí adoptar ya las decisiones de
diseño que no dependen del motor.**

1. ~~Corregir la curva de la boca en producción (§4).~~ Hecho.
2. **Medir B en la Pi** con `bin/banco_rostro.py --carga` a la resolución
   real. Regla propuesta, que el responsable debería confirmar antes de
   medir: adoptar el motor B solo si en la Pi, con carga, sostiene
   **≥ 25 FPS**, con un **p95 < 60 ms** y **≤ 50 % de un núcleo**. En PC,
   B ×1 a 800×480 queda en 35 %, que es demasiado justo para dar nada por
   hecho.
3. **Pasar C4** con A ya corregido y con B. Si B no gana claramente en
   legibilidad, el motor no compensa su coste.
4. **Si B no rinde en la Pi**, llevar al motor Tkinter lo que no depende de
   Pillow: ojos más grandes, cejas gruesas, curva de la boca e interior de
   la boca al hablar. Lo que exige Pillow (antialiasing, degradados, halo)
   se queda fuera. Es la vía de menor riesgo.
   **Hecho el 22-11, sin esperar a la Pi** (ver la bitácora): la geometría y
   las formas ya están en el motor Tkinter (cejas en cápsula con arco), sin rubor, con un coste de CPU
   igual o menor. Además, ese motor tiene ahora un modo sin carcasa a pantalla completa. Lo que
   decide la Pi el viernes es solo el motor: suavizado, degradados y halo.
5. No hace falta migrar a pygame ni a SDL para nada de lo anterior.
