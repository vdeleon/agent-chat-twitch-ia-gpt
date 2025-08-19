import os
import asyncio
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
NICK = os.getenv("NICK")  # Aquí el nick del bot
MAX_HISTORIAL = 30

openai.api_key = OPENAI_API_KEY
client = openai.OpenAI()

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
        {"role": "system", "content": "Eres un bot amigable de Twitch llamado tuIaPapi, responde de manera divertida a lo que dice la gente."},
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
    def __init__(self, token, channel, nick):
        self.server = "irc.chat.twitch.tv"
        self.port = 6697
        self.token = token
        self.channel = f"#{channel.lower()}"
        self.nick = nick.lower()
        self.reader = None
        self.writer = None
        self.mensajes = []    # Historial general de mensajes
        self.menciones = []   # Cola de menciones al bot

    async def connect(self):
        print("[INFO] Conectando a Twitch IRC...")
        ssl_context = ssl.create_default_context()
        self.reader, self.writer = await asyncio.open_connection(self.server, self.port, ssl=ssl_context)
        
        await self.send_cmd(f"PASS {self.token}")
        await self.send_cmd(f"NICK {self.nick}")
        await self.send_cmd(f"JOIN {self.channel}")
        print(f"[INFO] Conectado al canal {self.channel} como {self.nick}")

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
                if decoded.startswith("PING"):
                    await self.send_cmd(f"PONG {decoded.split()[1]}")
                    continue

                if "PRIVMSG" in decoded:
                    prefix, msg = decoded.split(" PRIVMSG ", 1)
                    user = prefix.split("!")[0][1:]
                    channel, message = msg.split(" :", 1)
                    print(f"{user} en {channel}: {message}")

                    if user.lower() != self.nick.lower():
                        self.mensajes.append(f"{user}: {message}")

                        if f"@{self.nick}" in message.lower():
                            print(f"[INFO] Mención detectada de {user}")
                            self.menciones.append({"user": user, "message": message})

            except Exception as e:
                print(f"[ERROR] Error leyendo mensaje IRC: {e}")

    async def responder_periodicamente(self):
        while True:
            await asyncio.sleep(15)
            if self.menciones:
                print(f"[DEBUG] Procesando {len(self.menciones)} menciones...")

                for mencion in self.menciones:
                    usuario = mencion["user"]
                    mensaje = mencion["message"]
                    prompt = f"{usuario} dijo: {mensaje}"
                    respuesta = preguntar_chatgpt_con_contexto([prompt])

                    if respuesta:
                        respuesta_dirigida = f"@{usuario} {respuesta}"
                        try:
                            await self.send_message(respuesta_dirigida)
                            await asyncio.sleep(1.5)
                        except Exception as e:
                            print(f"[ERROR] Error enviando respuesta a {usuario}: {e}")
                self.menciones.clear()
            else:
                print("[DEBUG] No hay menciones nuevas.")

    async def anunciar_presencia_periodicamente(self):
        while True:
            await asyncio.sleep(1800)  # 30 minutos = 1800 segundos
            try:
                mensaje = f"¡Hola! Soy {self.nick}. Si quieres que te responda algo divertido, solo mencióname con @{self.nick} en el chat."
                await self.send_message(mensaje)
                print(f"[INFO] Mensaje automático enviado: {mensaje}")
            except Exception as e:
                print(f"[ERROR] Error al enviar mensaje automático: {e}")

async def main():
    client = TwitchIRCClient(TWITCH_TOKEN, CHANNEL, NICK)
    await client.connect()

    await asyncio.gather(
        client.handle_messages(),
        client.responder_periodicamente(),
        client.anunciar_presencia_periodicamente(),  # Nueva tarea añadida aquí
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Bot detenido manualmente.")
