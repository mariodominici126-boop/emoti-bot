"""Contador de consumo con memoria entre ejecuciones.

Esto es lo que faltaba cuando se agotó la cuota: el prototipo no contaba sus
propias llamadas, así que no había forma de saber cuántas quedaban ni de
frenar antes del límite.

Política, deliberadamente conservadora con el proveedor:

- Límite propio por día y por minuto, POR MODELO, por debajo del límite real
  de cada servicio: no es lo mismo Groq con 1.000 solicitudes diarias que un
  modelo :free de OpenRouter con 50. Un tope global dejaría corto al generoso
  y pasado de rosca al estricto.
- Un 429 NO se reintenta nunca. Se bloquea ese modelo un rato.
- Tres 429 seguidos en el mismo modelo lo bloquean hasta el día siguiente: si
  el límite agotado es el diario, insistir cada minuto no sirve de nada.
- Nada de rotación de claves ni de cuentas múltiples: esas prácticas van
  contra las condiciones del proveedor y no se implementan aquí.

Fase 1, A3: tokens además de solicitudes
---------------------------------------
Los proveedores limitan solicitudes Y tokens, por minuto y por día, y suele
mandar el de tokens: con ~1.025 tokens por turno, 200.000 tokens/día dan
~195 turnos, frente a 1.000 solicitudes. Contar solo solicitudes medía lo
que no limita. Ahora hay dos etapas:

1. Antes (`reservar`): se comprueban las solicitudes y los tokens del día y
   del último minuto con la reserva = entrada estimada al alza + max_tokens
   (ver `ia/tokens.py`). Si no cabe, no se llama. El INTENTO se cuenta ya
   aquí, porque en varios servicios los fallidos también gastan cuota.
2. Después (`confirmar` / `anular`): se sustituye la reserva por el consumo
   real del `usage`. Si el proveedor no lo informa, cuenta la reserva entera,
   que es lo conservador. En un fallo se cuenta lo que el proveedor pudo
   haber procesado.

Los contadores locales no tienen por qué coincidir con los del proveedor:
son NUESTRO tope, por debajo del suyo, y un 429 sigue bloqueando aunque
nuestras cuentas digan que queda margen. Nunca se guarda el contenido de los
mensajes: solo números.
"""
from __future__ import annotations

import itertools
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .. import registro, rutas

log = registro.obtener("ia.presupuesto")

ESPERA_TRAS_429_S = 120
BLOQUEOS_PARA_PARAR_EL_DIA = 3
VENTANA_MINUTO_S = 60.0


@dataclass
class LimiteModelo:
    diario: int
    por_minuto: int
    # Topes propios de tokens; 0 = sin tope propio (se cuentan igual).
    tokens_dia: int = 0
    tokens_minuto: int = 0


@dataclass
class EstadoModelo:
    consultas: int = 0            # solicitudes que devolvieron respuesta
    rechazos_cuota: int = 0
    bloqueado_hasta: float = 0.0
    bloqueado_todo_el_dia: bool = False
    intentos: int = 0             # solicitudes enviadas, fueran bien o no
    tokens: int = 0               # tokens contabilizados hoy (real o reserva)
    tokens_reservados: int = 0    # reservas de solicitudes aún en vuelo
    truncadas: int = 0            # respuestas cortadas por el tope de tokens
    sin_uso: int = 0              # respuestas sin `usage`: contó la reserva
    _recientes: deque = field(default_factory=lambda: deque(maxlen=120), repr=False)
    # [instante, tokens] de cada intento del último minuto. Son listas
    # mutables para poder reconciliar la reserva con el consumo real.
    _tokens_recientes: deque = field(default_factory=lambda: deque(maxlen=240),
                                     repr=False)


@dataclass
class Reserva:
    """Lo apartado para una solicitud en vuelo. No contiene texto."""

    modelo: str
    dia: str
    tokens: int                   # entrada estimada + max_tokens
    entrada_estimada: int = 0
    cerrada: bool = False
    _marca: list = field(default_factory=list, repr=False)
    _id: int = 0


class Presupuesto:
    def __init__(
        self,
        maximo_diario: int,
        maximo_por_minuto: int,
        ruta: Path | None = None,
    ) -> None:
        self.maximo_diario = max(1, int(maximo_diario))
        self.maximo_por_minuto = max(1, int(maximo_por_minuto))
        self.ruta = ruta or rutas.ARCHIVO_PRESUPUESTO
        self.dia = date.today().isoformat()
        self.modelos: dict[str, EstadoModelo] = {}
        self.limites: dict[str, LimiteModelo] = {}
        # Lo normal es un turno a la vez, pero el reconocimiento remoto y la
        # consulta podrían coincidir. El cerrojo impide que dos reservas
        # simultáneas quepan juntas donde solo cabía una.
        self._cerrojo = threading.RLock()
        self._ids = itertools.count(1)
        self._cargar()

    def fijar_limites(self, modelo: str, diario: int, por_minuto: int,
                      tokens_dia: int = 0, tokens_minuto: int = 0) -> None:
        """Límites propios de un modelo concreto, de su archivo de proveedor."""
        if not modelo:
            return
        self.limites[modelo] = LimiteModelo(
            diario=max(1, int(diario)), por_minuto=max(1, int(por_minuto)),
            tokens_dia=max(0, int(tokens_dia or 0)),
            tokens_minuto=max(0, int(tokens_minuto or 0)),
        )

    def _limite(self, modelo: str) -> LimiteModelo:
        return self.limites.get(
            modelo, LimiteModelo(self.maximo_diario, self.maximo_por_minuto)
        )

    # ------------------------------------------------------------ persistencia
    def _cargar(self) -> None:
        if not self.ruta.is_file():
            return
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(datos, dict) or datos.get("dia") != self.dia:
            return  # otro día: los contadores arrancan de cero
        for nombre, crudo in (datos.get("modelos") or {}).items():
            if not isinstance(crudo, dict):
                continue
            # Los campos de la Fase 1 no existen en los archivos de la v1.7:
            # valen 0 y el archivo antiguo se sigue leyendo igual.
            try:
                self.modelos[str(nombre)] = EstadoModelo(
                    consultas=int(crudo.get("consultas", 0)),
                    rechazos_cuota=int(crudo.get("rechazos_cuota", 0)),
                    bloqueado_hasta=0.0,  # los relojes monotónicos no sobreviven
                    bloqueado_todo_el_dia=bool(crudo.get("bloqueado_todo_el_dia")),
                    intentos=int(crudo.get("intentos", 0)),
                    tokens=int(crudo.get("tokens", 0)),
                    truncadas=int(crudo.get("truncadas", 0)),
                    sin_uso=int(crudo.get("sin_uso", 0)),
                )
            except (TypeError, ValueError):
                continue

    def _guardar(self) -> None:
        try:
            rutas.asegurar_directorio(self.ruta.parent, privado=True)
            self.ruta.write_text(
                json.dumps(
                    {
                        "dia": self.dia,
                        "modelos": {
                            nombre: {
                                "consultas": estado.consultas,
                                "rechazos_cuota": estado.rechazos_cuota,
                                "bloqueado_todo_el_dia": estado.bloqueado_todo_el_dia,
                                "intentos": estado.intentos,
                                "tokens": estado.tokens,
                                "truncadas": estado.truncadas,
                                "sin_uso": estado.sin_uso,
                            }
                            for nombre, estado in self.modelos.items()
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            log.debug("No pude guardar el presupuesto: %s", exc)

    # ------------------------------------------------------------------ consulta
    def _estado(self, modelo: str) -> EstadoModelo:
        return self.modelos.setdefault(modelo or "desconocido", EstadoModelo())

    def _rotar_dia(self) -> None:
        hoy = date.today().isoformat()
        if hoy != self.dia:
            log.info("Nuevo día: reinicio los contadores de consumo.")
            self.dia = hoy
            self.modelos.clear()

    def puede_consultar(self, modelo: str, tokens: int = 0) -> tuple[bool, str]:
        """¿Cabe otra solicitud? Con `tokens`, también si caben esos tokens."""
        with self._cerrojo:
            self._rotar_dia()
            estado = self._estado(modelo)
            limite = self._limite(modelo)
            if estado.bloqueado_todo_el_dia:
                return False, "El proveedor agotó su cuota diaria."
            if estado.bloqueado_hasta and time.monotonic() < estado.bloqueado_hasta:
                espera = int(estado.bloqueado_hasta - time.monotonic())
                return False, f"En pausa {espera} s tras un rechazo por cuota."
            if max(estado.consultas, estado.intentos) >= limite.diario:
                return False, (f"Alcancé mi límite propio de {limite.diario} "
                               "consultas al día.")
            ahora = time.monotonic()
            while estado._recientes and ahora - estado._recientes[0] > VENTANA_MINUTO_S:
                estado._recientes.popleft()
            if len(estado._recientes) >= limite.por_minuto:
                return False, "Demasiadas consultas en el último minuto."
            return self._caben_tokens(estado, limite, max(0, int(tokens)), ahora)

    def bloqueo(self, modelo: str, tokens: int = 0) -> tuple[str, float]:
        """POR QUÉ no cabe otra consulta y cuánto falta, para los tres
        estados honestos (§14.4.1). Devuelve (tipo, segundos):

        - ("", 0): cabe;
        - ("minuto", s): solo lo impide el límite del último minuto
          (solicitudes o tokens); en `s` segundos vuelve a caber;
        - ("pausa", s): pausa tras un 429; vuelve sola en `s` segundos;
        - ("dia", inf): cuota del día agotada (propia o del proveedor).
        Misma lógica que `puede_consultar`, sin cambiar ningún contador.
        """
        tokens = max(0, int(tokens))
        infinito = float("inf")
        with self._cerrojo:
            self._rotar_dia()
            estado = self._estado(modelo)
            limite = self._limite(modelo)
            ahora = time.monotonic()
            if estado.bloqueado_todo_el_dia:
                return "dia", infinito
            if estado.bloqueado_hasta and ahora < estado.bloqueado_hasta:
                return "pausa", estado.bloqueado_hasta - ahora
            if max(estado.consultas, estado.intentos) >= limite.diario:
                return "dia", infinito
            if limite.tokens_dia and (estado.tokens + estado.tokens_reservados
                                      + tokens) > limite.tokens_dia:
                return "dia", infinito
            espera = 0.0
            recientes = [t for t in estado._recientes if ahora - t <= VENTANA_MINUTO_S]
            sobran = len(recientes) - limite.por_minuto + 1
            if sobran > 0:
                espera = max(espera, recientes[sobran - 1] + VENTANA_MINUTO_S - ahora)
            if limite.tokens_minuto:
                marcas = [m for m in estado._tokens_recientes
                          if ahora - m[0] <= VENTANA_MINUTO_S]
                exceso = sum(m[1] for m in marcas) + tokens - limite.tokens_minuto
                for instante, cantidad in marcas:
                    if exceso <= 0:
                        break
                    exceso -= cantidad
                    espera = max(espera, instante + VENTANA_MINUTO_S - ahora)
            if espera > 0:
                return "minuto", espera
            return "", 0.0

    @staticmethod
    def _caben_tokens(estado: EstadoModelo, limite: LimiteModelo, tokens: int,
                      ahora: float) -> tuple[bool, str]:
        if limite.tokens_dia and (estado.tokens + estado.tokens_reservados
                                  + tokens) > limite.tokens_dia:
            return False, (f"Alcancé mi límite propio de {limite.tokens_dia} "
                           "tokens al día.")
        while (estado._tokens_recientes
               and ahora - estado._tokens_recientes[0][0] > VENTANA_MINUTO_S):
            estado._tokens_recientes.popleft()
        if limite.tokens_minuto:
            en_minuto = sum(marca[1] for marca in estado._tokens_recientes)
            if en_minuto + tokens > limite.tokens_minuto:
                return False, "Demasiados tokens en el último minuto."
        return True, ""

    # -------------------------------------------------------- reservas (A3)
    def reservar(self, modelo: str, tokens: int,
                 entrada_estimada: int = 0) -> tuple[Reserva | None, str]:
        """Etapa previa: aparta `tokens` y cuenta el intento, o dice por qué no.

        `tokens` es la reserva completa: entrada estimada + max_tokens.
        """
        tokens = max(0, int(tokens))
        with self._cerrojo:
            permitido, motivo = self.puede_consultar(modelo, tokens)
            if not permitido:
                return None, motivo
            estado = self._estado(modelo)
            ahora = time.monotonic()
            marca = [ahora, tokens]
            estado._tokens_recientes.append(marca)
            estado._recientes.append(ahora)
            estado.intentos += 1
            estado.tokens_reservados += tokens
            reserva = Reserva(
                modelo=modelo, dia=self.dia, tokens=tokens,
                entrada_estimada=max(0, int(entrada_estimada)),
                _marca=marca, _id=next(self._ids),
            )
            self._guardar()
            return reserva, ""

    def _cerrar(self, reserva: Reserva, contabilizados: int) -> EstadoModelo:
        """Sustituye la reserva por lo que de verdad se contabiliza."""
        self._rotar_dia()
        estado = self._estado(reserva.modelo)
        contabilizados = max(0, int(contabilizados))
        if reserva.dia == self.dia:
            estado.tokens_reservados = max(
                0, estado.tokens_reservados - reserva.tokens)
        # Si cambió el día entre la reserva y la respuesta, la reserva se
        # borró con los contadores de ayer. El consumo se apunta a hoy, que
        # es lo conservador.
        estado.tokens += contabilizados
        if reserva._marca:
            reserva._marca[1] = contabilizados
        reserva.cerrada = True
        return estado

    def confirmar(self, reserva: Reserva, tokens_entrada: int | None = None,
                  tokens_salida: int | None = None) -> None:
        """Etapa posterior de una solicitud que devolvió respuesta."""
        with self._cerrojo:
            if reserva.cerrada:
                return
            sin_uso = tokens_entrada is None and tokens_salida is None
            if sin_uso:
                reales = reserva.tokens            # sin usage: la reserva entera
            else:
                reales = int(tokens_entrada or 0) + int(tokens_salida or 0)
            estado = self._cerrar(reserva, reales)
            estado.consultas += 1
            estado.rechazos_cuota = 0
            if sin_uso:
                estado.sin_uso += 1
            self._guardar()

    def anular(self, reserva: Reserva, contabilizados: int = 0) -> None:
        """Etapa posterior de una solicitud fallida.

        `contabilizados` es lo que el proveedor pudo haber procesado: 0 si
        rechazó la petición sin procesarla, la entrada estimada si falló a
        medias, y la reserva entera si no se sabe (tiempo agotado). El
        intento ya quedó contado al reservar.
        """
        with self._cerrojo:
            if reserva.cerrada:
                return
            self._cerrar(reserva, contabilizados)
            self._guardar()

    def registrar_truncada(self, modelo: str) -> None:
        """Métrica agregada (A2): solo un contador, nunca el texto."""
        with self._cerrojo:
            self._rotar_dia()
            self._estado(modelo).truncadas += 1
            self._guardar()

    # ----------------------------------------------------------------- registro
    def registrar_consulta(self, modelo: str) -> None:
        """Ruta sin reserva. La usa el reconocimiento remoto de Gemini."""
        with self._cerrojo:
            self._rotar_dia()
            estado = self._estado(modelo)
            estado.consultas += 1
            estado._recientes.append(time.monotonic())
            estado.rechazos_cuota = 0
            self._guardar()

    def registrar_rechazo_cuota(self, modelo: str) -> None:
        """Un 429. No se reintenta: se frena."""
        with self._cerrojo:
            self._rotar_dia()
            estado = self._estado(modelo)
            estado.rechazos_cuota += 1
            estado.bloqueado_hasta = time.monotonic() + ESPERA_TRAS_429_S
            if estado.rechazos_cuota >= BLOQUEOS_PARA_PARAR_EL_DIA:
                estado.bloqueado_todo_el_dia = True
                log.warning(
                    "Tercer rechazo por cuota en %s: lo dejo para hoy y paso al "
                    "modo local. Revisa los límites de tu proyecto.", modelo,
                )
            else:
                log.warning("Rechazo por cuota en %s; pausa de %d s.",
                            modelo, ESPERA_TRAS_429_S)
            self._guardar()

    def liberar(self, modelo: str) -> None:
        """Rehabilita un modelo a mano (tecla de la interfaz)."""
        with self._cerrojo:
            estado = self._estado(modelo)
            estado.bloqueado_hasta = 0.0
            estado.bloqueado_todo_el_dia = False
            estado.rechazos_cuota = 0
            self._guardar()

    def resumen(self, modelo: str) -> str:
        with self._cerrojo:
            estado = self._estado(modelo)
            if estado.bloqueado_todo_el_dia:
                return "cuota agotada hoy"
            limite = self._limite(modelo)
            texto = (f"{max(estado.consultas, estado.intentos)}/"
                     f"{limite.diario} hoy")
            if limite.tokens_dia:
                texto += f" · {estado.tokens}/{limite.tokens_dia} tok"
            elif estado.tokens:
                texto += f" · {estado.tokens} tok"
            return texto
