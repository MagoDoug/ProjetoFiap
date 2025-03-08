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
        port=result.port,
        sslmode='require'  # Importante para Supabase
    )

def init_db():
    """Criação da tabela localizacao no banco de dados"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS localizacao (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            pedido_id INT UNIQUE,
            latitude TEXT,
            longitude TEXT
        )
    ''')
    
    conn.commit()
    cur.close()
    conn.close()

@app.route('/update_location', methods=['POST'])
def update_location():
    """Atualiza a localização do pedido e emite WebSocket"""
    data = request.get_json()
    pedido_id = data.get('pedido_id')
    latitude = data.get('latitude')
    longitude = data.get('longitude')

    if not pedido_id or latitude is None or longitude is None:
        return jsonify({'error': 'Dados inválidos'}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE localizacao 
        SET latitude = %s, longitude = %s
        WHERE pedido_id = %s
        RETURNING id, created_at
    """, (latitude, longitude, pedido_id))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    if row:
        socketio.emit('location_update', {'id': row[0], 'created_at': row[1], 'pedido_id': pedido_id, 'latitude': latitude, 'longitude': longitude})
        return jsonify({'message': 'Localização atualizada e enviada via WebSocket'})
    else:
        return jsonify({'error': 'Pedido não encontrado'}), 404

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
