import asyncio
import json
import logging
import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, PreCheckoutQueryHandler, filters)

import store


def load_env(path):
    if not path.exists():
        return  # настройки можно задать и на сайте хостинга, тогда файла нет
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def value(name):
    """Значение из settings.txt; пустая строка, если не заполнено."""
    v = os.environ.get(name, "").strip()
    return "" if v.startswith("ВСТАВЬ") else v


def need(name):
    if not value(name):
        raise SystemExit(f"В файле settings.txt не заполнено: {name}")
    return value(name)


load_env(Path(__file__).with_name("settings.txt"))
BOT_TOKEN = need("BOT_TOKEN")
OFFER_URL, PRIVACY_URL = need("OFFER_URL"), need("PRIVACY_URL")
CONTACT, SELLER = need("CONTACT"), need("SELLER")
PAYMENT_TOKEN, TABLE_URL, VIDEO_URL = value("PAYMENT_TOKEN"), value("TABLE_URL"), value("VIDEO_URL")
OWNER_ID = value("OWNER_ID")
PAYMENTS_ON = bool(PAYMENT_TOKEN)  # без платёжного токена бот работает как «витрина»
if PAYMENTS_ON and not (TABLE_URL and VIDEO_URL):
    raise SystemExit("Оплата включена, но TABLE_URL или VIDEO_URL не заполнены: покупатель ничего не получит.")
USE_RECEIPT = os.environ.get("USE_RECEIPT") == "1"

PRICE_RUB, PAYLOAD = 390, "finance-table"
TITLE = "Таблица «Финансовая грамотность»"

DELAY = 5  # секунд между кружочками
START_TEXT = (
    "Что внутри 👇\n"
    "💰 бюджет и подушка безопасности\n"
    "🎯 цели с учётом инфляции\n"
    "💳 долги, капитал и регулярные платежи\n"
    "📊 дашборд с итогами и графиками\n"
    "📖 справочник, где все умные слова объяснены по-человечески\n\n"
    f"Стоит {PRICE_RUB} рублей. Один раз, и доступ к таблице навсегда 🙌\n"
    "После оплаты бот сразу пришлёт ссылку на таблицу и видеоинструкцию.\n\n"
    "Перед оплатой нажми «Да, принимаю оферту» 👇"
)
MATERIALS = (
    "Спасибо за покупку! 🎉 Вот всё, что нужно.\n\n"
    f"📊 Таблица (откроется кнопка «Создать копию»):\n{TABLE_URL}\n\n"
    "Чтобы открыть таблицу, нужен Google-аккаунт: если ты ещё не вошёл, войди или создай его, это бесплатно.\n\n"
    f"🎬 Видеоинструкция:\n{VIDEO_URL}\n\n"
    "Первые шаги: создай копию, на вкладке «Старт» настрой валюту и доли, "
    "а потом записывай траты в «Журнал» 💪"
)


async def send_materials(chat_id, context):
    await context.bot.send_message(chat_id, MATERIALS)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, chat_id = update.effective_user.id, update.effective_chat.id
    if store.has_paid(uid):
        return await send_materials(chat_id, context)
    seen = context.application.bot_data.setdefault("seen", set())  # кружочки показываем один раз за запуск бота
    if uid not in seen:
        seen.add(uid)
        for file_id in store.get_circles():
            await context.bot.send_video_note(chat_id, file_id)
            await asyncio.sleep(DELAY)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Да, принимаю оферту", callback_data="accept")],
        [InlineKeyboardButton("Оферта", url=OFFER_URL),
         InlineKeyboardButton("Политика данных", url=PRIVACY_URL)],
    ])
    await update.message.reply_text(START_TEXT, reply_markup=keyboard)


def is_owner(update):
    return bool(OWNER_ID) and str(update.effective_user.id) == OWNER_ID


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Твой Telegram-ID: {update.effective_user.id}")


async def save_circle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    n = store.add_circle(update.message.video_note.file_id)
    await update.message.reply_text(f"Кружочек №{n} сохранён.")


async def clear_circles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_owner(update):
        store.clear_circles()
        await update.message.reply_text("Все кружочки удалены. Присылай заново по порядку.")


async def accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id, chat_id = query.from_user.id, query.message.chat_id
    if store.has_paid(user_id):
        return await send_materials(chat_id, context)
    if not PAYMENTS_ON:
        return await context.bot.send_message(chat_id, "Оплата подключается и скоро заработает. Загляните сюда позже.")
    store.save_accept(user_id)
    extra = {}
    if USE_RECEIPT:
        extra = {"need_email": True, "send_email_to_provider": True,
                 "provider_data": json.dumps({"receipt": {"items": [{
                     "description": TITLE, "quantity": "1.00", "vat_code": 1,
                     "amount": {"value": f"{PRICE_RUB}.00", "currency": "RUB"}}]}})}
    await context.bot.send_invoice(
        chat_id=chat_id, title=TITLE, description="Google Таблица и видеоинструкция",
        payload=PAYLOAD, provider_token=PAYMENT_TOKEN, currency="RUB",
        prices=[LabeledPrice("Таблица", PRICE_RUB * 100)], **extra)


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.pre_checkout_query
    ok = (q.invoice_payload == PAYLOAD and q.currency == "RUB"
          and q.total_amount == PRICE_RUB * 100 and store.has_accepted(q.from_user.id))
    await q.answer(ok=ok, error_message=None if ok else "Не получилось, начните сначала командой /start.")


async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    if payment.invoice_payload != PAYLOAD:
        return
    store.save_buyer(update.effective_user.id, payment.total_amount // 100)
    await send_materials(update.effective_chat.id, context)


async def help_(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Оферта: {OFFER_URL}\nПолитика данных: {PRIVACY_URL}")


def main():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # иначе токен бота попадёт в лог
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("clear", clear_circles))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE, save_circle))
    app.add_handler(CallbackQueryHandler(accept, pattern="^accept$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, paid))
    app.run_polling()


if __name__ == "__main__":
    main()
