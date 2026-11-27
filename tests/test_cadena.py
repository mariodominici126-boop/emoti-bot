"""Cadena completa de audio con motores simulados.

Valida la integración captura → recorte → reproducción sin tocar ningún
dispositivo real, que es lo que permite comprobarla en cualquier máquina y en
integración continua.

El motor falso entrega bloques al instante, sin esperar al ritmo real del
audio. Eso es deliberado: comprueba que el recorte funciona por índice de
bloque y no por marca de tiempo. Con el cálculo anterior, basado en tiempos,
esta prueba recortaba el 100 % del audio.
"""
import array
import math
import threading
import time
import unittest

from emotibot.ajustes import cargar
from emotibot.audio import motores
from emotibot.audio.captura import Microfono, MotivoFin
from emotibot.audio.reproduccion import Altavoz

BLOQUES_RUIDO = 16
BLOQUES_VOZ = 34


def tono(amplitud: int, muestras: int) -> bytes:
    return array.array(
        "h", [int(amplitud * math.sin(i * 0.1)) for i in range(muestras)]
    ).tobytes()


class EntradaFalsa:
    """Ruido, luego voz, luego silencio: la forma de un turno real."""

    nombre = "falso"

    def __init__(self) -> None:
        self.llamadas = 0
        self.cerrada = False

    def iniciar(self) -> None:
        self.cerrada = False

    def leer(self, max_bytes: int) -> bytes:
        self.llamadas += 1
        muestras = max_bytes // 2
        if self.llamadas <= BLOQUES_RUIDO:
            return tono(60, muestras)
        if self.llamadas <= BLOQUES_RUIDO + BLOQUES_VOZ:
            return tono(7000, muestras)
        return tono(40, muestras)

    def cerrar(self) -> None:
        self.cerrada = True


class SalidaFalsa:
    nombre = "falso"
    latencia_buffer_s = 0.01

    def __init__(self) -> None:
        self.bytes_escritos = 0
        self.vaciados = 0
        self.frecuencia = 0
        self.cerrada = False

    def abrir(self, frecuencia: int) -> None:
        self.frecuencia = frecuencia

    def escribir(self, pcm: bytes) -> None:
        self.bytes_escritos += len(pcm)

    def vaciar(self) -> None:
        self.vaciados += 1

    def cerrar(self) -> None:
        self.cerrada = True


class CadenaTest(unittest.TestCase):
    def setUp(self):
        self.config = cargar()
        self.entrada = EntradaFalsa()
        self.salida = SalidaFalsa()
        self._crear_entrada = motores.crear_entrada
        self._crear_salida = motores.crear_salida
        self._hay_entrada = motores.hay_entrada
        self._hay_salida = motores.hay_salida
        motores.crear_entrada = lambda c, b, d=None: self.entrada
        motores.crear_salida = lambda c: self.salida
        motores.hay_entrada = lambda c: True
        motores.hay_salida = lambda c: True

    def tearDown(self):
        motores.crear_entrada = self._crear_entrada
        motores.crear_salida = self._crear_salida
        motores.hay_entrada = self._hay_entrada
        motores.hay_salida = self._hay_salida

    # ------------------------------------------------------------- captura
    def test_detecta_voz_y_recorta_a_la_parte_util(self):
        captura = Microfono(self.config.audio).escuchar(threading.Event())
        self.assertIs(captura.motivo, MotivoFin.SILENCIO)
        self.assertTrue(captura.hay_voz)
        # 34 bloques de voz + 4 de pre-voz + 5 de cola, a 50 ms cada uno.
        self.assertGreater(captura.duracion_util_s, 1.5)
        self.assertLess(captura.duracion_util_s, 2.6)
        self.assertTrue(self.entrada.cerrada, "el micrófono debe cerrarse")

    def test_cancelar_cierra_el_microfono(self):
        cancelar = threading.Event()
        cancelar.set()
        captura = Microfono(self.config.audio).escuchar(cancelar)
        self.assertIs(captura.motivo, MotivoFin.CANCELADO)
        self.assertTrue(self.entrada.cerrada)

    # -------------------------------------------------------- reproducción
    def test_avisa_del_primer_sonido_y_escribe_todo(self):
        avisos: list[float] = []
        fin = threading.Event()
        altavoz = Altavoz(self.config.audio)
        try:
            altavoz.hablar(
                iter([tono(9000, 4000), tono(9000, 4000)]), 22050,
                al_primer_sonido=lambda: avisos.append(time.monotonic()),
                al_terminar=lambda completo: fin.set(),
            )
            self.assertTrue(fin.wait(timeout=5), "el turno no terminó")
        finally:
            altavoz.cerrar()
        self.assertEqual(len(avisos), 1, "el aviso llega una sola vez")
        self.assertEqual(self.salida.bytes_escritos, 16000)
        self.assertEqual(self.salida.frecuencia, 22050)

    def test_interrumpir_vacia_el_buffer(self):
        """Sin vaciar, el robot seguiría sonando tras pedirle que pare."""
        fin = threading.Event()
        altavoz = Altavoz(self.config.audio)

        def muchos():
            for _ in range(400):
                yield tono(9000, 4000)

        try:
            altavoz.hablar(muchos(), 22050,
                           al_terminar=lambda completo: fin.set())
            time.sleep(0.05)
            altavoz.detener()
            self.assertTrue(fin.wait(timeout=5))
        finally:
            altavoz.cerrar()
        self.assertGreaterEqual(self.salida.vaciados, 1)

    def test_cerrar_libera_el_dispositivo(self):
        altavoz = Altavoz(self.config.audio)
        fin = threading.Event()
        altavoz.hablar(iter([tono(9000, 2000)]), 22050,
                       al_terminar=lambda c: fin.set())
        fin.wait(timeout=5)
        altavoz.cerrar()
        self.assertTrue(self.salida.cerrada,
                        "ningún dispositivo debe quedar abierto al salir")


if __name__ == "__main__":
    unittest.main()
