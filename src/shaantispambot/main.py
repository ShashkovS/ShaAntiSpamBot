import asyncio

from aiohttp import web
import datetime

from config import config, logger, APP_PATH
from botmain import run_tg_bot_in_polling_mode, setup_tgbot_webhook, post_logging_message, post_logging_message_in_task

routes = web.RouteTableDef()


async def on_startup(app):
    logger.warning('MainApp Start up!')
    logger.info('Routes:')
    for route in app.router.routes():
        logger.info(f'{route.method}: {route.resource.canonical}')
    post_logging_message_in_task('Веб-приложение тоже стартовало.')


async def on_shutdown(app):
    """
    Graceful shutdown. This method is recommended by aiohttp docs.
    """
    logger.warning('on_shutdown')
    logger.warning('MainApp Shutting down..')
    # К этому моменту все задания уже должны быть закончены. Поэтому закрываем прямо всё
    await post_logging_message('Бот остановил свою работу')

    all_async_tasks_but_current = list(asyncio.all_tasks() - {asyncio.current_task()})
    for i in range(len(all_async_tasks_but_current) - 1, -1, -1):
        task = all_async_tasks_but_current[i]
        coro_name = task.get_coro().__qualname__
        logger.warning(f'{i=} {coro_name=}')
        # TODO Это, конечно, отстой... Но хз, как сделать лучше
        if 'start_polling' in coro_name or 'Client._' in coro_name or 'Subscription._' in coro_name:
            all_async_tasks_but_current.pop(i)
        else:
            logger.warning(f'Pending task: {task.get_coro().__qualname__}')
    if all_async_tasks_but_current:
        await asyncio.wait(all_async_tasks_but_current, timeout=20)
    logger.warning('MainApp Bye!')


def create_app(loop=None):
    app = web.Application(loop=loop)
    app.router.add_routes(routes)

    # Adding startup and cleanup signals
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    # Интеграция Telegram-бота
    if config.use_webhook:
        setup_tgbot_webhook(app)
    else:
        logger.info("Работа бота в режиме polling – webhook не настраивается.")

    return app


app = create_app()


async def dev_main():
    # Настройка и запуск веб-сервера aiohttp
    polling_task = await run_tg_bot_in_polling_mode()
    await asyncio.Event().wait()


if __name__ == '__main__':
    try:
        asyncio.run(dev_main())
    except KeyboardInterrupt:
        pass
