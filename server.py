# server.py
import argparse
import yaml
import itertools
import uuid
import json
from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# Database connection
def get_db_connection(db_host, db_port, db_name, db_user, db_password):
    return psycopg2.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_password,
        cursor_factory=RealDictCursor
    )

# Initialize database tables
def init_db(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sweeps (
                id SERIAL PRIMARY KEY,
                sweep_id VARCHAR(32) NOT NULL,
                config JSONB NOT NULL,
                status VARCHAR(20) DEFAULT 'pending'
            );
        """)
        conn.commit()

# Generate all combinations for grid search
def generate_sweep_configs(config):
    parameters = config['parameters']
    keys = [k for k, v in parameters.items() if 'values' in v]
    values = [parameters[k]['values'] for k in keys]
    
    base_config = {}
    for k, v in parameters.items():
        if 'value' in v:
            base_config[k] = v['value']
        elif 'values' in v:
            base_config[k] = v['values'][0]
    base_config.update({k: v for k, v in config.items() if k != 'parameters'})
    base_config['program'] = config['program']
    
    sweep_configs = []
    for combo in itertools.product(*values):
        sweep_config = base_config.copy()
        for key, val in zip(keys, combo):
            sweep_config[key] = val
        sweep_configs.append(sweep_config)
    return sweep_configs

# Global DB connection (will be set in main)
db_conn = None

@app.route('/upload_config', methods=['POST'])
def upload_config():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    config = yaml.safe_load(file)
    sweep_configs = generate_sweep_configs(config)
    sweep_id = uuid.uuid4().hex  # Use hex for a 32-char string without hyphens
    
    with db_conn.cursor() as cur:
        for sweep_config in sweep_configs:
            cur.execute(
                "INSERT INTO sweeps (sweep_id, config, status) VALUES (%s, %s, 'pending')",
                (sweep_id, json.dumps(sweep_config))
            )
        db_conn.commit()
    
    return jsonify({"sweep_id": sweep_id}), 201

@app.route('/get_sweep/<sweep_id>', methods=['GET'])
def get_sweep(sweep_id):
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT id, sweep_id, config FROM sweeps 
            WHERE sweep_id = %s AND status = 'pending' 
            LIMIT 1 FOR UPDATE SKIP LOCKED""", (sweep_id,))
        sweep = cur.fetchone()
        
        if sweep:
            cur.execute("UPDATE sweeps SET status = 'running' WHERE id = %s",
                        (sweep['id'],))
            db_conn.commit()
            return jsonify({"sweep_id": sweep['sweep_id'], "config": sweep['config']}), 200
        else:
            cur.execute("SELECT COUNT(*) FROM sweeps WHERE sweep_id = %s AND status = 'pending'", (sweep_id,))
            if cur.fetchone()['count'] == 0:
                return jsonify({"message": "No sweeps left"}), 404
            return jsonify({"message": "All sweeps currently in progress"}), 202

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Sweep Server')
    parser.add_argument('--db-host', required=True, help='Database host')
    parser.add_argument('--db-port', default='5432', help='Database port')
    parser.add_argument('--db-name', default='sweeps', help='Database name')
    parser.add_argument('--db-user', default='postgres', help='Database user')
    parser.add_argument('--db-password', default='password', help='Database password')
    parser.add_argument('--port', type=int, default=5000, help='Port to run the server on')
    args = parser.parse_args()

    db_conn = get_db_connection(args.db_host, args.db_port, args.db_name, args.db_user, args.db_password)
    init_db(db_conn)
    app.run(host='0.0.0.0', port=args.port)