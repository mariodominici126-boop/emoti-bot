"""Las siete expresiones del protocolo C4: (estado funcional, expresión).

Módulo aparte, sin tkinter ni Pillow, para que las pruebas y los scripts
que solo necesitan la lista puedan cargarse en una máquina sin entorno
gráfico.
"""

EXPRESIONES_C4 = {
    "reposo": ("reposo", "reposo"),
    "escuchando": ("escuchando", "escuchando"),
    "pensando": ("pensando", "pensando"),
    "hablando": ("hablando", "hablando"),
    "feliz": ("reposo", "feliz"),
    "curioso": ("reposo", "curioso"),
    "preocupado": ("reposo", "preocupado"),
}
