# Se crea la api
import json
import re
from detoxify import Detoxify
from fastapi import FastAPI
from starlette.websockets import WebSocket, WebSocketDisconnect
from ConnectionManager import ConnectionManager

app = FastAPI()

# Se crea el modelo ML
model = Detoxify("multilingual")

def es_toxico_ml(texto: str):
    results = model.predict(texto)

    # Convertir a float normal (evita problemas con numpy)
    results = {k: float(v) for k, v in results.items()}

    toxicity = results.get("toxicity", 0)
    insult = results.get("insult", 0)
    threat = results.get("threat", 0)
    severe = results.get("severe_toxicity", 0)
    obscene = results.get("obscene", 0)

    # 🎯 Score ponderado (mejor que promedio)
    score = (
        toxicity * 0.4 +
        insult * 0.3 +
        obscene * 0.1 +
        threat * 1.0 +
        severe * 1.2
    )
    print(score)
    print(severe)

    # 🧠 Lógica de decisión
    if severe > 0.5 or threat > 0.4:
        return True, score, "ban"

    if toxicity > 0.8 and insult > 0.6:
        return True, score, "strike"

    if toxicity > 0.6:
        return False, score, "warning"

    return False, score, "ok"
# filtro rapido con regex
BAD_WORDS = [
    "pendejo", "puta", "verga", "mierda", "culero"
]

def contiene_malas_palabras(texto: str):
    texto = texto.lower()
    for word in BAD_WORDS:
        if re.search(rf"{word}", texto):
            return True
    return False

manager = ConnectionManager()

# Web Socket principal
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # 1. recibir username al conectar
    await websocket.accept()
    init_data = await websocket.receive_text()
    init_json = json.loads(init_data)

    username = init_json.get("username", "Anon")
    user_id = await manager.connect(websocket, username)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            msg_type = msg.get("type")

            # Emit Typing
            if msg_type == "typing":
                await manager.broadcast_typing(username)
                continue

            # Emit Mensajes
            if msg_type == "message":
                if manager.muted[user_id]:
                    await manager.send_personal({
                        "type": "system",
                        "data": "Estas Silenciado"
                    }, user_id)
                    continue

                text = msg.get("data", "")

                # Filtro rápido
                if contiene_malas_palabras(text):
                    manager.strikes[user_id] += 1
                    await manager.send_personal({
                        "type": "system",
                        "data": f"Strike {manager.strikes[user_id]} (lenguaje prohibido)"
                    }, user_id)
                    continue

                # Filtro ML
                toxico, score, nivel = es_toxico_ml(text)

                # 🚨 BAN directo
                if nivel == "ban":
                    await manager.send_personal({
                        "type": "system",
                        "data": f"Mensaje bloqueado (toxicidad extrema {score:.2f})"
                    }, user_id)

                    await websocket.close()
                    manager.disconnect(user_id)
                    return

                # ⚠️ STRIKE
                elif nivel == "strike":
                    manager.strikes[user_id] += 1

                    await manager.send_personal({
                        "type": "strike",
                        "data": f"Strike {manager.strikes[user_id]} (score {score:.2f})"
                    }, user_id)

                # ⚠️ WARNING (no suma strike)
                elif nivel == "warning":
                    await manager.send_personal({
                        "type": "warning",
                        "data": f"Lenguaje inapropiado (score {score:.2f})"
                    }, user_id)

                # ✅ OK → enviar mensaje
                else:
                    await manager.broadcast({
                        "type": "message",
                        "user": username,
                        "data": text
                    })

                # 🔇 SILENCIO
                if manager.strikes[user_id] >= 3 and not manager.muted.get(user_id, False):
                    manager.muted[user_id] = True

                    await manager.send_personal({
                        "type": "system",
                        "data": "Has sido silenciado por acumulación de strikes"
                    }, user_id)

                # 🚫 EXPULSIÓN
                if manager.strikes[user_id] >= 5:
                    await manager.send_personal({
                        "type": "system",
                        "data": "Has sido expulsado por toxicidad"
                    }, user_id)

                    await websocket.close()
                    manager.disconnect(user_id)
                    return
    except WebSocketDisconnect:
        manager.disconnect(user_id)
        await manager.broadcast_users()
        await manager.broadcast({
            "type": "system",
            "data": f"👋 {username} se desconectó"
        })
