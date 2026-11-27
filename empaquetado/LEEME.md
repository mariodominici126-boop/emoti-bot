# Ejecutable de Windows (PyInstaller, --onedir)

Construir (desde la raíz, con el entorno de `requisitos-ejecutable-windows.txt`):

```powershell
.venv\Scripts\python.exe -m pip install -r empaquetado\requisitos-ejecutable-windows.txt
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist --workpath build empaquetado\EmotiBot.spec
```

Requisitos previos en la máquina que construye: Whisper `small` en la caché de
Hugging Face y `~/emoti-voices/es_MX-claude-high.onnx` (+ `.onnx.json`).

| Dentro del paquete | Fuera (a petición) |
|---|---|
| voz `claude` (Apache-2.0, con `voces/LICENCIA_VOZ_CLAUDE.txt`) | voz `daniela` (CC BY-SA 4.0): se baja al elegirla |
| Whisper `small` (conversación) | Whisper `base` (solo «Hola Emoti»): se baja al encenderlo |

- **PyAV** no va: `sustitutos/av` es un módulo vacío. faster-whisper lo importa
  pero EMOTI-BOT solo le pasa muestras de numpy (`stt/whisper_local.py`).
- **Hebreo y árabe de Piper** (`nakdimon.onnx`, `tashkeel/model.onnx`) no van.
- **Registros**: `%LOCALAPPDATA%\emotibot\logs` (la carpeta del programa puede
  no admitir escritura).
- Sin red en el primer arranque: habla con `claude`, conversa con `small`; la
  voz elegida y «Hola Emoti» esperan a la próxima vez con red. ESPACIO funciona.
