"""Objetos y reglas de Pong, independientes de la red y de la ventana.

Todas las posiciones se expresan en píxeles y las velocidades en píxeles por
segundo. El servidor y el modo local utilizan las mismas reglas.
"""

from dataclasses import dataclass
import random


ANCHO_PANTALLA = 800
ALTO_PANTALLA = 600
ANCHO_PALETA = 14
ALTO_PALETA = 90
MARGEN_PALETA = 25
RADIO_PELOTA = 12
VELOCIDAD_PALETA = 480
PUNTOS_PARA_GANAR = 10


@dataclass
class Paleta:
    """Representa una paleta y limita su movimiento al interior de la pista."""

    posicion_x: float
    posicion_y: float = (ALTO_PANTALLA - ALTO_PALETA) / 2

    def mover(self, direccion: int, segundos: float) -> None:
        """Recibe -1 para subir, 1 para bajar y 0 para permanecer quieta."""
        limite_inferior = ALTO_PANTALLA - ALTO_PALETA - 10
        desplazamiento = direccion * VELOCIDAD_PALETA * segundos
        self.posicion_y = max(10, min(limite_inferior, self.posicion_y + desplazamiento))


@dataclass
class Pelota:
    """Guarda la posición y la velocidad de la pelota."""

    posicion_x: float = ANCHO_PANTALLA / 2
    posicion_y: float = ALTO_PANTALLA / 2
    velocidad_x: float = 380
    velocidad_y: float = 280

    def reiniciar(self) -> None:
        """Coloca la pelota en el centro y elige la dirección del siguiente saque."""
        self.posicion_x = ANCHO_PANTALLA / 2
        self.posicion_y = ALTO_PANTALLA / 2
        self.velocidad_x = random.choice((-380, 380))
        self.velocidad_y = random.choice((-280, 280))

    def mover(self, segundos: float) -> None:
        self.posicion_x += self.velocidad_x * segundos
        self.posicion_y += self.velocidad_y * segundos

    def rebotar_en_bordes(self) -> None:
        limite_inferior = ALTO_PANTALLA - RADIO_PELOTA
        if self.posicion_y < RADIO_PELOTA or self.posicion_y > limite_inferior:
            self.posicion_y = max(RADIO_PELOTA, min(limite_inferior, self.posicion_y))
            self.velocidad_y *= -1

    def rebotar_en_paleta(self, paleta: Paleta, lado: int) -> None:
        """El lado 0 es el izquierdo; el lado 1 es el derecho."""
        se_acerca = self.velocidad_x < 0 if lado == 0 else self.velocidad_x > 0
        coincide_en_x = (
            self.posicion_x + RADIO_PELOTA >= paleta.posicion_x
            and self.posicion_x - RADIO_PELOTA <= paleta.posicion_x + ANCHO_PALETA
        )
        coincide_en_y = (
            self.posicion_y + RADIO_PELOTA >= paleta.posicion_y
            and self.posicion_y - RADIO_PELOTA <= paleta.posicion_y + ALTO_PALETA
        )
        if not (se_acerca and coincide_en_x and coincide_en_y):
            return

        direccion = 1 if lado == 0 else -1
        self.velocidad_x = direccion * min(abs(self.velocidad_x) * 1.08, 950)
        self.velocidad_y = max(-750, min(750, self.velocidad_y * 1.05))
        # Sacar la pelota de la paleta evita repetir el rebote en el siguiente paso.
        if lado == 0:
            self.posicion_x = paleta.posicion_x + ANCHO_PALETA + RADIO_PELOTA
        else:
            self.posicion_x = paleta.posicion_x - RADIO_PELOTA


class Partida:
    """Compone dos paletas y una pelota; administra puntos y ganador."""

    def __init__(self):
        self.paletas = [
            Paleta(MARGEN_PALETA),
            Paleta(ANCHO_PANTALLA - MARGEN_PALETA - ANCHO_PALETA),
        ]
        self.pelota = Pelota()
        self.reiniciar()

    def reiniciar(self) -> None:
        self.puntos = [0, 0]
        self.ganador = None
        for paleta in self.paletas:
            paleta.posicion_y = (ALTO_PANTALLA - ALTO_PALETA) / 2
        self.pelota.reiniciar()

    def actualizar(self, segundos: float, direcciones: tuple) -> None:
        """Avanza una partida activa según el tiempo y las entradas de ambos jugadores."""
        if self.ganador is not None:
            return
        for paleta, direccion in zip(self.paletas, direcciones):
            paleta.mover(direccion, segundos)

        # Dividir el recorrido en tramos cortos evita atravesar paletas al acelerar.
        velocidad_maxima = max(abs(self.pelota.velocidad_x), abs(self.pelota.velocidad_y))
        pasos = max(1, int(velocidad_maxima * segundos / 6) + 1)
        for _ in range(pasos):
            self.pelota.mover(segundos / pasos)
            self.pelota.rebotar_en_bordes()
            for lado, paleta in enumerate(self.paletas):
                self.pelota.rebotar_en_paleta(paleta, lado)
            if self.registrar_punto():
                break

    def registrar_punto(self) -> bool:
        """Devuelve True al salir la pelota; anota y prepara el siguiente saque."""
        if self.pelota.posicion_x < -RADIO_PELOTA:
            anotador = 1
        elif self.pelota.posicion_x > ANCHO_PANTALLA + RADIO_PELOTA:
            anotador = 0
        else:
            return False
        self.puntos[anotador] += 1
        if self.puntos[anotador] >= PUNTOS_PARA_GANAR:
            self.ganador = anotador
        self.pelota.reiniciar()
        return True

    def obtener_estado(self) -> dict:
        """Produce datos simples que pueden dibujarse o enviarse como JSON."""
        return {
            "posicion_pelota": [self.pelota.posicion_x, self.pelota.posicion_y],
            "paleta_izquierda": self.paletas[0].posicion_y,
            "paleta_derecha": self.paletas[1].posicion_y,
            "puntos_izquierda": self.puntos[0],
            "puntos_derecha": self.puntos[1],
            "ganador": self.ganador,
        }
