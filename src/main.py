"""Application entrypoint — lifecycle management only, zero business logic."""

import logging
import signal
import threading

import telebot
import uvicorn

from src import config
from src.agent.deep_agent import build_agent
from src.api.server import app as dashboard_app
from src.persistence.client import setup_indexes
from src.scheduler.service import SchedulerService
from src.telegram.consumer import TelegramConsumer
from src.telegram.producer import TelegramProducer
from src.utils.logging import setup_logging


class Application:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._agent = build_agent(model_name=config.ORCHESTRATOR_MODEL)

        # Telegram consumer and scheduler need the agent to be initialized
        self._telegram_bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, threaded=False)
        self._telegram_producer = TelegramProducer(bot=self._telegram_bot, agent=self._agent)
        self._telegram_consumer = TelegramConsumer(
            stop_event=self.stop_event,
            bot=self._telegram_bot,
            telegram_producer=self._telegram_producer,
        )
        self._scheduler = SchedulerService(telegram_producer=self._telegram_producer)

    def _register_signals(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, frame: object) -> None:
        logging.info("Signal %s received — initiating graceful shutdown.", signum)
        self.stop_event.set()

    def _spawn(self, target: threading.Thread) -> None:
        target.daemon = True
        target.start()
        self._threads.append(target)

    def start(self) -> None:
        self._register_signals()
        logging.info("Starting %s.", config.APP_NAME)

        self._scheduler.start()

        self._spawn(
            threading.Thread(
                target=self._telegram_consumer.run,
                name="telegram-consumer",
                daemon=True,
            )
        )

        if config.DASHBOARD_ENABLED:
            uvi_config = uvicorn.Config(
                dashboard_app,
                host="0.0.0.0",
                port=config.DASHBOARD_PORT,
                log_level="warning",
            )
            uvi_server = uvicorn.Server(uvi_config)
            uvi_server.config.install_signal_handlers = False
            self._spawn(threading.Thread(target=uvi_server.run, name="dashboard", daemon=True))
            logging.info("Dashboard running on http://0.0.0.0:%s", config.DASHBOARD_PORT)

        self._monitor()

    def _monitor(self) -> None:
        """Main loop: watch thread liveness; shut down if any worker dies unexpectedly."""
        while not self.stop_event.is_set():
            for thread in self._threads:
                if not thread.is_alive():
                    logging.error("Thread '%s' died unexpectedly — shutting down.", thread.name)
                    self.stop_event.set()
                    break
            self.stop_event.wait(timeout=5)

        self._scheduler.stop()
        for thread in self._threads:
            thread.join(timeout=10)
        logging.info("%s stopped.", config.APP_NAME)


def main() -> None:
    setup_logging()
    setup_indexes()
    app = Application()
    app.start()


if __name__ == "__main__":
    main()
