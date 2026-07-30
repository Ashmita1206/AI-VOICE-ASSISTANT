"""
Flask Application Factory
==========================

Entry point for the Jarvis AI Voice Assistant web server.

Run:
    python -m web.app
"""

import os
import sys
import io
import logging

# Prevent UnicodeEncodeError on Windows stdout when printing emojis
if sys.platform.startswith("win") and not hasattr(sys.stdout, "_pytest_captured_and_tear_down") and "pytest" not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pyrefly: ignore [missing-import]
from flask import Flask, render_template
from flask_cors import CORS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    CORS(app)

    # Initialise persistent storage
    from storage.database import init_db
    init_db()

    # Register API routes
    from web.routes import api
    app.register_blueprint(api)

    # Ping remote planner
    import config
    import requests
    try:
        # Check /health endpoint if possible, otherwise just a quick HEAD or GET
        health_url = config.COLAB_API_URL.replace("/plan", "/health")
        resp = requests.get(health_url, timeout=5)
        if resp.status_code == 200:
            print("Remote Planner: Connected")
        else:
            print("Remote Planner: Offline")
    except Exception:
        print("Remote Planner: Offline")

    # Serve the main page
    @app.route("/")
    def index():
        return render_template("index.html")
        
    @app.route("/history_page")
    def history_page():
        return render_template("history.html")

    # Ensure audio directory exists
    os.makedirs(os.path.join(app.static_folder, "audio"), exist_ok=True)

    return app


if __name__ == "__main__":
    app = create_app()
    # Disable auto-reloader so PyTorch/torch_dynamo background file touches do not restart Flask mid-request
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
