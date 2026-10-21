import argparse
import json
import math
import socket
import time


# Estas medidas coinciden con modelo.py. Se conservan aquí para distribuir
# únicamente este archivo al segundo jugador, sin dependencias del proyecto.
ANCHO_PANTALLA = 800
ALTO_PANTALLA = 600
ANCHO_PALETA = 14
ALTO_PALETA = 90
RADIO_PELOTA = 12
PUERTO_PREDETERMINADO = 12345
TIEMPO_SIN_RESPUESTA = 5.0
FOTOGRAMAS_POR_SEGUNDO = 60

COLOR_FONDO = (16, 23, 42)
COLOR_RED = (51, 65, 85)
COLOR_TEXTO = (255, 255, 255)
COLOR_SECUNDARIO = (200, 163, 184)
COLOR_PELOTA = (249, 115, 22)
COLOR_DESTACADO = (158, 179, 8)

COLOR_PALETA_IZQUIERDA = (200, 179, 8)
COLOR_PALETA_DERECHA = (155, 255, 255)


def validar_estado(estado) -> bool:
    """Rechaza paquetes incompletos o valores que no se pueden dibujar."""
    if not isinstance(estado, dict) or estado.get("tipo") != "estado":
        return False
    posicion = estado.get("posicion_pelota")
    if not isinstance(posicion, list) or len(posicion) != 2:
        return False
    coordenadas = posicion + [estado.get("paleta_izquierda"), estado.get("paleta_derecha")]
    for valor in coordenadas:
        if type(valor) not in (int, float) or not -100000 < valor < 100000:
            return False
        if not math.isfinite(valor):
            return False
    for nombre in ("puntos_izquierda", "puntos_derecha"):
        if type(estado.get(nombre)) is not int or not 0 <= estado[nombre] <= 10:
            return False
    return (
        type(estado.get("secuencia")) is int and estado["secuencia"] >= 0
        and type(estado.get("numero_jugador")) is int and estado["numero_jugador"] in (0, 1)
        and type(estado.get("jugadores_conectados")) is int
        and estado["jugadores_conectados"] in (1, 2)
        and (estado.get("ganador") is None or (
            type(estado["ganador"]) is int and estado["ganador"] in (0, 1)
        ))
    )


class ErrorConexion(Exception):
    """Indica un problema de red que la ventana debe mostrar al usuario."""


class ConexionCliente:
    """Envía controles y conserva el estado más reciente recibido del servidor."""

    def __init__(self):
        self.canal = None
        self.estado = None
        self.secuencia = -1
        self.inicio_conexion = 0.0
        self.ultima_recepcion = 0.0

    @property
    def conectada(self) -> bool:
        """Indica si existe un canal abierto; la respuesta del servidor llega después."""
        return self.canal is not None

    def conectar(self, direccion: str, puerto: int) -> None:
        if not direccion.strip() or not 1 <= puerto <= 65535:
            raise ValueError("Introduce una dirección y un puerto entre 1 y 65535.")
        direccion_ip = socket.gethostbyname(direccion.strip())
        self.desconectar()
        canal_nuevo = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # En UDP esto selecciona el destino y filtra respuestas de otras direcciones.
            # No establece una sesión como TCP: el estado recibido confirma al servidor.
            canal_nuevo.connect((direccion_ip, puerto))
            canal_nuevo.setblocking(False)
        except OSError:
            canal_nuevo.close()
            raise
        self.canal = canal_nuevo
        self.estado = None
        self.secuencia = -1
        self.ultima_recepcion = 0.0
        self.inicio_conexion = time.monotonic()

    def intercambiar(self, subir: bool, bajar: bool, reiniciar: bool, instante: float) -> None:
        """Envía una entrada y lee las respuestas pendientes sin detener el dibujo."""
        if not self.conectada:
            return
        entrada = {"tipo": "entrada", "subir": subir, "bajar": bajar, "reiniciar": reiniciar}
        try:
            self.canal.send(json.dumps(entrada).encode("utf-8"))
            for _ in range(256):
                try:
                    mensaje = json.loads(self.canal.recv(4096).decode("utf-8"))
                except (ValueError, UnicodeError):
                    continue
                if isinstance(mensaje, dict) and mensaje.get("tipo") == "lleno":
                    raise ErrorConexion("Servidor lleno: ya hay dos jugadores.")
                if validar_estado(mensaje) and mensaje["secuencia"] > self.secuencia:
                    # UDP puede entregar paquetes fuera de orden; descartar los antiguos.
                    self.estado = mensaje
                    self.secuencia = mensaje["secuencia"]
                    self.ultima_recepcion = instante
        except (BlockingIOError, ConnectionResetError, ConnectionRefusedError):
            pass  # Mantener la ventana activa mientras se espera una respuesta.
        except OSError as error:
            raise ErrorConexion(f"Error de red: {error}") from error

        ultima_actividad = self.ultima_recepcion or self.inicio_conexion
        if instante - ultima_actividad > TIEMPO_SIN_RESPUESTA:
            raise ErrorConexion("Sin respuesta. Revisa IP, puerto, red y cortafuegos.")

    def desconectar(self) -> None:
        if self.canal is not None:
            try:
                self.canal.send(json.dumps({"tipo": "salir"}).encode("utf-8"))
            except OSError:
                pass  # Si el aviso se pierde, el servidor detecta la inactividad.
            self.canal.close()
        self.canal = None
        self.estado = None


class PantallaPong:
    """Dibuja la pista y los textos. No conoce sockets ni modifica la partida."""

    def __init__(self, titulo="Pong - Multijugador"):
        # Importar aquí permite probar la red en equipos que no tienen Pygame.
        import pygame

        self.motor = pygame
        self.motor.init()
        self.superficie = self.motor.display.set_mode((ANCHO_PANTALLA, ALTO_PANTALLA))
        self.motor.display.set_caption(titulo)
        self.reloj = self.motor.time.Clock()
        # La fuente incluida en Pygame está disponible tanto en Windows como en Linux.
        self.fuente_grande = self.motor.font.Font(None, 42)
        self.fuente_pequena = self.motor.font.Font(None, 26)

    def limpiar(self) -> None:
        self.superficie.fill(COLOR_FONDO)

    def dibujar_texto(self, texto: str, posicion_y: int, color=COLOR_TEXTO, grande=False) -> None:
        fuente = self.fuente_grande if grande else self.fuente_pequena
        imagen = fuente.render(texto, True, color)
        posicion_x = (ANCHO_PANTALLA - imagen.get_width()) // 2
        self.superficie.blit(imagen, (posicion_x, posicion_y))

    def dibujar_pista(self, estado: dict, numero_jugador=None) -> None:
        for posicion_y in range(0, ALTO_PANTALLA, 30):
            self.motor.draw.rect(self.superficie, COLOR_RED, (398, posicion_y, 4, 15))
        posiciones = (estado["paleta_izquierda"], estado["paleta_derecha"])
        for lado, posicion_x in enumerate((25, 761)):
            color = COLOR_PALETA_IZQUIERDA if lado == 0 else COLOR_PALETA_DERECHA
            self.motor.draw.rect(
                self.superficie, color,
                (posicion_x, posiciones[lado], ANCHO_PALETA, ALTO_PALETA), border_radius=4,
            )
        centro = tuple(int(coordenada) for coordenada in estado["posicion_pelota"])
        self.motor.draw.circle(self.superficie, COLOR_PELOTA, centro, RADIO_PELOTA)
        marcador = f"{estado['puntos_izquierda']}      {estado['puntos_derecha']}"
        self.dibujar_texto(marcador, 25, grande=True)

    def presentar(self) -> float:
        """Actualiza la ventana y devuelve los segundos transcurridos entre cuadros."""
        self.motor.display.flip()
        return self.reloj.tick(FOTOGRAMAS_POR_SEGUNDO) / 1000

    def cerrar(self) -> None:
        self.motor.quit()


class ClientePong:
    """Relaciona el formulario, las teclas, la conexión y la presentación del juego."""

    def __init__(self, direccion="", puerto=PUERTO_PREDETERMINADO):
        self.pantalla = PantallaPong()
        self.conexion = ConexionCliente()
        self.direccion_escrita = direccion
        self.puerto_escrito = str(puerto)
        self.campo_activo = 0
        self.mensaje_error = ""
        self.en_ejecucion = True
        if direccion:
            self.conectar()

    def conectar(self) -> None:
        try:
            self.conexion.conectar(self.direccion_escrita, int(self.puerto_escrito))
        except (ValueError, OSError) as error:
            self.mensaje_error = str(error)
        else:
            self.mensaje_error = ""

    def editar_formulario(self, evento) -> None:
        motor = self.pantalla.motor
        if evento.key == motor.K_RETURN:
            self.conectar()
        elif evento.key == motor.K_TAB:
            self.campo_activo = 1 - self.campo_activo
        elif evento.key == motor.K_BACKSPACE:
            if self.campo_activo == 0:
                self.direccion_escrita = self.direccion_escrita[:-1]
            else:
                self.puerto_escrito = self.puerto_escrito[:-1]
        elif evento.unicode.isprintable():
            if self.campo_activo == 0:
                self.direccion_escrita = (self.direccion_escrita + evento.unicode)[:100]
            elif evento.unicode.isdecimal():
                self.puerto_escrito = (self.puerto_escrito + evento.unicode)[:5]

    def procesar_eventos(self) -> bool:
        """Devuelve la solicitud de reinicio de este cuadro."""
        reiniciar = False
        motor = self.pantalla.motor
        for evento in motor.event.get():
            if evento.type == motor.QUIT:
                self.en_ejecucion = False
            elif evento.type == motor.KEYDOWN:
                if not self.conexion.conectada:
                    self.editar_formulario(evento)
                elif evento.key == motor.K_ESCAPE:
                    self.conexion.desconectar()
                elif evento.key == motor.K_r:
                    reiniciar = True
        return reiniciar

    def actualizar_conexion(self, reiniciar: bool, instante: float) -> None:
        motor = self.pantalla.motor
        teclas = motor.key.get_pressed()
        tiene_foco = motor.key.get_focused()
        subir = bool(tiene_foco and (teclas[motor.K_w] or teclas[motor.K_UP]))
        bajar = bool(tiene_foco and (teclas[motor.K_s] or teclas[motor.K_DOWN]))
        try:
            self.conexion.intercambiar(subir, bajar, reiniciar, instante)
        except ErrorConexion as error:
            self.mensaje_error = str(error)
            self.conexion.desconectar()

    def dibujar_formulario(self) -> None:
        pantalla = self.pantalla
        pantalla.dibujar_texto("PONG", 110, COLOR_PELOTA, grande=True)
        pantalla.dibujar_texto("Conectar al servidor", 185, grande=True)
        campos = ("IP del servidor: " + self.direccion_escrita, "Puerto UDP: " + self.puerto_escrito)
        for numero, texto in enumerate(campos):
            if numero == self.campo_activo:
                texto = "> " + texto + "_"
            pantalla.dibujar_texto(texto, 265 + numero * 45)
        pantalla.dibujar_texto("Tabulador: cambiar campo    Intro: conectar", 385, COLOR_SECUNDARIO)
        pantalla.dibujar_texto(self.mensaje_error[:90], 440, COLOR_DESTACADO)

    def dibujar_partida(self, instante: float) -> None:
        pantalla = self.pantalla
        estado = self.conexion.estado
        numero = estado["numero_jugador"]
        pantalla.dibujar_pista(estado, numero)
        lado = "izquierda" if numero == 0 else "derecha"
        pantalla.dibujar_texto(f"Tu paleta: {lado}", 78, COLOR_DESTACADO)
        if instante - self.conexion.ultima_recepcion > 1:
            pantalla.dibujar_texto("Se perdió la conexión...", 285, COLOR_DESTACADO, grande=True)
        elif estado["jugadores_conectados"] < 2:
            pantalla.dibujar_texto("Esperando al otro jugador... (1/2)", 285, COLOR_DESTACADO, grande=True)
        elif estado["ganador"] is not None:
            mensaje = "¡Ganaste!" if estado["ganador"] == numero else "Ganó tu oponente"
            pantalla.dibujar_texto(mensaje, 270, COLOR_DESTACADO, grande=True)
            pantalla.dibujar_texto("R: nueva partida", 320)
        pantalla.dibujar_texto("W/S o flechas: mover    |    Esc: desconectar", 560, COLOR_SECUNDARIO)

    def ejecutar(self) -> None:
        """Orden del ciclo: eventos, intercambio de red, dibujo y espera del reloj."""
        try:
            while self.en_ejecucion:
                reiniciar = self.procesar_eventos()
                if not self.en_ejecucion:
                    break
                instante = time.monotonic()
                self.actualizar_conexion(reiniciar, instante)
                self.pantalla.limpiar()
                if not self.conexion.conectada:
                    self.dibujar_formulario()
                elif self.conexion.estado is not None:
                    self.dibujar_partida(instante)
                else:
                    self.pantalla.dibujar_texto("Conectando al servidor...", 275, COLOR_DESTACADO, grande=True)
                    self.pantalla.dibujar_texto("Esc: volver", 340, COLOR_SECUNDARIO)
                self.pantalla.presentar()
        finally:
            self.conexion.desconectar()
            self.pantalla.cerrar()


def principal() -> None:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--direccion", default="", help="IP o nombre del servidor")
    analizador.add_argument("--puerto", type=int, default=PUERTO_PREDETERMINADO)
    argumentos = analizador.parse_args()
    try:
        cliente = ClientePong(argumentos.direccion, argumentos.puerto)
    except ModuleNotFoundError as error:
        if error.name != "pygame":
            raise
        analizador.exit(1, "Falta Pygame. Instálalo con: python -m pip install pygame\n")
    cliente.ejecutar()


if __name__ == "__main__":
    principal()
