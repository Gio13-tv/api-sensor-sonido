import os
import pytz
from datetime import datetime
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pymongo import MongoClient

app = FastAPI()

# Inicialización de plantillas HTML
templates = Jinja2Templates(directory="templates")

# Conexión optimizada a MongoDB Atlas
MONGO_URI = "mongodb+srv://esp32:paTos123@cluster0.0wdqvuo.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client["proy"]
coleccion = db["registrossonido"]

class SensorData(BaseModel):
    valor_bruto: int

# --- ADMINISTRADOR DE WEBSOCKETS PARA TRANSMISIÓN EN TIEMPO REAL ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def class_connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def class_disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
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

    # Filtro umbilical para limpiar el ruido eléctrico de fondo en el protoboard
    if ruido_real < 120:
        valor_a_procesar = 0
    else:
        valor_a_procesar = ruido_real

    # Escalado matemático exacto basado en tu umbral de 700 unidades
    porcentaje = min(int((valor_a_procesar / 700) * 100), 100)
    
    # Clasificación estricta de categorías (Garantiza el paso por Moderado)
    if porcentaje < 15:
        categoria = "Silencio"
        alerta = False
    elif porcentaje < 75:
        categoria = "Moderado"
        alerta = False
    else:
        categoria = "Ruido Alto"
        alerta = True

    # Estampado de tiempo nativo de la CDMX (Formato de 12 horas)
    zona_horaria_mx = pytz.timezone("America/Mexico_City")
    ahora_mx = datetime.now(zona_horaria_mx)
    hora_12h = ahora_mx.strftime("%I:%M:%S %p")
    hora_exacta_num = int(ahora_mx.strftime("%I"))

    documento = {
        "valor_bruto": valor_a_procesar,
        "porcentaje": porcentaje,
        "categoria": categoria,
        "alerta_critica": alerta,
        "fecha_hora": hora_12h,  
        "hora_exacta": hora_exacta_num,
        "dia_semana": ahora_mx.strftime("%A")
    }
    
    # 1. TRANSMISIÓN EN TIEMPO REAL: Se envía al frontend instantáneamente por la RAM (Cero latencia)
    await manager.broadcast(documento)
    
    # 2. ALMACENAMIENTO DE RESPALDO: Se guarda en MongoDB en segundo plano
    coleccion.insert_one(documento)
    
    return {"status": "procesado_y_transmitido"}

# Ruta del Canal WebSocket para el Dashboard
@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await manager.class_connect(websocket)
    try:
        while True:
            # Mantiene la conexión abierta escuchando señales de vida
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.class_disconnect(websocket)

# --- ENRUTAMIENTO DE LA INTERFAZ WEB ---
@app.get("/", response_class=HTMLResponse)
async def leer_interfaz(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Carga inicial rápida: Trae solo los últimos 10 registros al abrir la página
@app.get("/api/historial/inicial")
async def obtener_inicial():
    datos = list(coleccion.find().sort("$natural", -1).limit(10))
    for d in datos:
        d["_id"] = str(d["_id"])
    return datos

@app.get("/api/historial/alertas")
async def obtener_alertas():
    datos = list(coleccion.find({"alerta_critica": True}).sort("$natural", -1).limit(30))
    for d in datos:
        d["_id"] = str(d["_id"])
    return datos