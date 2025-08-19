import os
import asyncio
import ssl
import requests
import openai
import re
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWITCH_TOKEN = os.getenv("TWITCH_TOKEN")  # debe incluir 'oauth:' prefix
CHANNEL = os.getenv("CHANNEL")
NICK = os.getenv("NICK")  # nick del bot
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
        {"role": "system", "content": "Eres un bot amigable de Twitch llamado iaTuPapi, responde de manera divertida a lo que dice la gente."},
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
        self.nick = nick
        self.reader = None
        self.writer = None
        self.mensajes = []
        self.menciones = []

    async def connect(self):
        print("[INFO] Conectando a Twitch IRC...")
        ssl_context = ssl.create_default_context()
        self.reader, self.writer = await asyncio.open_connection(self.server, self.port, ssl=ssl_context)
        print(f"[DEBUG] Usando NICK: '{self.nick}'")
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
        pattern = re.compile(rf"@{re.escape(self.nick)}\b", re.IGNORECASE)
        print(f"[DEBUG] Nick del bot para detección: '{self.nick}'")
        print(f"[DEBUG] Regex usado: {pattern.pattern}")

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
                    print(f"[DEBUG] Mensaje recibido de '{user}' en '{channel}': {message}")

                    if user.lower() == self.nick.lower():
                        continue

                    self.mensajes.append(f"{user}: {message}")

                    if pattern.search(message):
                        print(f"[INFO] Mención detectada en mensaje: {message}")
                        mensaje_limpio = pattern.sub("", message).strip()  # Eliminar la mención
                        self.menciones.append({"user": user, "message": mensaje_limpio})
                    else:
                        print("[DEBUG] No se encontró mención en este mensaje.")

            except Exception as e:
                print(f"[ERROR] Error leyendo mensaje IRC: {e}")

    async def responder_periodicamente(self):
        while True:
            await asyncio.sleep(30)
            if self.menciones:
                for mencion in self.menciones:
                    user = mencion["user"]
                    mensaje = mencion["message"]
                    print(f"[DEBUG] Generando respuesta para mención de {user}...")
                    respuesta = preguntar_chatgpt_con_contexto([f"{user}: {mensaje}"])
                    if respuesta and respuesta != "No hay mensajes recientes.":
                        try:
                            await self.send_message(f"@{user} {respuesta}")
                            print(f"🤖 Respuesta a @{user}: {respuesta}")
                        except Exception as e:
                            print(f"[ERROR] Error enviando mensaje: {e}")
                self.menciones.clear()
            else:
                print("[DEBUG] No hay menciones nuevas.")

async def main():
    client = TwitchIRCClient(TWITCH_TOKEN, CHANNEL, NICK)
    await client.connect()

    await asyncio.gather(
        client.handle_messages(),
        client.responder_periodicamente(),
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Bot detenido manualmente.")