import os
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pymongo import MongoClient
import pytz
import random

app = FastAPI()

# Configuración de plantillas HTML
templates = Jinja2Templates(directory="templates")

# Conexión segura a MongoDB Atlas 
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://esp32:paTos123@cluster0.0wdqvuo.mongodb.net/?appName=Cluster0")
client = MongoClient(MONGO_URI)
db = client["proy"]
coleccion = db["registrossonido"]

# Modelo de datos para validar lo que manda el ESP32
class SensorData(BaseModel):
    valor_bruto: int

ultimo_ruido = 0
# 1. ENDPOINT PARA RECIBIR DATOS DEL ESP32
@app.post("/api/datos")
async def recibir_datos(data: SensorData):
    global ultimo_ruido
    
    # Capturamos lo que manda el ESP32 en este instante
    ruido_actual = data.valor_bruto
    
    # 1. Si el sensor detecta un golpe fuerte, actualizamos el tope de memoria
    if ruido_actual > 2000:
        ultimo_ruido = ruido_actual
        valor_a_procesar = ruido_actual
    else:
        # 2. Si el sensor manda 0 (silencio), pero tenemos un ruido fuerte en memoria, lo amortiguamos
        if ultimo_ruido > 0:
            ultimo_ruido = int(ultimo_ruido * 0.40)  # Baja al 40% en cada ciclo
            
            # Si el eco ya es muy bajito, lo rompemos para que regrese a silencio absoluto
            if ultimo_ruido < 100:
                ultimo_ruido = 0
                
        # El valor final será la amortiguación calculada (o 0 si ya se extinguió)
        valor_a_procesar = ultimo_ruido

    # Escalado para sacar el porcentaje en base a tu tope de 700
    valor_tope = 700
    porcentaje = min(int((valor_a_procesar / valor_tope) * 100), 100)
    
    # --- CLASIFICACIÓN CORREGIDA DE CATEGORÍAS ---
    if porcentaje < 15:
        categoria = "Silencio"
        alerta = False
    elif porcentaje < 75:
        categoria = "Moderado"
        alerta = False
    else:
        categoria = "Ruido Alto"
        alerta = True

    # --- FORMATO DE 12 HORAS PERFECTO PARA EL CLÚSTER MONGODB ---
    zona_horaria_mx = pytz.timezone("America/Mexico_City")
    ahora_mx = datetime.now(zona_horaria_mx)
    
    hora_12h = ahora_mx.strftime("%I:%M:%S %p")  # Ejemplo: "07:47:15 PM"
    hora_exacta_num = int(ahora_mx.strftime("%I"))

    documento = {
        "valor_bruto": valor_a_procesar,
        "porcentaje": porcentaje,
        "categoria": categoria,
        "alerta_critica": alerta,
        "fecha_hora": hora_12h,  # Esto se reflejará idéntico en tu MongoDB Atlas
        "hora_exacta": hora_exacta_num,
        "dia_semana": ahora_mx.strftime("%A")
    }
    
    resultado = coleccion.insert_one(documento)
    return {"status": "guardado", "id": str(resultado.inserted_id)}

# 2. ENDPOINT PARA LA GRÁFICA EN TIEMPO REAL (Últimos 20 registros)
@app.get("/api/historial/reciente")
async def obtener_recientes():
    # Trae los registros más nuevos de la base de datos
    cursor = coleccion.find({}, {"_id": 0}).sort("_id", -1).limit(20)
    registros = list(cursor)
    # Se invierte el orden para que en Chart.js el tiempo corra de izquierda a derecha
    return registros[::-1] 

# 3. ENDPOINT PARA FILTRADO DE LOGS (Solo alertas críticas)
@app.get("/api/historial/alertas")
async def obtener_alertas():
    cursor = coleccion.find({"alerta_critica": True}, {"_id": 0}).sort("_id", -1).limit(50)
    return list(cursor)

# 4. ENRUTAMIENTO PRINCIPAL DE LA INTERFAZ WEB
@app.get("/", response_class=HTMLResponse)
async def leer_interfaz(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})