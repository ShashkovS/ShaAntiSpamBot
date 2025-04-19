import asyncio
from aiohttp import web
import re

from aiogram.webhook.aiohttp_server import setup_application, SimpleRequestHandler
from aiogram.client.default import DefaultBotProperties
from aiogram import Bot, Dispatcher, types, Router
from aiogram.filters import Command
from aiogram.enums import ChatType, ParseMode
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError

from config import config, logger, APP_PATH

# Инициализация бота и диспетчера aiogram 3
bot = Bot(token=config.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

SOME_TYPICAL_SPAM = re.compile(
    r'бонанз|играю в этом казино|КТО ХОЧЕТ ЗАРАБОТАТЬ|онлайн казик|\bинтим\b'
    r'|срочно.*требу.тся.*человек|лучшее казино|официальное казино|(?:доход|оплата).*от.*рублей.*(?:месяц|день)'
    r'|казино|доходность от|доход от.*день',
    flags=re.IGNORECASE | re.UNICODE  # Добавлен флаг UNICODE для лучшей работы с кириллицей
)
BOT_LINK_PATTERN = re.compile(r"(?:t\.me/|\B@)(\w+(?:_bot|bot))\b", re.IGNORECASE | re.UNICODE)


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Hi! This is ShaAntiSpamBot")


def check_sos_channel(message: types.Message):
    return message.chat.id == config.sos_channel or '@' + str(message.chat.username) == config.sos_channel


async def log_bot_name(username):
    await asyncio.sleep(1)
    logger.info(f'Бот начал свою работу: https://t.me/{username}')


async def start_polling_bot():
    logger.info("Запуск бота в режиме polling...")
    await dp.start_polling(bot)


async def on_startup(bot: Bot) -> None:
    # If you have a self-signed SSL certificate, then you will need to send a public
    # certificate to Telegram
    bot.username = (await bot.me()).username
    url = f"{config.webhook_host}/{config.webhook_path}"
    await bot.set_webhook(url, secret_token=config.webhook_secret_token)
    asyncio.create_task(post_logging_message(f'Бот начал свою работу, {url=}'))
    asyncio.create_task(log_bot_name(bot.username))


def setup_tgbot_webhook(app: web.Application):
    # Формируем URL-путь для webhook (например, /webhook/<token>/)
    path = f"/{config.webhook_path}"
    dp.startup.register(on_startup)
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=config.webhook_secret_token,
    )
    # Register webhook handler on application
    webhook_requests_handler.register(app, path=path)
    setup_application(app, dp, bot=bot, path=path)
    logger.info(f"Webhook установлен по пути: {path}")


async def post_logging_message(msg):
    logger.debug('bot.post_logging_message')
    bot_type = 'PRODUCTION' if config.production_mode else 'DEV MODE'
    full_msg = f'{bot_type} @ShaAntiSpamBot\n{msg}'
    if len(full_msg) > 4096:
        full_msg = full_msg[:4096]
    try:
        res = await bot.send_message(config.exceptions_channel, full_msg)
        # У секрентного чата id — это число. А у открытого — это строка.
        if type(config.exceptions_channel) == str:
            await bot.send_message(config.exceptions_channel, f'(Exceptions chat id = {res.chat.id})')
    except Exception as e:
        logger.exception(f'SHIT: {e}')


def post_logging_message_in_task(msg):
    try:
        asyncio.create_task(post_logging_message(msg))
    except Exception:
        pass


async def run_tg_bot_in_polling_mode():
    # Запуск polling-бота как отдельной задачи
    bot.username = (await bot.me()).username
    await bot.delete_webhook(drop_pending_updates=False)
    polling_task = asyncio.create_task(start_polling_bot())
    asyncio.create_task(post_logging_message(f'Бот начал свою работу'))
    asyncio.create_task(log_bot_name(bot.username))
    return polling_task


member_status_cache = {}


@router.message()
@router.channel_post()
async def group_message_handler(message: types.Message, bot: Bot):
    """
    Обрабатывает сообщения в группах и супергруппах для борьбы со спамом.
    """
    user = message.from_user
    chat = message.chat

    if not user:
        # Сообщение от канала от имени чата или анонимного админа.
        # Можно добавить специфическую логику, если нужно, но пока игнорируем.
        # GroupAnonymousBot имеет id 1087968824, можно проверять его, если нужно.
        # logger.debug(f"Message from channel or anonymous admin in chat {chat.id}")
        return

    # 1. Проверка на админа группы
    key = (chat.id, user.id)
    if key in member_status_cache:
        member_status = member_status_cache[key]
    else:
        try:
            member = await bot.get_chat_member(chat.id, user.id)
            member_status = member.status
            member_status_cache[key] = member_status
        except TelegramAPIError as e:
            logger.warning(
                f"Could not get chat member status for {user.id} in {chat.id}: {e}. Bot might lack permissions.")
            return
    if member_status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
        logger.debug(f"Ignoring message from admin {user.id} in chat {chat.id}")
        return
    logger.info(f'{member_status=} {member_status_cache=}')

    # 2. Удаление сообщений о входе/выходе
    if message.new_chat_members or message.left_chat_member:
        try:
            await message.delete()
            logger.info(f"Deleted service message (join/leave) in chat {chat.id}")
        except TelegramAPIError as e:
            logger.error(f"Failed to delete service message in {chat.id}: {e}. Bot might lack permissions.")
        return  # Завершаем обработку

    # --- Инициализация флагов и сбор текста ---
    delete_message_flag = False
    ban_user_flag = False
    reasons = []  # Список причин для логгирования

    # 3. Проверка на кнопки (inline keyboard)
    if message.reply_markup and isinstance(message.reply_markup, types.InlineKeyboardMarkup):
        logger.debug(f"Detected inline keyboard in message {message.message_id} from {user.id}")
        delete_message_flag = True
        ban_user_flag = True
        reasons.append("сообщение с кнопками")

    # 4. Сбор всего текста из сообщения
    text_parts = []
    if message.text:
        text_parts.append(message.text)
    if message.caption:  # Текст под медиа
        text_parts.append(message.caption)

    # Добавляем информацию о пользователе
    user_info_parts = []
    if user:
        if user.first_name:
            user_info_parts.append(user.first_name)
        if user.last_name:
            user_info_parts.append(user.last_name)
        if user.username:
            # Добавляем @ для более точного поиска ссылок и простоты чтения
            user_info_parts.append(f"@{user.username}")

    # Объединяем текст сообщения и информацию о пользователе для анализа
    # Приводим к нижнему регистру для регистронезависимого поиска
    full_text_to_check = " ".join(filter(None, text_parts + user_info_parts)).lower()
    logger.debug(f"Checking text (len={len(full_text_to_check)}): {full_text_to_check[:200]}...")

    # 5. Проверка текста регулярным выражением на спам
    if SOME_TYPICAL_SPAM.search(full_text_to_check):
        logger.debug(f"Matched typical spam regex in message {message.message_id} from {user.id}")
        delete_message_flag = True
        ban_user_flag = True
        reasons.append("типичный спам")

    # 6. Проверка на ссылки на других ботов
    own_username = bot.username
    found_external_bot = False
    for match in BOT_LINK_PATTERN.finditer(full_text_to_check):
        bot_link_username = match.group(1)
        # Сравниваем без учета регистра
        if bot_link_username.lower() != own_username.lower():
            logger.debug(
                f"Found link to another bot: {bot_link_username} in message {message.message_id} from {user.id}")
            delete_message_flag = True  # Только удаление, не бан
            found_external_bot = True
            break  # Достаточно найти одну ссылку

    if found_external_bot:
        reasons.append("ссылка на другого бота")

    # --- Выполнение действий ---
    action_log_message = None

    if ban_user_flag:  # Бан приоритетнее простого удаления
        action_log_message = (
            f"Пользователь {message.from_user.mention_html()} (ID: {user.id}) "
            f"ЗАБАНЕН в чате {message.chat.title} (ID: {chat.id}).\n"
            f"Причина: {', '.join(reasons)}."
        )
        try:
            # Сначала пересылаем сообщение для анализа
            await bot.forward_message(
                chat_id=config.exceptions_channel,
                from_chat_id=chat.id,
                message_id=message.message_id,
                disable_notification=True  # Чтобы не спамить в лог-канал
            )
        except TelegramAPIError as e:
            logger.error(f"Failed to forward message {message.message_id} from {chat.id} before ban: {e}")
            action_log_message += f"\nНЕ УДАЛОСЬ переслать исходное сообщение: {e.message}"

        try:
            # Баним пользователя
            # await bot.ban_chat_member(chat_id=chat.id,
            #                           user_id=user.id)  # revoke_messages=True - можно добавить для удаления всех сообщений
            logger.info(f"Banned user {user.id} in chat {chat.id}. Reason: {', '.join(reasons)}")
            # Удаляем исходное сообщение после успешного бана
            try:
                await message.delete()
            except TelegramAPIError as e_del:
                logger.warning(
                    f"Failed to delete message {message.message_id} after banning user {user.id} in {chat.id}: {e_del}")
                action_log_message += f"\nНе удалось удалить исходное сообщение после бана: {e_del.message}"

        except TelegramAPIError as e_ban:
            logger.error(f"Failed to ban user {user.id} in chat {chat.id}: {e_ban}")
            action_log_message = (
                f"НЕ УДАЛОСЬ забанить пользователя {message.from_user.mention_html()} (ID: {user.id}) "
                f"в чате {message.chat.title} (ID: {chat.id}).\n"
                f"Причина: {', '.join(reasons)}.\nОшибка: {e_ban.message}"
            )
            # Попытка удалить сообщение, даже если бан не удался (если флаг был)
            if delete_message_flag:
                try:
                    await message.delete()
                    action_log_message += "\nИсходное сообщение УДАЛЕНО."
                except TelegramAPIError as e_del:
                    logger.warning(
                        f"Failed to delete message {message.message_id} after failed ban attempt for user {user.id} in {chat.id}: {e_del}")
                    action_log_message += "\nИсходное сообщение удалить НЕ УДАЛОСЬ."

    elif delete_message_flag:  # Только удаление (без бана)
        action_log_message = (
            f"Сообщение от {message.from_user.mention_html()} (ID: {user.id}) "
            f"УДАЛЕНО в чате {message.chat.title} (ID: {chat.id}).\n"
            f"Причина: {', '.join(reasons)}."
        )
        try:
            # Сначала пересылаем
            await bot.forward_message(
                chat_id=config.exceptions_channel,
                from_chat_id=chat.id,
                message_id=message.message_id,
                disable_notification=True
            )
        except TelegramAPIError as e:
            logger.error(f"Failed to forward message {message.message_id} from {chat.id} before delete: {e}")
            action_log_message += f"\nНЕ УДАЛОСЬ переслать исходное сообщение: {e.message}"

        try:
            # Удаляем
            await message.delete()
            logger.info(
                f"Deleted message {message.message_id} from {user.id} in chat {chat.id}. Reason: {', '.join(reasons)}")
        except TelegramAPIError as e_del:
            logger.error(f"Failed to delete message {message.message_id} from {user.id} in chat {chat.id}: {e_del}")
            action_log_message = (
                f"НЕ УДАЛОСЬ удалить сообщение от {message.from_user.mention_html()} (ID: {user.id}) "
                f"в чате {message.chat.title} (ID: {chat.id}).\n"
                f"Причина: {', '.join(reasons)}.\nОшибка: {e_del.message}"
            )

    # Отправляем итоговое сообщение в лог-канал, если было какое-то действие
    if action_log_message:
        # Используем вашу функцию для отправки логов
        # Убедитесь, что post_logging_message доступна в этой области видимости
        # и обрабатывает возможные ошибки отправки сама
        await post_logging_message(action_log_message)
