# EMOTI-BOT

Robot de escritorio conversacional con rostro animado, voz en español y
herramientas sencillas de bienestar cotidiano.

Diseñado por el **grupo Emoti**. El modelo de inteligencia artificial que
utiliza lo desarrolla un tercero; son cosas distintas, y el robot lo dice así
cuando se le pregunta.

> EMOTI-BOT no es un psicólogo, un terapeuta ni un dispositivo médico. No
> diagnostica, no prescribe y no sustituye el apoyo humano.

---

## Principio de diseño

**La disponibilidad de la inteligencia está separada de la disponibilidad del
robot.** Sin clave, sin cuota y sin Internet, EMOTI-BOT abre, muestra su
rostro, se presenta, guía sus actividades y conserva su ruta de seguridad.

Ese era el defecto de fondo del prototipo: el 100 % del reconocimiento de voz
y del razonamiento vivían en una sola API externa, de modo que cuando se agotó
la cuota el robot dejó de ser un robot.

---

## Qué funciona sin conexión

| Capacidad | Sin Internet | Sin cuota | Sin clave |
|---|---|---|---|
| Rostro y estados | sí | sí | sí |
| Presentación e identidad | sí | sí | sí |
| Respiración guiada | sí | sí | sí |
| Ordenar ideas | sí | sí | sí |
| **Ruta de seguridad** | **sí** | **sí** | **sí** |
| Reconocimiento de voz | sí, con Whisper local | sí | sí |
| Conversación abierta | solo con modelo local | guion reducido | guion reducido |

---

## Dónde se desarrolla y dónde se ejecuta

El proyecto es **multiplataforma**: puedes desarrollar y probar todo —voz,
micrófono, rostro, actividades— en Windows o macOS, y llevarlo a la Raspberry
Pi cuando esté listo. La capa de audio tiene dos motores intercambiables y se
elige solo:

| | Motor de audio | Se elige cuando |
|---|---|---|
| Raspberry Pi / Linux | ALSA (`arecord` / `aplay`) | hay `arecord` instalado |
| Windows / macOS | PortAudio (`sounddevice`) | en todo lo demás |

Se puede forzar con `audio.motor` en `config/ajustes.json` o con
`EMOTI_AUDIO_MOTOR=portaudio`.

Lo primero en cualquier máquina nueva:

```bash
python bin/comprobar_entorno.py
```

Te dice qué hay, qué falta y el comando exacto para **tu** sistema.

---

## Instalación en Windows

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe bin\comprobar_entorno.py
.venv\Scripts\python.exe bin\emotibot.py
```

**No hace falta `activate`.** Por defecto PowerShell bloquea la ejecución de
scripts y `Activate.ps1` falla con `UnauthorizedAccess`. Llamar al
`python.exe` del entorno evita el problema sin tocar ninguna configuración de
seguridad: es un ejecutable, no un script.

Si prefieres activar el entorno, `Set-ExecutionPolicy -Scope Process
-ExecutionPolicy Bypass` lo permite solo en esa ventana.

**Usa siempre el mismo intérprete.** Mezclar `py` con
`.venv\Scripts\python.exe` lleva a que un comando vea las dependencias y
otro no.

Python desde python.org, marcando **«Add python.exe to PATH»** y **tcl/tk**.
`sounddevice` trae PortAudio dentro de la rueda, así que el micrófono y el
altavoz funcionan sin instalar nada más.

Opcional, para la voz de respaldo:

```powershell
winget install eSpeak-NG.eSpeak-NG
```

Para elegir un micrófono concreto, `py bin\diagnostico_audio.py
--solo-inventario` lista los dispositivos con su número; ese número va en
`config/ajustes.json` → `audio.dispositivo_captura`.

---

## Instalación en Raspberry Pi 5

```bash
sudo apt install alsa-utils espeak-ng python3-tk

python3 -m venv ~/emoti-env
source ~/emoti-env/bin/activate

cd ~/emoti-bot
python -m pip install --timeout 180 --retries 10 -r requirements.txt
```

El tiempo de espera largo evita el `ReadTimeoutError` que apareció al instalar
NumPy durante el desarrollo.

Voz neuronal (opcional pero recomendada):

```bash
mkdir -p ~/emoti-voices
python -m piper.download_voices --data-dir ~/emoti-voices es_MX-claude-high
```

Hacen falta los dos archivos, `es_MX-claude-high.onnx` y
`es_MX-claude-high.onnx.json`: sin el `.json`, Piper no carga el modelo. La
voz `daniela` es opcional: si se elige y falta, el robot la baja a petición.
Ver las licencias en [Voz y licencia](#voz-y-licencia).

Arranque:

```bash
./bin/emotibot            # Linux
python bin\emotibot.py    # Windows
```

La primera vez, pulsa **K** para introducir la clave de la API. Se guarda en
`~/.config/emotibot/credenciales.json` con permisos restringidos, **fuera del
repositorio**, así no hay que reescribirla en cada arranque.

---

## Controles

| Tecla | Acción |
|---|---|
| `ESPACIO` | Hablar (detección automática de pausa) |
| `F` | Grabación fija de 5 s, si la detección falla |
| `2` | Respiración guiada |
| `4` | Ordenar ideas |
| `1` | Volver a reposo / cancelar actividad |
| `M` | Silenciar o reactivar el micrófono |
| `S` | Detener la voz |
| `0` | Olvidar la conversación de esta sesión |
| `K` | Introducir la clave de la API |
| `D` | Diagnóstico en pantalla |
| `L` | Reintentar el proveedor remoto tras un bloqueo |
| `T` | Ver la transcripción en pantalla (depuración; no se guarda) |
| `A` | Números de ayuda: abre y cierra la barra lateral del directorio |
| `P` | Cambiar el perfil: abre el asistente (rostro, voz, personalidad, estilo) |
| `C` | Con o sin carcasa; se guarda en los ajustes de esta máquina y sigue así al volver a arrancar |
| `Esc` | Salir |

La fila de teclas del borde inferior se apaga con `"mostrar_controles": false`
en la sección `rostro` de `config/ajustes.json`. Lo demás baja a ocupar su
sitio, sin dejar franja vacía. Los textos se colocan con su tamaño real y nunca
se salen de la ventana ni se pisan. Si no caben debajo del rostro, la letra se
reduce y, como último recurso, se quita primero la fila de teclas y después la
línea de métricas.

**Números de ayuda (República Dominicana).** Hay tres formas de llegar a ellos.
- **Tecla A o petición hablada** («dame los números de ayuda», «¿a quién puedo
  llamar?»): abre una barra lateral con el 911 (peligro ahora mismo, 24 h), el
  711 (crisis emocional, de 8:00 a 24:00) y el *212 (violencia hacia la mujer,
  24 h, español y criollo).
- **Fuera de horario:** una línea cerrada va al final, marcada.
- **Un modelo no los da:** los números salen solo de `config/crisis.json`; si
  un modelo intenta dar uno, su respuesta se sustituye.

El robot no puede llamar y lo dice. El país se configura en `region.pais`.
Detalles y límites: `docs/SEGURIDAD.md`.

---

## Estructura

```
emoti-bot/
├── bin/                      herramientas ejecutables
│   ├── emotibot              lanzador (Linux)
│   ├── emotibot.py           lanzador (multiplataforma)
│   ├── diagnostico_audio.py  ¿el micrófono o la ganancia?
│   ├── diagnostico_ia.py     ¿qué cuota se agotó exactamente?
│   ├── banco_latencia.py     mediana y p90 por etapa
│   ├── comprobar_entorno.py  qué falta y cómo instalarlo en este sistema
│   ├── comparar_modelos.py   los modelos ante la misma batería en español
│   └── vista_previa_rostro.py  visor del rostro (ventana; --svg sin entorno gráfico)
├── config/
│   ├── identidad.json        nombre, autoría, propósito, límites, estilo
│   ├── proveedores.json      modelos: url, nombre de modelo y clave
│   ├── ajustes.json          audio, voz, STT, IA, rostro
│   └── crisis.json           números de ayuda (ruta de crisis y directorio)
├── emotibot/
│   ├── app.py                ensamblaje, interfaz y flujo de un turno
│   ├── ajustes.py            JSON + entorno, con validación
│   ├── credenciales.py       clave fuera del repositorio, 0600
│   ├── identidad.py          lee TODOS los campos del JSON
│   ├── metricas.py           latencia por etapas → CSV
│   ├── registro.py           logs con redacción de secretos
│   ├── audio/                motores, captura, VAD, reproducción
│   ├── voz/                  Piper → eSpeak → silencio
│   ├── stt/                  Whisper local → remoto → ninguno
│   ├── ia/                   enrutado entre dos modelos, con presupuesto
│   ├── dialogo/              seguridad, intención, actividades
│   └── rostro/               paleta, estados, formas y cara animada
├── docs/
│   ├── ARQUITECTURA.md
│   ├── SEGURIDAD.md
│   ├── BITACORA.md
│   └── rostro.svg            vista previa de todas las expresiones
└── tests/                    94 pruebas, sin dependencias externas
```

---

## Flujo de un turno

```
micrófono
   │  arecord, bloques de 50 ms
   ▼
VAD  ── asentar → CALIBRAR → avisar → detectar voz → silencio final
   │  (el aviso llega DESPUÉS de calibrar: ahí estaba el fallo antiguo)
   ▼
recorte  ── solo la parte útil; el silencio no se envía a ningún sitio
   ▼
reconocimiento  ── Whisper local: el audio no sale del dispositivo
   ▼
GUARDIA DE SEGURIDAD  ── determinista, local, antes de cualquier proveedor
   ▼
gestor de diálogo  ── actividad en curso → intención local → IA
   ▼
orquestador  ── Qwen → gpt-oss → Gemini → local → guion, con plazo de turno
   ▼
síntesis por frases  ── la frase 1 suena mientras se genera la 2
   ▼
altavoz  ── hilo propio, dueño único del proceso, envolvente real
   ▼
rostro  ── la boca se mueve con el audio que suena
```

Cada etapa se cronometra por separado en `logs/latencia.csv`.

**Plazo del turno.** `ia.plazo_turno_ms` (15 s) es el techo de TODA la cadena;
cada proveedor conserva su timeout como techo individual (Groq 12 s, Gemini
20 s). Agotado, deja de probar y contesta lo local sin esperar a la consulta
en curso.

**Tres estados honestos (§14.4.1)**, que se distinguen sin texto (captura:
`docs/fase1/capturas/tres_estados.png`):

| Estado | Cuándo | Cara | Voz |
|---|---|---|---|
| PROCESANDO | solo con una consulta en curso | «pensando» | — |
| ESPERANDO | límite por minuto o pausa tras un 429, y se espera de verdad (cabe en el plazo) | «esperando»: párpados a media asta, boca plana, mirada barriendo de lado a lado | solo si pasa de 4 s, una vez por turno |
| NO DISPONIBLE | cuota agotada, sin conexión, sin clave o plazo vencido: solo queda lo local | «no_disponible» (la de sin conexión, en azul) | siempre, antes de la respuesta local |

Los textos de pantalla y hablados son fijos (`emotibot/ia/disponibilidad.py`);
ningún modelo los escribe. En reposo la cara sigue diciendo cómo está la
inteligencia y vuelve sola cuando pasa el límite por minuto.

---

## Diagnóstico

```bash
python3 bin/comprobar_entorno.py     # qué falta en esta máquina
python3 bin/comparar_modelos.py      # compara los modelos configurados
python3 bin/diagnostico_audio.py     # ruido, voz a 30/60/100 cm, veredicto
python3 bin/diagnostico_ia.py        # cuerpo completo del error de cuota
python3 bin/banco_latencia.py        # mediana y p90 por etapa
python3 bin/banco_latencia.py --sintesis
```

`diagnostico_audio.py` distingue tres causas que se confundían en una sola
queja: ganancia baja, ruido ambiental dominante y límite físico del
micrófono. Solo en el tercer caso tiene sentido plantear otro micrófono.

## Perfil de usuario (D10)

**Primer arranque.** Si en esta máquina no hay perfil elegido (no existe
`perfil.json` en la carpeta de configuración del usuario), el robot abre el
asistente antes de nada:
- `ENTER`: empieza ya con el perfil estándar. Una tecla, ninguna pantalla más.
- `P`: elige el rostro viéndolo (la cara real, sin nombre), la voz oyéndola
  (dice una frase al seleccionarla), y la personalidad y el estilo con una
  línea de descripción. `← →` cambian, `ENTER` elige, `RETROCESO` vuelve
  atrás y `Esc` sale guardando lo elegido; lo no elegido queda como estaba
  (en el primer arranque, por defecto).

La tecla `P` abre el mismo asistente con la aplicación en marcha, y el perfil
se aplica **sin reiniciar**: rostro y paleta al momento, la voz al terminar de
cargar su modelo de Piper (nunca a mitad de una frase), y la personalidad y el
estilo desde el turno siguiente. El modelo de conversación no se elige en el
asistente y no cambia en caliente: si «estándar» lo devuelve al de por
defecto, la aplicación avisa de que cambia al reiniciar. El asistente solo
escribe los cinco ejes, validados con las mismas reglas que al cargar. Un
perfil corrupto o incompleto no impide arrancar: se usa el estándar y se
avisa, también con la cara (expresión «error»), que es lo único que se ve
sin carcasa. El rostro se elige en el modo en que se usa: sin carcasa, sin
carcasa. Capturas: `docs/fase1/capturas/asistente.png` y
`asistente_sin_carcasa.png`.

`config/perfil.json` elige **una opción en cada uno de cinco ejes**, de forma
independiente: cambiar uno no cambia ninguno de los otros (hay una prueba que
recorre las 32 combinaciones de dos opciones por eje). Si existe
`perfil.json` en la carpeta de configuración del usuario, manda ese.

```json
{
  "rostro": "hybrid_balanced",
  "voz": "claude",
  "personalidad": "estandar",
  "estilo": "estandar",
  "modelo": "conversacion"
}
```

| Eje | Valores admitidos | Dónde vive cada opción | Qué cambia, y nada más |
|---|---|---|---|
| `rostro` | nombre de un archivo de `config/rostro/` | `config/rostro/<nombre>.json` (proporciones y colores, ver «El rostro») | qué perfil de rostro se dibuja |
| `voz` | nombre de un archivo de `config/voces/` | `config/voces/<nombre>.json`: `motor`, `modelo_piper`, `velocidad`, `velocidad_espeak` | esos cuatro campos de voz |
| `personalidad` | nombre de un archivo de `config/personalidades/` | `config/personalidades/<nombre>.json`: `"tono"`, frases de hasta 100 caracteres (techo compartido con el estilo) | la sección de tono de las instrucciones |
| `estilo` | nombre de un archivo de `config/estilos/` | `config/estilos/<nombre>.json`: `"reglas"`, frases de hasta 100 caracteres (techo compartido con la personalidad) | la sección de estilo comunicativo, que se **suma** a las normas de `config/identidad.json` |
| `modelo` | `conversacion` o una entrada de `config/proveedores.json` con `"papel": "conversacion"` | `config/proveedores.json` | qué modelo hace de conversación |

Opciones publicadas:
- `rostro`: `hybrid_balanced` (por defecto), `tele` y `capsula`;
- `voz`: `claude` (por defecto) y `daniela`;
- `personalidad`: `estandar` (sin tono añadido), `amigable`, `tranquila`,
  `analitica` y `energetica`;
- `estilo`: `estandar` (no añade nada), `formal`, `casual`, `directo` y
  `explicativo`;
- `modelo`: `conversacion` (Qwen) y `candidato_gpt_oss_20b`.

**Los rostros** comparten la misma **gramática de expresión**: los canales
que tiene cada uno (ángulo de la ceja, apertura del ojo, curva de la boca,
mirada, inclinación, color) significan lo mismo en los tres, así que lo
validado en C4 con uno se transfiere a los demás. Lo que cambia es el mueble
y el trazo:
- `hybrid_balanced`: la cabeza de siempre, trazo de líneas;
- `tele`: televisor retro (marco grueso, tubo muy redondeado, líneas de
  barrido, dos mandos con muesca, rejilla de altavoz, botón gris y rojo,
  antenas en V y zócalo) con la cara **en píxeles**: bloques y brillo
  cuadrado;
- `capsula`: carcasa crema muy redondeada, más alta que ancha, con marco
  grueso alrededor de la pantalla, auriculares redondos y compactos,
  antenas, ojos circulares limpios (sin pupila) y boca de guion redondeado.
  **No tiene cejas**: lo que la ceja dice en los otros dos lo dice el ojo
  (bloque `sin_cejas` del perfil). Preocupado: un párpado tapa el ojo más
  por fuera que por dentro y lo achata. Curioso: un ojo crece y el otro
  mengua, hacia donde mira. Ver `docs/fase1/capturas/capsula_sin_cejas.png`.

El mueble de `tele` y `capsula` es **estático**: se dibuja una vez con
bandas planas (`paleta.mezclar`) y un filo de luz, y no se toca nunca más.
Lo declaran los bloques `mueble` (tipo `cabeza`, `tele` o `capsula`) y
`trazo` (`lineas`, `pixeles` o `redondo`) de `config/rostro/<nombre>.json`.
**Sin carcasa** (`rostro.carcasa` en `config/ajustes.json`) los tres
muestran solo los rasgos: la tele, su cara de píxeles sin mueble.

Un rostro nuevo debe cumplir `tests/test_opciones_publicadas.py` (gramática
campo a campo y dibujada en los canales que tenga, colores de estado a menos de 25°, que nada salga
de la ventana sin carcasa, mueble estático) y tener su referencia de 720
casos: `python bin/referencia_rostro.py grabar <rostro>`. Comparativa real:
`python bin/capturas_rostro.py --rostros`, que genera
`docs/fase1/capturas/comparativa_rostros*.png`; el coste por rostro se mide
con `python bin/banco_rostro.py --rostro <nombre>`.

El registro (tú o usted) es cosa del estilo, no de la personalidad.

Con el perfil por defecto, el robot es exactamente el de antes: mismas
instrucciones byte a byte y mismos ajustes.

**Un solo techo para personalidad y estilo juntos**: 5 frases y 320
caracteres entre los dos, con frases de hasta 100 caracteres. Si cada eje
tuviera el suyo, elegir los dos duplicaría el coste. Se derivó de las 16
combinaciones publicadas: todas llevan 4 frases y la peor (`analitica` ×
`casual`) suma 278 caracteres. Lo impone el código: un perfil cuya
combinación se pase se rechaza entero, y una opción nueva que se pase hace
fallar la batería.

**Añadir una opción** es escribir un archivo de datos, sin código:
- copiar el de la opción estándar en la carpeta de su eje con otro nombre,
  cambiar los valores y poner ese nombre en `config/perfil.json`;
- un modelo nuevo es una entrada en `config/proveedores.json` con
  `"papel": "conversacion"`.

En los archivos, las claves que empiezan por `_` son notas, y `descripcion`
es libre. La carga es estricta:
- un perfil con cualquier otra clave (`seguridad`, `max_tokens`, `creador`…)
  o con una opción que no existe se rechaza entero, y se usa el perfil por
  defecto;
- una voz con campos de más se rechaza;
- en el tono y el estilo, una frase no puede tener saltos de línea, imitar una
  sección de las instrucciones ni contener números de teléfono.

**Lo que ningún perfil puede cambiar (§14.5).** Es la forma del código, no una
comprobación al guardar:
- la ruta de seguridad y el directorio de ayuda no importan el perfil;
- el perfil solo puede escribir sus campos, así que los topes de longitud,
  caracteres y consumo quedan fuera de su alcance;
- la personalidad y el estilo van en sus propias secciones, siempre seguidas
  de «Esto prevalece sobre el estilo y el tono». Con un tono o un estilo
  elegido, lo invariante de `config/identidad.json` (el creador, los límites
  y sus «normas») **se mueve** a ese bloque en vez de repetirse delante, y se
  añade una sola línea fija del código: amabilidad con quien está mal;
- la longitud la pone `max_tokens` (`config/longitud.json`), y los números de
  teléfono los bloquea el filtro del gestor: las dos cosas están en el
  código y no dependen de que el modelo obedezca.

`tests/test_perfil_usuario.py` intenta romper cada punto con un perfil
malicioso.

**Coste.** El rostro, la voz y el modelo no gastan tokens. La personalidad y
el estilo sí, en cada turno:
- con el perfil por defecto, 0;
- en cuanto alguna de las dos no es la estándar, el andamiaje cuesta unos 33
  tokens, más el texto elegido;
- combinando personalidad y estilo publicados: de 95 a 105 tokens por turno,
  y el techo, 115;
- en turnos por minuto, en régimen, el peor caso publicado queda en 5–6,
  frente a 6 con el perfil por defecto.

Las cifras están en la bitácora.

## El rostro

Las expresiones viven en `emotibot/rostro/estados.py` como parámetros
(apertura de ojos, curva de boca, cejas, inclinación, mirada). Las
proporciones y los colores del dibujo viven en un **perfil de rostro**,
`config/rostro/hybrid_balanced.json`, elegido con el eje `rostro` del perfil
de usuario (`config/perfil.json`). Una variante de diseño es otro archivo en esa
carpeta, no código nuevo. La carga es estricta: si falta o sobra un valor, el
perfil se rechaza y el mensaje dice cuál.

```bash
python3 bin/vista_previa_rostro.py                 # visor en una ventana
python3 bin/vista_previa_rostro.py --svg           # todas, a SVG
python3 bin/vista_previa_rostro.py --svg feliz escuchando -o prueba.svg
```

En el visor: → / ESPACIO y ← cambian de expresión, C alterna carcasa sí/no,
H hace hablar con una voz de demostración, M enciende el micrófono real
(la cara pasa a escuchar, como en la aplicación, y arriba se ve el nivel
numérico en vivo), P vuelve a leer el perfil del disco y Esc sale. El visor crea la cara con la **misma función que la aplicación**
(`crear_cara`), con los mismos ajustes y el mismo bucle de pintado: lo que
se ve en él es lo que se verá en la aplicación. Una prueba comprueba que
ninguno de los dos crea la cara por otro camino. Al arrancar, la
aplicación escribe en el registro qué perfil dibuja y con o sin carcasa.

Detalles que no son decorativos:

- La boca se mueve con la envolvente **real** del audio que está sonando.
  Cuando la voz calla, la boca se cierra de verdad.
- `CALIBRANDO` es un estado visible y distinto, para que nadie hable creyendo
  que ya se le escucha.
- Las **barras del micrófono** (21, bajo la cabeza; sin carcasa, abajo del
  todo) son el indicador de captación. Micrófono cerrado: no se dibuja nada.
  Abierto y en silencio: todas a una altura mínima visible («estoy
  escuchando»). Abierto y con voz: la altura crece con el nivel real. La
  presencia significa micrófono abierto; la altura, sonido real. Cuando el
  robot habla, lo que se mueve con el audio es la boca.

El rostro es una cabeza de robot: carcasa de esquinas redondeadas, pantalla
oscura dentro y orejas laterales. Sin banda de reflejo: sin degradados, en
Tkinter se leía como una línea en la frente. Con `"carcasa": false` en la sección
`rostro` de `config/ajustes.json`, solo se dibujan los rasgos sobre el fondo,
para la pantalla montada dentro del robot. La cara ocupa entonces la ventana
entera, en alto y en ancho, y la interfaz no escribe ningún texto: el
micrófono abierto lo indican las barras del micrófono. La única excepción es
la depuración de la transcripción (T), que se ve mientras está activa. Las formas que Tkinter no trae —los
rectángulos redondeados— se generan en `rostro/formas.py`, con rotación
incorporada para inclinar la cabeza.

## Voz y licencia

Hay dos voces, las dos de la colección
[rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices). Se
eligen con el eje `voz` del perfil de usuario (`config/perfil.json`), y cada
una lleva su propia velocidad en su archivo (`config/voces/`):

| Opción | Modelo | Velocidad (`length_scale`) | Licencia de los datos |
|---|---|---|---|
| `claude` (por defecto) | `es_MX-claude-high` | 0,71 | Apache-2.0 |
| `daniela` | `es_AR-daniela-high` | 1,00 | CC BY-SA 4.0 |

**En el ejecutable de Windows** va dentro solo `claude`: su licencia
(Apache-2.0) permite redistribuirla con su aviso. `daniela` NO va dentro: se
baja de rhasspy/piper-voices cuando alguien la elige, con el progreso en
pantalla y su licencia a la vista; mientras tanto, o sin conexión, suena
`claude`. El reconocimiento de la conversación (Whisper `small`) también va
dentro; el del despertar (`base`) se baja al encender «Hola Emoti».

Las velocidades están medidas, no puestas a ojo: con las mismas cinco frases,
claude a 1,00 tarda un 30 % más que Daniela, y a 0,71 tarda lo mismo (un
0,7 % de diferencia).

**Daniela: `es_AR-daniela-high`**, de la colección
[rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)
(`es/es_AR/daniela/high/`). Es español de Argentina, calidad alta, 1 locutor
y 22.050 Hz.

**Licencia: Creative Commons Atribución-CompartirIgual 4.0 Internacional
(CC BY-SA 4.0).** Es la licencia del conjunto de datos con que se entrenó, y
así lo declara la ficha del modelo (`MODEL_CARD`). Obliga a:

- **atribuir** al usarla o distribuirla;
- **compartir igual**: si se distribuye el propio modelo, o una obra
  derivada de él (por ejemplo, una imagen de tarjeta que lo incluya), tiene
  que ir con la misma licencia.

Atribución:

> Voz «daniela» (es_AR, high) de Piper, entrenada por
> [larcanio](https://huggingface.co/larcanio/piper-voices) a partir de la voz
> lessac (en_US). Datos: *Crowdsourced high-quality Argentinian Spanish
> speech data set* (OpenSLR 61, <https://www.openslr.org/61/>), © 2018, 2019
> Google, Inc., CC BY-SA 4.0. Cita del conjunto: Guevara-Rukoz, A. et al.
> (2020), *Crowdsourcing Latin American Spanish for Low-Resource
> Text-to-Speech*, Proceedings of LREC 2020, pp. 6504–6513.

**Claude: `es_MX-claude-high`** (`es/es_MX/claude/high/`), español de México,
calidad alta, 22.050 Hz. **Su ficha (`MODEL_CARD`) declara licencia
Apache-2.0 para sus datos, no CC BY-SA 4.0** (comprobado el 22-11-2026).
Apache-2.0 obliga a conservar el aviso de licencia y la atribución al
distribuir la voz.

Atribución:

> Voz «claude» (es_MX, high) de Piper, de la colección rhasspy/piper-voices.
> Datos: <https://huggingface.co/spaces/HirCoir/Piper-TTS-Spanish>, licencia
> Apache-2.0.

Ninguna de las dos fichas declara una licencia para el modelo de voz en sí;
solo la de sus datos.

Licencias de las demás voces en español de la colección, según sus fichas:
davefx (CC0), ald (Unlicense), carlfm (dominio público), mls_9972 y
mls_10246 (CC BY 4.0) y sharvard (CC BY 3.0). Varían entre sí: revisa la
ficha antes de cambiar de voz.

## Pruebas

```bash
python3 -m unittest discover -s tests -t .
```

94 pruebas, sin dependencias externas ni dispositivos reales. Cubren la
calibración del VAD, la ruta de seguridad (incluidos los modismos que NO deben
activarla), el orden de decisión del diálogo, el presupuesto de cuota, la
selección de motor de audio, la cadena completa de captura y reproducción con
motores simulados, la redacción de secretos y el rostro con un lienzo simulado.

---

## Qué está medido y qué no

**Medido:** las 94 pruebas pasan; los defectos de la tabla en
`docs/BITACORA.md` están corregidos y cubiertos.

**No medido todavía:** la latencia real en el Pi, la precisión de Whisper en
español con el micrófono real, si el micrófono es limitación física, qué cuota
se agotó exactamente, la calidad de un modelo local en la Pi, y cualquier
beneficio para las personas.

Una prueba que funciona no es un producto terminado.

---

## Hoja de ruta

- [x] Estructura modular, pruebas y control de versiones
- [x] Corregir la calibración del VAD
- [x] Instrumentar la latencia por etapas
- [x] Separar reconocimiento de razonamiento
- [x] Presupuesto de cuota y degradación ordenada
- [x] Ruta de seguridad determinista
- [x] Rostro nuevo
- [x] Audio multiplataforma: desarrollar en PC, ejecutar en la Pi
- [ ] Diagnosticar el micrófono con `bin/diagnostico_audio.py`
- [ ] Diagnosticar la cuota con `bin/diagnostico_ia.py`
- [ ] Medir 20 interacciones y comparar con los 7–8 s de partida
- [ ] VAD neuronal (Silero) para discriminar voz de ruido
- [ ] Modelo local como respaldo real
- [ ] Validación con 5–8 personas y tareas guionizadas
