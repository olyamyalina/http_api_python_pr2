import argparse
import configparser
from pathlib import Path

from bottle import run

from .api import create_app
from .storage import Store
from .worker import Worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.ini")
    args = parser.parse_args()
    config = configparser.ConfigParser()
    if not config.read(args.config, encoding="utf-8"):
        parser.error("Configuration file not found; copy config.example.ini")
    options = config["server"]
    database = Path(args.config).resolve().parent / options["database"]
    store = Store(database)
    worker = Worker(
        store, test_mode=options.getboolean("test_mode"),
        workers=options.getint("workers"), timeout=options.getint("timeout"),
    )
    app = create_app(store, worker, options["username"], options["password"])
    for message in store.collect("message", completed=0):
        worker.submit(message)
    try:
        run(app, host=options["host"], port=options.getint("port"))
    finally:
        worker.close()


if __name__ == "__main__":
    main()
