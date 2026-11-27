"""Proveedor local vía servidor compatible con OpenAI (llama.cpp, Ollama…).

Pensado para `llama-server` de llama.cpp en la propia Raspberry Pi:

    llama-server -m qwen2.5-1.5b-instruct-q4_k_m.gguf -c 2048 --port 8080

Expectativa realista, no promesa: en una Pi 5 de 8 GB un modelo de 1–1,5 B
cuantizado a 4 bits ronda los 10–17 tokens por segundo, y uno de 3 B baja a
unos pocos. Sirve para respuestas breves y para sostener el robot cuando no
hay red; NO iguala la calidad conversacional de un modelo remoto grande, y
este módulo no pretende lo contrario.

Se usa urllib de la biblioteca estándar: una dependencia menos que instalar
en el dispositivo.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .. import registro
from ..ajustes import AjustesIa
from .base import Clase, ErrorProveedor, Peticion, Respuesta

log = registro.obtener("ia.local")

_TIEMPO_SONDEO = 1.5


class ProveedorLocal:
    nombre = "local"

    def __init__(self, config: AjustesIa) -> None:
        self.config = config
        self.base = config.url_local.rstrip("/")
        self.modelo = config.modelo_local
        self.ultimo_motivo = ""
        self._ultimo_sondeo = 0.0
        self._estaba_vivo = False

    # ------------------------------------------------------------ disponibilidad
    def disponible(self) -> bool:
        if not self.base:
            self.ultimo_motivo = "Sin servidor local configurado."
            return False
        ahora = time.monotonic()
        # El sondeo se repite como mucho cada 15 s: no tiene sentido golpear
        # el servidor en cada turno.
        if ahora - self._ultimo_sondeo < 15.0:
            return self._estaba_vivo
        self._ultimo_sondeo = ahora
        self._estaba_vivo = self._sondear()
        if not self._estaba_vivo:
            self.ultimo_motivo = "El servidor local no responde."
        return self._estaba_vivo

    def _sondear(self) -> bool:
        for sufijo in ("/health", "/v1/models"):
            try:
                peticion = urllib.request.Request(self.base + sufijo, method="GET")
                with urllib.request.urlopen(peticion, timeout=_TIEMPO_SONDEO) as r:
                    if 200 <= r.status < 300:
                        return True
            except (urllib.error.URLError, OSError, ValueError):
                continue
        return False

    # ------------------------------------------------------------------ consulta
    def responder(self, peticion: Peticion) -> Respuesta:
        mensajes = [{"role": "system", "content": peticion.instrucciones}]
        for turno in peticion.historial:
            mensajes.append({"role": "user", "content": turno.usuario})
            mensajes.append({"role": "assistant", "content": turno.robot})
        mensajes.append({"role": "user", "content": peticion.texto})

        cuerpo = json.dumps({
            "model": self.modelo,
            "messages": mensajes,
            "temperature": self.config.temperatura,
            "max_tokens": self.config.max_tokens_respuesta,
            "stream": False,
        }).encode("utf-8")

        solicitud = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=cuerpo,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        inicio = time.monotonic()
        try:
            with urllib.request.urlopen(
                solicitud, timeout=self.config.timeout_local_ms / 1000.0
            ) as respuesta:
                datos = json.loads(respuesta.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            raise ErrorProveedor(
                Clase.OTRO, f"El servidor local devolvió HTTP {exc.code}."
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ErrorProveedor(Clase.RED, f"Servidor local inaccesible: {exc}") from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise ErrorProveedor(Clase.TIEMPO, f"Respuesta local inválida: {exc}") from exc

        try:
            texto = datos["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ErrorProveedor(Clase.VACIA, "Respuesta local sin contenido.") from exc
        if not texto:
            raise ErrorProveedor(Clase.VACIA, "Respuesta local vacía.")

        return Respuesta(
            texto=texto,
            proveedor=self.nombre,
            modelo=self.modelo,
            segundos=time.monotonic() - inicio,
        )
