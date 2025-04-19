# -*- coding: utf-8 -*-
import json
import logging
import os
import pathlib
from dataclasses import dataclass
from typing import Optional

APP_LOGGER = 'asb'
APP_PATH = pathlib.Path(__file__).parent.resolve()

__all__ = ['APP_PATH', 'logger', 'config', 'DEBUG']

config_filename = APP_PATH / 'config' / 'secrets.json'


def _absolute_path(path: str) -> pathlib.Path:
    path_obj = pathlib.Path(path)
    if path_obj.is_absolute():
        return path_obj
    else:
        # Используем путь от корня проекта
        return APP_PATH / path


@dataclass()
class Config:
    config_name: str = ''
    production_mode: bool = False
    # tg bot
    telegram_bot_token: Optional[str] = None
    use_webhook: Optional[str] = None
    webhook_host: Optional[str] = None
    webhook_path: Optional[str] = None
    webhook_secret_token: Optional[str] = None
    sos_channel: Optional[str | int] = None
    exceptions_channel: Optional[str | int] = None


def _create_logger():
    # Настраиваем
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)-8s: %(levelname)-8s %(message)s',
        datefmt='%Y-%d-%m %H:%M:%S'
    )
    logger = logging.getLogger(APP_LOGGER)
    return logger


def _setup(*, force_production=False):
    config = Config()
    logging.info(f'Current working dir: {os.getcwd()}')
    config.config_name = 'dev'

    try:
        with open(config_filename, 'r', encoding='utf-8') as f:
            config_from_json = json.load(f)
    except:
        logging.critical(f'Запишите конфиг в {config_filename}')
        raise

    # Обновляем настройки
    config.__dict__.update(config_from_json)
    return config


logger = _create_logger()
DEBUG = logging.DEBUG
config = _setup()
logger.debug(f'{config=}')

if config.production_mode:
    logger.info(('*' * 50 + '\n') * 5)
    logger.info('Production mode')
    logger.info('*' * 50)
else:
    logger.info('Dev mode')

if __name__ == '__main__':
    print(config)
    print('-' * 50)
