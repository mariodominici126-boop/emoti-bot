"""El defecto que más daño hizo: la calibración contaminada por la voz."""
import unittest
from array import array

from emotibot.audio.vad import DetectorVoz, Fase

BLOQUE = 0.05
MUESTRAS = int(16000 * BLOQUE)


def tono(amplitud: int) -> bytes:
    """Bloque PCM con una amplitud constante conocida."""
    return array("h", [amplitud] * MUESTRAS).tobytes()


def detector(**extra) -> DetectorVoz:
    base = dict(
        segundos_bloque=BLOQUE, ms_asentamiento=100, ms_calibracion=200,
        factor_umbral=2.2, piso_umbral_rms=120.0, histeresis=0.65,
        bloques_confirmacion=3, silencio_final_s=0.3,
    )
    base.update(extra)
    return DetectorVoz(**base)


class CalibracionTest(unittest.TestCase):
    def test_no_avisa_antes_de_calibrar(self):
        d = detector()
        self.assertIs(d.fase, Fase.ASENTANDO)
        d.procesar(tono(40), 0.0)
        d.procesar(tono(40), BLOQUE)
        self.assertIs(d.fase, Fase.CALIBRANDO,
                      "tras asentar debe calibrar, no pedir que se hable")
        self.assertTrue(d.calibrando)

    def test_calibracion_con_silencio_fija_umbral_razonable(self):
        d = detector()
        t = 0.0
        for _ in range(12):
            d.procesar(tono(40), t)
            t += BLOQUE
        self.assertIs(d.fase, Fase.ESPERANDO_VOZ)
        self.assertGreaterEqual(d.diagnostico.umbral_inicio, 120.0)
        self.assertLess(d.diagnostico.umbral_inicio, 500.0)

    def test_un_transitorio_no_invalida_la_calibracion(self):
        """El clic de la tecla con la que se inicia el turno entra en la
        medición. Un pico suelto no es voz y no puede tirar la calibración al
        piso absoluto: eso desperdiciaba la medición del ruido real."""
        d = detector(ms_calibracion=450)
        t = 0.0
        for indice in range(14):
            # Ruido de sala de 78 RMS con un único golpe fuerte.
            d.procesar(tono(5000 if indice == 3 else 78), t)
            t += BLOQUE
        self.assertFalse(d.diagnostico.calibracion_contaminada,
                         "un transitorio aislado no es voz")
        self.assertGreater(d.diagnostico.umbral_inicio, 150,
                           "debe usar el ruido medido, no el piso absoluto")

    def test_voz_durante_la_calibracion_no_envenena_el_umbral(self):
        """Reproduce el fallo del prototipo.

        Antes: la voz entraba en la muestra de ruido, el umbral quedaba en 3x
        la propia voz y la persona nunca era detectada. El mensaje resultante
        culpaba a la distancia del micrófono.
        """
        d = detector()
        t = 0.0
        for _ in range(2):
            d.procesar(tono(40), t)
            t += BLOQUE
        for _ in range(10):
            d.procesar(tono(4000), t)
            t += BLOQUE

        self.assertTrue(d.diagnostico.calibracion_contaminada,
                        "debe detectar que la calibración se contaminó")
        self.assertLess(
            d.diagnostico.umbral_inicio, 4000.0,
            "el umbral no puede quedar por encima de la voz de la persona",
        )

        for _ in range(8):
            d.procesar(tono(4000), t)
            t += BLOQUE
        self.assertTrue(d.detecto_voz, "la voz debe detectarse tras recalibrar")


class DeteccionTest(unittest.TestCase):
    def _llevar_a_esperando(self, d: DetectorVoz) -> float:
        t = 0.0
        while d.calibrando and t < 2.0:
            d.procesar(tono(40), t)
            t += BLOQUE
        return t

    def test_exige_bloques_consecutivos(self):
        d = detector(bloques_confirmacion=3)
        t = self._llevar_a_esperando(d)
        d.procesar(tono(5000), t)
        t += BLOQUE
        d.procesar(tono(30), t)
        t += BLOQUE
        self.assertFalse(d.detecto_voz)
        for _ in range(3):
            d.procesar(tono(5000), t)
            t += BLOQUE
        self.assertTrue(d.detecto_voz)

    def test_histeresis_no_corta_en_silabas_suaves(self):
        d = detector()
        t = self._llevar_a_esperando(d)
        for _ in range(4):
            d.procesar(tono(5000), t)
            t += BLOQUE
        self.assertIs(d.fase, Fase.EN_VOZ)
        continuidad = d.diagnostico.umbral_continuidad
        self.assertLess(continuidad, d.diagnostico.umbral_inicio)
        self.assertFalse(d.procesar(tono(int(continuidad) + 50), t))

    def test_cierra_tras_el_silencio_configurado(self):
        d = detector(silencio_final_s=0.2)
        t = self._llevar_a_esperando(d)
        for _ in range(4):
            d.procesar(tono(5000), t)
            t += BLOQUE
        termino = False
        for _ in range(10):
            termino = d.procesar(tono(20), t)
            t += BLOQUE
            if termino:
                break
        self.assertTrue(termino)
        self.assertIsNotNone(d.ultima_voz)

    def test_registra_los_indices_de_bloque_de_la_voz(self):
        """El recorte usa índices, no marcas de tiempo: deben ser exactos."""
        d = detector(bloques_confirmacion=2)
        t = self._llevar_a_esperando(d)
        bloques_calibracion = d.diagnostico.bloques_totales
        for _ in range(6):
            d.procesar(tono(5000), t)
            t += BLOQUE
        self.assertIsNotNone(d.indice_primera_voz)
        self.assertIsNotNone(d.indice_ultima_voz)
        self.assertEqual(d.indice_primera_voz, bloques_calibracion,
                         "la voz empieza justo tras la calibración")
        self.assertEqual(d.indice_ultima_voz,
                         d.diagnostico.bloques_totales - 1)

    def test_umbral_manual_salta_la_calibracion(self):
        d = detector(umbral_manual=300.0)
        self.assertIs(d.fase, Fase.ESPERANDO_VOZ)
        t = 0.0
        for _ in range(4):
            d.procesar(tono(5000), t)
            t += BLOQUE
        self.assertTrue(d.detecto_voz)


if __name__ == "__main__":
    unittest.main()
