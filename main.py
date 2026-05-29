import os
from datetime import datetime
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pymongo import MongoClient

app = FastAPI()

templates = Jinja2Templates(directory="templates")

# Conexión Segura a MongoDB Atlas
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://esp32:paTos123@cluster0.0wdqvuo.mongodb.net/?appName=Cluster0")
client = MongoClient(MONGO_URI)
db = client["proy"]
coleccion = db["registrossonido"]

class SensorData(BaseModel):
    valor_bruto: int

# Administrador de conexiones WebSocket en tiempo real
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

@app.post("/api/datos")
async def recibir_datos(data: SensorData):
    ruido_real = data.valor_bruto

    # Filtro físico directo: Evitamos falsos positivos por ruido eléctrico de fondo
    if ruido_real < 80:
        valor_a_procesar = 0
    else:
        valor_a_procesar = ruido_real

    # Escalado matemático exacto basado en tu umbral de 700 unidades
    porcentaje = min(int((valor_a_procesar / 700) * 100), 100)
    
    # Clasificación estricta de rangos para asegurar el paso por "Moderado"
    if porcentaje < 15:
        categoria = "Silencio"
        alerta = False
    elif porcentaje < 75:
        categoria = "Moderado"
        alerta = False
    else:
        categoria = "Ruido Alto"
        alerta = True

    # Estampado de tiempo rápido compatible con servidores cloud
    ahora = datetime.now()
    hora_12h = ahora.strftime("%I:%M:%S %p")
    hora_exacta_num = int(ahora.strftime("%I"))

    documento = {
        "valor_bruto": valor_a_procesar,
        "porcentaje": porcentaje,
        "categoria": categoria,
        "alerta_critica": alerta,
        "fecha_hora": hora_12h,  
        "hora_exacta": hora_exacta_num,
        "dia_semana": ahora.strftime("%A")
    }
    
    # Transmitimos instantáneamente al frontend por WebSocket (Cero latencia)
    await manager.broadcast(documento)
    
    # Guardamos el respaldo en MongoDB Atlas
    coleccion.insert_one(documento)
    
    return {"status": "entregado_inmediato"}

# Canal WebSocket para la interfaz web
@websocket_route("/ws/en_vivo")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text() # Mantiene la conexión viva
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/", response_class=HTMLResponse)
async def leer_interfaz(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/historial/alertas")
async def obtener_alertas():
    datos = list(coleccion.find({"alerta_critica": True}).sort("$natural", -1).limit(30))
    for d in datos:
        d["_id"] = str(d["_id"])
    return datos