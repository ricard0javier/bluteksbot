"""Application entrypoint — lifecycle management only, zero business logic."""

import logging
import signal
import threading

from src import config
from src.telegram.consumer import TelegramConsumer
from src.utils.logging import setup_logging


class Application:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._consumer = TelegramConsumer(stop_event=self.stop_event)

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

        self._spawn(
            threading.Thread(
                target=self._consumer.run,
                name="telegram-consumer",
                daemon=True,
            )
        )

        self._monitor()

    def _monitor(self) -> None:
        """Main loop: watch thread liveness; shut down if any worker dies unexpectedly."""
        while not self.stop_event.is_set():
            for thread in self._threads:
                if not thread.is_alive():
                    logging.error(
                        "Thread '%s' died unexpectedly — shutting down.", thread.name
                    )
                    self.stop_event.set()
                    break
            self.stop_event.wait(timeout=5)

        for thread in self._threads:
            thread.join(timeout=10)
        logging.info("%s stopped.", config.APP_NAME)


def main() -> None:
    setup_logging()
    app = Application()
    app.start()


if __name__ == "__main__":
    main()
