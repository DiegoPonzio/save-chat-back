import json
import re
from detoxify import Detoxify
from fastapi import FastAPI
from starlette.websockets import WebSocket, WebSocketDisconnect
from ConnectionManager import ConnectionManager

app = FastAPI()

model = Detoxify("multilingual")

def es_toxico_ml(texto: str):
    results = model.predict(texto)
    results = {k: float(v) for k, v in results.items()}

    toxicity = results.get("toxicity", 0)
    insult = results.get("insult", 0)
    threat = results.get("threat", 0)
    severe = results.get("severe_toxicity", 0)
    obscene = results.get("obscene", 0)

    score = (
        toxicity * 0.4 +
        insult * 0.3 +
        obscene * 0.1 +
        threat * 1.0 +
        severe * 1.2
    )

    if severe > 0.5 or threat > 0.4:
        return True, score, "ban"

    if toxicity > 0.8 and insult > 0.6:
        return True, score, "strike"

    if toxicity > 0.6:
        return False, score, "warning"

    return False, score, "ok"


BAD_WORDS = ["pendejo", "puta", "verga", "mierda", "culero"]

def contiene_malas_palabras(texto: str):
    texto = texto.lower()
    return any(re.search(rf"{word}", texto) for word in BAD_WORDS)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

    # 🔥 inicialización segura
    user_id = None
    username = "Anon"

    # 🔌 aceptar conexión
    try:
        await websocket.accept()
    except Exception as e:
        print("Error en accept:", e)
        return

    # 🧠 handshake inicial
    try:
        init_data = await websocket.receive_text()
        init_json = json.loads(init_data)

        username = init_json.get("username", "Anon")
        user_id = manager.connect(websocket, username)

        await manager.broadcast_users()

    except WebSocketDisconnect:
        print("Se desconectó antes de iniciar")
        return
    except Exception as e:
        print("Error inicial:", e)
        try:
            await websocket.close()
        except:
            pass
        return

    # 💬 loop principal
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            msg_type = msg.get("type")

            # ✍️ typing
            if msg_type == "typing":
                await manager.broadcast_typing(username)
                continue

            # 💬 mensajes
            if msg_type == "message":

                # 🔇 mute
                if manager.muted.get(user_id, False):
                    await manager.send_personal({
                        "type": "system",
                        "data": "🔇 Estás silenciado"
                    }, user_id)
                    continue

                text = msg.get("data", "")

                # 🚫 filtro regex
                if contiene_malas_palabras(text):
                    manager.strikes[user_id] += 1

                    await manager.send_personal({
                        "type": "strike",
                        "data": f"⚠️ Strike {manager.strikes[user_id]} (lenguaje prohibido)"
                    }, user_id)
                    continue

                # 🤖 ML
                toxico, score, nivel = es_toxico_ml(text)

                # 🚨 BAN
                if nivel == "ban":
                    await manager.send_personal({
                        "type": "system",
                        "data": f"⛔ Mensaje bloqueado ({score:.2f})"
                    }, user_id)

                    manager.disconnect(user_id)
                    try:
                        await websocket.close()
                    except:
                        pass
                    return

                # ⚠️ STRIKE
                elif nivel == "strike":
                    manager.strikes[user_id] += 1

                    await manager.send_personal({
                        "type": "strike",
                        "data": f"⚠️ Strike {manager.strikes[user_id]} ({score:.2f})"
                    }, user_id)

                # ⚠️ WARNING
                elif nivel == "warning":
                    await manager.send_personal({
                        "type": "warning",
                        "data": f"⚠️ Lenguaje inapropiado ({score:.2f})"
                    }, user_id)

                # ✅ OK
                else:
                    await manager.broadcast({
                        "type": "message",
                        "user": username,
                        "data": text
                    })

                # 🔇 silencio
                if manager.strikes[user_id] >= 3 and not manager.muted.get(user_id, False):
                    manager.muted[user_id] = True

                    await manager.send_personal({
                        "type": "system",
                        "data": "🔇 Has sido silenciado"
                    }, user_id)

                # 🚫 expulsión
                if manager.strikes[user_id] >= 5:
                    await manager.send_personal({
                        "type": "system",
                        "data": "⛔ Has sido expulsado"
                    }, user_id)

                    manager.disconnect(user_id)
                    try:
                        await websocket.close()
                    except:
                        pass
                    return

    except WebSocketDisconnect:
        print(f"{username} desconectado")

    except Exception as e:
        print("Error en loop:", e)

    finally:
        # 🧹 limpieza SIEMPRE
        if user_id and user_id in manager.active_connections:
            manager.disconnect(user_id)

            await manager.broadcast_users()

            await manager.broadcast({
                "type": "system",
                "data": f"👋 {username} se desconectó"
            })