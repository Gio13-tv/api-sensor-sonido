import os
import pytz
from datetime import datetime
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pymongo import MongoClient

app = FastAPI()

# Configuración de carpetas para los archivos HTML
templates = Jinja2Templates(directory="templates")

# Conexión limpia y directa a MongoDB Atlas
MONGO_URI = "mongodb+srv://esp32:paTos123@cluster0.0wdqvuo.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client["proy"]
coleccion = db["registrossonido"]

class SensorData(BaseModel):
    valor_bruto: int

# --- CONTROLADOR GLOBAL DE CONEXIONES EN VIVO (RAM) ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# --- ENDPOINT POST: RECIBE DATOS DEL ESP32 ---
@app.post("/api/datos")
async def recibir_datos(data: SensorData):
    ruido_real = data.valor_bruto

    # --- CHISMOSO DE CONSOLA (LOGS DE AUDITORÍA) ---
    print("\n" + "="*40)
    print(f"¡LLEGÓ UN DATO DEL ESP32! -> Valor Bruto Recibido: {ruido_real}")
    print("="*40 + "\n")

    # Bypass de seguridad: Si el pin físico del microcontrolador se queda pegado 
    # en el límite del ADC (4095) por falso contacto, lo forzamos a 0 para no trabar la gráfica.
    if ruido_real >= 4095:
        valor_a_procesar = 0
    elif ruido_real < 120:
        valor_a_procesar = 0
    else:
        valor_a_procesar = ruido_real

    # Mapeo a porcentaje basado en tu umbral de 700 unidades
    porcentaje = min(int((valor_a_procesar / 700) * 100), 100)
    
    # Clasificación estricta de categorías
    if porcentaje < 15:
        categoria = "Silencio"
        alerta = False
    elif porcentaje < 75:
        categoria = "Moderado"
        alerta = False
    else:
        categoria = "Ruido Alto"
        alerta = True

    # Gestión del tiempo para México
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
        "dia_semana": ahora_mx.strftime("%A")
    }
    
    # Transmisión inmediata por memoria RAM a los navegadores web conectados
    await manager.broadcast(documento)
    
    # Respaldo histórico asíncrono en MongoDB Atlas
    coleccion.insert_one(documento)
    
    return {"status": "enviado_al_vuelo"}

# --- ENDPOINT WEBSOCKET: MANTIENE EL CANAL VIVO ---
@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Escucha infinita y segura: Esto mantiene el puente abierto con el navegador
            # impidiendo que se cierre abruptamente de forma automática.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"Aviso controlado sobre el estado del canal: {e}")
        manager.disconnect(websocket)

# --- RUTAS DE CONSULTA E INTERFAZ UI ---
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
    datos = list(coleccion.find({"alerta_critica": True}).sort("$natural", -1).limit(30))
    for d in datos:
        d["_id"] = str(d["_id"])
    return datos