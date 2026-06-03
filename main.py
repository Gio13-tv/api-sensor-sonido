import asyncio
import os
import pytz
from datetime import datetime
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pymongo import MongoClient

app = FastAPI()
 
templates = Jinja2Templates(directory="templates")
 
# ── MongoDB ──────────────────────────────────────────────────────────────────
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://esp32:paTos123@cluster0.0wdqvuo.mongodb.net/?appName=Cluster0",
)
client = MongoClient(MONGO_URI)
db = client["proy"]
coleccion = db["registrossonido"]
 
 
class SensorData(BaseModel):
    valor_bruto: int
 
 
# ── WebSocket Manager ─────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
 
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WS] Cliente conectado. Total: {len(self.active_connections)}")
 
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"[WS] Cliente desconectado. Total: {len(self.active_connections)}")
 
    async def broadcast(self, message: dict):
        """Transmite a todos los clientes; elimina los que fallen."""
        muertos = []
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                muertos.append(ws)
        for ws in muertos:
            self.disconnect(ws)
 
 
manager = ConnectionManager()
 
 
# ── POST: recibe datos del ESP32 ──────────────────────────────────────────────
@app.post("/api/datos")
async def recibir_datos(data: SensorData):
    ruido_real = data.valor_bruto
 
    print(f"\n{'='*40}")
    print(f"ESP32 → valor bruto: {ruido_real}")
    print(f"{'='*40}\n")
 
    # Filtros de ADC roto / pin pegado
    if ruido_real >= 4095 or ruido_real < 120:
        valor_a_procesar = 0
    else:
        valor_a_procesar = ruido_real
 
    porcentaje = min(int((valor_a_procesar / 700) * 100), 100)
 
    if porcentaje < 15:
        categoria = "Silencio"
        alerta = False
    elif porcentaje < 75:
        categoria = "Moderado"
        alerta = False
    else:
        categoria = "Ruido Alto"
        alerta = True
 
    zona_horaria_mx = pytz.timezone("America/Mexico_City")
    ahora_mx = datetime.now(zona_horaria_mx)
    hora_12h = ahora_mx.strftime("%I:%M:%S %p")
    hora_exacta_num = int(ahora_mx.strftime("%I"))
 
    documento = {
        "valor_bruto": ruido_real,
        "porcentaje": porcentaje,
        "categoria": categoria,
        "alerta_critica": alerta,
        "fecha_hora": hora_12h,
        "hora_exacta": hora_exacta_num,
        "dia_semana": ahora_mx.strftime("%A"),
    }
 
    # 1. Broadcast inmediato por WebSocket (memoria RAM)
    await manager.broadcast(documento)
 
    # 2. Persistencia en MongoDB en hilo separado para no bloquear el event loop
    await asyncio.to_thread(coleccion.insert_one, documento)
 
    return {"status": "ok", "clientes_activos": len(manager.active_connections)}
 
 
# ── WebSocket: mantiene el canal vivo con ping/pong ──────────────────────────
@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Bucle de ping cada 20 s para evitar que proxies/Render cierren la conexión
        while True:
            try:
                # Espera un mensaje del cliente con timeout de 20 s
                await asyncio.wait_for(websocket.receive_text(), timeout=20)
            except asyncio.TimeoutError:
                # Manda un ping para mantener el canal abierto
                await websocket.send_json({"tipo": "ping"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"[WS] Canal cerrado inesperadamente: {e}")
        manager.disconnect(websocket)
 
 
# ── Rutas de la UI ────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def leer_interfaz(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
 
 
@app.get("/api/historial/inicial")
async def obtener_inicial():
    datos = list(coleccion.find().sort("$natural", -1).limit(10))
    for d in datos:
        d["_id"] = str(d["_id"])
    return datos
 
 
@app.get("/api/historial/alertas")
async def obtener_alertas():
    datos = list(
        coleccion.find({"alerta_critica": True}).sort("$natural", -1).limit(30)
    )
    for d in datos:
        d["_id"] = str(d["_id"])
    return datos