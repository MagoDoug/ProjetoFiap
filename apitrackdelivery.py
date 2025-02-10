# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit
from flasgger import Swagger
import psycopg2
import os
from urllib.parse import urlparse
from flask_cors import CORS
import pytz
from datetime import datetime

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
    conn = psycopg2.connect(
        dbname=result.path[1:],  
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )

    # Define o timezone para São Paulo
    cur = conn.cursor()
    cur.execute("SET timezone TO 'America/Sao_Paulo';")
    cur.close()

    return conn

def init_db():
    """Criação das tabelas no banco de dados"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS pedidos (
            id SERIAL PRIMARY KEY,
            status_id INT NOT NULL DEFAULT 1, -- Começa com "Pedido Confirmado"
            latitude FLOAT NOT NULL,
            longitude FLOAT NOT NULL,
            entregador_id TEXT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS status (
            id SERIAL PRIMARY KEY,
            descricao TEXT NOT NULL UNIQUE,
            descricao_detalhada TEXT NOT NULL
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS historico_status (
            id SERIAL PRIMARY KEY,
            pedido_id INT NOT NULL,
            status_id INT NOT NULL,
            data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pedido_id) REFERENCES pedidos(id),
            FOREIGN KEY (status_id) REFERENCES status(id)
        )
    ''')

    conn.commit()
    cur.close()
    conn.close()

@app.route('/create_pedido', methods=['POST'])
def create_pedido():
    """Cria um novo pedido com localização inicial e status 'Pedido Confirmado'"""
    data = request.json
    latitude = data.get("latitude")
    longitude = data.get("longitude")

    if latitude is None or longitude is None:
        return jsonify({"error": "Latitude e Longitude são obrigatórios"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    # Insere o novo pedido e define o status como "Pedido Confirmado"
    cur.execute("""
        INSERT INTO pedidos (status_id, latitude, longitude) 
        VALUES (1, %s, %s) RETURNING id
    """, (latitude, longitude))

    pedido_id = cur.fetchone()[0]

    # Adiciona ao histórico de status
    cur.execute("""
        INSERT INTO historico_status (pedido_id, status_id) 
        VALUES (%s, 1)
    """, (pedido_id,))

    conn.commit()
    cur.close()
    conn.close()

    # Emite evento WebSocket para atualização em tempo real
    socketio.emit("status_update", {"pedido_id": pedido_id, "status_id": 1})

    return jsonify({"message": "Pedido criado com sucesso", "pedido_id": pedido_id})

@app.route('/get_status_history/<int:pedido_id>', methods=['GET'])
def get_status_history(pedido_id):
    """Retorna o histórico de status de um pedido específico"""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT s.id, s.descricao 
        FROM historico_status hs
        JOIN status s ON hs.status_id = s.id
        WHERE hs.pedido_id = %s
        ORDER BY hs.data_hora ASC
    """, (pedido_id,))

    historico = [{"status_id": row[0], "status": row[1]} for row in cur.fetchall()]

    cur.close()
    conn.close()

    if not historico:
        return jsonify({"error": "Pedido não encontrado ou sem histórico"}), 404

    return jsonify(historico)

@app.route('/assign_entregador', methods=['POST'])
def assign_entregador():
    """Atribui um entregador ao pedido e registra a localização do restaurante"""
    data = request.json
    pedido_id = data.get("pedido_id")
    entregador_id = data.get("entregador_id")
    latitude = data.get("latitude")
    longitude = data.get("longitude")

    if not pedido_id or not entregador_id or latitude is None or longitude is None:
        return jsonify({"error": "Pedido ID, Entregador ID, Latitude e Longitude são obrigatórios"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    # Verifica se o pedido existe
    cur.execute("SELECT id FROM pedidos WHERE id = %s", (pedido_id,))
    pedido = cur.fetchone()

    if not pedido:
        return jsonify({"error": "Pedido não encontrado"}), 404

    # Atualiza o pedido com o entregador e localização do restaurante
    cur.execute("""
        UPDATE pedidos 
        SET entregador_id = %s, latitude = %s, longitude = %s, status_id = 2
        WHERE id = %s
    """, (entregador_id, latitude, longitude, pedido_id))

    # Salva no histórico de status como "Em Preparação"
    cur.execute("""
        INSERT INTO historico_status (pedido_id, status_id) 
        VALUES (%s, 2)
    """, (pedido_id,))

    conn.commit()
    cur.close()
    conn.close()

    # Emite evento WebSocket para atualização em tempo real
    socketio.emit("status_update", {"pedido_id": pedido_id, "status_id": 2, "entregador_id": entregador_id})

    return jsonify({"message": "Entregador atribuído ao pedido e status atualizado para 'Em Preparação'"})

@app.route('/update_status', methods=['POST'])
def update_status():
    """Atualiza o status de um pedido e salva no histórico"""
    data = request.json
    pedido_id = data.get("pedido_id")
    status_id = data.get("status_id")

    if not pedido_id or not status_id:
        return jsonify({"error": "Pedido ID e status ID são obrigatórios"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    # Atualiza o status do pedido
    cur.execute("UPDATE pedidos SET status_id = %s WHERE id = %s", (status_id, pedido_id))

    # Salva no histórico
    cur.execute("INSERT INTO historico_status (pedido_id, status_id) VALUES (%s, %s)", (pedido_id, status_id))

    conn.commit()
    cur.close()
    conn.close()

    socketio.emit("status_update", {"pedido_id": pedido_id, "status_id": status_id})

    return jsonify({"message": "Status atualizado e registrado no histórico"})

@socketio.on('connect')
def handle_connect():
    print('Cliente conectado')

@socketio.on('disconnect')
def handle_disconnect():
    print('Cliente desconectado')

if __name__ == '__main__':
    init_db()
    print("✅ A API está rodando com WebSockets e gerenciamento de entregadores!")
    socketio.run(app, host='0.0.0.0', port=5000)
