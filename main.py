import os
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pymongo import MongoClient

app = FastAPI()

# plantillas HTML
templates = Jinja2Templates(directory="templates")

# Conexión a MongoDB Atlas 
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://esp32:paTos123@cluster0.0wdqvuo.mongodb.net/?appName=Cluster0")
client = MongoClient(MONGO_URI)
db = client["proy"]
coleccion = db["registrossonido"]

# Modelo de datos del ESP32
class SensorData(BaseModel):
    valor_bruto: int

#  ENDPOINT PARA RECIBIR DATOS DEL ESP32
@app.post("/api/datos")
async def recibir_datos(data: SensorData):
    # Convierte a porcentaje aproximado (0 a 100) basado en el rango del ESP32 (0-4095)
    porcentaje = min(int((data.valor_bruto / 4095) * 100), 100)
    
    # Clasificación automática en el Backend 
    if porcentaje < 20:
        categoria = "Silencio"
        alerta = False
    elif porcentaje < 60:
        categoria = "Moderado"
        alerta = False
    else:
        categoria = "Ruido Alto"
        alerta = True # Dispara alerta si el escándalo es fuerte

    ahora = datetime.now()

    # Estructura del documento para MongoDB
    documento = {
        "valor_bruto": data.valor_bruto,
        "porcentaje": porcentaje,
        "categoria": categoria,
        "alerta_critica": alerta,
        "fecha_hora": ahora.isoformat(),
        "hora_exacta": ahora.hour,
        "dia_semana": ahora.strftime("%A")
    }
    
    # Insertar en MongoDB Atlas
    resultado = coleccion.insert_one(documento)
    return {"status": "guardado", "id": str(resultado.inserted_id)}

# ENDPOINT PARA TRAER LOS ÚLTIMOS DATOS (Para la gráfica en tiempo real)
@app.get("/api/historial/reciente")
async def obtener_recientes():
    # Trae los últimos 20 registros ordenados del más viejo al más nuevo para la gráfica
    cursor = coleccion.find({}, {"_id": 0}).sort("_id", -1).limit(20)
    registros = list(cursor)
    return registros[::-1] # Invierte el tiempo para que el tiempo corra de izquierda a derecha

# ENDPOINT PARA FILTRADO AVANZADO 
@app.get("/api/historial/alertas")
async def obtener_alertas():
    # Trae solo donde hubo ruido crítico
    cursor = coleccion.find({"alerta_critica": True}, {"_id": 0}).sort("_id", -1).limit(50)
    return list(cursor)

# RUTA PARA MOSTRAR LA PÁGINA WEB
@app.get("/", response_class=HTMLResponse)
async def leer_interfaz(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})