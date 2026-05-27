"""
Zyphraxis Phase 8 — Local API Bridge
Wraps the Phase 7 engine so the Phase 8 chatbot UI can call it.
Run: python zyphraxis_phase8_server.py
"""
import sys, os
import os as _os; sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "engine"))

from flask import Flask, request, jsonify
from flask_cors import CORS
from pipeline_integration import run_phase6

app = Flask(__name__)
CORS(app)

@app.route("/run", methods=["POST"])
def run():
    patient = request.json
    try:
        result = run_phase6(patient)
        return jsonify({"output": result, "ok": True})
    except Exception as e:
        return jsonify({"output": None, "ok": False, "error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok", "engine": "zyphraxis_phase7"})

if __name__ == "__main__":
    app.run(port=7845, debug=False)
