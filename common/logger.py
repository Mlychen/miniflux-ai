import logging


def get_logger(log_level='INFO', name='miniflux_ai'):
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(filename)s - %(levelname)s - %(message)s')
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)

    logger.propagate = False
    return logger
