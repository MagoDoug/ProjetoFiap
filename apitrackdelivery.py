# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit
from flasgger import Swagger
import psycopg2
import requests
import os
from urllib.parse import urlparse
from flask_cors import CORS  # Importa a biblioteca CORS

app = Flask(__name__)
CORS(app)  # Habilita CORS para toda a API
socketio = SocketIO(app, cors_allowed_origins="*")  # Permite WebSocket de qualquer origem
Swagger(app)

# Configuração do Banco de Dados PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("⚠️ ERRO: A variável DATABASE_URL não está definida!")

def get_db_connection():
    """Converte DATABASE_URL para um formato compatível e cria a conexão com PostgreSQL"""
    result = urlparse(DATABASE_URL)

    conn = psycopg2.connect(
        dbname=result.path[1:],  # Remove a barra inicial do nome do banco
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )
    return conn

# URL do OpenStreetMap para geolocalização
OSM_BASE_URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {"User-Agent": "MyTrackingApp/1.0 (magodoug@hotmail.com)"}  

def init_db():
    """Cria as tabelas no banco de dados se ainda não existirem"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS entregadores (
            id TEXT PRIMARY KEY,
            latitude REAL,
            longitude REAL
        )
    ''')
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS pedidos (
            id SERIAL PRIMARY KEY,
            status_id INT NOT NULL,
            latitude FLOAT,
            longitude FLOAT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS status (
            id SERIAL PRIMARY KEY,
            descricao TEXT NOT NULL UNIQUE,
            descricao_detalhada TEXT NOT NULL
        )
    ''')

    conn.commit()
    cur.close()
    conn.close()

@app.route('/update_location', methods=['POST'])
def update_location():
    """Atualiza a localização do entregador"""
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

    return jsonify({'message': 'Localização atualizada com sucesso'})

@app.route('/get_location/<entregador_id>', methods=['GET'])
def get_location(entregador_id):
    """Obtém a localização do entregador"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT latitude, longitude FROM entregadores WHERE id = %s", (entregador_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        latitude, longitude = row
        try:
            response = requests.get(OSM_BASE_URL, params={"lat": latitude, "lon": longitude, "format": "json"}, headers=HEADERS)
            address = response.json().get("display_name", "Endereço não encontrado") if response.status_code == 200 else "Erro ao obter endereço"
        except requests.exceptions.RequestException:
            address = "Falha na comunicação com OpenStreetMap"

        #return jsonify({'id': entregador_id, 'latitude': latitude, 'longitude': longitude, 'address': address})
        return jsonify({'id': entregador_id, 'latitude': latitude, 'longitude': longitude})

    return jsonify({'error': 'Entregador não encontrado'}), 404

@app.route('/update_status', methods=['POST'])
def update_status():
    """Atualiza o status de um pedido"""
    data = request.json
    pedido_id = data.get("pedido_id")
    status_id = data.get("status_id")

    if not pedido_id or not status_id:
        return jsonify({"error": "Pedido ID e status ID são obrigatórios"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    # Verifica se o pedido existe antes de atualizar
    cur.execute("SELECT id FROM pedidos WHERE id = %s", (pedido_id,))
    pedido = cur.fetchone()
    if not pedido:
        return jsonify({"error": "Pedido não encontrado"}), 404

    cur.execute("UPDATE pedidos SET status_id = %s WHERE id = %s", (status_id, pedido_id))
    conn.commit()
    cur.close()
    conn.close()

    socketio.emit("status_update", {"pedido_id": pedido_id, "status_id": status_id})

    return jsonify({"message": "Status atualizado com sucesso!"})

@app.route('/get_status/<pedido_id>', methods=['GET'])
def get_status(pedido_id):
    """Obtém o status do pedido"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT COALESCE(s.descricao, 'Status não encontrado'), COALESCE(s.descricao_detalhada, 'Sem descrição detalhada')
        FROM pedidos p
        LEFT JOIN status s ON p.status_id = s.id
        WHERE p.id = %s
    ''', (pedido_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        return jsonify({"pedido_id": pedido_id, "status": row[0], "descricao_detalhada": row[1]})
    
    return jsonify({"error": "Pedido não encontrado"}), 404

@socketio.on('connect')
def handle_connect():
    print('Cliente conectado')

@socketio.on('disconnect')
def handle_disconnect():
    print('Cliente desconectado')

if __name__ == '__main__':
    init_db()
    print("✅ A API está rodando!")
    socketio.run(app, host='0.0.0.0', port=5000)
