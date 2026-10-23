"""Servidor de Pong: recibe controles, actualiza la partida y comparte su estado."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

from modelo import Partida


PUERTO_PREDETERMINADO = 12345
TIEMPO_DESCONEXION = 5.0
VIGENCIA_CONTROLES = 0.3
ACTUALIZACIONES_POR_SEGUNDO = 60
MAXIMO_MENSAJES_POR_CICLO = 256


@dataclass
class JugadorConectado:
    """Asocia una dirección de red con los últimos controles recibidos."""

    direccion: tuple
    ultima_actividad: float
    subir: bool = False
    bajar: bool = False
    ultima_solicitud_pausa: int = 0

    def obtener_direccion(self, instante: float) -> int:
        # Si dejan de llegar controles, detener la paleta evita movimientos fantasma.
        if instante - self.ultima_actividad >= VIGENCIA_CONTROLES:
            return 0
        return int(self.bajar) - int(self.subir)


class ServidorPong:
    """Coordina dos jugadores y conserva la autoridad sobre las reglas del juego."""

    def __init__(self, direccion="0.0.0.0", puerto=PUERTO_PREDETERMINADO):
        self.canal = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.canal.bind((direccion, puerto))
            self.canal.setblocking(False)
        except OSError:
            self.canal.close()
            raise
        self.jugadores = [None, None]
        self.partida = Partida()
        self.secuencia = 0

    def buscar_jugador(self, direccion: tuple):
        for numero, jugador in enumerate(self.jugadores):
            if jugador is not None and jugador.direccion == direccion:
                return numero
        return None

    def retirar_jugador(self, numero: int) -> None:
        self.jugadores[numero] = None
        self.partida.reiniciar()
        print(f"[SERVIDOR] Jugador {numero + 1} desconectado.", flush=True)

    def retirar_inactivos(self, instante: float) -> None:
        for numero, jugador in enumerate(self.jugadores):
            if jugador is not None and instante - jugador.ultima_actividad > TIEMPO_DESCONEXION:
                self.retirar_jugador(numero)

    def procesar_mensaje(self, mensaje: dict, direccion: tuple, instante: float) -> None:
        """Registra jugadores y aplica sus controles; ignora mensajes desconocidos."""
        if not isinstance(mensaje, dict) or mensaje.get("tipo") not in ("entrada", "salir"):
            return
        numero = self.buscar_jugador(direccion)
        if mensaje["tipo"] == "salir":
            if numero is not None:
                self.retirar_jugador(numero)
            return

        if numero is None:
            numero = next((indice for indice, jugador in enumerate(self.jugadores)
                           if jugador is None), None)
            if numero is None:
                self.enviar({"tipo": "lleno"}, direccion)
                return
            self.jugadores[numero] = JugadorConectado(direccion, instante)
            print(f"[SERVIDOR] Jugador {numero + 1}: {direccion}", flush=True)

        jugador = self.jugadores[numero]
        jugador.ultima_actividad = instante
        jugador.subir = mensaje.get("subir") is True
        jugador.bajar = mensaje.get("bajar") is True
        solicitud = mensaje.get("solicitud_pausa", 0)
        if type(solicitud) is int and solicitud > jugador.ultima_solicitud_pausa:
            pulsaciones = solicitud - jugador.ultima_solicitud_pausa
            jugador.ultima_solicitud_pausa = solicitud
            # El contador evita repetir una pulsación si UDP duplica un paquete.
            # Si se pierden paquetes, se conserva la cantidad de pulsaciones.
            if (pulsaciones % 2 == 1 and all(self.jugadores)
                    and self.partida.ganador is None):
                self.partida.en_pausa = not self.partida.en_pausa
        if self.partida.ganador is not None and mensaje.get("reiniciar") is True:
            self.partida.reiniciar()

    def recibir(self, instante: float) -> None:
        self.retirar_inactivos(instante)
        # El límite permite seguir actualizando el juego aunque lleguen muchos paquetes.
        for _ in range(MAXIMO_MENSAJES_POR_CICLO):
            try:
                datos, direccion = self.canal.recvfrom(2048)
            except (BlockingIOError, ConnectionResetError):
                break
            try:
                mensaje = json.loads(datos.decode("utf-8"))
            except (ValueError, UnicodeError):
                continue
            self.procesar_mensaje(mensaje, direccion, instante)

    def actualizar(self, segundos: float, instante: float) -> None:
        if all(jugador is not None for jugador in self.jugadores):
            direcciones = tuple(jugador.obtener_direccion(instante) for jugador in self.jugadores)
            self.partida.actualizar(segundos, direcciones)

    def enviar(self, mensaje: dict, direccion: tuple) -> None:
        try:
            self.canal.sendto(json.dumps(mensaje).encode("utf-8"), direccion)
        except OSError:
            # UDP no confirma la entrega; la falta de actividad libera el lugar después.
            pass

    def difundir_estado(self) -> None:
        self.secuencia += 1
        estado = self.partida.obtener_estado()
        estado.update(
            tipo="estado", secuencia=self.secuencia,
            jugadores_conectados=sum(jugador is not None for jugador in self.jugadores),
        )
        for numero, jugador in enumerate(self.jugadores):
            if jugador is not None:
                self.enviar(dict(estado, numero_jugador=numero), jugador.direccion)

    def ejecutar(self) -> None:
        """Repite recepción, física y envío unas 60 veces por segundo."""
        instante_anterior = time.monotonic()
        while True:
            inicio = time.monotonic()
            segundos = min(inicio - instante_anterior, 0.05)
            instante_anterior = inicio
            self.recibir(inicio)
            self.actualizar(segundos, inicio)
            self.difundir_estado()
            duracion = time.monotonic() - inicio
            time.sleep(max(0, 1 / ACTUALIZACIONES_POR_SEGUNDO - duracion))

    def cerrar(self) -> None:
        self.canal.close()


def mostrar_direcciones() -> None:
    """Muestra las IPv4 disponibles; el anfitrión elige la de su red compartida."""
    try:
        resultados = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM)
        direcciones = sorted({resultado[4][0] for resultado in resultados
                              if not resultado[4][0].startswith("127.")})
        if direcciones:
            print("[SERVIDOR] Direcciones de esta PC: " + ", ".join(direcciones), flush=True)
    except OSError:
        pass  # También se pueden consultar manualmente con ipconfig.


def principal() -> None:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--direccion", default="0.0.0.0", help="Interfaz de escucha")
    analizador.add_argument("--puerto", type=int, default=PUERTO_PREDETERMINADO)
    analizador.add_argument("--jugar", action="store_true", help="Abrir el cliente local")
    argumentos = analizador.parse_args()
    if not 1 <= argumentos.puerto <= 65535:
        analizador.error("El puerto debe estar entre 1 y 65535")
    try:
        servidor = ServidorPong(argumentos.direccion, argumentos.puerto)
    except OSError as error:
        analizador.exit(1, f"No se pudo iniciar el servidor: {error}\n")

    print(f"[SERVIDOR] Escuchando en {argumentos.direccion}:{argumentos.puerto} (UDP).", flush=True)
    mostrar_direcciones()
    print("El otro jugador debe introducir la IPv4 de esta PC (ver ipconfig).", flush=True)
    proceso_cliente = None
    try:
        if argumentos.jugar:
            direccion_local = "127.0.0.1" if argumentos.direccion == "0.0.0.0" else argumentos.direccion
            ruta_cliente = Path(__file__).with_name("cliente.py")
            proceso_cliente = subprocess.Popen([
                sys.executable, str(ruta_cliente), "--direccion", direccion_local,
                "--puerto", str(argumentos.puerto),
            ])
        servidor.ejecutar()
    except KeyboardInterrupt:
        print("\n[SERVIDOR] Cerrado.")
    finally:
        servidor.cerrar()
        if proceso_cliente is not None and proceso_cliente.poll() is None:
            proceso_cliente.terminate()
            proceso_cliente.wait()


if __name__ == "__main__":
    principal()
