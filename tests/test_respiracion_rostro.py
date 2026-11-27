"""La respiración guiada tiene DIRECCIÓN en el rostro (22-11-2026).

Antes, inhalar y exhalar tenían el mismo `respira=2.4` (la amplitud de una
oscilación de periodo fijo), los tres pasos usaban el color «feliz» con ojos
«^ ^» y la boca solo variaba 2-3 px: se veían iguales y sonriendo.

Se comprueba:
- que los tres pasos producen geometrías distintas entre sí;
- que la escala evoluciona en la dirección correcta a lo largo del paso:
  crece durante los 4 s de inhalar, se mantiene en el sostén y mengua
  durante los 6 s de exhalar;
- que no sonríen;
- que exhalar tiene la boca entreabierta, pero solo fuera de «hablando».
"""
import unittest
from unittest import mock

from emotibot.dialogo.actividades import respiracion as mod_respiracion
from emotibot.rostro import EXPRESIONES
from emotibot.rostro import cara as mod_cara
from emotibot.rostro.cara import Cara
from emotibot.rostro.estados import componer
from emotibot.rostro.paleta import PALETA
from tests.test_rostro import LienzoSimulado

PASOS = ("respirando_inhalar", "respirando_sostener", "respirando_exhalar")


def _geometria(estado: str) -> dict:
    """Coordenadas de todas las piezas con el paso ya asentado."""
    lienzo = LienzoSimulado()
    cara = Cara(lienzo, PALETA)
    cara.fijar(funcional="reposo", expresion=estado)
    cara.fijar_nivel_voz(0.0)
    for _ in range(4):
        cara.asentar()
        cara._inicio = mod_cara.time.monotonic()     # respiración periódica en 0
        cara.dibujar()
    return {clave: tuple(round(v, 1) for v in lienzo.items[item]["coords"])
            for clave, item in cara._items.items()}


def _ancho_carcasa(lienzo, cara) -> float:
    xs = lienzo.items[cara._items["carcasa"]]["coords"][0::2]
    return max(xs) - min(xs)


class GeometriaTest(unittest.TestCase):
    def test_los_tres_pasos_son_distintos_entre_si(self):
        geometrias = {paso: _geometria(paso) for paso in PASOS}
        for i, a in enumerate(PASOS):
            for b in PASOS[i + 1:]:
                with self.subTest(a=a, b=b):
                    self.assertNotEqual(geometrias[a], geometrias[b])

    def test_no_sonrien(self):
        for paso in ("respirando", *PASOS):
            e = EXPRESIONES[paso]
            with self.subTest(paso=paso):
                self.assertNotEqual(e.color, "feliz")
                self.assertFalse(e.ojos_arco, "ojos «^ ^» = cara de alegría")
                self.assertLess(e.curva_boca, 0.3)
                self.assertFalse(e.destellos)

    def test_inhalar_y_exhalar_ya_no_son_iguales(self):
        inhalar, exhalar = EXPRESIONES[PASOS[0]], EXPRESIONES[PASOS[2]]
        self.assertGreater(inhalar.escala, 1.0)
        self.assertLess(exhalar.escala, 1.0)
        self.assertEqual(EXPRESIONES[PASOS[1]].escala, inhalar.escala,
                         "el sostén mantiene lo inhalado")

    def test_las_rampas_duran_lo_que_cuenta_la_actividad(self):
        self.assertEqual(EXPRESIONES[PASOS[0]].segundos_escala, mod_respiracion.INHALAR_S)
        self.assertEqual(EXPRESIONES[PASOS[2]].segundos_escala, mod_respiracion.EXHALAR_S)


class DireccionTest(unittest.TestCase):
    """La escala evoluciona en el sentido correcto a lo largo de cada paso."""

    def setUp(self):
        self.reloj = [1000.0]
        parche = mock.patch.object(mod_cara.time, "monotonic", lambda: self.reloj[0])
        parche.start()
        self.addCleanup(parche.stop)
        self.lienzo = LienzoSimulado()
        self.cara = Cara(self.lienzo, PALETA)
        self.cara.fijar_estado("respirando")
        self.cara.asentar()
        self.cara.dibujar()

    def _recorrer(self, paso: str, segundos: float, muestras: int = 9):
        self.cara.fijar(funcional="reposo", expresion=paso)
        self.cara.reiniciar_rampa()                  # lo que hace la app al callar
        escalas, anchos = [], []
        for k in range(muestras):
            self.reloj[0] += segundos / (muestras - 1) if k else 0.0
            self.cara.dibujar()
            escalas.append(self.cara._anim.escala)
            anchos.append(_ancho_carcasa(self.lienzo, self.cara))
        return escalas, anchos

    def test_inhalar_crece_sostener_mantiene_exhalar_mengua(self):
        sube, anchos_sube = self._recorrer("respirando_inhalar", 4.0)
        for a, b in zip(sube, sube[1:]):
            self.assertGreaterEqual(b, a)
        self.assertAlmostEqual(sube[0], 1.0, places=2)
        self.assertAlmostEqual(sube[-1], 1.08, places=3)
        self.assertGreater(anchos_sube[-1], anchos_sube[0] * 1.05,
                           "la cara crece de verdad en pantalla")

        quieto, _ = self._recorrer("respirando_sostener", 4.0)
        self.assertLess(max(quieto) - min(quieto), 0.005)

        baja, anchos_baja = self._recorrer("respirando_exhalar", 6.0)
        for a, b in zip(baja, baja[1:]):
            self.assertLessEqual(b, a)
        self.assertAlmostEqual(baja[-1], 0.97, places=3)
        self.assertLess(anchos_baja[-1], anchos_baja[0] * 0.95)

    def test_a_mitad_de_paso_aun_no_ha_llegado(self):
        """Es una rampa en el tiempo, no un salto ni un suavizado de 0,5 s."""
        escalas, _ = self._recorrer("respirando_inhalar", 2.0, muestras=2)
        self.assertGreater(escalas[-1], 1.02)
        self.assertLess(escalas[-1], 1.06)

    def test_al_volver_a_reposo_recupera_el_tamano(self):
        self._recorrer("respirando_exhalar", 6.0)
        escalas, _ = self._recorrer("reposo", 1.0)
        self.assertAlmostEqual(escalas[-1], 1.0, places=3)


class BocaExhalarTest(unittest.TestCase):
    def _alto_boca(self, funcional: str, voz: float) -> float:
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        cara.fijar(funcional=funcional, expresion="respirando_exhalar")
        cara.fijar_nivel_voz(voz)
        for _ in range(4):
            cara.asentar()
            cara.dibujar()
        ys = lienzo.items[cara._items["boca"]]["coords"][1::2]
        return max(ys) - min(ys)

    def test_entreabierta_sin_hablar(self):
        self.assertGreater(componer("reposo", "respirando_exhalar").boca_reposo, 0)
        # Referencia: inhalar en silencio tiene la boca cerrada.
        self.assertGreater(self._alto_boca("reposo", 0.0),
                           self._alto_boca_de("respirando_inhalar") * 1.5)

    def _alto_boca_de(self, expresion: str) -> float:
        lienzo = LienzoSimulado()
        cara = Cara(lienzo, PALETA)
        cara.fijar(funcional="reposo", expresion=expresion)
        for _ in range(4):
            cara.asentar()
            cara.dibujar()
        ys = lienzo.items[cara._items["boca"]]["coords"][1::2]
        return max(ys) - min(ys)

    def test_solo_fuera_de_hablando(self):
        """Hablando manda la voz real (A1): en silencio, la boca se cierra."""
        self.assertEqual(componer("hablando", "respirando_exhalar").boca_reposo, 0.0)
        self.assertLess(self._alto_boca("hablando", 0.0),
                        self._alto_boca("reposo", 0.0) * 0.7)

    def test_hablando_la_voz_la_abre_mas(self):
        self.assertGreater(self._alto_boca("hablando", 1.0),
                           self._alto_boca("reposo", 0.0))


if __name__ == "__main__":
    unittest.main()
