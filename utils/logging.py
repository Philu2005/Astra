import logging


class CleanLogs(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()

        # Webhook Logs raus
        if "/webhook/" in msg:
            return False

        # Scanner Müll raus
        noise = [
            "UNKNOWN / HTTP",
            "GET / HTTP",
            "POST / HTTP",
            "favicon.ico",
            ".well-known",
            "/api",
            "/_next",
            "BadHttpMessage"
        ]

        return not any(n in msg for n in noise)


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-5s | %(message)-60s",
        datefmt="%H:%M:%S"
    )

    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger().addFilter(CleanLogs())