"""Selección de motor de audio y validación de dispositivos.

No abre ningún dispositivo real: comprueba la lógica que decide qué motor se
usa en cada sistema y cómo se interpreta el dispositivo configurado.
"""
import dataclasses
import unittest
from unittest import mock

from emotibot.ajustes import AjustesAudio, dispositivo_valido
from emotibot.audio import motores


def audio(**extra) -> AjustesAudio:
    return dataclasses.replace(AjustesAudio(), **extra)


class SeleccionTest(unittest.TestCase):
    def test_respeta_el_motor_forzado(self):
        self.assertEqual(motores.motor_preferido(audio(motor="alsa")),
                         motores.ALSA)
        self.assertEqual(motores.motor_preferido(audio(motor="portaudio")),
                         motores.PORTAUDIO)

    def test_en_linux_con_arecord_prefiere_alsa(self):
        """En la Raspberry Pi se usa la vía ya validada en el dispositivo."""
        with mock.patch.object(motores.EntradaAlsa, "disponible",
                               return_value=True), \
             mock.patch.object(motores.sys, "platform", "linux"):
            self.assertEqual(motores.motor_preferido(audio()), motores.ALSA)

    def test_en_windows_elige_portaudio(self):
        with mock.patch.object(motores.sys, "platform", "win32"), \
             mock.patch.object(motores.EntradaPortAudio, "disponible",
                               return_value=True):
            self.assertEqual(motores.motor_preferido(audio()),
                             motores.PORTAUDIO)

    def test_en_linux_sin_arecord_cae_a_portaudio(self):
        with mock.patch.object(motores.sys, "platform", "linux"), \
             mock.patch.object(motores.EntradaAlsa, "disponible",
                               return_value=False), \
             mock.patch.object(motores.EntradaPortAudio, "disponible",
                               return_value=True):
            self.assertEqual(motores.motor_preferido(audio()),
                             motores.PORTAUDIO)

    def test_sin_ningun_motor_el_error_explica_que_instalar(self):
        with mock.patch.object(motores.EntradaAlsa, "disponible",
                               return_value=False), \
             mock.patch.object(motores.EntradaPortAudio, "disponible",
                               return_value=False):
            with self.assertRaises(motores.ErrorMotor):
                motores.crear_entrada(audio(motor="alsa"), 1600)


class DispositivoTest(unittest.TestCase):
    def test_alsa_valida_porque_va_a_un_subproceso(self):
        self.assertEqual(dispositivo_valido("plughw:1,0"), "plughw:1,0")
        self.assertIsNone(dispositivo_valido("hw:1,0; rm -rf /"))
        self.assertIsNone(dispositivo_valido("$(whoami)"))

    def test_entrada_alsa_descarta_un_dispositivo_peligroso(self):
        entrada = motores.EntradaAlsa(16000, "hw:1,0 && curl malo")
        self.assertIsNone(entrada.dispositivo)
        self.assertNotIn("curl", " ".join(entrada._argumentos()))

    def test_entrada_alsa_construye_argumentos_correctos(self):
        args = motores.EntradaAlsa(16000, "plughw:2,0")._argumentos()
        self.assertIn("-D", args)
        self.assertIn("plughw:2,0", args)
        self.assertIn("16000", args)

    def test_portaudio_acepta_indice_y_nombre_con_espacios(self):
        """En Windows los nombres llevan espacios y paréntesis."""
        self.assertEqual(motores._dispositivo_portaudio("3"), 3)
        self.assertEqual(
            motores._dispositivo_portaudio("Micrófono (Realtek Audio)"),
            "Micrófono (Realtek Audio)")
        self.assertIsNone(motores._dispositivo_portaudio(""))
        self.assertIsNone(motores._dispositivo_portaudio(None))


class DiagnosticoTest(unittest.TestCase):
    def test_informa_de_los_dos_motores(self):
        estado = motores.diagnostico_motores()
        self.assertIn(motores.ALSA, estado)
        self.assertIn(motores.PORTAUDIO, estado)
        for texto in estado.values():
            self.assertTrue(texto)

    def test_distingue_paquete_ausente_de_biblioteca_ausente(self):
        """Son dos fallos con soluciones distintas: no pueden confundirse."""
        with mock.patch.dict("sys.modules", {"sounddevice": None}):
            with mock.patch("builtins.__import__",
                            side_effect=ImportError("no module")):
                with self.assertRaises(motores.ErrorMotor) as caso:
                    motores.cargar_sounddevice()
        self.assertIn("pip install", str(caso.exception))


if __name__ == "__main__":
    unittest.main()
