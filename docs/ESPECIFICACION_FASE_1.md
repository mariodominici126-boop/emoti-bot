# EMOTI-BOT v1.8 — ESPECIFICACIÓN DE LA FASE 1

**Documento autoritativo para la implementación.** Sustituye a cualquier
borrador anterior que circule por chat. Si algo de este documento contradice
una conversación previa, manda este documento.

- **Versión base:** v1.7 (la que está en este árbol de código)
- **Objetivo:** convertirla en una v1.8 más coherente, medible, estable y
  preparada para una evolución visual y conversacional de mayor calidad
- **Fecha de cierre de decisiones:** 21 de noviembre de 2026
- **Línea base verificada:** 94 pruebas, todas en verde

La Fase 1 **no** requiere demostrar que EMOTI-BOT sea diez veces más
inteligente ni alcanzar una latencia predeterminada. Requiere **mejoras
concretas y mediciones fiables**.

---

# 0. PROCEDENCIA Y REGISTRO DE DECISIONES

## 0.1 Quién decidió qué

| Papel | Quién | Autoridad |
|---|---|---|
| Responsable del proyecto | **Mario Dominici** | **Decisión final. Solo lo que él dice es ley** |
| Investigación y diseño funcional | ChatGPT | Propone |
| Revisión independiente y debate | Claude (chat) | Contrasta y verifica |
| Implementación | Claude Code | Ejecuta esta especificación |

Este documento es el resultado de tres rondas de debate entre ChatGPT y
Claude, resueltas por el responsable. Las secciones 1 a 12 recogen el diseño
acordado. La sección 13 recoge **correcciones verificadas por inspección
directa del código**, no por memoria ni por resumen.

## 0.2 Decisiones aprobadas por el responsable

**D1. Longitud adaptable de respuestas.** La longitud será adaptable según la
intención, con límites configurables. No un límite idéntico para saludos,
explicaciones, razonamiento y actividades. **Los valores 40 y 160 tokens que
se propusieron en el debate quedan retirados**: eran propuestas, no
mediciones. Primero se miden truncamientos, duración hablada y calidad.

**D2. Evaluación de calidad.** Las pruebas comparativas usarán **evaluación a
ciegas con varios evaluadores** y criterios objetivos y reproducibles. El
responsable organiza la participación. Motivo: un A/B con un solo evaluador,
que además es el autor de lo evaluado, no mide nada.

**D3. Monitoreo de salud.** **Retirar toda afirmación de que EMOTI-BOT
dispone de monitoreo de salud** hasta que exista e esté verificada. Puede
describirse como acompañante conversacional y herramienta experimental de
bienestar cotidiano. **Conservar la atribución de autoría actualmente
configurada**, salvo autorización expresa.

**D4. Memoria persistente.** Se mantiene como **posibilidad futura,
desactivada por defecto. No se implementa en esta fase.** Cualquier
implementación futura exigirá las cuatro precondiciones de §0.4.

**D5. Geometría del rostro.** Se pueden modificar las proporciones siempre
que conserve identidad visual reconocible. Dirección artística aprobada:
**HYBRID BALANCED — adorable, expresiva y futurista.** No se está obligado a
conservar tamaño, separación ni forma actuales. No copiar el diseño de otro
robot.

## 0.3 Propuestas rechazadas o aplazadas, y por qué

No las reintroduzcas. Si crees que alguna debe volver, **detente y pide
decisión** en vez de implementarla.

| Propuesta | Estado | Motivo |
|---|---|---|
| Streaming en producción | **Aplazado** | Con un modelo rápido la generación de 120 tokens son ~0,27 s; el ahorro teórico es ~0,18 s. Pero esa cifra es de benchmarks de terceros, no medida aquí. **Se decide después de medir TTFT real (B4)** |
| Memoria persistente entre sesiones | **Rechazado en esta fase** | Ver §0.4 |
| Sustituir Piper | **Rechazado** | La voz no se ha medido. Cambiar antes de medir es adivinar |
| Migrar a pygame / SDL | **Rechazado** | Pagaría una reescritura por un antialiasing que Pillow da dentro de Tkinter |
| Matriz extensa de combinaciones estado × expresión | **Rechazado** | Se acepta el diagnóstico, se implementa como superposición ligera (A1) |
| Métrica de cortes del VAD por "volvió a hablar en <1,5 s" | **Rechazado** | No distingue un corte real de una respuesta rápida legítima. Sustituido por el barrido de pausas controladas (B3) |
| Reescritura completa del proyecto | **Rechazado** | Fuera de alcance |

## 0.4 Precondiciones de la memoria persistente (para el futuro)

La ruta de seguridad está diseñada hoy para **no registrar contenido nunca**
y para **no entrar en la memoria de sesión**. Una memoria persistente que no
excluya esa ruta guardaría en disco lo que alguien dijo en su peor momento.
Eso es un hueco de seguridad y la condición del responsable es que no queden
huecos de seguridad.

Cualquier implementación futura exige las cuatro, sin excepción:

1. Consentimiento previo y visible, no en la documentación
2. Exclusión de la ruta de seguridad **por diseño y con prueba que lo verifique**
3. Controles accesibles para consultar y borrar, sin tocar archivos
4. Presentación del robot coherente con lo que realmente almacena, reescrita
   **antes** y no después

La memoria de sesión actual sigue siendo temporal.

---

# 1. ROL Y MISIÓN

Actúa como ingeniero responsable de implementación, pruebas, depuración y
mantenimiento.

**Misión: implementar la Fase 1 sin reescribir el proyecto.** Preserva el
funcionamiento actual, mantén la arquitectura modular y justifica cualquier
modificación que exceda el alcance.

**No supongas que el código está exactamente como lo describen los resúmenes
de chat. Inspecciona el estado real antes de actuar.** Las cifras de §13 sí
están verificadas sobre este árbol; el resto, verifícalo.

---

# 2. CONTEXTO DEL PROYECTO

EMOTI-BOT es un robot acompañante con IA que funciona sobre Raspberry Pi 5, y
que actualmente se desarrolla y prueba en Windows.

Dispone de: reconocimiento de voz con Whisper, detección de actividad vocal
(VAD), síntesis con Piper, rostro animado en Tkinter, gestión de diálogo,
enrutamiento de proveedores, APIs de IA, actividades locales, ruta de
seguridad independiente de las APIs, métricas y pruebas automatizadas.

El prototipo ya escucha, interpreta, responde y habla.

**El problema actual no es solo técnico: la experiencia se percibe poco
inteligente, artificial y visualmente poco refinada.** La prioridad es
mejorar eso sin sacrificar estabilidad.

## 2.1 Defectos confirmados por dos auditorías independientes

- Historial conversacional de cuatro turnos, sin resumen
- Respuestas sin streaming
- Límites internos por solicitudes, no por tokens
- Ausencia de contabilización de tokens
- Falta de inspección de `finish_reason`
- **Estados emocionales que impiden la animación bucal** (ver §13.2)
- Presentación que menciona monitoreo de salud sin que exista

---

# 3. ALCANCE Y RESTRICCIONES

## 3.1 Bloques

- **Bloque A:** corrección de defectos demostrados
- **Bloque B:** instrumentación y medición
- **Bloque C:** prototipo visual experimental

A y B son secuenciales entre sí en lo que toca al mismo archivo. **C es
independiente de B** (C mide carga de CPU, B mide audio) y puede avanzar en
paralelo. Completa y valida cada bloque antes de integrar cambios
adicionales.

## 3.2 Prohibido

- Reescribir completamente el proyecto
- Cambiar proveedores sin justificación
- Utilizar servicios de pago
- Introducir dependencias innecesarias
- Almacenar conversaciones privadas como parte de la depuración
- Implementar memoria persistente
- Eliminar el respaldo sin conexión
- Alterar la ruta de seguridad sin pruebas específicas
- Introducir funcionalidades de monitoreo de salud
- Sustituir el rostro actual por uno experimental sin validación
- Modificar configuraciones de hardware sin necesidad
- **Exponer API keys en registros, pruebas o documentación**
- Enviar consultas reales a APIs en las pruebas automatizadas ordinarias

Conserva el funcionamiento existente siempre que no interfiera con una
corrección aprobada.

## 3.3 Fuera de alcance de la Fase 1

Memoria persistente entre sesiones · base de datos personal de recuerdos ·
reconocimiento emocional por cámara · diagnóstico o monitoreo de salud ·
sustitución definitiva de Piper · migración completa de Tkinter · reescritura
del sistema de IA · sustitución de modelos sin pruebas · streaming completo
en producción · funciones dependientes de servicios de pago.

Pueden incluirse como recomendaciones futuras en el informe final.

---

# FASE 1A — CORRECCIÓN DE DEFECTOS DEMOSTRADOS

## A1. Separación de estado funcional y expresión facial

### Problema

La arquitectura actual combina funciones operativas y expresiones emocionales
en el mismo catálogo de estados. Consecuencia: **EMOTI-BOT produce audio
mientras la expresión activa tiene apertura bucal cero.**

**Alcance real verificado (§13.2): 17 sitios emiten texto hablado, 16 de
ellos con `apertura_boca <= 0.18`. Solo `gestor.py:198` usa boca completa.**
Entre los 16 están la ruta de seguridad entera, las dos actividades completas
y la ruta de respuestas literales.

### Objetivo

Que la boca se anime durante cualquier respuesta hablada,
independientemente de la expresión emocional activa, conservando las
excepciones visuales justificadas.

### Arquitectura

Separar conceptualmente:

**Estado funcional:** reposo · calibrando · escuchando · pensando · hablando ·
error · sin conexión

**Expresión visual:** neutra · feliz · curiosa · preocupada · y las
expresiones existentes

La composición debe permitir: hablando + feliz, hablando + preocupado,
hablando + curioso, escuchando + atento.

**El estado funcional aporta boca e indicador. La expresión aporta ojos,
cejas e inclinación. Se superponen.** No construyas una matriz extensa:
implementa una composición ligera que aproveche las estructuras actuales.

### Archivos a inspeccionar

`emotibot/rostro/cara.py` · `emotibot/rostro/estados.py` ·
`emotibot/dialogo/gestor.py` · `emotibot/app.py` ·
`emotibot/dialogo/actividades/` · `tests/test_rostro.py` ·
`tests/test_dialogo.py`

Puedes intervenir en otros archivos si una dependencia real lo requiere,
documentando el motivo. **Excepción: `emotibot/dialogo/intencion.py`, ver
§13.6.**

### Criterios de aceptación

- La boca responde a la señal de audio real durante las respuestas habladas
- La expresión emocional se conserva mientras habla
- El indicador de escucha solo señala captura real
- La boca se detiene al terminar o interrumpir la reproducción
- No aparecen transiciones visuales abruptas
- La ruta de seguridad conserva su funcionamiento independiente y su privacidad
- **La prueba recorre los 17 sitios de emisión, no una muestra**
- Las pruebas anteriores de rostro y diálogo continúan pasando

**No uses una animación artificial que simule voz cuando el altavoz está
realmente en silencio.** La boca se mueve con la envolvente real del audio.

---

## A2. Detección de respuestas truncadas

### Problema

El proveedor compatible con OpenAI extrae el texto pero no interpreta por qué
terminó la generación. Una respuesta que alcance el límite de tokens se
pronuncia incompleta.

### Archivos

Principal: `emotibot/ia/openai_compat.py`
Revisa también: `emotibot/ia/base.py` · `emotibot/ia/orquestador.py` ·
`emotibot/dialogo/gestor.py` · `tests/test_proveedor.py`

**Lee §13.3 antes de empezar: esto obliga a ampliar un contrato compartido.**

### Requisitos

- Leer `finish_reason` cuando esté disponible
- Distinguir finalización normal, truncamiento y otros motivos
- Contabilizar truncamientos en métricas agregadas
- Evitar pronunciar fragmentos manifiestamente incompletos como respuestas terminadas
- Recuperación segura, **sin repetir llamadas de forma ilimitada**
- Conservar los límites de cuota
- Evitar reintentos automáticos que dupliquen gasto o latencia

### Política de recuperación

**Decisión pendiente del responsable (§13.8a).** Mientras no la haya,
implementa la opción conservadora: **recortar a la última frase completa y no
añadir nada.** Si no queda ninguna frase completa, cae al respaldo local. Es
determinista, no gasta cuota y no añade latencia. Márcala como provisional y
deja la reversión en un solo punto de configuración.

### Criterios de aceptación

- Una respuesta truncada queda identificada
- El sistema no presenta una oración evidentemente cortada como respuesta normal
- La información diagnóstica no contiene conversaciones privadas
- Existen pruebas con respuestas simuladas y distintos valores de `finish_reason`

---

## A3. Contabilidad de tokens y solicitudes

### Problema

El presupuesto actual controla el número de consultas. Pero los proveedores
imponen restricciones distintas para solicitudes/minuto, solicitudes/día,
tokens/minuto y tokens/día. **El contador de solicitudes no basta.**

Medición del coste real por turno sobre la configuración actual:

```
instrucciones del sistema   680 tokens   (75 % de la entrada)
historial (4 turnos)        200
mensaje del usuario          25
                           ─────
entrada                     905
salida máxima               120
TOTAL POR TURNO           1.025 tokens
```

Con límites de 8.000 tokens/min y 200.000/día: **~195 turnos/día por tokens
y ~7 turnos/min**, frente a 1.000 solicitudes/día. **Manda el límite de
tokens.** El tope interno de 400 solicitudes/día nunca se alcanza: los tokens
se agotan en el turno 195. El contador mide lo que no limita.

Verifica los límites vigentes en la consola de cada proveedor: son por cuenta
y cambian.

### Archivos

`emotibot/ia/presupuesto.py` · `emotibot/ia/openai_compat.py` ·
`config/proveedores.json` · `tests/test_proveedor.py` · `tests/test_nucleo.py`

### Requisitos: dos etapas

**Antes de cada solicitud:** comprobar cuotas conocidas · estimar el consumo
máximo razonable · reservar margen de seguridad · evitar solicitudes que
excedan el presupuesto interno · contabilizar intentos.

**Después de cada solicitud:** leer `usage` cuando exista · registrar tokens
de entrada y salida · reconciliar la reserva con el consumo real · gestionar
respuestas sin información de uso · tratar errores y solicitudes
potencialmente contabilizadas por el proveedor.

**Dirección del error en la estimación: ver §13.4. Es obligatorio.**

### Requisitos adicionales

- Respetar ventanas por minuto y por día
- No asumir que los contadores locales coinciden con los del proveedor
- Mantener la gestión de errores 429
- **No rotar cuentas ni API keys para evadir límites**
- No realizar reintentos ilimitados
- **No almacenar el contenido de los mensajes para contar tokens**
- Mantener compatible el formato de persistencia existente, o migrarlo con seguridad

### Criterios de aceptación

Pruebas con `usage` presente · con `usage` ausente · de límite diario · de
límite por minuto · de solicitudes fallidas · de cambio de día · de
concurrencia si el diseño la admite. El sistema puede detener nuevas
peticiones antes de agotar su presupuesto interno conocido.

**No afirmes que puede predecir exactamente el consumo de una respuesta que
todavía no se ha generado.**

---

## A4. Corrección de presentación e identidad

### Problema

`config/identidad.json` afirma que EMOTI-BOT tiene funciones de monitoreo de
salud. Esa capacidad no existe. El robot dice de sí mismo algo falso, y es lo
más fácil de cuestionar si alguien le pregunta qué monitorea.

### Requisitos

- Eliminar la afirmación de monitoreo de salud
- Conservar el propósito de acompañamiento conversacional
- Mantener las limitaciones sobre diagnósticos y atención médica
- **Conservar la atribución de autoría actualmente aprobada**
- Revisar otras respuestas de presentación que repitan capacidades inexistentes
- No añadir afirmaciones sobre funciones futuras como si ya estuvieran disponibles

### Criterios de aceptación

El robot responde de forma breve, coherente y verdadera a: ¿Quién eres? ·
¿Qué puedes hacer? · ¿Quién te creó? · ¿Puedes monitorear mi salud? · ¿Qué
limitaciones tienes?

**Al trabajar en este apartado, respeta §13.6.**

---

# FASE 1B — INSTRUMENTACIÓN Y VALIDACIÓN

> **Antes de empezar el bloque B, lee §13.7.** Cuatro de estos apartados no
> los puedes completar tú: requieren que el responsable esté delante. Tu
> entregable en esos casos es el instrumento, y debes declararlo así.

## B1. Línea base y errores del reconocimiento

### Objetivo

Comprobar si los problemas de reconocimiento siguen presentes. Los registros
anteriores daban **4 fallos técnicos de transcripción en 22 interacciones
(18 %)**. Era una incompatibilidad con PyAV, corregida, pero **no hay
mediciones posteriores suficientes**. Si la cadena sigue dando errores,
cualquier medición de precisión mide ruido.

### Procedimiento

Prueba reproducible de al menos 30 intervenciones. Distinguir: fallos
técnicos del motor STT · transcripciones vacías · errores de reconocimiento ·
cortes prematuros de audio · problemas de captura o dispositivo.

**No considerar que 30 intervenciones sin errores demuestran fiabilidad
perfecta.**

### Entregables

Cantidad de intervenciones · errores por categoría · tasa observada ·
condiciones de prueba · versión usada · observaciones · comparación con los
registros anteriores.

---

## B2. Modo de depuración de transcripción

### Objetivo

Que el desarrollador pueda comprobar qué entendió Whisper. Hoy no se registra
la transcripción (decisión deliberada de privacidad), así que **ni el
responsable puede verlo**.

### Requisitos

- Mostrar temporalmente el texto reconocido
- **Desactivado por defecto**
- Activación mediante un control claramente identificado
- **No guardar transcripciones en disco automáticamente**
- No enviarlas a servicios externos
- No modificar el comportamiento habitual del robot
- Poder desactivarse inmediatamente
- Evitar que el texto mostrado termine en registros persistentes
- **Mantener fuera de esta función el contenido de las rutas de seguridad**

### Criterio de aceptación

El desarrollador puede comparar lo dicho con lo reconocido sin comprometer la
política de privacidad vigente.

---

## B3. Evaluación del VAD

### Problema

La configuración usa `silencio_final_s = 0.60`. No sabemos si sirve para
personas que hablan con pausas, y elegir otro número a ojo no es una
solución.

### Prueba

~20 intervenciones controladas con pausas internas de duración conocida:
**0,3 s · 0,5 s · 0,8 s · 1,2 s**.

Registrar: duración de pausa · si hubo corte prematuro · si se conservó la
intervención completa · tiempo desde la última voz hasta el cierre del turno ·
calidad de la transcripción resultante.

La evaluación debe distinguir **un corte real de una nueva intervención
legítima**.

### Resultado esperado

Una tabla pausa → tasa de corte que permita elegir el umbral **por
evidencia**. **No implementes un VAD adaptativo hasta tener datos que
justifiquen su necesidad.**

---

## B4. Medición real de los modelos

### Modelos

| Papel | Modelo | Proveedor |
|---|---|---|
| Conversación | `qwen/qwen3.8-27b` | Groq |
| Razonamiento | `deepseek/deepseek-v4.1-flash-1017:free` | OpenRouter |

### Objetivo

Medir el rendimiento real **desde el entorno de ejecución del proyecto**.

### Métricas

Tiempo de conexión y respuesta · **TTFT (tiempo hasta el primer token)** ·
tiempo de generación completa · tokens de entrada · tokens de salida ·
velocidad efectiva · tiempo hasta el primer sonido · tiempo total de
intervención · errores y rechazos · truncamientos.

Para medir TTFT puedes crear una prueba aislada con streaming, **sin activar
streaming en la aplicación principal**.

### Condiciones

- **Al menos dos franjas horarias.** Los niveles gratuitos son capacidad
  compartida: medir una vez a las tres de la tarde dice cómo va a las tres de
  la tarde. Si el proyecto se va a presentar a una hora concreta, mide **a esa
  hora**
- Documentar dispositivo y conexión
- **Respetar los topes de cuota de §13.5**
- Usar solicitudes de prueba no sensibles
- No asumir que las cifras publicitarias representan el rendimiento local
- **No confundir latencias anteriores de Gemini con Qwen o DeepSeek.** Las
  mediciones previas de ~0,71 s eran de Gemini (n=8), no de estos modelos

### Decisión posterior

Estos datos determinan si el streaming debe priorizarse y si los dos modelos
aportan ventaja suficiente. Referencia del debate: el enrutado dual reparte
una cuota ya estrecha (~195 turnos/día en conversación, ~40 en razonamiento) y
añade un punto de fallo.

---

## B5. Longitud adaptable de las respuestas

### Decisión aprobada (D1)

Longitud adaptable según intención, con límites configurables.

### Nota sobre el orden

Hay una circularidad: **no se puede medir la duración hablada de una
configuración que no existe.** Por tanto el orden es:

1. Valores provisionales, marcados como tales
2. Medir truncamientos, duración hablada y calidad
3. Valores definitivos

Los 40/160 propuestos en el debate **no son los valores definitivos** y no
deben presentarse como tales.

Referencia de magnitud para el diseño: 120 tokens son unas 79 palabras, y 79
palabras habladas en español son **unos 30 segundos de monólogo**. Para un
acompañante conversacional eso es mucho. El problema del tope no es su valor
sino que sea **el mismo** para «¿cómo estás?» y para «ayúdame a ordenar
esto». Incoherencia a resolver: el comparador marca «largo» a partir de 45
palabras mientras el modelo puede generar 79. Hay que elegir una cifra por
ruta y que todas las piezas manden desde ahí.

### Estrategia a diferenciar

Conversación breve · explicación · razonamiento · actividades guiadas ·
interacciones que necesiten aclaración.

### Requisitos

- No introducir límites definitivos arbitrarios
- Revisar la longitud actual de las respuestas
- Medir truncamientos y duración hablada
- Evaluar si las respuestas contestan completamente la pregunta
- Considerar el comportamiento cuando responde un proveedor alternativo
- Conservar el comportamiento apropiado en rutas locales y de seguridad
- Si hacen falta valores provisionales, documentarlos como tales con una
  forma sencilla de revertirlos

### Criterios de aceptación

Las respuestas breves no son innecesariamente largas · las preguntas
complejas reciben explicación suficiente · los límites se configuran sin
modificar múltiples módulos · el enrutamiento alternativo no provoca
truncamientos inesperados · las respuestas no se cortan por restricciones
inconsistentes.

---

## B6. Evaluación a ciegas con varios evaluadores

### Decisión aprobada (D2)

### Objetivo

Protocolo reproducible para evaluar calidad conversacional · coherencia ·
comprensión de la pregunta · utilidad · naturalidad · respeto a la identidad ·
reconocimiento de incertidumbre · continuidad de diálogo.

### Metodología

- Conjunto fijo de ~15–20 situaciones, **incluyendo conversaciones de varios
  turnos**
- Cada configuración recibe **las mismas entradas**
- Respuestas presentadas con identificadores neutrales, sin revelar modelo ni
  configuración
- **Al menos tres evaluadores**; el número final depende de las personas
  disponibles
- **Aleatorizar el orden** y conservar el vínculo respuesta ↔ configuración en
  un archivo separado

### Rúbrica

De 1 a 5 en: comprensión · utilidad · coherencia · naturalidad · adecuación al
contexto.

Registrar además: errores factuales · respuestas truncadas · fallos de
identidad.

### Entregables

Protocolo · batería fija · rúbrica · sistema de presentación anónima ·
formato de resultados · instrucciones para los evaluadores.

**No utilizar conversaciones privadas reales sin consentimiento. No inventar
evaluaciones humanas.**

---

# FASE 1C — PROTOTIPO VISUAL HYBRID BALANCED

## C1. Objetivo

Investigar una evolución visual del rostro **sin sustituir todavía la
interfaz de producción**.

Identidad aprobada: **Hybrid Balanced — adorable, expresiva y futurista.**

Mejorar: proporciones · geometría de los ojos · distribución de rasgos ·
calidad de los contornos · profundidad visual · iluminación · contraste ·
coherencia de expresiones.

**No copiar el diseño de otro robot.**

## C2. Proporciones

Autorizado explorar: marco más refinado · ojos más grandes o estilizados ·
nueva separación ocular · cambios en cejas y boca · módulos laterales ·
ajustes de la barra inferior. Debe mantener identidad reconocible.

## C3. Experimento Tkinter + Pillow

Tkinter Canvas **no tiene antialiasing ni canal alfa**. No es cuestión de
habilidad: los bordes salen dentados y los degradados hay que falsearlos con
figuras premezcladas. Eso limita el techo visual de Hybrid Balanced con el
motor actual.

La propuesta es dibujar el rostro en una imagen RGBA con Pillow —antialiasing
y degradados reales— y mostrarla en el mismo Canvas. Se conserva la ventana,
el bucle de eventos y la arquitectura; solo cambia el interior de `cara.py`.

**Importante: Pillow resuelve el renderizado, no la identidad.** Proporciones
y legibilidad de la expresión son una decisión de diseño separada, que se
evalúa en C4. No confundir las dos.

### Tarea

Prototipo **aislado** que compare:

- **A.** Renderizado actual
- **B.** Renderizado experimental con Pillow

**No sustituyas el sistema vigente durante este bloque.**

### Evaluación

FPS efectivos · tiempo de renderizado por fotograma · consumo de CPU ·
consumo de memoria · estabilidad durante animaciones · impacto junto con
otras tareas del robot si es posible · calidad percibida · artefactos
visuales · escalado a distintas resoluciones.

Considera prerenderizar elementos estáticos y reutilizar recursos.

**El riesgo es el rendimiento en la Raspberry Pi, y es medible antes de
comprometerse. Si no da, se vuelve atrás sin haber tocado nada más.**

**No migres a pygame, SDL u otro framework en esta fase.**

## C4. Expresiones y evaluación humana

Preparar al menos: reposo · escuchando · pensando · hablando · feliz ·
curioso · preocupado. Con geometría coherente.

> **Aclaración (27-11-2026, decisión del responsable).**
> - **«curioso» se quita.** Sin el ámbar era idéntica a «escuchando» y en el
>   sondeo nadie la acertó. «No te oí» y «no te entendí» son la cara de
>   reposo con un «?».
> - **Conjunto de C4: seis expresiones.** Son tranquilo, escuchando, pensando,
>   contento, preocupado y algo va mal; «hablando» y la respiración no caben en
>   una lámina quieta. `config/c4_umbral.json` no cambia: su «sus siete
>   expresiones» se lee ahora sobre estas seis, con el mismo listón (70 %).
> - **Un glifo no es texto.** Sin carcasa no se escribe nada encima de la
>   cara: la regla va contra la interfaz (estado, detalle, avisos), no contra
>   los signos de dibujo animado. Un «!» o un «?» dibujados junto a la cara
>   son parte del rostro y se ven también sin carcasa.

### Prueba de legibilidad

**Mostrar cada expresión sin etiqueta y pedir a personas ajenas al proyecto
que identifiquen la emoción.** Registrar aciertos y confusiones.

Una expresión que no se reconoce falla por bien dibujada que esté. El fallo de
la boca de A1 es, visto así, un fallo de legibilidad.

**El umbral de aceptación debe fijarse ANTES de ver los resultados**
(§13.8c), o se acomodará a lo que salga.

**No sustituir el diseño actual hasta que exista comparación de resultados.**

### Criterios de aceptación

Prototipo ejecutable independientemente · sin cambios destructivos en la
interfaz principal · capturas comparables · datos de rendimiento · registro
de decisiones artísticas · procedimiento de reversión · recomendación
argumentada de adopción o descarte.

---

# 4. ARCHIVOS Y COMPATIBILIDAD

Antes de modificar el proyecto:

1. Inspecciona la estructura actual
2. Verifica qué versión está realmente presente
3. Ejecuta las pruebas existentes cuando el entorno lo permita
4. **Registra los fallos previos en un archivo** (§13.1)
5. Identifica dependencias y rutas relevantes
6. Asegura una forma de recuperar el estado anterior

**Este árbol no es un repositorio Git.** Crea una copia de seguridad
controlada antes de modificar archivos. Si existiera un repositorio válido,
usa un punto de restauración apropiado.

No sobrescribas ni elimines archivos del usuario sin necesidad.

Sobre `emotibot/ia/local.py`: **ver §13.9. La verificación de dependencias ya
está hecha. No es prioridad funcional de esta fase.**

---

# 5. POLÍTICA DE PRUEBAS

Batería general en Windows:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

En Raspberry Pi, el equivalente dentro de su entorno virtual. **No supongas
que la ubicación o el nombre del entorno virtual son iguales en ambos
sistemas.**

### Requisitos

- Ejecutar la batería **antes y después de cada bloque**
- Crear pruebas específicas para los nuevos comportamientos
- Mantener separadas las pruebas simuladas y las de hardware
- **No depender de claves reales para los tests unitarios**
- Evitar consumir cuotas gratuitas innecesariamente
- No guardar contenido sensible en registros
- **No declarar aprobada una prueba que no se haya ejecutado**

Si el entorno no permite ejecutar alguna prueba, **indícalo explícitamente**.

---

# 6. CRITERIOS GENERALES DE ACEPTACIÓN

La Fase 1 se considera completada cuando:

1. Los defectos del Bloque A están corregidos y probados
2. La boca acompaña la reproducción real en los 17 recorridos de emisión
3. Las respuestas truncadas son detectables
4. Existe contabilización de tokens y solicitudes con medidas conservadoras
5. La presentación no afirma monitoreo de salud
6. Existen herramientas para medir reconocimiento, VAD y latencia
7. Existe un procedimiento de evaluación a ciegas
8. La longitud adaptable está diseñada, con límites configurables y valores
   provisionales claramente identificados
9. El prototipo visual puede evaluarse sin sustituir el rostro actual
10. Las funciones existentes mantienen su comportamiento esperado
11. La documentación y la bitácora reflejan los cambios reales
12. El responsable recibe un informe con resultados, limitaciones y pruebas
    pendientes

**Los apartados de §13.7 se consideran completos cuando el instrumento está
entregado, no cuando la medición está hecha.** La medición depende del
responsable.

---

# 7. DOCUMENTACIÓN Y BITÁCORA

Actualiza la documentación técnica después de cada bloque. Como mínimo: qué
problema se corrigió · qué archivos cambiaron · por qué se eligió esa
solución · qué pruebas se ejecutaron · cuáles aprobaron · cuáles fallaron ·
qué resultados se midieron · qué limitaciones permanecen · cómo revertir.

**No sustituyas resultados observados por estimaciones. No presentes
funciones pendientes como terminadas.**

Respeta §13.6 al documentar.

---

# 8. FORMA DE TRABAJO

1. Inspeccionar el proyecto y establecer la línea base
2. Implementar el Bloque A
3. Validar el Bloque A con pruebas
4. Desarrollar los instrumentos del Bloque B y ejecutar lo que el entorno permita
5. Preparar el prototipo aislado del Bloque C (puede solaparse con 4)
6. Consolidar resultados y preparar recomendaciones

**No mezcles modificaciones de varios bloques en una intervención difícil de
auditar.**

Si descubres un defecto nuevo, documenta su impacto y determina si es
imprescindible corregirlo antes de continuar. **Si implica una modificación
importante de arquitectura, detente y pide decisión al responsable.**

---

# 9. INFORME FINAL

Al terminar, entrega:

- **Resumen ejecutivo:** qué se mejoró y qué sigue pendiente
- **Bloque A:** defectos corregidos, archivos modificados, pruebas
- **Bloque B:** instrumentación, resultados y mediciones; **y qué mediciones
  quedan pendientes del responsable**
- **Bloque C:** prototipo visual, rendimiento y comparación
- **Calidad conversacional:** resultados disponibles y limitaciones
- **Seguridad y privacidad:** confirmación de que las rutas de seguridad, la
  privacidad y la gestión de credenciales conservan su comportamiento previsto
- **Regresiones:** problemas nuevos, resueltos o pendientes
- **Recomendaciones:** qué desarrollar en la próxima fase

---

# 10. INSTRUCCIÓN DE INICIO

Antes de modificar cualquier archivo, presenta una auditoría breve con:

- Versión detectada
- Archivos involucrados
- Resultados de la batería de pruebas existente
- **Intérprete en uso (`sys.executable`) y confirmación de que es el del
  entorno virtual**
- Diferencias respecto a esta especificación
- Orden previsto de modificaciones
- Posibles bloqueos o dependencias
- Estrategia de reversión

Si no hay bloqueo importante, procede con el Bloque A y sus pruebas dentro
del alcance aprobado.

**No asumas autorización para cambios fuera de esta especificación.**

---

# 13. ADDENDUM TÉCNICO — CORRECCIONES VERIFICADAS SOBRE CÓDIGO

Las afirmaciones de esta sección se verificaron por inspección directa del
árbol de código el 21 de noviembre de 2026, no por memoria ni por resumen de
conversación. **Donde esta sección contradice a otra, manda esta.**

## 13.1 Línea base confirmada

**94 pruebas, todas en verde.** Antes de modificar un solo archivo, guarda la
salida completa de la batería en un archivo dentro del proyecto. No describas
la línea base: regístrala. Sin eso, «las pruebas anteriores siguen pasando»
es una afirmación no verificable.

Informa además del intérprete en uso y confirma que es el del entorno
virtual. En este proyecto ya hubo diagnósticos contradictorios por usar dos
Python distintos: el comprobador decía que PortAudio estaba disponible y el
diagnóstico decía que faltaba.

## 13.2 Corrección al alcance de A1

El recuento que circuló en el debate (13 recorridos) **era bajo**. Verificado:

```
17 sitios emiten texto hablado
16 de ellos con apertura_boca <= 0.18
 1 solo con boca completa  ->  gestor.py:198
```

De los 15 estados del catálogo, **solo dos tienen `apertura_boca > 0`**:
`hablando` (0.62) y `respirando_exhalar` (0.18).

Los 16 sitios afectados incluyen la ruta de seguridad entera
(`gestor.py:135`), las dos actividades completas (`respiracion.py`,
`ordenar_ideas.py`) y la ruta de respuestas literales (`gestor.py:150`).

**La prueba de aceptación debe recorrer los 17 sitios de emisión, no una
muestra.**

## 13.3 Corrección al alcance de A2 y A3 — CONTRATO COMPARTIDO

El dataclass `Respuesta` de `emotibot/ia/base.py` contiene hoy solo:

```
texto, proveedor, modelo, segundos
```

**No tiene campos para `finish_reason` ni para tokens.** A2 y A3 no son
cambios locales en `openai_compat.py`: obligan a **ampliar un contrato
compartido** que implementan también `gemini.py` y `guion.py`.

**Requisito: todo campo nuevo lleva valor por defecto.** Un campo
obligatorio rompe los otros dos proveedores en silencio.

**Prueba de regresión obligatoria:** los tres proveedores construyen
`Respuesta` sin error tras el cambio.

## 13.4 Estimación de tokens: dirección del error

Los tokens de **entrada se conocen antes de llamar** —el prompt ya está
construido—. Solo la salida es incierta, y está acotada por `max_tokens`.

Reserva previa = entrada estimada al alza + `max_tokens`.

Si no hay tokenizador disponible, estima por caracteres y **sobreestima
deliberadamente**. Quedarse corto provoca un 429, que cuesta el turno más la
pausa de recuperación de 120 segundos. Pasarse solo cuesta un turno de
margen. **El error debe ir hacia arriba.**

Documenta el método de estimación y su error esperado.

## 13.5 Presupuesto de la propia medición (B4)

Las mediciones consumen la misma cuota que el uso real. Con ~50 solicitudes
diarias en OpenRouter, dos franjas de 10 solicitudes gastan el 40 % del día
de DeepSeek en medir.

Topes para toda la Fase 1B:

- **OpenRouter / DeepSeek: máximo 8 solicitudes por franja, 16 en total**
- **Groq / Qwen: máximo 20 por franja**

Si una medición necesita más, **detente y pide autorización**.

No ejecutes mediciones de latencia y batería de evaluación a ciegas el mismo
día sobre el mismo proveedor.

## 13.6 Módulo de intención: no reescribir

**No modifiques `emotibot/dialogo/intencion.py` más allá de lo
imprescindible.** Si una corrección obliga a tocarlo, conserva su contenido
literal sin reescribirlo ni reordenarlo, y **no lo enumeres, cites, resumas
ni describas** en la bitácora, la documentación, los comentarios ni las
pruebas.

Si una tarea pareciera exigir cambiarlo, **detente y pide decisión al
responsable.**

Nota: A1 y A4 te llevan a `gestor.py` y a las respuestas de identidad, que
son adyacentes a este módulo. Ninguna prueba cubre su contenido, así que nada
lo protege automáticamente. Esta cláusula lo protege.

## 13.7 Qué puede y qué no puede completar Claude Code

Cuatro apartados exigen participación física del responsable. Tu entregable
es únicamente el instrumento, y debes declararlo así:

```
B1  30 intervenciones habladas      -> instrumento + guion
B3  20 frases con pausas medidas    -> instrumento + guion
B6  evaluación con 3 evaluadores    -> protocolo + batería
C4  reconocimiento de expresiones   -> láminas + hoja de registro
```

Para estos cuatro, el estado final admitido es **«instrumento entregado,
medición pendiente del responsable»**.

**Está prohibido declararlos completados, estimar sus resultados o
rellenarlos con datos simulados presentados como observados.**

## 13.8 Decisiones que NO debe tomar Claude Code

Las tres siguientes son del responsable y están abiertas:

**a) Política de respuesta truncada (A2):** recortar a la última frase
completa, reintentar con más tokens, o caer al respaldo local.
*Recomendación del debate: recortar a la última frase completa, sin reintento.*

**b) Valores provisionales de longitud por intención (B5).**

**c) Umbral de aceptación del reconocimiento de expresiones (C4).** Debe
fijarse antes de ver los resultados.

Si no hay decisión, implementa la opción más conservadora, **márcala como
provisional** en el código y en la bitácora, y deja la reversión en un solo
punto de configuración.

## 13.9 Estado real de `emotibot/ia/local.py`

**Verificado:** el módulo no existe en la versión canónica y **nada lo
importa**. Todas las referencias a `local` en el proyecto son identificadores
de cadena en `config/proveedores.json`, `config/ajustes.json`,
`emotibot/ajustes.py` y el enum de `gestor.py`. Cero importaciones del
módulo.

En la copia de trabajo del responsable **sí hay un archivo huérfano**
(`emotibot/ia/local.py`, ~4,6 KB, con fecha anterior al resto del árbol). El
respaldo sin conexión funciona a través de la entrada `local` de
`proveedores.json`, no de ese módulo.

Conclusión: borrarlo es de riesgo cero, pero **sigue siendo baja prioridad y
no es requisito de esta fase.**

## 13.10 Dato a no repetir

Las mediciones de latencia previas (`t_ia` ~0,71 s) **son de Gemini, n=8**.
No son de Qwen ni de DeepSeek. Cualquier informe que las presente como
latencia de los modelos actuales está mal. La medición real es B4.

---


# 14. DISTRIBUCIÓN, PERSONALIZACIÓN, SEGURIDAD Y SOSTENIBILIDAD ECONÓMICA

## 14.0 Estado de esta sección — LEER PRIMERO

**Esta sección NO forma parte del alcance de la Fase 1.** No ordena ningún
cambio, ni de modelo, ni de arquitectura, ni de configuración.

Su función es **registrar decisiones ya tomadas y cifras ya verificadas**
para que no haya que rediscutirlas, y para que las correcciones del Bloque A
no se hagan de una forma que las impida después.

Instrucciones para la implementación de la Fase 1:

- **No cambies el modelo de producción.** Qwen3.8-27B sigue siendo el modelo
  de conversación configurado
- **No implementes nada de esta sección** salvo lo que §14.6 marca como
  restricción, que ya es una prohibición vigente
- **Sí ten en cuenta §14.5 y §14.6** al diseñar cualquier cosa que toque
  identidad, preferencias o credenciales, para no cerrar puertas
- Las cifras de §14.2 son **simulaciones condicionadas**, no presupuestos

Las tres categorías están separadas a propósito: **§14.1 decisiones
aprobadas · §14.2 hipótesis económicas · §14.3 pendiente de pruebas.** No
mezclarlas.

---

## 14.1 DECISIONES APROBADAS POR EL RESPONSABLE

### D6. No se sustituye todavía el modelo

GPT-OSS 20B se incorpora como **tercer candidato económico** en la
comparación a ciegas de B6, junto a Qwen3.8-27B y DeepSeek V4.1 Flash.

El cambio definitivo dependerá de cuatro criterios, no solo del precio:
**calidad conversacional · latencia · consumo real de tokens · coste real.**

*Justificación:* todo el esfuerzo de la Fase 1 va dirigido a que el robot
parezca más inteligente y más natural. Cambiar el modelo principal por uno
más barato sin comprobar su calidad podría devolver el proyecto al problema
que está intentando resolver. El precio es un criterio, no el criterio.

### D7. Las cuotas gratuitas no implican facturación automática

Agotar la cuota gratuita de Groq **no activa ningún cobro**. Groq exige pasar
expresamente a un plan de pago y añadir un método de pago.

No se confundirán **precios de catálogo** con **cargos actuales**. Hoy el
proyecto no paga nada, y agotar la cuota produce bloqueo, no factura.

*Justificación:* una afirmación anterior de Claude sugería que al agotarse el
nivel gratuito el proyecto «aterrizaría» en el modelo más caro. Era una
descripción incorrecta del mecanismo. Ver §14.7.

### D8. Demostración escolar: robot físico, usuarios por turnos

La demostración se hará con **un solo robot físico**, con usuarios por
turnos, y **sin ninguna API key distribuida**.

El ejecutable sin terminal sigue siendo prioridad, pero **futura**.

*Justificación:* un solo dispositivo elimina de golpe el problema del
empaquetado, el de la clave distribuida y el del reparto de cuota entre
instalaciones. Es la configuración con menos piezas que pueden fallar
delante de un profesor.

### D9. Treinta instalaciones o más exigen un backend

Para 30 instalaciones o más se estudiará un **backend seguro** con:

- Control de consumo
- Límites por usuario y por dispositivo
- Presupuesto global diario y mensual
- **Interruptor de emergencia**

**No se distribuirán credenciales de proveedores en aplicaciones cliente.**

*Justificación:* ver §14.6. Es una restricción de seguridad, no una
preferencia de diseño.

### D10. Personalización aprobada como dirección futura

| Elemento | Alcance aprobado |
|---|---|
| Primer inicio | Modo estándar o personalizable, modificable después |
| Rostros | 3–4 diseños originales |
| Voces | Cuatro voces locales |
| Personalidad | Configurable |
| Estilo comunicativo | Configurable |
| Longitud de respuesta | Asociada al perfil, **con techo** |
| Idioma | Español inicialmente |

**Las normas de seguridad no serán modificables mediante preferencias.** Ver
§14.5.

*Justificación arquitectónica:* rostro, voz, personalidad y modelo se
configuran **independientemente**. Una cara adorable con voz tranquila y
personalidad analítica no debe requerir un modelo distinto. Los rostros y las
voces se procesan **localmente** y no consumen tokens; la personalidad sí
(§14.2.4).

### D11. Domótica y aplicación móvil fuera de la fase actual

Permanecen como evolución futura. **Se procurará mantener una arquitectura
extensible**, sin construir las capacidades todavía.

*Nota de diseño:* si se llega a la domótica, la IA interpretaría peticiones
flexibles pero el control del dispositivo se ejecutaría mediante
**instrucciones estructuradas con permisos explícitos**, y las acciones
sensibles requerirían confirmación. No se diseña ahora.

---

## 14.2 HIPÓTESIS ECONÓMICAS

> **Todo lo de esta subsección es simulación condicionada al consumo real.**
> No es un presupuesto garantizado. No incluye alojamiento, bases de datos,
> audio en la nube, almacenamiento, atención a usuarios ni costes
> operativos. Si las conversaciones acumulan más contexto o generan más
> texto, el consumo sube.

### 14.2.1 Precios verificados (Groq, noviembre de 2026)

| Modelo | Clasificación | Entrada /1M | Salida /1M | Caché |
|---|---|---|---|---|
| Qwen3.8-27B | **Preview** | $0,80 | $4,00 | **no disponible** |
| GPT-OSS 20B | Production | $0,075 | $0,30 | $0,037 |
| GPT-OSS 120B | Production | $0,15 | $0,60 | $0,075 |

Verificar en la consola antes de cualquier decisión: los precios y las
clasificaciones cambian.

### 14.2.2 Coste por turno con la configuración medida

Configuración medida: **905 tokens de entrada (680 de instrucciones) + 120 de
salida = 1.025 por turno.**

| Modelo | $/turno | Entrada | Salida |
|---|---|---|---|
| Qwen3.8-27B | $0,001204 | 60 % | 40 % |
| GPT-OSS 120B | $0,000208 | 65 % | 35 % |
| GPT-OSS 20B | $0,000104 | 65 % | 35 % |

**GPT-OSS 20B cuesta 11,6 veces menos por turno que Qwen3.8-27B.** Esta es la
cifra que sobrevivió a la verificación de los dos lados.

**Dato importante y contraintuitivo:** las instrucciones del sistema son el
**75 % de los tokens de entrada** pero solo el **60–65 % del coste**, porque
el token de salida cuesta entre 4 y 13 veces más que el de entrada. No
confundir cuota de tokens con cuota de factura.

### 14.2.3 Ahorro real por recortar las instrucciones

Recortar las instrucciones de 680 a 340 tokens (entrada 905 → 565):

| Modelo | Ahorro |
|---|---|
| Qwen3.8-27B | **−22,6 %** |
| GPT-OSS 20B | **−24,5 %** |

**No es el 40 % que se afirmó antes.** La salida no cambia y es la parte
caras por token, así que el recorte no puede escalar linealmente. Ver §14.7.

### 14.2.4 Coste de la personalización

- **Rostros y voces: cero por turno.** Se procesan localmente
- **Personalidad: incremento fijo, no múltiplo.** Unas 80 fichas de
  instrucciones de carácter sobre 580 son un **+14 % por turno**. Cuatro
  personalidades no multiplican por cuatro: solo una está activa
- **Longitud de respuesta configurable: es una perilla sobre la factura.**
  Quien elija «detallada» cuesta el triple en tokens de salida, que son los
  caros. **Por eso D10 exige techo y no un rango abierto**

### 14.2.5 Simulación de 1.000 usuarios

Supuestos: 1.000 usuarios activos diarios · 10 intervenciones de IA cada uno
· 30 días · configuración medida de 905 + 120 · **tarifas de pago, que hoy no
se están pagando.**

| Modelo | Instrucciones actuales | Recortadas a 340 |
|---|---|---|
| Qwen3.8-27B | ~$361/mes | ~$280/mes |
| GPT-OSS 120B | ~$62/mes | ~$47/mes |
| GPT-OSS 20B | **~$31/mes** | **~$24/mes** |

Lectura: **el orden de magnitud del escalamiento no es la quiebra, es la
decena de dólares al mes, siempre que el modelo y el prompt sean los
correctos.** Con el modelo equivocado es más de diez veces eso.

**Lo que sí causa quiebras no es el coste medio: es la ausencia de tope.** Un
usuario en bucle, un error que reintenta o alguien abusando, sin límite por
encima, es el modo de fallo real. De ahí D9.

### 14.2.6 El nivel gratuito y la demostración

Cuotas gratuitas de Groq, **idénticas para GPT-OSS 20B y para Qwen3.8-27B**:

```
30 solicitudes/minuto · 1.000 solicitudes/día
8.000 tokens/minuto   ·  200.000 tokens/día
```

**Cambiar de modelo no da más tokens gratuitos.** La ventaja de GPT-OSS es el
precio cuando se pase a un plan de pago, la velocidad y la caché.

Capacidad de la cuota diaria:

| Configuración | Tokens/turno | Turnos/día | 30 personas |
|---|---|---|---|
| Actual | 1.025 | 195 | 6,5 cada una |
| Instrucciones a 340 | 685 | 292 | 9,7 cada una |

**Treinta personas con diez intervenciones cada una son 205.500 tokens, y la
cuota diaria son 200.000. Se pasa.** Por poco, pero se pasa.

Planificación de la demostración: **presupuestar 9 intervenciones por
persona, no 10**, reservar margen, y no dar por garantizadas las 300.

Límite por minuto, que es el más agresivo:

| Configuración | Turnos/minuto |
|---|---|
| Actual | 7,8 |
| Instrucciones a 340 | 11,7 |

**Un grupo agolpado alrededor del robot topa el límite por minuto en menos de
un minuto de uso activo.** De ahí los requisitos de §14.4.

---

## 14.3 PENDIENTE DE PRUEBAS

Nada de esta lista está decidido. Son las preguntas que las pruebas deben
responder.

| Asunto | Qué hay que saber | Dónde se mide |
|---|---|---|
| Calidad de GPT-OSS 20B | ¿Iguala a Qwen en español conversacional, sensibilidad y razonamiento? | B6, a ciegas |
| **Tokens de razonamiento de GPT-OSS** | Es un modelo de razonamiento: su esfuerzo se configura en bajo/medio/alto pero **no se puede desactivar**. Los tokens de razonamiento pueden elevar la salida real muy por encima de 120, y la salida es la parte caras | B4 + contabilidad de A3 |
| Aciertos de caché | El descuento solo aplica cuando la caché acierta, y **Qwen no la admite** | B4 |
| Latencia real | Groq anuncia ~1.000 tok/s para GPT-OSS 20B frente a ~450 para Qwen. **Cifras de catálogo, no medidas aquí** | B4 |
| Las cuatro voces | **Calidad audible, licencia de cada voz y compatibilidad con el hardware.** No se implementan cuatro voces porque sean baratas: hay que escucharlas primero | Fase de personalización |
| Legibilidad de 3–4 rostros | Cada rostro necesita su propia validación de expresiones. Cuatro rostros son cuatro validaciones | C4, por rostro |
| Privacidad del backend | Un backend protege las claves pero **introduce responsabilidades de autenticación, almacenamiento y datos personales** que hay que diseñar | Antes de D9 |

**La contabilidad de tokens de A3 es el instrumento que resuelve la mitad de
esta tabla.** Por eso A3 va en la Fase 1 y el cambio de modelo no.

---

## 14.4 REQUISITOS DE LA DEMOSTRACIÓN ESCOLAR

Aprobados. **Implementación posterior a la Fase 1.**

1. **Inicio automático.** Encender la Raspberry Pi y entrar directamente a
   EMOTI-BOT, sin terminal ni escritorio visible
2. **Cola visible.** El robot indica en qué estado está
3. **Respaldo sin internet.** Funciones locales demostrables aunque falle la
   conexión
4. **Presupuesto reservado.** Separar una parte de la cuota diaria
   exclusivamente para la presentación, y hacer pruebas de uso intensivo
   antes

### 14.4.1 Los tres estados deben distinguirse

**Mostrar «estoy pensando» cuando en realidad se agotó la cuota sería
engañoso.** Un acompañante de bienestar no puede mentir sobre su propio
estado.

El robot debe distinguir visualmente:

| Estado | Significado |
|---|---|
| Procesando | Está trabajando normalmente |
| Esperando | Topó el límite por minuto; volverá en seguida |
| No disponible | Cuota agotada o sin conexión; funciona lo local |

### 14.4.2 El riesgo real de la presentación

Por orden de probabilidad, no de gravedad:

1. **El wifi del aula.** Es el fallo más probable de todos
2. **El límite por minuto**, con gente agolpada
3. **La cuota diaria**, si se hacen pruebas el mismo día
4. El coste. Son centavos

**El respaldo sin conexión no es un extra: es el seguro de la
presentación.**

---

## 14.5 PERSONALIZACIÓN: LO QUE NO PUEDE CAMBIAR

La personalidad puede cambiar el **tono**. No puede cambiar lo siguiente,
por ninguna vía de preferencias, perfil ni configuración:

- **No puede desactivar, suavizar ni retrasar la ruta de crisis**
- **No puede hacer que el robot afirme capacidades que no tiene**, médicas
  incluidas (ver D3)
- **No puede volverlo cortante, burlón ni duro con alguien que está mal**
- No puede alterar la atribución de autoría
- No puede levantar los topes de longitud ni de consumo

*Justificación:* un acompañante de bienestar con actitud configurable sin
límites es un riesgo real, no un detalle de diseño. La personalidad y las
normas de seguridad se implementan en capas separadas, y la de seguridad no
recibe parámetros de la de personalidad.

---

## 14.6 SEGURIDAD DE LA DISTRIBUCIÓN — RESTRICCIÓN VIGENTE

**Esta es la única parte de §14 que rige ya.**

**Prohibido incrustar una API key en cualquier artefacto distribuible:**
ejecutable, instalador, imagen de tarjeta, repositorio o paquete.

*Justificación:* una clave dentro de un binario distribuido se extrae en
minutos. Treinta copias con la misma clave son treinta personas capaces de
agotar el presupuesto del proyecto, y una de ellas basta. Groq recomienda
expresamente usar un servidor intermediario y no incrustar la clave en una
aplicación distribuida.

Las tres configuraciones admisibles:

| Configuración | Dónde vive la clave | Cuándo |
|---|---|---|
| Un solo robot | En el dispositivo del equipo, no se distribuye | **La demostración (D8)** |
| Backend propio | Solo en el servidor, con topes por usuario | 30 instalaciones o más (D9) |
| Cada usuario trae su clave | La suya | Rompe el «sin configurar nada» |

El sistema de credenciales actual (una clave por proveedor, permisos 0600,
redacción obligatoria en registros) **ya cumple esta restricción para el
escenario de un solo robot.** No hay que cambiarlo en la Fase 1.

---

## 14.7 CORRECCIONES A CIFRAS QUE CIRCULARON EN EL DEBATE

Registradas para que nadie las reutilice. Todas son correcciones a
afirmaciones de Claude, verificadas por ChatGPT contra la documentación de
Groq y recomprobadas aritméticamente.

| Afirmación anterior | Corrección |
|---|---|
| «Al agotarse el gratis aterrizan en el modelo más caro» | **Incorrecto.** Agotar la cuota gratuita no factura nada. Hay que pasar expresamente a un plan de pago |
| «Las instrucciones son el 75 % de la factura» | **Incorrecto.** Son el 75 % de los **tokens de entrada**, pero el 60–65 % del **coste**. La salida cuesta de 4 a 13 veces más por token |
| «Recortar el prompt a la mitad baja ~40 % el coste» | **Incorrecto.** −22,6 % con Qwen, −24,5 % con GPT-OSS 20B |
| «Tras el recorte son 580 tokens por turno» | **Incorrecto.** Son **685**. El 580 salía de mezclar el supuesto de 800 tokens de entrada de ChatGPT con los 905 realmente medidos |
| «Con el recorte el demo cabe en la cuota gratuita» | **Incorrecto.** 685 × 300 = **205.500**, contra 200.000 de cuota. Se pasa |
| «La caché reduce a la mitad la entrada» | **Correcto pero condicionado.** Solo con aciertos de caché, y **Qwen3.8 no la admite** |
| «Mil usuarios cuestan $39/mes» | **Escenario optimizado, no presupuesto.** Con la configuración medida son ~$31/mes con GPT-OSS 20B, y la cifra no incluye infraestructura ni audio en la nube |
| «Las cuatro voces son casi gratis» | **Cierto en coste de API, incompleto.** Faltaba verificar calidad audible, licencia de cada voz y compatibilidad con el hardware |

**Patrón:** todos los errores iban en la misma dirección, hacia el
optimismo. Conviene pedir verificación de cualquier cifra económica que no
venga acompañada de su aritmética.

### Lo que sí sobrevivió a la verificación

- GPT-OSS 20B cuesta **11,6 veces menos por turno** que Qwen3.8-27B
- **Qwen3.8-27B está clasificado Preview** y puede retirarse con poca
  antelación; GPT-OSS 20B es Production. **Esta es la razón más grave para
  no construir producción sobre Qwen, y no tiene nada que ver con el precio**
- Una API key nunca puede viajar dentro de una aplicación distribuida
- Los riesgos reales de la presentación son el wifi, el límite por minuto y
  la cuota, no el coste
- El kiosco de arranque automático vale más, para presentar, que cuatro
  personalidades

---

**Fin de la especificación.**
