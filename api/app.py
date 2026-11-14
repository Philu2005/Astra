import logging
from flask import Flask, jsonify
from waitress import serve
from api.routes import api_bp

logger = logging.getLogger("astra.api")


def create_app(bot=None, guild_cache=None, guild_cache_lock=None, config=None) -> Flask:
    """Erstellt und konfiguriert die Flask-Anwendung für die interne API."""
    app = Flask(__name__)

    # Standard-Konfigurationen
    if config:
        app.config.update(config)

    app.config["DISCORD_BOT"] = bot
    app.config["GUILD_CACHE"] = guild_cache if guild_cache is not None else {}
    app.config["GUILD_CACHE_LOCK"] = guild_cache_lock

    # Blueprint registrieren
    app.register_blueprint(api_bp)

    # Einheitliche JSON-Fehlerbehandlung
    @app.errorhandler(400)
    def bad_request(e):
        description = getattr(e, "description", "Bad Request")
        return jsonify(success=False, error=description), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify(success=False, error="Endpoint not found"), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify(success=False, error="Method not allowed"), 405

    @app.errorhandler(500)
    def internal_server_error(e):
        logger.error(f"Interner Serverfehler in API: {e}")
        return jsonify(success=False, error="Internal server error"), 500

    return app


def run_flask(app: Flask, host: str = "127.0.0.1", port: int = 5000):
    """Startet den Waitress-WSGI-Server für die interne Flask-API gebunden an 127.0.0.1."""
    logger.info(f"🚀 Interne Flask-API startet auf http://{host}:{port}")
    serve(app, host=host, port=port)
