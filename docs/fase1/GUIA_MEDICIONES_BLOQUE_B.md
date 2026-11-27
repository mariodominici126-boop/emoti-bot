# Guía de mediciones del Bloque B (para el responsable)

Estado de cada apartado, según §13.7 de la especificación:

| Apartado | Entregable | Estado |
|---|---|---|
| B1 | `bin/medir_stt.py` + guion de 30 frases | **Instrumento entregado, medición pendiente del responsable** |
| B2 | Tecla **T** en la aplicación | Implementado y probado con pruebas automáticas. Sin verificar en pantalla |
| B3 | `bin/medir_vad.py` + guion de 5×4 intervenciones | **Instrumento entregado, medición pendiente del responsable** |
| B4 | `bin/medir_modelos.py` | Instrumento entregado. **Medición pendiente.** Desde el 22-11 las claves están en el equipo y el diagnóstico de Groq y Gemini sale limpio |
| B5 | `config/longitud.json` + `bin/medir_longitud.py` | Diseño implementado con valores provisionales. La medición necesita uso real |
| B6 | `bin/evaluacion_ciegas.py` + [protocolo](B6_PROTOCOLO_EVALUACION.md) | **Protocolo y batería entregados, evaluación pendiente del responsable** |

Todo se ejecuta desde la raíz del proyecto con el intérprete del entorno
virtual. En la Raspberry Pi, con el de su propio entorno virtual.

Los resultados se guardan en `logs/mediciones/` y `logs/evaluacion/`, que
están fuera del control de versiones. **Ningún instrumento guarda texto
reconocido ni audio**: solo cifras, categorías y el número de la frase del
guion.

---

## B2 — Ver lo que entendió Whisper (empieza por aquí)

1. Abre EMOTI-BOT normalmente.
2. Pulsa **T**. Aparece «DEPURACIÓN STT ACTIVA» bajo el texto de estado.
3. Habla. Durante 10 s verás «Whisper oyó: «…»».
4. Pulsa **T** otra vez para apagarlo; el texto desaparece al momento.

Reglas:
- Siempre arranca apagado.
- No se escribe en disco ni en el registro.
- Nunca se muestra en un turno de la ruta de seguridad: en ese caso se borra
  incluso lo anterior.

## B1 — Línea base del reconocimiento (≈15 min)

```powershell
.venv\Scripts\python.exe bin\medir_stt.py
```

1. Te pide las condiciones: sala, micrófono, distancia y hablante (iniciales
   como mucho).
2. Para cada una de las 30 frases: pulsa Enter, espera a «Te escucho» y di la
   frase con naturalidad.
3. Verás lo reconocido y una categoría automática. Enter la acepta. Una letra
   la corrige; por ejemplo, **p** si te cortó y **r** si entendió mal. **x**
   repite la frase.
4. Al final verás el recuento por categoría con su intervalo de confianza del
   95 %, la tasa de error de palabra y la comparación con los registros
   anteriores (4 fallos técnicos en 22 interacciones).

Para retomar si se interrumpe: `--desde 17`. Con `--fijo` se repite la prueba
con grabación fija, sin VAD. Sirve para separar los errores del VAD de los de
Whisper.

Ten en cuenta: 30 intervenciones sin fallos **no** demuestran fiabilidad
perfecta. Con 0 de 30, la tasa real puede llegar hasta ~11 %.

## B3 — Pausas y VAD (≈10 min)

```powershell
.venv\Scripts\python.exe bin\medir_vad.py --transcribir
```

1. Te pide 4 s de silencio para medir el ruido de la sala.
2. Para cada una de las 5 frases, dices la **primera mitad** en una grabación
   y la **segunda** en otra.
3. El script une las mitades con pausas **exactas** de 0,3, 0,5, 0,8 y 1,2 s
   de ruido real de tu sala: son 20 intervenciones. Las pasa por el detector
   real con el umbral vigente (0,6 s) y con 0,8, 1,0 y 1,2 s.

La tabla resultante dice, para cada umbral y cada pausa:
- la tasa de cortes prematuros;
- el tiempo de espera hasta cerrar el turno.

Lo que se gana en cortes se paga en espera: el umbral se elige con las dos
columnas. Como se sabe que la segunda mitad continúa la primera, un cierre en
la pausa es siempre un corte y nunca una intervención nueva.

`--sintetico` solo comprueba que el instrumento funciona. Su salida está
marcada como «SINTETICO-NO-ES-MEDICION» y no sirve para elegir nada.

No se implementa un VAD adaptativo hasta tener esta tabla.

## B4 — Modelos (dos franjas horarias)

Requiere las claves de Groq y de Gemini en el equipo (tecla K en la
aplicación, o `EMOTI_CLAVE_GROQ` / `EMOTI_CLAVE_GEMINI`). Desde el 22-11 la
ruta de OpenRouter está desactivada (opción d, provisional) y B4 no la usa.

```powershell
.venv\Scripts\python.exe bin\medir_modelos.py --conexion "wifi 5 GHz"
```

- El plan por defecto compara **Qwen contra GPT-OSS 20B**, cada uno con
  7 preguntas de conversación (tope de 120 tokens) y 3 de razonamiento
  (tope de 320 tokens, porque ahora el modelo de conversación atiende las
  dos rutas). Son 20 solicitudes a Groq, justo su tope por franja.
- Además toma **4 muestras del respaldo Gemini** («remoto») por el mismo
  camino que usa el robot, con su timeout real de 12 s. No gasta cuota de
  Groq ni de OpenRouter. En el diagnóstico del 22-11 tardó 9,71 s, frente a
  ~0,71 s de mediana en el historial: con OpenRouter fuera, es el único
  respaldo remoto. Un tiempo agotado aparece como dato («tiempo»), no como
  fallo del instrumento.
- `--plan nombre=N,…` elige otra combinación. `nombre@razonamiento=N` mide
  ese modelo con las preguntas y el tope de la ruta de razonamiento.
- Repítelo en una **segunda franja horaria** y, si se va a presentar a una
  hora concreta, a esa hora. La franja se nombra sola por fecha y hora; o
  usa `--franja`.
- Topes de §13.5 por franja: Groq 20 (**sumando Qwen y GPT-OSS**, misma
  cuenta) y Gemini 4. OpenRouter, si se reactiva: 8 por franja y 16 en
  total. Están en `logs/mediciones/b4_registro.json` y el script se niega a
  superarlos.
- **Razonamiento de GPT-OSS (§14.3).** Para saber cuántos tokens necesita
  sin cortarse, haz en una franja una tanda corta con más tope, solo para
  medir; el robot no cambia. Para no pasar de 20 en Groq, reparte así:

  ```powershell
  .venv\Scripts\python.exe bin\medir_modelos.py --plan conversacion=6,conversacion@razonamiento=2,candidato_gpt_oss_20b=6,candidato_gpt_oss_20b@razonamiento=2,remoto=4
  ```
  ```powershell
  .venv\Scripts\python.exe bin\medir_modelos.py --plan candidato_gpt_oss_20b@razonamiento=4 --max-tokens 400
  ```
- Antes de medir GPT-OSS, comprueba en console.groq.com que el
  identificador `openai/gpt-oss-20b` y su clasificación (Production) siguen
  vigentes.
- Las solicitudes también cuentan en el presupuesto del robot.
- `--resumen` muestra lo medido por franja, modelo y ruta: mediana y p90 de
  conexión, TTFT, tiempo total, tokens/s, tokens de salida y de
  razonamiento, aciertos de caché, truncadas y errores. Gemini no tiene
  TTFT (sin streaming), solo tiempo total. También muestra el tiempo hasta
  el primer sonido del uso real (`latencia.csv`), que es el que percibe la
  persona.

**No** ejecutes B4 y la generación de B6 el mismo día con el mismo
proveedor. El script de B6 lo comprueba.

## B5 — Longitud de las respuestas

`config/longitud.json` es el único sitio donde se fija la longitud por ruta.
Los valores son **provisionales** (§13.8b) y coinciden con los de la v1.7:
120 tokens para conversación y 320 para razonamiento. Lo nuevo es que el tope
va con la pregunta y no con quien la contesta.

Tras unos días de uso con conexión:

```powershell
.venv\Scripts\python.exe bin\medir_longitud.py
```

Verás, por ruta y proveedor:
- palabras (mediana y p90) y el % que supera el objetivo;
- truncadas y recortadas;
- duración hablada medida y estimada.

Con eso, y con la columna `utilidad` de B6 («¿contesta del todo?»), se fijan
los valores definitivos.

## B6 — Evaluación a ciegas

Ver [B6_PROTOCOLO_EVALUACION.md](B6_PROTOCOLO_EVALUACION.md).
