"""Sustituto VACÍO de PyAV, solo para el ejecutable de Windows.

faster-whisper hace `import av` al cargarse, pero EMOTI-BOT nunca le pasa un
archivo: le pasa siempre muestras float32 de numpy (stt/whisper_local.py,
el único sitio que llama a `transcribe`), y con eso faster-whisper no toca
PyAV. Así se ahorran sus ~68 MB de FFmpeg. Si algún día algo intentara
decodificar un archivo, falla aquí con un mensaje claro en vez de en una DLL.
"""


def __getattr__(nombre):
    raise RuntimeError(
        f"PyAV no va en el ejecutable (se pidió av.{nombre}). EMOTI-BOT solo "
        "pasa a Whisper muestras de numpy; decodificar archivos no está soportado.")
