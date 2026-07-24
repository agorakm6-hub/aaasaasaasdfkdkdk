"""
bot_guard.py — защита аккаунта Telegram-бота от несанкционированных изменений
(смена аватара/имени через угнанный токен), + keep-alive для бесплатного хостинга.

ЗАВИСИМОСТИ (requirements.txt):
    telethon
    aiohttp

ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (задать в Render -> Environment):
    API_ID          - число, с https://my.telegram.org/apps
    API_HASH        - строка оттуда же
    BOT_TOKEN       - токен вашего бота (от BotFather)
    OWNER_ID        - ваш личный Telegram user_id (числом), куда слать алерты
    CHECK_INTERVAL  - опционально, секунды между проверками (по умолчанию 30)
    PORT            - опционально, порт для keep-alive http-сервера (по умолчанию 10000)

Как получить OWNER_ID: напишите @userinfobot в Telegram, он покажет ваш id.

ЛОГИКА:
    1. При старте логинимся под ботом через MTProto (Telethon), запоминаем
       текущее фото (file id / отсутствие фото) и текущее имя как "эталон".
    2. Каждые CHECK_INTERVAL секунд сверяем текущее состояние с эталоном.
    3. Если фото изменилось (появилось новое / другое) -> удаляем все фото
       профиля бота и шлём вам алерт.
    4. Если изменилось имя -> возвращаем эталонное имя и шлём алерт.
    5. Поднят маленький HTTP-эндпоинт /health для внешнего пинга
       (UptimeRobot / cron-job.org), чтобы Render не усыплял сервис —
       БЕЗ рассылки сообщений пользователям.
"""

import asyncio
import logging
import os
from datetime import datetime

from aiohttp import web
from telethon import TelegramClient
from telethon.tl.functions.photos import (
    DeletePhotosRequest,
    UploadProfilePhotoRequest,
)
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.types import InputPhoto

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bot_guard")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "30"))
PORT = int(os.environ.get("PORT", "10000"))

client = TelegramClient("bot_guard_session", API_ID, API_HASH)

state = {
    "photo_id": None,      # id текущего "легитимного" фото, None = фото нет
    "first_name": None,
    "last_name": None,
}


async def notify_owner(text: str):
    try:
        await client.send_message(OWNER_ID, text)
    except Exception as e:
        log.error(f"Не смог отправить алерт владельцу: {e}")


async def get_current_photo_id():
    photos = await client.get_profile_photos("me")
    if not photos:
        return None
    return photos[0].id


async def capture_baseline():
    me = await client.get_me()
    state["first_name"] = me.first_name
    state["last_name"] = me.last_name
    state["photo_id"] = await get_current_photo_id()
    log.info(f"Эталон сохранён: name={me.first_name!r}, photo_id={state['photo_id']}")


async def remove_all_profile_photos():
    photos = await client.get_profile_photos("me")
    if not photos:
        return
    input_photos = [
        InputPhoto(id=p.id, access_hash=p.access_hash, file_reference=p.file_reference)
        for p in photos
    ]
    await client(DeletePhotosRequest(id=input_photos))
    log.info("Все фото профиля удалены.")


async def restore_name():
    await client(UpdateProfileRequest(
        first_name=state["first_name"] or "",
        last_name=state["last_name"] or "",
    ))


async def check_loop():
    await capture_baseline()
    await notify_owner("🛡 Мониторинг бота запущен. Эталон сохранён.")

    while True:
        try:
            await asyncio.sleep(CHECK_INTERVAL)

            current_photo_id = await get_current_photo_id()
            if current_photo_id != state["photo_id"]:
                ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                await remove_all_profile_photos()
                state["photo_id"] = None
                await notify_owner(
                    f"⚠️ [{ts}] Обнаружена и удалена посторонняя аватарка бота!\n"
                    f"Рекомендую немедленно перевыпустить токен через @BotFather "
                    f"(/revoke) и обновить его в переменных окружения."
                )

            me = await client.get_me()
            if me.first_name != state["first_name"] or me.last_name != state["last_name"]:
                ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                await restore_name()
                await notify_owner(
                    f"⚠️ [{ts}] Обнаружена и откачена смена имени бота "
                    f"(было: {me.first_name!r} {me.last_name!r})!\n"
                    f"Рекомендую перевыпустить токен через @BotFather."
                )

        except Exception as e:
            log.error(f"Ошибка в цикле проверки: {e}")
            await asyncio.sleep(5)


async def health(request):
    return web.Response(text="ok")


async def run_web_server():
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info(f"Keep-alive сервер поднят на порту {PORT} (эндпоинт /health)")


async def main():
    await client.start(bot_token=BOT_TOKEN)
    await run_web_server()
    await check_loop()


if __name__ == "__main__":
    asyncio.run(main())
