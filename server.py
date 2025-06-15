import yaml
import itertools
import uuid
import json
import random
from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool

db_pool = None


def create_app(db_pool):
    app = Flask(__name__)

    def generate_sweep_configs(config, sweep_id):
        parameters = config["parameters"]
        keys = [k for k, v in parameters.items() if "values" in v]
        values = [parameters[k]["values"] for k in keys]

        # Separate hyperparameters from metadata
        hyperparameters = {}
        for k, v in parameters.items():
            if "value" in v:
                hyperparameters[k] = v["value"]
            elif "values" in v:
                hyperparameters[k] = v["values"][0]

        # Combine original name with sweep_id
        base_name = config.get("name", "unnamed") + f"_{sweep_id}"

        sweep_configs = []
        for combo in itertools.product(*values):
            sweep_config = hyperparameters.copy()
            for key, val in zip(keys, combo):
                sweep_config[key] = val
            sweep_configs.append({"program": config["program"], "name": base_name, "config": sweep_config})
        return sweep_configs

    @app.route("/upload_config", methods=["POST"])
    def upload_config():
        if "file" not in request.files:
            return jsonify({"error": "No file part"}), 400

        file = request.files["file"]
        config = yaml.safe_load(file)
        if "method" not in config:
            config["method"] = "sweep"  # Default to sweep
        sweep_id = uuid.uuid4().hex
        sweep_configs = generate_sweep_configs(config, sweep_id)

        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                # Store original config in sweep_definitions
                cur.execute(
                    "INSERT INTO sweep_definitions (sweep_id, original_config, method) VALUES (%s, %s, %s)",
                    (sweep_id, json.dumps(config), config["method"]),
                )
                # Store all configurations
                for sweep_config in sweep_configs:
                    cur.execute(
                        "INSERT INTO hyperparameter_configs (sweep_id, config, status) VALUES (%s, %s, 'pending')",
                        (sweep_id, json.dumps(sweep_config)),
                    )
                conn.commit()
        finally:
            db_pool.putconn(conn)

        return jsonify({"sweep_id": sweep_id}), 201

    @app.route("/get_sweep/<sweep_id>", methods=["GET"])
    def get_sweep(sweep_id):
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                # Check sweep method
                cur.execute("SELECT method FROM sweep_definitions WHERE sweep_id = %s", (sweep_id,))
                result = cur.fetchone()
                if not result:
                    return jsonify({"error": "Sweep ID not found"}), 404

                method = result["method"]
                if method == "random":
                    # Randomly select one pending configuration without marking as running
                    cur.execute(
                        """
                        SELECT id, sweep_id, config FROM hyperparameter_configs 
                        WHERE sweep_id = %s AND status = 'pending' 
                        ORDER BY RANDOM() LIMIT 1""",
                        (sweep_id,),
                    )
                    sweep = cur.fetchone()
                    if sweep:
                        config_data = sweep["config"]
                        return jsonify(
                            {
                                "sweep_id": sweep["sweep_id"],
                                "program": config_data["program"],
                                "name": config_data["name"],
                                "config": config_data["config"],
                            }
                        ), 200
                    return jsonify({"message": "No pending configurations available"}), 404
                else:
                    # Sweep method: select and mark as running
                    cur.execute(
                        """
                        SELECT id, sweep_id, config FROM hyperparameter_configs 
                        WHERE sweep_id = %s AND status = 'pending' 
                        LIMIT 1 FOR UPDATE SKIP LOCKED""",
                        (sweep_id,),
                    )
                    sweep = cur.fetchone()
                    if sweep:
                        cur.execute(
                            "UPDATE hyperparameter_configs SET status = 'running' WHERE id = %s", (sweep["id"],)
                        )
                        conn.commit()
                        config_data = sweep["config"]
                        return jsonify(
                            {
                                "sweep_id": sweep["sweep_id"],
                                "program": config_data["program"],
                                "name": config_data["name"],
                                "config": config_data["config"],
                            }
                        ), 200
                    else:
                        cur.execute(
                            "SELECT COUNT(*) FROM hyperparameter_configs WHERE sweep_id = %s AND status = 'pending'",
                            (sweep_id,),
                        )
                        if cur.fetchone()["count"] == 0:
                            return jsonify({"message": "No sweeps left"}), 404
                        return jsonify({"message": "All sweeps currently in progress"}), 202
        finally:
            db_pool.putconn(conn)

    @app.route("/sweep_count/<sweep_id>", methods=["GET"])
    def get_sweep_count(sweep_id):
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM hyperparameter_configs WHERE sweep_id = %s AND status = 'pending'",
                    (sweep_id,),
                )
                count = cur.fetchone()["count"]
                return jsonify({"sweep_id": sweep_id, "remaining_configs": count}), 200
        finally:
            db_pool.putconn(conn)

    @app.route("/active_sweeps", methods=["GET"])
    def get_active_sweeps():
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT sweep_id FROM hyperparameter_configs WHERE status IN ('pending', 'running')"
                )
                sweep_ids = [row["sweep_id"] for row in cur.fetchall()]
                return jsonify({"active_sweeps": sweep_ids}), 200
        finally:
            db_pool.putconn(conn)

    @app.route("/sweep_config/<sweep_id>", methods=["GET"])
    def get_sweep_config(sweep_id):
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT original_config FROM sweep_definitions WHERE sweep_id = %s", (sweep_id,))
                result = cur.fetchone()
                if result:
                    return jsonify(result["original_config"]), 200
                return jsonify({"error": "Sweep ID not found"}), 404
        finally:
            db_pool.putconn(conn)

    @app.route("/cancel_sweep/<sweep_id>", methods=["POST"])
    def cancel_sweep(sweep_id):
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE hyperparameter_configs SET status = 'cancelled' WHERE sweep_id = %s AND status = 'pending'",
                    (sweep_id,),
                )
                conn.commit()
                return jsonify({"message": f"Sweep {sweep_id} cancelled"}), 200
        finally:
            db_pool.putconn(conn)

    @app.route("/reset_sweep/<sweep_id>", methods=["POST"])
    def reset_sweep(sweep_id):
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                # Get original config and method from sweep_definitions
                cur.execute("SELECT original_config, method FROM sweep_definitions WHERE sweep_id = %s", (sweep_id,))
                result = cur.fetchone()
                if not result:
                    return jsonify({"error": "Sweep ID not found"}), 404

                config = result["original_config"]
                method = result["method"]
                # For sweep method, check if number of configs matches expected
                if method == "sweep":
                    parameters = config["parameters"]
                    keys = [k for k, v in parameters.items() if "values" in v]
                    expected_count = 1
                    for key in keys:
                        expected_count *= len(parameters[key]["values"])

                    cur.execute("SELECT COUNT(*) FROM hyperparameter_configs WHERE sweep_id = %s", (sweep_id,))
                    actual_count = cur.fetchone()["count"]
                    if actual_count != expected_count:
                        return jsonify({"error": "Configuration count mismatch, cannot reset"}), 400

                # Reset status to pending for all configurations
                cur.execute("UPDATE hyperparameter_configs SET status = 'pending' WHERE sweep_id = %s", (sweep_id,))
                conn.commit()
                return jsonify({"message": f"Sweep {sweep_id} reset"}), 200
        finally:
            db_pool.putconn(conn)

    @app.route("/delete_sweep/<sweep_id>", methods=["DELETE"])
    def delete_sweep(sweep_id):
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                # Delete from both tables
                cur.execute("DELETE FROM hyperparameter_configs WHERE sweep_id = %s", (sweep_id,))
                cur.execute("DELETE FROM sweep_definitions WHERE sweep_id = %s", (sweep_id,))
                if cur.rowcount == 0:
                    return jsonify({"error": "Sweep ID not found"}), 404
                conn.commit()
                return jsonify({"message": f"Sweep {sweep_id} deleted"}), 200
        finally:
            db_pool.putconn(conn)

    return app


def app_main(db_host, db_port, db_name, db_user, db_password):
    global db_pool
    db_pool = psycopg2.pool.SimpleConnectionPool(
        1,
        10,
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_password,
        cursor_factory=RealDictCursor,
    )
    return create_app(db_pool)
