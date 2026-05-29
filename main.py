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

templates = Jinja2Templates(directory="templates")

# Conexión limpia a MongoDB Atlas (Solo para almacenamiento de respaldo)
MONGO_URI = "mongodb+srv://esp32:paTos123@cluster0.0wdqvuo.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client["proy"]
coleccion = db["registrossonido"]

class SensorData(BaseModel):
    valor_bruto: int

# --- VARIABLE EN MEMORIA RAM PARA TIEMPO REAL ULTRA RÁPIDO ---
ultimo_registro_en_vivo = {
    "valor_bruto": 0,
    "porcentaje": 0,
    "categoria": "Silencio",
    "fecha_hora": "--:--:--"
}

@app.post("/api/datos")
async def recibir_datos(data: SensorData):
    global ultimo_registro_en_vivo
    
    ruido_real = data.valor_bruto

    # Si tu sensor físico se queda trabado en 4095 de forma fija por el cable, 
    # puedes descomentar estas dos líneas para limpiar la señal a 0:
    # if ruido_real >= 4095:
    #     ruido_real = 0

    # Mapeo matemático directo basado en tu tope de calibración de 700 unidades
    porcentaje = min(int((ruido_real / 700) * 100), 100)
    
    # Clasificación estricta de categorías (Asegura el paso por Moderado)
    if porcentaje < 15:
        categoria = "Silencio"
        alerta = False
    elif porcentaje < 75:
        categoria = "Moderado"
        alerta = False
    else:
        categoria = "Ruido Alto"
        alerta = True

    # Estampado de tiempo nativo CDMX
    zona_horaria_mx = pytz.timezone("America/Mexico_City")
    ahora_mx = datetime.now(zona_horaria_mx)
    hora_12h = ahora_mx.strftime("%I:%M:%S %p")
    hora_exacta_num = int(ahora_mx.strftime("%I"))

    # Estructura del documento
    documento = {
        "valor_bruto": ruido_real,
        "porcentaje": porcentaje,
        "categoria": categoria,
        "alerta_critica": alerta,
        "fecha_hora": hora_12h,  
        "hora_exacta": hora_exacta_num,
        "dia_semana": ahora_mx.strftime("%A")
    }
    
    # 1. Actualizamos la memoria RAM al instante para el flujo web
    ultimo_registro_en_vivo = documento
    
    # 2. Guardamos en la base de datos en segundo plano sin retrasar la respuesta
    coleccion.insert_one(documento)
    
    return {"status": "ok"}

# Endpoint en memoria RAM: Responde instantáneamente sin tocar MongoDB
@app.get("/api/en_vivo_ram")
async def obtener_en_vivo_ram():
    return ultimo_registro_en_vivo

# --- INTERFAZ E HISTORIAL ---
@app.get("/", response_class=HTMLResponse)
async def leer_interfaz(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/historial/alertas")
async def obtener_alertas():
    datos = list(coleccion.find({"alerta_critica": True}).sort("$natural", -1).limit(50))
    for d in datos:
        d["_id"] = str(d["_id"])
    return datos