"""Modo local: dos personas juegan desde el teclado de una misma computadora."""

from cliente import COLOR_DESTACADO, COLOR_SECUNDARIO, PantallaPong
from modelo import Partida


class JuegoLocal:
    """Compone una partida y una pantalla; administra los controles del teclado."""

    def __init__(self):
        self.partida = Partida()
        self.pantalla = PantallaPong("Pong - Dos jugadores locales")
        self.en_ejecucion = True
        self.en_pausa = False

    def procesar_eventos(self) -> None:
        motor = self.pantalla.motor
        for evento in motor.event.get():
            if evento.type == motor.QUIT:
                self.en_ejecucion = False
            elif evento.type == motor.KEYDOWN:
                if evento.key == motor.K_r or self.partida.ganador is not None:
                    self.partida.reiniciar()
                    self.en_pausa = False
                elif evento.key == motor.K_p:
                    self.en_pausa = not self.en_pausa

    def actualizar(self, segundos: float) -> None:
        if self.en_pausa:
            return
        motor = self.pantalla.motor
        teclas = motor.key.get_pressed()
        izquierda = int(teclas[motor.K_s]) - int(teclas[motor.K_w])
        derecha = int(teclas[motor.K_DOWN]) - int(teclas[motor.K_UP])
        self.partida.actualizar(segundos, (izquierda, derecha))

    def dibujar(self) -> None:
        self.pantalla.limpiar()
        self.pantalla.dibujar_pista(self.partida.obtener_estado())
        self.pantalla.dibujar_texto("Izquierda: W/S    Derecha: flechas    P: pausa    R: reiniciar", 560, COLOR_SECUNDARIO)
        if self.partida.ganador is not None:
            lado = "izquierdo" if self.partida.ganador == 0 else "derecho"
            self.pantalla.dibujar_texto(f"¡Gana el jugador {lado}!", 270, COLOR_DESTACADO, grande=True)
            self.pantalla.dibujar_texto("Presiona cualquier tecla para reiniciar", 320)
        elif self.en_pausa:
            self.pantalla.dibujar_texto("JUEGO PAUSADO", 275, grande=True)

    def ejecutar(self) -> None:
        segundos = 0.0
        try:
            while self.en_ejecucion:
                self.procesar_eventos()
                if not self.en_ejecucion:
                    break
                # Limitar el salto temporal evita avances grandes si se arrastra la ventana.
                self.actualizar(min(segundos, 0.05))
                self.dibujar()
                segundos = self.pantalla.presentar()
        finally:
            self.pantalla.cerrar()


def principal() -> None:
    juego = JuegoLocal()
    juego.ejecutar()


if __name__ == "__main__":
    principal()
