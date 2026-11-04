
import hashlib
import hmac
import json
import logging
import time

from aiohttp import web


WEBHOOK_PATH = "/topggwebhook"
EXPECTED_BOT_ID = 1113403511045107773
SIGNATURE_TOLERANCE_SECONDS = 300


def verify_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    """Prüft die Top.gg-v1-Signatur."""

    try:
        parts = {}

        for item in signature_header.split(","):
            key, value = item.strip().split("=", 1)
            parts[key] = value

        timestamp = parts["t"]
        received_signature = parts["v1"].lower()

        if not timestamp.isdigit() or len(received_signature) != 64:
            return False

        # Schutz vor alten bzw. erneut abgespielten Anfragen
        if abs(time.time() - int(timestamp)) > SIGNATURE_TOLERANCE_SECONDS:
            logging.warning("[Top.gg] Webhook-Signatur ist abgelaufen.")
            return False

        signed_payload = timestamp.encode("ascii") + b"." + raw_body

        expected_signature = hmac.new(
            secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_signature, received_signature)

    except (KeyError, ValueError, UnicodeError):
        return False


def create_webhook_app(bot, secret: str):
    app = web.Application(client_max_size=1024 * 1024)

    async def handle_webhook(request: web.Request):
        # Originalen Request-Body lesen
        raw_body = await request.read()
        signature = request.headers.get("x-topgg-signature")

        if not signature:
            logging.warning("[Top.gg] Anfrage ohne Signatur abgelehnt.")
            return web.Response(status=401)

        if not verify_signature(raw_body, signature, secret):
            logging.warning("[Top.gg] Ungültige Signatur abgelehnt.")
            return web.Response(status=401)

        # JSON verarbeiten
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logging.warning("[Top.gg] Ungültiges JSON erhalten.")
            return web.Response(status=400)

        if not isinstance(payload, dict):
            return web.Response(status=400)

        event_type = payload.get("type")

        # Unbekannte Events ignorieren
        if event_type not in ("vote.create", "webhook.test"):
            logging.info("[Top.gg] Unbekanntes Event: %s", event_type)
            return web.Response(status=204)

        data = payload.get("data")

        if not isinstance(data, dict):
            return web.Response(status=400)

        user = data.get("user")
        project = data.get("project")

        if not isinstance(user, dict) or not isinstance(project, dict):
            return web.Response(status=400)

        try:
            user_id = int(user["platform_id"])
            project_id = int(project["platform_id"])
        except (KeyError, TypeError, ValueError):
            return web.Response(status=400)

        # Sicherstellen, dass der Vote wirklich für Astra bestimmt ist
        expected_bot_id = bot.user.id if bot.user else EXPECTED_BOT_ID

        if project_id != expected_bot_id:
            logging.warning(
                "[Top.gg] Falsche Bot-ID erhalten: %s",
                project_id
            )
            return web.Response(status=403)

        # Test-Webhook
        if event_type == "webhook.test":
            logging.info("[Top.gg] Test-Webhook erhalten.")

            bot.dispatch("dbl_test", {
                "user": str(user_id),
                "bot": str(project_id),
                "type": "test"
            })

            return web.Response(status=204)

        # Echter Vote
        vote_id = data.get("id")
        weight = data.get("weight")

        if not isinstance(vote_id, str) or not vote_id:
            return web.Response(status=400)

        if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1:
            return web.Response(status=400)

        logging.info(
            "[Top.gg] Vote erhalten: User=%s | Gewicht=%s | ID=%s",
            user_id,
            weight,
            vote_id
        )

        # An die bestehende Vote-Verarbeitung weitergeben
        bot.dispatch("dbl_vote", {
            "user": str(user_id),
            "bot": str(project_id),
            "type": "upvote",
            "weight": weight,
            "event_id": vote_id
        })

        return web.Response(status=204)

    app.router.add_post(WEBHOOK_PATH, handle_webhook)

    return app


async def start_topgg_webhook(bot, secret: str, port: int):
    """Startet den neuen Top.gg-Webhook."""

    app = create_webhook_app(bot, secret)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        host="127.0.0.1",
        port=port
    )

    await site.start()

    logging.info(
        "[Top.gg] Neuer Webhook gestartet auf 127.0.0.1:%s",
        port
    )

    return runner
