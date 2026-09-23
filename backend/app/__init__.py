"""MiroFish Backend - Flask application factory."""

import hmac
import os
import re
import warnings

warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request, send_from_directory, jsonify, Response
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger

# IDs accepted by MiroFish are generated internally with prefixes such as
# proj_, sim_, report_. Restricting request-supplied identifiers prevents
# path traversal through values later passed to os.path.join().
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SAFE_PLATFORM_VALUES = {"twitter", "reddit"}
ID_KEYS = {"project_id", "simulation_id", "report_id", "graph_id"}


def _invalid_identifier(value):
    return not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value)


def create_app(config_class=Config):
    """Create the Flask application."""
    frontend_dist = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'dist')
    )
    app = Flask(__name__, static_folder=None)
    app.config.from_object(config_class)

    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    logger = setup_logger('mirofish')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process

    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish Backend starting...")
        logger.info("=" * 50)

    # Same-origin production deployment: cross-origin API access is not needed.
    # Keep localhost origins only for local development.
    CORS(
        app,
        resources={r"/api/*": {"origins": [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]}},
    )

    from .services.simulation_manager import SimulationManager
    SimulationManager.SIMULATION_DATA_DIR = app.config['OASIS_SIMULATION_DATA_DIR']

    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("Simulation process cleanup registered")

    @app.before_request
    def security_gate():
        # Health endpoint stays unauthenticated so Render can monitor the service.
        if request.path == '/health':
            return None

        username = app.config.get('BASIC_AUTH_USERNAME')
        password = app.config.get('BASIC_AUTH_PASSWORD')
        if username and password:
            auth = request.authorization
            valid = (
                auth is not None
                and hmac.compare_digest(auth.username or '', username)
                and hmac.compare_digest(auth.password or '', password)
            )
            if not valid:
                return Response(
                    'Authentication required',
                    401,
                    {'WWW-Authenticate': 'Basic realm="MiroFish", charset="UTF-8"'},
                )

        # Validate path parameters exposed by Flask routes.
        for key, value in (request.view_args or {}).items():
            if key in ID_KEYS and _invalid_identifier(value):
                return jsonify({'error': f'Invalid {key}'}), 400
            if key == 'platform' and value not in SAFE_PLATFORM_VALUES:
                return jsonify({'error': 'Invalid platform'}), 400

        # Validate identifier-like values supplied in query parameters.
        for key in ID_KEYS:
            if key in request.args and _invalid_identifier(request.args.get(key)):
                return jsonify({'error': f'Invalid {key}'}), 400
        if 'platform' in request.args and request.args.get('platform') not in SAFE_PLATFORM_VALUES:
            return jsonify({'error': 'Invalid platform'}), 400

        # Validate JSON bodies before service code can use IDs as filesystem paths.
        if request.is_json:
            body = request.get_json(silent=True)
            if isinstance(body, dict):
                for key in ID_KEYS:
                    if key in body and _invalid_identifier(body[key]):
                        return jsonify({'error': f'Invalid {key}'}), 400
                if 'platform' in body and body['platform'] not in SAFE_PLATFORM_VALUES:
                    return jsonify({'error': 'Invalid platform'}), 400
        return None

    @app.before_request
    def log_request():
        # Never log request bodies: simulation prompts and credentials can contain
        # commercially sensitive material.
        get_logger('mirofish.request').debug(
            f"request: {request.method} {request.path}"
        )

    @app.after_request
    def secure_response(response):
        get_logger('mirofish.request').debug(f"response: {response.status_code}")
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Cache-Control'] = 'no-store' if request.path.startswith('/api/') else response.headers.get('Cache-Control', 'no-cache')
        return response

    from .api import graph_bp, simulation_bp, report_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')

    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish Backend'}

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_frontend(path):
        if path.startswith('api/'):
            return {'error': 'Not found'}, 404
        requested = os.path.join(frontend_dist, path)
        if path and os.path.isfile(requested):
            return send_from_directory(frontend_dist, path)
        return send_from_directory(frontend_dist, 'index.html')

    if should_log_startup:
        if not (app.config.get('BASIC_AUTH_USERNAME') and app.config.get('BASIC_AUTH_PASSWORD')):
            logger.warning('MIROFISH_USERNAME/MIROFISH_PASSWORD are not set; public UI is not password protected')
        logger.info("MiroFish Backend started")

    return app
