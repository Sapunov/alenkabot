import os
import sys
import logging
import logging.handlers

from signal import SIGTERM
import atexit

import settings


def setup_log(
    name, log_file, log_level=logging.DEBUG, log_format=None, date_format=None
):
    if not log_format:
        log_format = u"%(asctime)s LINE:%(lineno)-3d %(levelname)-8s %(message)s"

    if not date_format:
        date_format = "%d.%m.%y %H:%M:%S"

    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=(20 * 1024 ** 2), backupCount=3)

    log = logging.getLogger(name)
    log.setLevel(log_level)

    handler.setFormatter(logging.Formatter(log_format, date_format))
    log.addHandler(handler)

    return log
