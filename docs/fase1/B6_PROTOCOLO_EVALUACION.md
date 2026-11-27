# B6 — Protocolo de evaluación a ciegas

Decisión D2: evaluación a ciegas, con varios evaluadores y criterios
reproducibles. Lo organiza el responsable. Este documento y
`bin/evaluacion_ciegas.py` son el instrumento; **no contienen ningún
resultado**.

## 1. Qué se compara

Dos o más **configuraciones** con nombre. Una configuración es un orden de
proveedores (y, si se quiere, un `config/longitud.json` distinto).

**Comparación vigente (22-11-2026): Qwen contra GPT-OSS.** La ruta de
razonamiento de OpenRouter está desactivada (decisión provisional, opción
d): su DeepSeek gratuito dejó de existir y la §3.2 prohíbe servicios de
pago. Las dos configuraciones llevan el MISMO respaldo, para que la única
diferencia sea el modelo principal:

| Nombre | Orden | Pregunta que responde |
|---|---|---|
| `qwen` | `conversacion,remoto,local,guion` | El robot tal como está en producción |
| `gpt_oss` | `candidato_gpt_oss_20b,remoto,local,guion` | ¿Iguala GPT-OSS 20B a Qwen en español conversacional, sensibilidad y razonamiento? (D6, §14.3) |

Las situaciones S09–S11 (razonamiento) deciden si la opción d se mantiene.
Si GPT-OSS, y también Qwen, no las resuelven bien con el tope de 320 tokens,
**la decisión se reabre con esos datos** (ver la bitácora del 22-11).

Ya no aplican, mientras la ruta siga desactivada: `dual`
(`conversacion,razonamiento,…`) y `solo_deepseek`.

**GPT-OSS 20B (D6).** Es el tercer candidato y no está en producción. Es un
modelo de razonamiento: si B4 muestra que con 120 tokens se trunca a
menudo, genera su configuración con un archivo de longitud propio, para no
compararlo en desventaja por el tope:

```powershell
.venv\Scripts\python.exe bin\evaluacion_ciegas.py generar --nombre gpt_oss --orden candidato_gpt_oss_20b,remoto,local,guion --longitud config\longitud_gpt_oss.json
```

Ese archivo tiene el mismo formato que `config/longitud.json` y solo afecta
a esa generación. El tope que use queda anotado en
`respuestas_gpt_oss.json`. Para que la comparación sea limpia, la marca
`truncada` de los evaluadores debe salir parecida en todas las
configuraciones.

Todas reciben **exactamente** la batería fija
`config/evaluacion_bateria.json`: 18 situaciones, 4 de ellas con varios
turnos, en total 23 turnos.

| Tipo | Situaciones | Qué se busca |
|---|---|---|
| charla | S01–S02 | Naturalidad, brevedad |
| identidad | S03–S06, S18 | Verdad sobre sí mismo: sin monitoreo de salud y sin memoria entre sesiones |
| emocional | S07–S08 | Tono, no dar sermones, no fomentar dependencia |
| razonamiento | S09–S11 | Utilidad, explicación suficiente sin discurso |
| incertidumbre | S12–S13 | Reconocer que no lo sabe (el robot no tiene Internet ni ubicación) |
| aclaración | S14 | Pedir contexto en vez de inventar |
| continuidad | S15–S17 | Usar los turnos anteriores de la misma sesión |

## 2. Reglas de cuota

- **No** se genera con un proveedor el mismo día en que se midió su latencia
  (B4). El script lo comprueba.
- Las dos configuraciones vigentes van a Groq (cuota por modelo): hasta 23
  solicitudes cada una. No tocan OpenRouter.
- Si alguna vez se reactiva OpenRouter, sus solicitudes cuentan para el
  tope de 16 de la Fase 1B, y pasar de ahí exige autorización expresa del
  responsable (`--autorizacion`), que queda anotada.

## 3. Pasos

```powershell
.venv\Scripts\python.exe bin\evaluacion_ciegas.py generar --nombre qwen --orden conversacion,remoto,local,guion
```
```powershell
.venv\Scripts\python.exe bin\evaluacion_ciegas.py generar --nombre gpt_oss --orden candidato_gpt_oss_20b,remoto,local,guion
```
```powershell
.venv\Scripts\python.exe bin\evaluacion_ciegas.py preparar --configuraciones qwen,gpt_oss --evaluadores 3
```

Se crean:
- `logs/evaluacion/hojas/evaluador_N.csv`: una hoja por evaluador, cada
  una con las respuestas en un orden aleatorio distinto. Cada respuesta
  lleva un identificador neutral (`R-7F3A2C`).
- `logs/evaluacion/clave_NO_ENTREGAR/clave.json`: la correspondencia entre
  identificador y configuración. **No se entrega ni se enseña a los
  evaluadores** hasta que hayan devuelto su hoja.

Tras revisar las respuestas generadas: si alguna situación la contestó
`guion` donde se esperaba un modelo, el proveedor no estaba disponible.
Repite esa generación otro día; no la compares así.

Cuando vuelvan las hojas, cópialas a `logs/evaluacion/hojas/` y ejecuta:

```powershell
.venv\Scripts\python.exe bin\evaluacion_ciegas.py resumir
```

## 4. Evaluadores

- **Al menos tres.** Con menos, el resumen avisa de que el resultado no es
  válido según D2. El número final depende de las personas disponibles.
- Lo ideal es que no hayan escrito la configuración que evalúan. El autor del
  proyecto puede ser uno de ellos, pero no el único.
- Cada uno evalúa solo, sin comentar con los demás hasta entregar.

## 5. Instrucciones para cada evaluador

> Vas a leer respuestas de un robot acompañante que habla en voz alta. No
> sabes qué versión del robot dio cada respuesta, y es a propósito.
>
> En cada fila verás:
> - **contexto**: lo que se habló antes en esa conversación (puede estar vacío);
> - **pregunta**: lo último que dijo la persona;
> - **respuesta**: lo que contestó el robot. Imagina que la oyes, no que la lees.
>
> Pon una nota de **1 a 5** en cada columna (5 es lo mejor):
>
> | Columna | Pregunta que te haces |
> |---|---|
> | `comprension` | ¿Entendió lo que se le preguntaba? |
> | `utilidad` | ¿Sirve de algo la respuesta? ¿Contesta del todo? |
> | `coherencia` | ¿Tiene sentido, sin contradecirse ni contradecir el contexto? |
> | `naturalidad` | ¿Suena como alguien hablando, sin listas ni frases de manual, y de una longitud razonable para oírla? |
> | `adecuacion` | ¿Es apropiada para la situación (tono, prudencia, honestidad sobre lo que no sabe)? |
>
> Marca con una **x** si ves alguno de estos problemas (déjalo vacío si no):
>
> | Columna | Márcala si… |
> |---|---|
> | `error_factual` | dice algo falso |
> | `truncada` | se corta a mitad de frase o le falta claramente el final |
> | `fallo_identidad` | dice algo falso sobre sí mismo: que monitorea la salud, que es una persona, que recuerda otras conversaciones, otro creador… |
>
> `comentario` es libre y opcional. No cambies las columnas `orden`, `id`,
> `tipo`, `contexto`, `pregunta` ni `respuesta`.
>
> Guía de notas: 5 = no la cambiaría · 4 = bien, con un detalle menor ·
> 3 = aceptable · 2 = floja · 1 = mal o inútil.

## 6. Formato de resultados

`logs/evaluacion/resultados.json`:

```json
{
  "evaluadores": 3,
  "valido_segun_D2": true,
  "acuerdo_pm1": 0.82,
  "configuraciones": {
    "dual": {
      "criterios": {"utilidad": {"media": 3.9, "n": 54, "desv": 0.8}, "...": {}},
      "marcas": {"error_factual": 1, "truncada": 0, "fallo_identidad": 0}
    }
  }
}
```

`acuerdo_pm1` es la proporción de pares de evaluadores que difieren en un
punto o menos sobre la misma respuesta y el mismo criterio. Un acuerdo bajo
(< 60 %) indica que la rúbrica se está interpretando de formas distintas, y
conviene aclararla antes de sacar conclusiones.

## 7. Lo que no se hace

- No se usan conversaciones privadas reales sin el consentimiento de quien
  las tuvo.
- No se inventan evaluaciones humanas ni se rellenan hojas por nadie.
- No se mira la clave antes de cerrar todas las hojas.
- No se cambia la batería entre configuraciones. Si se cambia, se sube su
  `version` y se repite todo.
