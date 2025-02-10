# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit
from flasgger import Swagger
import psycopg2
import os
from urllib.parse import urlparse
from flask_cors import CORS
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
    return psycopg2.connect(
        dbname=result.path[1:],  
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )

def init_db():
    """Criação das tabelas no banco de dados"""
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

    # Verifica se o pedido existe
    cur.execute("SELECT id FROM pedidos WHERE id = %s", (pedido_id,))
    pedido = cur.fetchone()

    if not pedido:
        return jsonify({"error": "Pedido não encontrado"}), 404

    # Atualiza o status do pedido
    cur.execute("UPDATE pedidos SET status_id = %s WHERE id = %s", (status_id, pedido_id))

    # Salva no histórico
    cur.execute("INSERT INTO historico_status (pedido_id, status_id) VALUES (%s, %s)", (pedido_id, status_id))

    conn.commit()
    cur.close()
    conn.close()

    socketio.emit("status_update", {"pedido_id": pedido_id, "status_id": status_id})

    return jsonify({"message": "Status atualizado e registrado no histórico"})


@app.route('/get_status_history/<pedido_id>', methods=['GET'])
def get_status_history(pedido_id):
    """Obtém o histórico de status de um pedido"""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('''
        SELECT s.descricao, h.data_hora 
        FROM historico_status h
        JOIN status s ON h.status_id = s.id
        WHERE h.pedido_id = %s
        ORDER BY h.data_hora ASC
    ''', (pedido_id,))

    historico = [{"status": row[0], "data_hora": row[1].strftime("%d/%m/%Y %H:%M:%S")} for row in cur.fetchall()]
    
    cur.close()
    conn.close()

    return jsonify(historico)

@socketio.on('connect')
def handle_connect():
    print('Cliente conectado')

@socketio.on('disconnect')
def handle_disconnect():
    print('Cliente desconectado')

if __name__ == '__main__':
    init_db()
    print("✅ A API está rodando com WebSockets e histórico de status!")
    socketio.run(app, host='0.0.0.0', port=5000)
