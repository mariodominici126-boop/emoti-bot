# Seguridad y responsabilidad

Dos cosas distintas con el mismo nombre: la **seguridad del software**
(credenciales, procesos, datos) y la **seguridad de la persona** que habla con
el robot. Las dos están aquí.

---

## 1. La ruta de crisis

### El problema que resuelve

En las versiones 0.5 a 0.7, una situación grave se gestionaba con una línea
del prompt del modelo:

> «Ante crisis graves, sugiere buscar apoyo humano o servicios de emergencia.»

Eso solo funciona si el modelo responde. Con la cuota agotada, el camino real
del código era:

```
429 → mensaje_error() → "Gemini alcanzó su cuota. Revisa los límites de uso."
```

Una persona que contara algo grave recibía un error de facturación.

### Cómo funciona ahora

`emotibot/dialogo/seguridad.py` evalúa **cada turno antes que cualquier
proveedor**. Es código y texto fijo: no pasa por ningún modelo, no depende de
la clave, de la cuota ni de Internet. Es la única parte del sistema con
disponibilidad garantizada.

```
texto → normalizar → quitar modismos → buscar intención explícita
                                           │
                            ┌──────────────┴──────────────┐
                        activa                        no activa
                            │                              │
                 respuesta fija de                 conversación normal
                 config/crisis.json
```

### Criterios

- **Solo intención explícita.** La tristeza, el agobio y el enfado normales
  NO activan la ruta: van a la conversación, que es donde deben estar.
- **Filtro de modismos primero.** «me muero de risa», «esto me mata», «muerto
  de cansancio» son español corriente. Se eliminan del texto y solo lo que
  queda se evalúa. Hay pruebas para ambos sentidos.
- **Reconocer el límite, no contener.** La respuesta dice que es un programa,
  deriva a una persona de confianza presente y a los servicios de emergencia.
- **Sin preguntas de evaluación de riesgo.** No es papel de un robot de
  escritorio y las guías de salud mental lo desaconsejan.
- **Sin métodos.** No se nombran ni describen, en ningún caso.
- **Sin registro del contenido.** Se anota que la ruta se activó, nunca qué
  se dijo. Ese turno tampoco entra en la memoria de sesión, así que no viaja
  a ningún proveedor en el turno siguiente.
- **Sin encadenar nada después.** No se inicia una actividad ni se vuelve a
  abrir el micrófono automáticamente. La persona decide el siguiente paso.

### Números de ayuda de República Dominicana (22-11-2026)

`config/crisis.json` trae tres líneas, cada una con su franja horaria:

| Situación | Número | Horario |
|---|---|---|
| peligro ahora mismo | 911 | 24 h |
| crisis emocional | 711 | **de 8:00 a 24:00, no 24 h** |
| violencia hacia la mujer | *212 | 24 h, español y criollo |

- **El horario es un requisito.** Fuera de su franja, una línea nunca se
  ofrece como principal. Entre medianoche y las 8:00, la ruta de crisis no
  ofrece el 711: deriva al 911 y a una persona de confianza. El directorio
  lo pone al final y marcado «fuera de horario». Se usa la hora del país
  (`desfase_utc_horas`), no la del ordenador. Hay pruebas con el reloj
  simulado a las 3:00 y a las 15:00 (`tests/test_directorio.py`).
- **El país es configurable** (`region.pais` en `config/ajustes.json`). Si
  no es el de los números, ni la ruta de crisis ni el directorio dan
  ninguno.
- **Los números viven solo en `config/crisis.json`.** Ningún modelo los
  genera, los completa ni los corrige. La petición hablada se resuelve sin
  modelo y no entra en la memoria. Si la respuesta de un modelo trae algo
  con forma de teléfono, se sustituye entera por la remisión al directorio.
- **Fuera:** el 711 sustituyó al 809-200-1400, que no se incluye ni como
  alternativa (un número muerto es peor que ninguno). Tampoco el 811, que
  sale de un anuncio de febrero de 2026; las fuentes de octubre dicen 711.

### Lo que falta y es tu responsabilidad, Mario

**La comprobación es DOCUMENTAL, no telefónica. Nadie ha marcado los
números.** El 711 se verificó con tres fuentes de octubre de 2026 que citan
al Ministerio de Salud Pública, y el *212 con la página del Ministerio de la
Mujer, el 22-11-2026. Por eso `verificado_por_responsable` sigue en `false`
y el programa avisa al arrancar. Marcar los números y comprobar que
responden es lo que falta para ponerlo en `true`, y te toca a ti.

No pongas un número que encontraste en un foro. Si no tienes el dato
confirmado, no lo pongas: la ruta funciona igual derivando a una persona de
confianza y a emergencias.

### Directorio de ayuda: consulta, no crisis

Alguien PIDE los números, con la tecla A o hablando («dame los números de
ayuda», «¿a quién puedo llamar?»), y se muestran en una barra lateral
derecha. Cada línea lleva su situación, su número y su horario. La barra
nunca está donde va el aviso «Revisa config/crisis.json». La ruta de crisis
es reactiva y solo habla: no abre la barra, y el directorio no pasa por
ella. No comparten interfaz.

### Nunca marcar

**EMOTI-BOT no puede llamar y no finge haberlo hecho.** Muestra el número y
dice que hay que marcarlo («Yo no puedo llamar: hay que marcar el número»).
En la aplicación no existe ninguna forma de abrir un enlace ni de lanzar un
proceso a partir de un número:
- nada de `webbrowser`, `os.startfile`, `os.system` ni `ShellExecute`;
- ningún esquema `tel:`, `callto:` o `sip:`;
- subprocesos solo en los tres archivos de audio y voz, sin shell, y ninguno
  de ellos toca los números;
- la barra no hace clicable ningún texto.

`tests/test_no_marcar.py` falla si aparece cualquiera de esas cosas.

### Límite honesto

Esta ruta reduce un daño concreto: que el robot responda un error de cuota a
quien está mal. No convierte a EMOTI-BOT en una herramienta de salud mental,
no detecta todas las formas de expresar riesgo, y un detector por patrones
tiene falsos negativos. Antes de cualquier prueba con poblaciones vulnerables
hace falta evaluación específica y consulta a profesionales competentes.

---

## 2. Credenciales

| Decisión | Por qué |
|---|---|
| `~/.config/emotibot/credenciales.json`, nunca el repositorio | El prototipo usaba variables de terminal que se perdían al reiniciar, o memoria que obligaba a reescribir la clave en cada arranque. |
| Directorio `0700`, archivo `0600` | Solo el usuario puede leerla. |
| Escritura atómica con permisos **antes** del contenido | No hay instante en el que el archivo exista con permisos abiertos. |
| Redacción obligatoria en los logs | `registro.proteger()` registra la clave; además un patrón genérico tapa cualquier cosa con forma de clave aunque no se haya registrado. |
| Se borra de memoria al salir | `_apagar()` vacía la clave y los secretos. |
| En Windows se avisa una vez | No hay equivalente de `chmod`: el archivo queda protegido solo por los permisos de la cuenta. |

Nunca: en archivos compartidos, en GitHub, en capturas, en logs, ni como
argumento de línea de comandos.

El `.gitignore` cubre `*.key`, `credenciales.json`, `.env`, `logs/`, `*.csv`,
`*.onnx`, `*.gguf` y `*.wav`.

---

## 3. Datos y privacidad

**Lo que no se guarda nunca:** audio en disco, transcripciones (salvo que
actives `guardar_transcripciones`, que viene en `false`), historiales entre
sesiones, imágenes.

**Lo que se guarda:** `logs/latencia.csv` con marcas de tiempo, proveedor y
modelo — **ningún contenido**; `logs/emotibot.log` con eventos técnicos
redactados; el contador de consumo del día.

**Lo que sale del dispositivo:** con Whisper local, solo **texto**. Esa es la
diferencia importante respecto al prototipo, que enviaba el WAV: la afirmación
de privacidad del proyecto pasa de dudosa a defendible.

**Lo que hay que seguir diciendo en voz alta:** cuando se usa un proveedor
remoto, el contenido llega a ese proveedor. En los niveles gratuitos de
algunos servicios ese contenido puede usarse para entrenar modelos. No se
puede afirmar que nada sale del dispositivo mientras exista una llamada
externa, y la documentación del proyecto no debe decirlo.

**Transparencia en la interfaz:** el anillo alrededor del rostro aparece si y
solo si el micrófono está abierto, y hay un texto explícito
(`● micrófono abierto`). `M` lo silencia. No hay grabación oculta. El estado
`CALIBRANDO` es visible para que nadie hable creyendo que ya se le escucha.

---

## 4. Seguridad del software

- **Subprocesos con lista de argumentos, nunca una shell.** `arecord`, `aplay`,
  `espeak-ng` reciben `list[str]`; no hay `shell=True` en el proyecto.
- **Nombres de dispositivo ALSA validados** contra
  `^[A-Za-z0-9_:,.=+\-]{1,64}$` antes de llegar a un subproceso, porque vienen
  de un archivo de configuración editable.
- **Un solo dueño por proceso.** El hilo del altavoz es el único que toca el
  `Popen` de `aplay`. El prototipo lo compartía entre hilos y dejaba procesos
  huérfanos que seguían sonando.
- **Cierre garantizado.** `arecord` y `aplay` se terminan con `terminate()` y,
  si no ceden, `kill()`, también en la ruta de error.
- **Dependencias opcionales aisladas.** Piper, Whisper y el SDK remoto se
  importan de forma tardía; su ausencia degrada con un aviso, no con un fallo.
- **Ningún hilo mata la interfaz.** Los trabajadores capturan `Exception` y
  comunican por cola.
- **Sin red en la capa local.** El guion, las actividades y la ruta de
  seguridad no abren ningún socket.

### Lo que NO está resuelto

- **Sin cancelación de eco.** Si algún día se abre el micrófono mientras suena
  el altavoz (requisito de la interrupción natural), el robot se oirá a sí
  mismo. Hoy el turno es half-duplex por diseño, y por eso no ocurre.
- El servidor local se asume de confianza: se habla con `127.0.0.1` sin
  autenticación.
- No hay arranque automático ni servicio supervisado.
- No hay firma ni verificación de los modelos de voz descargados.

---

## 5. Límites de producto

EMOTI-BOT **no es**: psicólogo, psiquiatra, terapeuta, dispositivo médico
validado, herramienta de diagnóstico ni sustituto del apoyo humano.

**No debe** prometer curación ni resultados psicológicos, fomentar dependencia
ni exclusividad, atribuirse emociones o experiencias propias, ni presentar como
hechos resultados que nadie ha medido.

**Sí puede** escuchar, ayudar a ordenar ideas, proponer una pausa, guiar una
respiración y orientar hacia apoyo humano cuando corresponde.
