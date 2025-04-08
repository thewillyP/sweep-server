import yaml
import itertools
import uuid
import json
from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool

db_pool = None

def create_app(db_pool):
    app = Flask(__name__)

    def generate_sweep_configs(config):
        parameters = config['parameters']
        keys = [k for k, v in parameters.items() if 'values' in v]
        values = [parameters[k]['values'] for k in keys]
        
        # Separate hyperparameters from metadata
        hyperparameters = {}
        for k, v in parameters.items():
            if 'value' in v:
                hyperparameters[k] = v['value']
            elif 'values' in v:
                hyperparameters[k] = v['values'][0]
        
        sweep_configs = []
        for combo in itertools.product(*values):
            sweep_config = hyperparameters.copy()
            for key, val in zip(keys, combo):
                sweep_config[key] = val
            sweep_configs.append({
                "program": config['program'],
                "name": config['name'],
                "config": sweep_config
            })
        return sweep_configs

    @app.route('/upload_config', methods=['POST'])
    def upload_config():
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400
        
        file = request.files['file']
        config = yaml.safe_load(file)
        sweep_configs = generate_sweep_configs(config)
        sweep_id = uuid.uuid4().hex
        
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                for sweep_config in sweep_configs:
                    cur.execute(
                        "INSERT INTO sweeps (sweep_id, config, status) VALUES (%s, %s, 'pending')",
                        (sweep_id, json.dumps(sweep_config))
                    )
                conn.commit()
        finally:
            db_pool.putconn(conn)
        
        return jsonify({"sweep_id": sweep_id}), 201

    @app.route('/get_sweep/<sweep_id>', methods=['GET'])
    def get_sweep(sweep_id):
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, sweep_id, config FROM sweeps 
                    WHERE sweep_id = %s AND status = 'pending' 
                    LIMIT 1 FOR UPDATE SKIP LOCKED""", (sweep_id,))
                sweep = cur.fetchone()
                
                if sweep:
                    cur.execute("UPDATE sweeps SET status = 'running' WHERE id = %s",
                                (sweep['id'],))
                    conn.commit()
                    config_data = json.loads(sweep['config'])
                    return jsonify({
                        "sweep_id": sweep['sweep_id'],
                        "program": config_data['program'],
                        "name": config_data['name'],
                        "config": config_data['config']
                    }), 200
                else:
                    cur.execute("SELECT COUNT(*) FROM sweeps WHERE sweep_id = %s AND status = 'pending'", (sweep_id,))
                    if cur.fetchone()['count'] == 0:
                        return jsonify({"message": "No sweeps left"}), 404
                    return jsonify({"message": "All sweeps currently in progress"}), 202
        finally:
            db_pool.putconn(conn)

    return app

def app_main(db_host, db_port, db_name, db_user, db_password):
    global db_pool
    db_pool = psycopg2.pool.SimpleConnectionPool(
        1, 10,
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_password,
        cursor_factory=RealDictCursor
    )
    return create_app(db_pool)