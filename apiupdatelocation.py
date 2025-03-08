# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit
from flasgger import Swagger
import psycopg2
import os
from urllib.parse import urlparse
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")
Swagger(app)

# Configuração do Banco de Dados PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("⚠️ ERRO: A variável DATABASE_URL não está definida!")

def get_db_connection():
    result = urlparse(DATABASE_URL)
    return psycopg2.connect(
        dbname=result.path[1:],  
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )

def init_db():
    """Criação da tabela de entregadores no banco de dados"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS entregadores (
            id TEXT PRIMARY KEY,
            latitude REAL,
            longitude REAL
        )
    ''')
    
    conn.commit()
    cur.close()
    conn.close()

@app.route('/update_location', methods=['POST'])
def update_location():
    """Atualiza a localização do entregador e emite WebSocket"""
    data = request.get_json()
    entregador_id = data.get('id')
    latitude = data.get('latitude')
    longitude = data.get('longitude')

    if not entregador_id or latitude is None or longitude is None:
        return jsonify({'error': 'Dados inválidos'}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO entregadores (id, latitude, longitude)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude
    """, (entregador_id, latitude, longitude))
    conn.commit()
    cur.close()
    conn.close()

    socketio.emit('location_update', {'id': entregador_id, 'latitude': latitude, 'longitude': longitude})

    return jsonify({'message': 'Localização atualizada e enviada via WebSocket'})

@socketio.on('connect')
def handle_connect():
    print('Cliente conectado')

@socketio.on('disconnect')
def handle_disconnect():
    print('Cliente desconectado')

if __name__ == '__main__':
    init_db()
    print("✅ A API está rodando apenas para atualização de localização!")
    socketio.run(app, host='0.0.0.0', port=5000)
