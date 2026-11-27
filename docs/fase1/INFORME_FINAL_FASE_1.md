# EMOTI-BOT v1.8 — Informe final de la Fase 1

- **Para:** Mario Dominici (responsable del proyecto)
- **De:** Claude Code (implementación)
- **Fechas:** 21 y 22 de noviembre de 2026
- **Especificación:** `docs/ESPECIFICACION_FASE_1.md`
- **Detalle de cada cambio:** `docs/BITACORA.md`

---

## 1. Resumen ejecutivo

**Bloque A, terminado y probado.** Los cuatro defectos demostrados están
corregidos:
- la boca se mueve al hablar en los 17 sitios de emisión;
- las respuestas truncadas se detectan y no se pronuncian a medias;
- se cuentan tokens además de solicitudes, con estimación al alza;
- el robot ya no dice que monitorea la salud.

**Bloque B, instrumentos entregados. No hay ninguna medición hecha.** B1,
B3 y B6 necesitan personas (§13.7). B4 no pudo ejecutarse: este equipo no
tiene las claves de Groq ni de OpenRouter. B2 (ver lo que oyó Whisper) y el
diseño de B5 (longitud por ruta) sí están implementados.

**Bloque C, prototipo entregado y medido solo en PC.** Pillow mejora mucho
el aspecto, pero cuesta de 6 a 18 veces más CPU que el rostro actual. Falta
medirlo en la Raspberry Pi y pasar la prueba de legibilidad con personas.

**Un defecto nuevo, corregido con tu autorización.** La curva de la boca
cerrada estaba invertida: «feliz» salía con la boca triste.

**Pruebas:** de 94 a **243, todas en verde**. Las 94 originales siguen
pasando (comparadas por nombre de prueba, no por recuento), con el
intérprete del `.venv` verificado.

**Pendiente de ti:** las mediciones (B1, B3, B4 en dos franjas, B6 y C4) y
tres decisiones abiertas (§13.8a, b y c).

**Después del informe (22-11):** se corrigieron cuatro hallazgos del
diagnóstico de IA. Groq vuelve a responder, ahora con un `User-Agent` propio.
La **ruta de razonamiento de OpenRouter quedó desactivada** por tu decisión
provisional (opción d). Ver §12.

**Sección 14:** se añadió a la especificación durante la ejecución (21-11,
20:57) y la leí al preparar este informe. Lo hecho la cumple. Con tu visto
bueno, **GPT-OSS 20B ya es el tercer candidato** de B4 y B6 (D6), sin
cambiar el modelo de producción. Ver §9.

---

## 2. Bloque A — Defectos corregidos

### A1. La boca se mueve al hablar (17 sitios)

- **Problema:** un solo nombre de estado mezclaba lo que el robot HACE con
  la CARA que pone. En 16 de los 17 sitios que emiten voz (toda la ruta de
  seguridad, las dos actividades y las respuestas literales) hablaba con la
  boca cerrada.
- **Además, sin estar en la especificación:** «ordenar ideas» y el aviso «No
  llegué a oírte» encendían el piloto y el texto «● micrófono abierto» con
  el micrófono cerrado.
- **Solución:** dos ejes superpuestos, sin matriz de combinaciones. El
  **estado funcional** (reposo, calibrando, escuchando, pensando, hablando,
  error, sin conexión) decide la boca y el piloto. La **expresión** decide
  ojos, cejas, inclinación y color. La boca sigue la envolvente REAL del
  altavoz y se cierra al terminar o interrumpir.
- **Prueba de aceptación:** recorre los 17 sitios uno a uno. Un análisis
  del código hace fallar la prueba si aparece un sitio nuevo sin cubrir.
- **Archivos:** `rostro/estados.py`, `rostro/cara.py`, `app.py`,
  `bin/vista_previa_rostro.py`; prueba `tests/test_composicion.py`.

### A2. Respuestas truncadas

- Se lee `finish_reason` en Groq/OpenRouter y en Gemini, y se distingue
  completa, truncada, filtrada y otra.
- **Política PROVISIONAL (§13.8a, decisión tuya pendiente):** recortar a la
  última frase completa; si no queda ninguna, una respuesta local honesta
  («Se me cortó la respuesta…»). **Nunca reintenta.**
- Las truncadas se cuentan en el presupuesto y en `latencia.csv`. El
  registro guarda la longitud, nunca el texto.
- **Reversión:** `"politica_truncado": "ninguna"` en `config/ajustes.json`.
- **Archivos:** `ia/base.py`, `ia/truncado.py` (nuevo), `ia/openai_compat.py`,
  `ia/gemini.py`, `ia/guion.py`, `ia/orquestador.py`, `ajustes.py`,
  `dialogo/gestor.py`, `metricas.py`.
- Los campos nuevos del contrato `Respuesta` llevan valor por defecto, y
  hay una prueba de que los tres proveedores lo siguen construyendo (§13.3).

### A3. Contabilidad de tokens y solicitudes

- **Antes de cada llamada:** se reserva la entrada estimada al alza más
  `max_tokens`. Se comprueban día y minuto, en solicitudes y en tokens, y
  el intento se cuenta aquí (los fallidos también cuentan).
- **Después:** se sustituye la reserva por el `usage` real. Si el proveedor
  no lo informa, cuenta la reserva entera.
- **Estimación (§13.4):** 3 caracteres por token frente a los ~3,6 medidos.
  Con las instrucciones reales: 905 estimados frente a ~680 reales (+33 %).
  El error va hacia arriba a propósito.
- **Topes propios PROVISIONALES:** Groq 180.000 tokens/día y 7.000/min, por
  debajo de los 200.000 y 8.000 del proveedor.
- Cerrojo contra reservas simultáneas.
- El formato de `presupuesto.json` de la v1.7 se sigue leyendo.
- **Archivos:** `ia/presupuesto.py`, `ia/tokens.py` (nuevo),
  `ia/openai_compat.py`, `ia/gemini.py`, `config/proveedores.json`.

### A4. Identidad

- Desaparece «funciones de monitoreo de salud».
- Los límites dicen «No monitoreo la salud: no tengo sensores ni mido
  constantes vitales» y «herramienta experimental de bienestar cotidiano».
- Autoría intacta: «el grupo Emoti».
- Sin conexión, las cinco preguntas de aceptación reciben respuestas
  verdaderas; la de salud empieza por «No.».
- **Sin verificar:** cómo las contesta el modelo con conexión (lo cubre B6).

### Corrección posterior: la curva de la boca (autorizada)

- `cara.py` dibujaba la sonrisa como ∩. Corregido con un cambio de signo.
- Curvatura medida (positivo = sonrisa): reposo −2,95 → +2,95 px; feliz
  −5,36 → +5,36; preocupado +0,96 → −0,96.
- Hay prueba de regresión.
- Las capturas y las láminas de C4 se regeneraron antes de recoger ninguna
  respuesta.

---

## 3. Bloque B — Instrumentación

| Apartado | Entregable | Estado |
|---|---|---|
| B1 STT | `bin/medir_stt.py`: 30 frases fijas y 7 categorías de fallo con IC 95 % | **Instrumento entregado, medición pendiente del responsable** |
| B2 Depuración | Tecla **T**: muestra 10 s lo que oyó Whisper | Implementado y probado. Sin verificar su posición en pantalla |
| B3 VAD | `bin/medir_vad.py`: mitades grabadas aparte y unidas con pausas exactas de 0,3–1,2 s, probadas con 4 umbrales | **Instrumento entregado, medición pendiente del responsable** |
| B4 Modelos | `bin/medir_modelos.py`: Qwen contra GPT-OSS 20B en las dos rutas, más 4 muestras de Gemini por franja; conexión, TTFT, tiempo total, tokens/s, tokens de razonamiento, aciertos de caché y truncadas, con los topes de §13.5 sumados por anfitrión | **Instrumento entregado. Medición pendiente; las claves ya están y el diagnóstico sale limpio** |
| B5 Longitud | `config/longitud.json` + `bin/medir_longitud.py` | Diseño implementado con valores provisionales; la medición necesita uso real |
| B6 Evaluación a ciegas | `bin/evaluacion_ciegas.py`, 18 situaciones, rúbrica y protocolo | **Protocolo entregado, evaluación pendiente del responsable** |

Lo esencial de cada uno:
- **B2.** Arranca siempre apagado. No escribe en disco ni en el registro.
  En la ruta de seguridad el texto ni siquiera entra en la cola de eventos.
- **B3.** Como se sabe que la segunda mitad continúa a la primera, un cierre
  durante la pausa es siempre un corte prematuro, nunca una intervención
  nueva. Es lo que la métrica rechazada no podía distinguir. Solo se
  ejecutó en modo sintético, como autoprueba; esa salida se borró.
- **B5.** Valores provisionales (§13.8b) iguales a los de la v1.7: 120 y 320
  tokens. Lo nuevo es que el tope va con la pregunta, no con quien la
  contesta. Antes, una pregunta de razonamiento atendida por Gemini recibía
  120 tokens. El comparador y el medidor usan la misma cifra.
- **B6.** Identificadores neutrales, orden aleatorio por evaluador y clave
  en un archivo aparte. Avisa si hay menos de 3 evaluadores (D2).

Procedimientos: `docs/fase1/GUIA_MEDICIONES_BLOQUE_B.md` y
`docs/fase1/B6_PROTOCOLO_EVALUACION.md`.

**Mediciones pendientes de ti:**
1. B1: 30 frases, unos 15 minutos.
2. B3: 10 grabaciones cortas, unos 10 minutos.
3. B4: dos franjas horarias, con las claves de Groq y OpenRouter en el
   equipo.
4. B6: al menos 3 evaluadores. **No el mismo día que B4 con el mismo
   proveedor**; el script lo impide.

**Dato a no repetir (§13.10):** las latencias previas de ~0,71 s son de
Gemini (n = 8), no de Qwen ni de DeepSeek. Los instrumentos lo advierten.

---

## 4. Bloque C — Prototipo visual Hybrid Balanced

- **Prototipo aislado** en `prototipos/rostro_pillow/`. Se ejecuta con
  `python -m prototipos.rostro_pillow` y la tecla B alterna A/B en vivo. La
  aplicación no lo importa, y una prueba lo vigila.
- **Motor y diseño, separados:**
  - Pillow aporta bordes suavizados, degradados, transparencia y halo.
  - El diseño aporta ojos más grandes, cejas de cápsula, una boca con
    interior al hablar, rubor y sombra.
  - Se conservan la silueta, la paleta, las orejas, los ojos en arco y el
    piloto de la barbilla.
- **Capturas comparables:** `docs/fase1/capturas/comparativa_A_B.png`. A se
  capturó de una ventana Tkinter real.

**Rendimiento medido en PC** (AMD Zen 3, 8 núcleos, 30 FPS objetivo; CPU =
% de un núcleo):

| Resolución | A Tkinter | B Pillow ×1 | B Pillow ×2 |
|---|---|---|---|
| 800×480 | 30 FPS · 1,7 ms · 6 % | 30 FPS · 10 ms · 35 % | 30 FPS · 13,5 ms · 47 % |
| 1280×720 | 30 FPS · 1,8 ms · 6 % | 27 FPS · 18,5 ms · 66 % | 26,5 FPS · 28 ms · 88 % |
| 1920×1080 | 30 FPS · 2,2 ms · 7 % | 17,5 FPS · 41 ms · 100 % | 12 FPS · 62 ms · 99 % |

**No medido:** la Raspberry Pi. Ninguna cifra de esta tabla dice cómo irá
allí.

**C4, legibilidad: instrumento entregado, medición pendiente del
responsable.**
- 14 láminas sin etiqueta y una página local que funciona sin Internet.
- La clave va aparte, y el análisis se niega a ejecutarse si el umbral se
  modificó después de la primera respuesta.
- **Umbral PROVISIONAL (§13.8c), fíjalo antes de ver resultados:** ≥ 70 %
  de acierto por expresión, ninguna confusión > 25 % y mínimo 8
  participantes.

Informe completo: `docs/fase1/C_PROTOTIPO_VISUAL.md`.

---

## 5. Calidad conversacional

**No hay resultados de calidad.** No se ha hecho ninguna evaluación humana y
no se ha inventado ninguna. Lo que sí mejora de forma verificable:
- ya no se pronuncian frases cortadas;
- la identidad es verdadera;
- el tope de longitud ya no depende de qué proveedor conteste.

La comparación de modelos y configuraciones es B6, con al menos tres
evaluadores.

---

## 6. Seguridad, privacidad y credenciales

- **La ruta de seguridad conserva su comportamiento.** `seguridad.py` y
  `crisis.json` son idénticos byte a byte a la copia previa. La ruta sigue
  yendo primero, sigue sin llamar a ningún proveedor y sigue fuera de la
  memoria de sesión, comprobado con pruebas. Ahora además mueve la boca al
  hablar (A1). La depuración B2 la excluye.
- **Privacidad.** Ningún instrumento guarda texto reconocido ni audio, solo
  cifras y categorías. `latencia.csv` gana columnas numéricas (motivo de
  fin, tokens, ruta, número de palabras), nunca contenido. No se ha
  implementado memoria persistente.
- **Credenciales (§14.6, vigente).**
  - `credenciales.py` y `registro.py` siguen idénticos.
  - No hay ninguna clave real en el código, las pruebas ni la
    documentación. La única cadena con forma de clave es una falsa que ya
    existía en la v1.7 (`tests/test_nucleo.py:109`), usada para probar el
    redactado.
  - Las pruebas no hacen llamadas reales ni usan claves.
- **Módulo de intención (§13.6).** `intencion.py` está idéntico byte a byte
  y no se describe en ninguna parte.

---

## 7. Regresiones

- **Nuevas detectadas:** ninguna. La batería pasa entera (213) tras cada
  cambio, con la salida guardada en `docs/fase1/pruebas_tras_*.txt`.
- **Corregido de paso:** el control de topes de B4 comparaba cada modelo
  por separado. Con dos modelos de Groq habría permitido pasar de 20
  solicitudes por franja. Ahora suma por anfitrión.
- **Resueltos:**
  - los defectos A1–A4;
  - el piloto de micrófono encendido mientras habla;
  - las solicitudes fallidas no contabilizadas;
  - la curva de la boca invertida;
  - la incoherencia entre las 45 palabras del comparador y las 79 posibles.
- **Cambio de formato a vigilar:** `logs/latencia.csv` se migrará solo la
  primera vez que el robot anote una medición (seis columnas nuevas,
  conservando todas las filas). Probado sobre una copia; tu archivo real aún
  no se ha migrado.
- **Sin verificar con hardware:** la aplicación entera en pantalla y con
  audio real, la Raspberry Pi y la voz.

---

## 8. Decisiones que te corresponden

| Decisión | Estado actual (provisional y reversible) |
|---|---|
| §13.8a Política de truncado | Recortar a la última frase; si no hay, respaldo local |
| §13.8b Longitud por intención | 120 / 320 tokens, como en la v1.7, hasta medir |
| §13.8c Umbral de C4 | 70 % / 25 % / 8 participantes. **Fíjalo antes de la prueba** |
| Topes de tokens de Groq | 180.000/día y 7.000/min propios. Verifica los vigentes en la consola |
| Regla para adoptar el motor Pillow | Propuesta: en la Pi, con carga, ≥ 25 FPS, p95 < 60 ms y ≤ 50 % de un núcleo |
| Lectura de §13.5 | Apliqué que el tope de 16 de OpenRouter vale para toda la Fase 1B, B6 incluido. Hoy no aplica: la ruta de OpenRouter está desactivada |
| Ruta de razonamiento | **Desactivada (opción d), decisión tuya y PROVISIONAL.** Se reabre si B6 muestra que el razonamiento no se resuelve bien sin ella |

---

## 9. Sección 14 — Encaje con lo hecho

La sección 14 se añadió a la especificación durante la ejecución y no
ordena cambios en la Fase 1. Comprobación:

- **§14.6 (vigente): cumplida.** Ver §6.
- **§14.5: no hay ninguna preferencia que pueda tocar la seguridad, la
  autoría ni los topes.** Para no cerrar puertas, cuando llegue la
  personalización conviene un **techo duro de longitud** en
  `ia/longitud.py`. Hoy solo hay un mínimo; los valores actuales (120 y
  320) quedan muy por debajo de cualquier techo razonable.
- **D6, GPT-OSS 20B como tercer candidato: cubierto, con tu visto bueno.**
  - Nueva entrada `candidato_gpt_oss_20b` en `config/proveedores.json`:
    modelo `openai/gpt-oss-20b` de Groq, con la misma clave que Qwen.
  - Está **fuera** de `orden_proveedores`, así que el robot sigue
    contestando con Qwen3.8-27B. Hay una prueba que lo vigila, y el cuerpo
    de las peticiones de producción es idéntico al de antes.
  - Los proveedores admiten `parametros` propios (aquí,
    `reasoning_effort: low`). No pueden pisar los campos que controla el
    robot: modelo, mensajes, `max_tokens` y streaming.
  - **B4** mide por defecto los tres candidatos (Qwen 10, DeepSeek 4,
    GPT-OSS 10). Los topes se suman por anfitrión, así que Qwen y GPT-OSS
    juntos no pasan de 20 por franja.
  - **B6:** `generar --nombre gpt_oss --orden candidato_gpt_oss_20b,remoto,local,guion`,
    contra `qwen` con el mismo respaldo.
    Admite `--longitud` con un archivo propio de esa configuración si hace
    falta más tope, sin tocar el del robot.
  - **Verifica en console.groq.com** el identificador del modelo y su
    clasificación antes de medir.
- **§14.3, tokens de razonamiento de GPT-OSS.** No se pueden desactivar, y
  con `max_tokens` = 120 es probable que se trunque. B4 ahora registra
  aparte los tokens de razonamiento, el tiempo hasta el primer fragmento
  (incluido el razonamiento) y los aciertos de caché.
  `--max-tokens 400` sube el tope solo en esa medición, para ver cuánto
  gasta sin cortarse. Con esos datos se decide su tope de ruta; si fuera
  mayor, el coste por turno de §14.2.2 sería distinto.
- **§14.2.6 y §14.4, la demostración.**
  - El tope propio de 7.000 tokens/min reserva ~1.600 por turno antes de
    conocer el consumo real. Con varias personas seguidas, **nuestro propio
    tope frenará antes que Groq** (~4–5 turnos/min, frente a los 7,8
    teóricos).
  - Es lo conservador, pero conviene probarlo en el ensayo de uso intensivo.
  - Los tres estados visibles que pide §14.4.1 (procesando, esperando, no
    disponible) son trabajo posterior. A3 ya distingue internamente
    «demasiadas en el último minuto» de «cuota agotada», que es la base.

---

## 10. Recomendaciones para la siguiente fase

1. **Hacer las mediciones pendientes**, en este orden: B2 (pulsar T, un
   minuto) → B1 → B3 → B4 en dos franjas (Qwen contra GPT-OSS en las dos
   rutas, más Gemini; y una tanda corta de GPT-OSS con `--max-tokens 400`)
   → B6 otro día → C4.
2. **Fijar el umbral de C4 y la regla de adopción de Pillow antes de
   medir.**
3. **Rostro:** no adoptar el motor Pillow hasta medirlo en la Pi. Si no
   rinde, llevar al rostro actual las mejoras que no dependen del motor:
   ojos más grandes, cejas gruesas e interior de la boca al hablar.
4. **Modelo:** decidir entre Qwen3.8-27B (Preview, puede retirarse) y
   GPT-OSS 20B (Production) con B4 + B6, según D6. No cambiar antes.
5. **Demostración (§14.4):** arranque automático, los tres estados
   visibles, una reserva de cuota para el día y un ensayo de uso intensivo
   con el tope por minuto.
6. **Mantenimiento:**
   - actualizar `__version__` a 1.8 cuando cierres la fase (hoy dice «1.0»);
   - decidir si se borra el huérfano `emotibot/ia/local.py` (riesgo cero,
     §13.9);
   - aclarar los valores por defecto «Mario» de `identidad.py`, que solo se
     usan si falta `identidad.json`;
   - `.claude/launch.json` solo sirve para abrir la página de C4 en el
     navegador de Claude y se puede borrar.

---

## 11. Reversión

- **Todo:**
  `%USERPROFILE%\Desktop\emoti-bot-respaldos\emoti-bot-v1.7-20261121-203009.tar.gz`
  (sin `.venv`). Tomada antes de tocar ningún archivo.
- **Por partes:**
  - truncado: `politica_truncado` = `"ninguna"`;
  - longitud por ruta: borrar `config/longitud.json`;
  - prototipo: borrar `prototipos/` y sus tres scripts;
  - Pillow: `pip uninstall pillow`.
- Cada entrada de `docs/BITACORA.md` lista sus archivos.

**Archivos modificados (20 de código y configuración):**
`bin/comparar_modelos.py`, `bin/vista_previa_rostro.py`,
`config/ajustes.json`, `config/identidad.json`, `config/proveedores.json`,
`emotibot/ajustes.py`, `emotibot/app.py`, `emotibot/dialogo/gestor.py`,
`emotibot/ia/base.py`, `emotibot/ia/gemini.py`, `emotibot/ia/guion.py`,
`emotibot/ia/openai_compat.py`, `emotibot/ia/orquestador.py`,
`emotibot/ia/presupuesto.py`, `emotibot/metricas.py`,
`emotibot/rostro/cara.py`, `emotibot/rostro/estados.py`, `requirements.txt`,
`tests/test_rostro.py`, `docs/ARQUITECTURA.md` (más `docs/BITACORA.md`).
`docs/ESPECIFICACION_FASE_1.md` también figura como cambiado, pero el cambio
es tuyo: la sección 14 añadida.

**Archivos nuevos:**
- 6 módulos: `depuracion.py`, `medicion.py`, `evaluacion.py`,
  `ia/tokens.py`, `ia/truncado.py`, `ia/longitud.py`.
- 9 scripts en `bin/`.
- 3 archivos de `config/`.
- 6 de pruebas.
- El paquete `prototipos/`.
- La documentación de `docs/fase1/`.

---

## 12. Después del informe (22-11-2026)

### Hallazgos del diagnóstico de IA

| # | Hallazgo | Estado |
|---|---|---|
| 1 | Groq: 403, código 1010 | **Resuelto.** Cloudflare bloqueaba la firma «Python-urllib». El código envía ahora `User-Agent: EMOTI-BOT/1.8`, también en B4. La configuración prevalece si trae otro |
| 2 | Un 403 de borde clasificado como «autenticación» | **Resuelto.** Nueva clase «bloqueo del cliente» (401/403 sin JSON de la API), separada de autenticación, modelo, cuota y error interno. El mensaje dice «No es la clave» |
| 3 | Identificador de cuenta impreso | **Resuelto.** `registro.redactar()` oculta los identificadores de cuenta y usuario y conserva el mensaje útil |
| 4 | OpenRouter: 404 | **Decidido: opción d, provisional.** Ver abajo |
| 5 | TypeError de Gemini en el diagnóstico | **Resuelto.** Era el script; producción ya pasaba la clave por nombre |

**Diagnóstico real tras los arreglos:**
- Groq/Qwen OK (0,37 s) y Groq/GPT-OSS OK (0,30 s).
- Gemini OK, pero en **9,71 s frente a un timeout de 12 s**.
- OpenRouter, 404, ya clasificado como «modelo».

### Ruta de razonamiento desactivada (opción d)

- El DeepSeek gratuito que la justificaba dejó de existir, y la §3.2
  prohíbe servicios de pago.
- La entrada queda en `config/proveedores.json` con `"url": ""` y el motivo
  escrito.
- Una pregunta de razonamiento va ahora directa al modelo de conversación:
  sin llamada fallida, sin aviso en pantalla y con su tope de 320 tokens.
  Hay prueba de regresión.
- B4 y B6 comparan Qwen con GPT-OSS. B4 añade 4 muestras de Gemini por
  franja, porque sin OpenRouter es el único respaldo remoto.
- **Es revisable:** si B6 muestra que GPT-OSS no resuelve bien el
  razonamiento, se reabre con datos.

