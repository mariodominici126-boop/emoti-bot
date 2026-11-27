# Arquitectura

## El problema de fondo del prototipo

```
                  ANTES
   ┌──────────────────────────────────┐
   │  arecord → WAV completo (256 KB) │
   │        ↓                         │
   │   ╔══════════════════════╗       │
   │   ║  UNA SOLA API        ║       │
   │   ║  transcribe Y piensa ║ ◄──── todo dependía de aquí
   │   ╚══════════════════════╝       │
   │        ↓                         │
   │  Piper sintetiza TODO            │
   │        ↓                         │
   │  aplay                           │
   └──────────────────────────────────┘
   Sin cuota → el robot deja de ser un robot.
```

```
                  AHORA
   ┌───────────────────────────────────────────────────┐
   │  arecord → VAD con fases → recorte                │
   │        ↓                                          │
   │  STT LOCAL (Whisper)   ← el audio no sale         │
   │        ↓                                          │
   │  GUARDIA DE SEGURIDAD  ← local, siempre primero   │
   │        ↓                                          │
   │  gestor: actividad → intención local → IA         │
   │        ↓                                          │
   │  orquestador: remoto → local → guion              │
   │        ↓                                          │
   │  síntesis POR FRASES → altavoz (hilo propio)      │
   └───────────────────────────────────────────────────┘
   Sin cuota → sigue siendo un robot, con menos conversación.
```

---

## Capas y dependencias

Las flechas van en una sola dirección. Ninguna capa inferior conoce a las
superiores, y eso es lo que permite sustituir un proveedor sin tocar nada más.

```
       app.py  (Tkinter, hilos, flujo del turno)
          │
    ┌─────┼─────────┬──────────┬──────────┐
    ▼     ▼         ▼          ▼          ▼
 rostro  dialogo   voz        stt        ia
          │                    │          │
          │  seguridad         │          ├─ gemini   (texto)
          │  intencion         │          ├─ local    (llama.cpp)
          │  actividades       │          ├─ guion    (sin red)
          │                    │          └─ presupuesto
          └──────────┬─────────┴──────────┘
                     ▼
                   audio  (captura, vad, reproduccion, senal)
                     │
                     ▼
                  motores  (ALSA │ PortAudio)
                     │
                     ▼
     nucleo: ajustes, identidad, credenciales, registro, metricas, rutas
```

---

## Hilos

Tres, con fronteras estrictas. Es lo que elimina las carreras del prototipo.

| Hilo | Hace | Nunca hace |
|---|---|---|
| **Tkinter** | Dibuja, lee el teclado, atiende la cola de eventos | Bloquearse, grabar, consultar la red |
| **Turno** (uno por interacción) | Graba, reconoce, consulta, procesa | Tocar widgets ni el proceso de audio |
| **Altavoz** (permanente) | Consume el generador de PCM y escribe en `aplay` | Tocar widgets |

Comunicación: `queue.Queue` en un sentido y `threading.Event` para cancelar.
El hilo del altavoz es el **único dueño** del `Popen` de `aplay`; el resto del
programa solo mueve un contador de token. En el prototipo, el hilo de voz
asignaba `voz = proceso` mientras el hilo de Tk lo leía y lo mataba: quedaban
procesos huérfanos sonando y el robot se hablaba encima.

---

## Decisiones y por qué

### Dos motores de audio detrás de una interfaz estrecha

El prototipo hablaba con `arecord` y `aplay` directamente. Eso ataba el
desarrollo a la Raspberry Pi: no se podía probar voz ni micrófono en otra
máquina, y cada diagnóstico exigía tener el dispositivo delante.

`audio/motores.py` define cuatro métodos por lado —abrir, leer o escribir,
vaciar, cerrar— con dos implementaciones: ALSA por subproceso y PortAudio por
`sounddevice`. Todo lo que está por encima (VAD, recorte, envolvente, turnos,
rostro) es idéntico en Windows y en la Pi.

Diferencias reales entre los dos, que la interfaz absorbe:

| | ALSA | PortAudio |
|---|---|---|
| Lectura | `select` + `os.read`, devuelve lo que haya | bloquea hasta completar el bloque |
| Interrumpir la voz | cerrar el proceso: es la única forma de vaciar el búfer | `abort()` y reanudar, sin reabrir |
| Dispositivo | cadena validada: va a los argumentos de un proceso | índice o nombre con espacios: va a una llamada de biblioteca |
| Latencia de búfer | fijada con `--buffer-time` | la declara el propio flujo |

La validación estricta del nombre de dispositivo vive dentro del motor ALSA,
que es el único que lo convierte en argumentos de un subproceso. Antes estaba
en la carga de ajustes, donde rechazaba nombres de Windows perfectamente
legítimos como «Micrófono (Realtek Audio)».

### Síntesis por frases, no por respuesta completa

El prototipo construía el WAV de toda la respuesta antes de que `aplay` viera
un byte. Aquí cada frase se sintetiza y se entrega por separado: la primera
suena mientras se genera la segunda. Granularidad de frase y no de palabra, a
propósito: captura casi toda la mejora perceptible sin depender de APIs de
streaming que cambian entre versiones de Piper.

### El primer sonido se mide donde se oye

`al_primer_sonido` se dispara al escribir el primer bloque en `aplay`. El
prototipo marcaba "HABLANDO" antes de sintetizar, así que la pantalla reportaba
sistemáticamente menos latencia de la real. Queda el retardo del búfer de ALSA,
acotado con `--buffer-time=120000` y documentado.

### Un 429 no se reintenta

Un 429 es un techo, no un fallo pasajero. `presupuesto.py` lleva la cuenta,
pausa el modelo tras un rechazo y lo deja para el día tras el tercero. El
prototipo reenviaba el audio completo a un segundo modelo ante errores
transitorios: doble consumo y 45 s de caso peor antes de avisar.

Nada de rotación de claves ni de cuentas múltiples: va contra las condiciones
del proveedor y no se implementa.

### Tokens además de solicitudes (v1.8)

Los proveedores limitan solicitudes y tokens, y suele mandar el de tokens.
Cada consulta pasa por dos etapas en `presupuesto.py`:

- **Antes** (`reservar`): la reserva es la entrada estimada al alza
  (`ia/tokens.py`) más `max_tokens`. Si no cabe en el tope de tokens o de
  solicitudes, del día o del minuto, no se llama. El intento se cuenta en
  este momento.
- **Después** (`confirmar` / `anular`): la reserva se sustituye por el
  `usage` real. Si el proveedor no lo informa, cuenta la reserva entera. En
  un fallo cuenta lo que el proveedor pudo haber procesado.

### Respuestas truncadas (v1.8)

Cada proveedor rellena `Respuesta.motivo_fin` a partir de su
`finish_reason`. El orquestador aplica la política de `ia/truncado.py` en un
solo punto: recortar a la última frase completa o, si no queda ninguna, usar
el respaldo local. Nunca reintenta. Esta política es provisional y se
revierte con `ia.politica_truncado`.

### Cliente remoto reutilizado

Un `Client` por clave, cacheado. El prototipo construía uno nuevo en cada
consulta: conexión y handshake TLS por turno, cientos de milisegundos
regalados sobre Wi-Fi en una Raspberry.

### La identidad es configuración, no código

`config/identidad.json` se lee **completo** y de ahí se componen las
instrucciones. El prototipo iteraba sobre un diccionario de respaldo con tres
claves, así que `proposito` y `limites` se ignoraban en silencio: editarlos no
cambiaba nada. Cambiar de proveedor no toca ni una línea de la identidad.

### El rostro dice la verdad

- La boca se mueve con la envolvente real del audio que suena, no con un seno.
- **Dos ejes (v1.8).** El *estado funcional* (reposo, calibrando, escuchando,
  pensando, hablando, error, sin conexión) aporta la boca y el indicador de
  escucha. La *expresión* (feliz, curiosa, preocupada, respirando…) aporta
  ojos, cejas, inclinación y color. `estados.componer()` los superpone, así
  que el robot habla con la boca animada sea cual sea su emoción.
- `CALIBRANDO` es un estado visible y distinto: nadie debe hablar creyendo que
  ya se le escucha.
- El anillo, y el texto «micrófono abierto», aparecen si y solo si el estado
  funcional es «escuchando». Una expresión no puede encenderlos.
- Figuras persistentes actualizadas con `coords`/`itemconfigure`, en lugar de
  `delete('all')` y recrear todo en cada fotograma.

---

## Puntos de extensión

| Quiero… | Toco… | No toco… |
|---|---|---|
| Otro proveedor remoto | un módulo nuevo en `ia/` con el protocolo `Proveedor` | diálogo, rostro, audio |
| VAD neuronal (Silero) | `audio/vad.py`, misma interfaz `procesar()` | captura, diálogo |
| Otra voz | `voz/`, con `sintetizar()` que devuelva PCM | altavoz, rostro |
| Otra actividad | `dialogo/actividades/` + entrada en `CATALOGO` | todo lo demás |
| Otra expresión | `rostro/estados.py` | `cara.py` |
| Cambiar la identidad | `config/identidad.json` | código |

---

## Comparación de arquitecturas conversacionales

| | Actual (turnos, STT local) | Local predominante | Tiempo real nativo |
|---|---|---|---|
| Viabilidad hoy | alta | media | sin validar |
| Latencia | buena con streaming de voz | depende del modelo | la mejor en teoría |
| Calidad en español | buena con proveedor remoto | notoriamente menor | buena |
| Disponibilidad | degrada en tres niveles | total | la peor: una sola API |
| Privacidad | solo texto sale | nada sale | audio continuo sale |
| Medible | sí, por etapas | sí | no sin transcripciones |
| Eco | no aplica (half-duplex) | no aplica | **problema sin resolver** |

La rama de tiempo real (Gemini Live 0.7) queda fuera de la línea principal.
El motivo está en `docs/BITACORA.md`: micrófono abierto mientras suena el
altavoz sin cancelación de eco, subida continua de ~32 KB/s mientras la sesión
está abierta, y ninguna transcripción con la que medir la conversación.

---

## Rendimiento esperado en Raspberry Pi 5

Expectativas, **no promesas**. Hay que medirlas con `bin/banco_latencia.py`.

| Etapa | Expectativa | Fuente |
|---|---|---|
| VAD | despreciable | `audioop.rms` en C |
| Whisper `tiny` | < 1 s en frases cortas | mediciones publicadas |
| Whisper `base` | 1–2 s, bastante mejor precisión | mediciones publicadas |
| Whisper `small` | por debajo del tiempo real | no sirve para conversar |
| Modelo remoto (texto) | depende de la red | por medir |
| Modelo local 1–1,5 B Q4 | ~10–17 tokens/s | mediciones publicadas |
| Modelo local 3 B Q4 | unos pocos tokens/s | mediciones publicadas |
| Piper, primera frase | por medir | `--sintesis` |

Contrapartida honesta del STT local: Whisper en español con un micrófono
mediocre cometerá errores de transcripción que antes absorbía el modelo remoto
al oír el audio directamente. Hay que medirlo, no suponerlo.
