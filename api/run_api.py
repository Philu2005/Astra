import os
from dotenv import load_dotenv
from api.app import create_app, run_flask


def main():
    load_dotenv()
    host = os.getenv("ASTRA_INTERNAL_API_HOST", "127.0.0.1")
    port = int(os.getenv("ASTRA_INTERNAL_API_PORT", "5000"))
    stale_after = float(os.getenv("ASTRA_HEARTBEAT_STALE_AFTER_SECONDS", "90"))

    app = create_app(config={"HEARTBEAT_STALE_AFTER_SECONDS": stale_after})
    run_flask(app, host=host, port=port)


if __name__ == "__main__":
    main()
