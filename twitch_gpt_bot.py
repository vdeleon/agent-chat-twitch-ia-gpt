import os
import asyncio
import socket
import ssl
import requests
import openai
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWITCH_TOKEN = os.getenv("TWITCH_TOKEN")  # debe incluir 'oauth:' prefix
CHANNEL = os.getenv("CHANNEL")
MAX_HISTORIAL = 30

openai.api_key = OPENAI_API_KEY
client = openai.OpenAI()  # Crear cliente OpenAI

def refrescar_token(refresh_token_actual):
    url = 'https://id.twitch.tv/oauth2/token'
    params = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token_actual,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
    }

    try:
        response = requests.post(url, data=params)
        response.raise_for_status()
        data = response.json()
        
        if 'access_token' in data:
            print('[INFO] Token refrescado correctamente.')
            return data['access_token'], data.get('refresh_token', refresh_token_actual), data['expires_in']
        else:
            print(f'[ERROR] Error refrescando token: {data}')
            return None, None, None
    except requests.exceptions.RequestException as e:
        print(f'[ERROR] Error en la solicitud de refresco de token: {e}')
        return None, None, None

def preguntar_chatgpt_con_contexto(mensajes_historial):
    if not mensajes_historial:
        return "No hay mensajes recientes."
    contexto = [
        {"role": "system", "content": "Eres un bot amigable de Twitch llamado ChatGPTBot, responde de manera divertida a lo que dice la gente."},
    ]
    historial_recortado = mensajes_historial[-MAX_HISTORIAL:]
    for msg in historial_recortado:
        contexto.append({"role": "user", "content": msg})

    try:
        respuesta = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=contexto,
            max_tokens=150,
            temperature=0.7
        )
        return respuesta.choices[0].message.content.strip()
    except openai.OpenAIError as e:
        print(f"[ERROR] Error al comunicarse con la API de OpenAI: {e}")
        return "Lo siento, tuve un problema y no puedo responder ahora mismo."

class TwitchIRCClient:
    def __init__(self, token, channel):
        self.server = "irc.chat.twitch.tv"
        self.port = 6697
        self.token = token
        self.channel = f"#{channel.lower()}"
        self.nick = None
        self.reader = None
        self.writer = None
        self.mensajes = []
    
    async def connect(self):
        print("[INFO] Conectando a Twitch IRC...")
        ssl_context = ssl.create_default_context()
        self.reader, self.writer = await asyncio.open_connection(self.server, self.port, ssl=ssl_context)
        # Enviar PASS, NICK y JOIN
        await self.send_cmd(f"PASS {self.token}")
        # Extraer nick del token, pero como no podemos, solo pedimos input o extraemos de CHANNEL
        self.nick = self.channel.lstrip("#")
        await self.send_cmd(f"NICK {self.nick}")
        await self.send_cmd(f"JOIN {self.channel}")
        print(f"[INFO] Conectado al canal {self.channel}")

    async def send_cmd(self, cmd):
        self.writer.write(f"{cmd}\r\n".encode("utf-8"))
        await self.writer.drain()

    async def send_message(self, message):
        await self.send_cmd(f"PRIVMSG {self.channel} :{message}")

    async def handle_messages(self):
        while True:
            try:
                line = await self.reader.readline()
                if not line:
                    print("[WARNING] Conexión cerrada por el servidor.")
                    break
                decoded = line.decode("utf-8").strip()
                # Respondemos a PING para mantener conexión
                if decoded.startswith("PING"):
                    await self.send_cmd(f"PONG {decoded.split()[1]}")
                    continue

                # Parsear mensajes PRIVMSG
                if "PRIVMSG" in decoded:
                    prefix, msg = decoded.split(" PRIVMSG ", 1)
                    user = prefix.split("!")[0][1:]
                    channel, message = msg.split(" :", 1)
                    print(f"{user} en {channel}: {message}")
                    if user.lower() != self.nick.lower():
                        self.mensajes.append(f"{user}: {message}")
                # Aquí podrías capturar más comandos o eventos si quieres

            except Exception as e:
                print(f"[ERROR] Error leyendo mensaje IRC: {e}")

    async def responder_periodicamente(self):
        while True:
            await asyncio.sleep(30)
            if self.mensajes:
                print(f"[DEBUG] Generando respuesta para {len(self.mensajes)} mensajes...")
                respuesta = preguntar_chatgpt_con_contexto(self.mensajes)
                if respuesta and respuesta != "No hay mensajes recientes.":
                    print(f"🤖 Respuesta: {respuesta}")
                    try:
                        await self.send_message(respuesta)
                        self.mensajes.clear()
                    except Exception as e:
                        print(f"[ERROR] Error enviando mensaje: {e}")
            else:
                print("[DEBUG] No hay mensajes nuevos para responder.")

async def main():
    client = TwitchIRCClient(TWITCH_TOKEN, CHANNEL)
    await client.connect()

    # Lanzamos tareas simultáneas: manejar mensajes y responder periódicamente
    await asyncio.gather(
        client.handle_messages(),
        client.responder_periodicamente(),
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Bot detenido manualmente.")
