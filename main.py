import os
from collections import deque
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pymongo import MongoClient
import numpy as np
import pytz
import random

app = FastAPI()

# Configuración de vistas
templates = Jinja2Templates(directory="templates")

# Conexión optimizada a MongoDB Atlas
MONGO_URI = "mongodb+srv://esp32:paTos123@cluster0.0wdqvuo.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client["proy"]
coleccion = db["registrossonido"]

class SensorData(BaseModel):
    valor_bruto: int

# Buffer en memoria para almacenar las últimas 15 lecturas físicas consecutivas del ESP32
# Esto nos permite calcular la amplitud real del sonido ignorando el ruido estático
buffer_lecturas = deque(maxlen=15)

@app.post("/api/datos")
async def recibir_datos(data: SensorData):
    ruido_fisico = data.valor_bruto
    buffer_lecturas.append(ruido_fisico)
    
    # --- FILTRO DIGITAL DE SEÑAL (Procesamiento en Tiempo Real) ---
    # Si el buffer tiene lecturas, calculamos la desviación respecto al punto medio analógico
    if len(buffer_lecturas) > 1:
        # Filtro de paso alto/amplitud: medimos la variabilidad real del pin analógico
        lector_array = np.array(buffer_lecturas)
        valor_a_procesar = int(np.std(lector_array) * 2) # Magnifica los cambios reales del entorno
        
        # Si el sensor está devolviendo un valor plano de saturación (como 4095 fijo por cable suelto), 
        # la desviación estándar será 0, por lo que el sistema marcará "Silencio" de forma inteligente.
        if np.all(lector_array == 4095) or np.all(lector_array == 0):
            valor_a_procesar = 0
    else:
        valor_a_procesar = ruido_fisico

    # Acotar valores máximos y mínimos de seguridad hardware
    if valor_a_procesar > 4095: valor_a_procesar = 4095
    if valor_a_procesar < 30: valor_a_procesar = 0

    # Escalado matemático exacto basado en tu tope de calibración (700 unidades)
    porcentaje = min(int((valor_a_procesar / 700) * 100), 100)
    
    # --- CLASIFICACIÓN ESTRICTA DE RANGOS ---
    if porcentaje < 15:
        categoria = "Silencio"
        alerta = False
    elif porcentaje < 75:
        categoria = "Moderado"
        alerta = False
    else:
        categoria = "Ruido Alto"
        alerta = True

    # --- ESTAMPADO DE TIEMPO CDMX (Formato nativo de 12 Horas) ---
    zona_horaria_mx = pytz.timezone("America/Mexico_City")
    ahora_mx = datetime.now(zona_horaria_mx)
    
    hora_12h = ahora_mx.strftime("%I:%M:%S %p")  # Ejemplo: "09:24:02 PM"
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
    
    resultado = coleccion.insert_one(documento)
    return {"status": "procesado_físico", "id": str(resultado.inserted_id)}

# --- ENRUTAMIENTO DE LA INTERFAZ ---
@app.get("/", response_class=HTMLResponse)
async def leer_interfaz(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# --- ENDPOINTS DE ALTA VELOCIDAD (Ordenamiento por Inserción Natural) ---
@app.get("/api/historial/reciente")
async def obtener_reciente():
    # Extrae directo los últimos 20 registros sin reordenar todo el clúster
    datos = list(coleccion.find().sort("$natural", -1).limit(20))
    for d in datos:
        d["_id"] = str(d["_id"])
    return datos

@app.get("/api/historial/alertas")
async def obtener_alertas():
    datos = list(coleccion.find({"alerta_critica": True}).sort("$natural", -1).limit(50))
    for d in datos:
        d["_id"] = str(d["_id"])
    return datos