from flask import Flask, Response, jsonify, send_from_directory
from flask_cors import CORS
import json
import os
import time
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

app = Flask(__name__, static_folder="static")

# Configure Flask-CORS
CORS(app, resources={
    r"/api/*": {
        "origins": "*",  # Allow all origins; restrict in production (e.g., ["http://localhost:5173"])
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Cache-Control", "Expires", "Pragma"]  # Added Pragma
    }
})

# Load configuration
try:
    with open("config/config.json", "r") as f:
        config = json.load(f)
    TRACE_FILE = config["data_paths"].get("execution_trace", "execution_trace.json")
except Exception as e:
    logging.error(f"Error loading config.json: {str(e)}")
    TRACE_FILE = "execution_trace.json"

# Set up logging
logging.basicConfig(level=logging.INFO, filename=config.get("log_file", "logs/app.log"))

class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback
        self.last_modified = 0

    def on_modified(self, event):
        if event.src_path.endswith(TRACE_FILE):
            current_mtime = os.path.getmtime(TRACE_FILE)
            if current_mtime > self.last_modified:
                self.last_modified = current_mtime
                self.callback()

def read_trace_file():
    """Read the execution trace JSON file."""
    try:
        with open(TRACE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"Error reading trace file: {str(e)}")
        return {"error": "Unable to read execution trace"}

@app.route("/api/execution_trace", methods=["GET"])
def get_execution_trace():
    """Return the full execution trace."""
    trace = read_trace_file()
    return jsonify(trace)

@app.route("/api/execution_stream")
def execution_stream():
    """Stream new execution steps as Server-Sent Events."""
    def generate():
        observer = Observer()
        event_handler = FileChangeHandler(lambda: None)
        observer.schedule(event_handler, os.path.dirname(TRACE_FILE), recursive=False)
        observer.start()
        last_step_count = 0

        try:
            while True:
                try:
                    trace = read_trace_file()
                    if "error" not in trace:
                        steps = trace.get("steps", [])
                        new_steps = steps[last_step_count:]
                        if new_steps:
                            for step in new_steps:
                                yield f"data: {json.dumps(step)}\n\n"
                            last_step_count = len(steps)
                        else:
                            # Send heartbeat to keep connection alive
                            yield ": heartbeat\n\n"
                    else:
                        yield f"data: {json.dumps({'error': 'Invalid trace file'})}\n\n"
                except Exception as e:
                    logging.error(f"SSE stream error: {str(e)}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                time.sleep(1)
        finally:
            observer.stop()
            observer.join()

    response = Response(generate(), mimetype="text/event-stream")
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'  # Ensure connection stays open
    return response

@app.route("/")
def index():
    """Serve the frontend HTML."""
    return send_from_directory("static", "index.html")

if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    app.run(host="0.0.0.0", port=5000, debug=True)