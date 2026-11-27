# Auditoría inicial — Fase 1 (21-11-2026)

Hecha antes de modificar ningún archivo del código, según §10 de la
especificación.

## Versión detectada

- El árbol es la **v1.7** según `docs/BITACORA.md` (entrada «v1.7 — Los dos
  modelos, en sus planes gratuitos»).
- Pero las cadenas de versión del código dicen `"1.0"`:
  `emotibot/__init__.py` (`__version__`) y `emotibot/app.py` (`VERSION`, que es
  el título de la ventana). No se han actualizado desde la reestructuración.
- No es un repositorio Git.

## Intérprete

```
sys.executable = .venv\Scripts\python.exe
sys.prefix     = .venv
base_prefix    = %USERPROFILE%\AppData\Local\Programs\Python\Python313
Python 3.13.15
```

`sys.prefix != sys.base_prefix`: es el entorno virtual del proyecto.

## Batería existente

**94 pruebas, todas en verde (1,2 s).** La salida completa, con el nombre de
cada prueba, está en [`linea_base_pruebas.txt`](linea_base_pruebas.txt).

## Copia de seguridad

`%USERPROFILE%\Desktop\emoti-bot-respaldos\emoti-bot-v1.7-20261121-203009.tar.gz`
(fuera del proyecto; excluye `.venv` y `__pycache__`).

Restaurar:

```powershell
tar -xzf %USERPROFILE%\Desktop\emoti-bot-respaldos\emoti-bot-v1.7-20261121-203009.tar.gz -C %USERPROFILE%\Desktop\emoti-bot
```

## Archivos implicados

| Bloque | Archivos |
|---|---|
| A1 | `emotibot/rostro/estados.py`, `emotibot/rostro/cara.py`, `emotibot/app.py`, `tests/test_rostro.py`, prueba nueva de los 17 sitios |
| A2 | `emotibot/ia/base.py`, `openai_compat.py`, `gemini.py`, `orquestador.py`, `guion.py`, `emotibot/metricas.py`, `config/ajustes.json`, `emotibot/ajustes.py` |
| A3 | `emotibot/ia/presupuesto.py`, `openai_compat.py`, `gemini.py`, `config/proveedores.json` |
| A4 | `config/identidad.json`, `emotibot/ia/guion.py` |

`emotibot/dialogo/intencion.py` no se toca (§13.6).

## Verificación de §13

- §13.2 confirmado: 17 sitios de emisión (7 en `gestor.py`, 6 en
  `respiracion.py`, 4 en `ordenar_ideas.py`); solo la conversación usa
  `hablando`.
- §13.3 confirmado: `Respuesta` tiene solo `texto, proveedor, modelo,
  segundos`. La construyen `openai_compat.py`, `gemini.py`, `guion.py`, el
  huérfano `local.py` y `tests/test_dialogo.py`.
- §13.9 confirmado: `emotibot/ia/local.py` existe y nada lo importa.

## Diferencias respecto a la especificación

1. **Versión en el código = "1.0"**, no 1.7 (ver arriba).
2. **Un segundo defecto dentro de A1.** `ordenar_ideas.py` pronuncia sus
   preguntas con el estado `escuchando`, que enciende el indicador de
   micrófono (la barra de la barbilla y «● micrófono abierto») **mientras el
   robot habla y el micrófono está cerrado**. Lo cubre el criterio «el
   indicador de escucha solo señala captura real», y se corrige en A1.
3. **Las solicitudes fallidas no se cuentan.** `registrar_consulta` solo se
   llama si la respuesta llega bien, aunque `config/proveedores.json` dice
   que en OpenRouter las fallidas también cuentan. Se corrige en A3
   («contabilizar intentos»).
4. **Atribución de autoría.** `config/identidad.json` dice «el grupo Emoti».
   Los valores por defecto del código (`identidad.py`) y el docstring de
   `emotibot/__init__.py` dicen «Mario». Solo se usan si falta el archivo. No
   lo cambio: la atribución no se toca sin autorización (D3).
5. **Ratio real de caracteres por token.** Las instrucciones del sistema
   tienen 2.447 caracteres. Si son 680 tokens (§A3), salen 3,6 caracteres por
   token. Con ese dato se calibra la estimación de A3.
6. **El respaldo sin conexión no sabe contestar** «¿puedes monitorear mi
   salud?» ni «¿qué limitaciones tienes?»: el guion cae en una frase genérica
   de acompañamiento. Con conexión lo contesta el modelo a partir de las
   instrucciones. Se corrige en A4.

## Orden de modificaciones

1. A1, separación entre estado funcional y expresión, y su prueba de los 17 sitios
2. A2 + A3 juntos en el contrato `Respuesta`: comparten el cambio de
   `base.py`. Se ejecutan en pasos separados y auditables
3. A4, identidad
4. Batería completa y bitácora

## Bloqueos o dependencias

Ninguno bloqueante para el Bloque A. Las decisiones §13.8a/b/c siguen
abiertas. Para a) se implementa la opción conservadora provisional.

## Estrategia de reversión

- Global: restaurar el `.tar.gz` de arriba.
- Por bloque: cada cambio queda descrito en `docs/BITACORA.md` con sus archivos.
- La política de truncado se revierte desde un solo ajuste
  (`ia.politica_truncado`).
