import logging
import json
import os
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ChatType

# Загрузка конфигурации
load_dotenv()
TOKEN = os.getenv("SUPPORT_BOT_TOKEN")
SUPPORT_CHAT_ID = int(os.getenv("SUPPORT_CHAT_ID"))
OWNER_ID = int(os.getenv("OWNER_ID"))
DB_FILE = "support_db.json"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


class SupportDB:
    def __init__(self, filename):
        self.filename = filename
        self.data = self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Инициализация ключей
                    for key in ["tickets", "active_chats", "banned", "agents", "ban_reasons", "user_metadata"]:
                        if key not in data:
                            data[key] = {} if key != "banned" else []
                    return data
            except:
                pass
        return {"tickets": {}, "active_chats": {}, "banned": [], "agents": {}, "ban_reasons": {}, "user_metadata": {}}

    def save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def register_user(self, user):
        uid = str(user.id)
        if uid not in self.data["user_metadata"]:
            self.data["user_metadata"][uid] = {
                "username": user.username,
                "ticket_count": 0
            }
        else:
            self.data["user_metadata"][uid]["username"] = user.username
        self.save()

    def increment_ticket(self, user_id):
        uid = str(user_id)
        if uid in self.data["user_metadata"]:
            self.data["user_metadata"][uid]["ticket_count"] += 1
            self.save()


db = SupportDB(DB_FILE)


# --- КЛАВИАТУРЫ ---
def get_admin_kb(uid, is_closed=False):
    uid_str = str(uid)
    buttons = []
    if not is_closed:
        is_active = uid_str in db.data.get("active_chats", {})
        if not is_active:
            buttons.append([InlineKeyboardButton("👨‍💻 Рассмотреть", callback_data=f"take_{uid}")])
        buttons.append([InlineKeyboardButton("✅ Закрыть", callback_data=f"close_{uid}")])

    is_banned = int(uid) in db.data.get("banned", [])
    ban_btn_text = "🔑 Разблокировать" if is_banned else "🔑 Заблокировать"
    ban_callback = f"unban_{uid}" if is_banned else f"ban_{uid}"
    buttons.append([InlineKeyboardButton(ban_btn_text, callback_data=ban_callback)])
    return InlineKeyboardMarkup(buttons)


def get_owner_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Все пользователи", callback_data="adm_users_list")],
        [InlineKeyboardButton("🛠 Добавить агента", callback_data="adm_request")],
        [InlineKeyboardButton("🎧 Список агентов", callback_data="adm_list")],
        [InlineKeyboardButton("📊 Статистика", callback_data="adm_stats")]
    ])


def get_user_close_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Закрыть обращение", callback_data="user_close_self")]])


# --- ХЕНДЛЕРЫ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE: return
    user = update.effective_user
    db.register_user(user)
    await update.message.reply_text("👋 Здравствуйте! Опишите вашу проблему.")


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_text("🛠 <b>Панель управления</b>", parse_mode="HTML", reply_markup=get_owner_kb())


async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    uid_str = str(user.id)

    # Проверка бана
    if chat.type == ChatType.PRIVATE and user.id in db.data.get("banned", []):
        await update.message.reply_text("🔑 Вы заблокированы в поддержке.")
        return

    # Добавление агента владельцем
    if chat.id == SUPPORT_CHAT_ID and user.id == OWNER_ID and context.user_data.get('waiting_agent'):
        agent_id = update.message.text.strip()
        if agent_id.isdigit():
            num = len(db.data["agents"]) + 1
            db.data["agents"][agent_id] = {"num": num, "replies": 0, "bans": 0}
            db.save()
            await update.message.reply_text(f"✅ Агент #{num} добавлен.")
        context.user_data['waiting_agent'] = False
        return

    # Причина бана
    if chat.id == SUPPORT_CHAT_ID and context.user_data.get('waiting_ban_reason'):
        target_uid = context.user_data.get('ban_target')
        reason = update.message.text
        agent = db.data["agents"].get(uid_str)
        if agent:
            db.data["banned"].append(int(target_uid))
            db.data["ban_reasons"][str(target_uid)] = {"reason": reason, "agent_num": agent["num"]}
            agent["bans"] += 1
            db.save()
            try:
                await context.bot.send_message(int(target_uid), f"🔑 Вы заблокированы. Причина: {reason}")
            except:
                pass
            await update.message.reply_text(f"🔑 Пользователь заблокирован агентом #{agent['num']}")
        context.user_data['waiting_ban_reason'] = False
        return

    # Пересылка сообщения пользователю
    if chat.id == SUPPORT_CHAT_ID:
        if not update.message.message_thread_id or update.message.message_thread_id == 1: return
        target_uid = next(
            (u for u, info in db.data["tickets"].items() if info.get("thread_id") == update.message.message_thread_id),
            None)
        if target_uid and uid_str in db.data["agents"]:
            try:
                await context.bot.copy_message(chat_id=int(target_uid), from_chat_id=SUPPORT_CHAT_ID,
                                               message_id=update.message.id)
                db.data["agents"][uid_str]["replies"] += 1
                db.save()
            except:
                pass

    # Создание обращения (Скрин №1)
    elif chat.type == ChatType.PRIVATE:
        if uid_str not in db.data["tickets"] or db.data["tickets"][uid_str].get("status") == "closed":
            db.increment_ticket(user.id)
            topic = await context.bot.create_forum_topic(chat_id=SUPPORT_CHAT_ID, name=f"{user.id} | {user.first_name}")

            # Сообщение с кнопками в топик (как на скрине №1)
            sent_msg = await context.bot.send_message(
                SUPPORT_CHAT_ID,
                message_thread_id=topic.message_thread_id,
                text=f"🆕 <b>Новое обращение</b>\nID: <code>{user.id}</code>\nЮзер: @{user.username}",
                parse_mode="HTML",
                reply_markup=get_admin_kb(uid_str)
            )

            db.data["tickets"][uid_str] = {"thread_id": topic.message_thread_id, "status": "open",
                                           "admin_msg_id": sent_msg.message_id}
            db.save()
            await update.message.reply_text("✅ Ваше обращение создано.", reply_markup=get_user_close_kb())

        await context.bot.copy_message(chat_id=SUPPORT_CHAT_ID,
                                       message_thread_id=db.data["tickets"][uid_str]["thread_id"], from_chat_id=user.id,
                                       message_id=update.message.id)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    uid_str = str(user_id)
    data = query.data
    await query.answer()

    # Закрытие пользователем
    if data == "user_close_self":
        ticket = db.data["tickets"].get(uid_str)
        if ticket and ticket["status"] == "open":
            db.data["tickets"][uid_str]["status"] = "closed"
            db.data["active_chats"].pop(uid_str, None)
            db.save()
            await query.edit_message_text("🔴 Вы закрыли обращение.")
            await context.bot.send_message(SUPPORT_CHAT_ID, message_thread_id=ticket["thread_id"],
                                           text="⚪️ Пользователь закрыл обращение.")
            await context.bot.close_forum_topic(SUPPORT_CHAT_ID, ticket["thread_id"])
            if ticket.get("admin_msg_id"):
                try:
                    await context.bot.edit_message_reply_markup(SUPPORT_CHAT_ID, ticket["admin_msg_id"],
                                                                reply_markup=get_admin_kb(uid_str, True))
                except:
                    pass
        return

    # Админские функции (Скрин №2)
    if data.startswith("adm_"):
        if user_id != OWNER_ID: return
        if data == "adm_users_list":
            users = db.data.get("user_metadata", {})
            res = "👥 <b>Список пользователей:</b>\n\n"
            for uid, info in users.items():
                status = "🔴 (BANNED)" if int(uid) in db.data["banned"] else ""
                res += f"• <code>{uid}</code> | @{info.get('username')} | Обращений: {info.get('ticket_count')} {status}\n"
            await query.message.reply_text(res, parse_mode="HTML")
        elif data == "adm_request":
            context.user_data['waiting_agent'] = True
            await query.message.reply_text("Введите ID агента:")
        return

    # Действия агентов
    if uid_str not in db.data["agents"]: return
    action, target_uid = data.split("_")
    agent = db.data["agents"][uid_str]

    if action == "take":
        db.data["active_chats"][target_uid] = {"agent_num": agent["num"]}
        db.save()
        await query.message.edit_reply_markup(reply_markup=get_admin_kb(target_uid))
        await context.bot.send_message(SUPPORT_CHAT_ID, message_thread_id=query.message.message_thread_id,
                                       text=f"👨‍💻 Агент #{agent['num']} взял обращение.")

    elif action == "close":
        ticket = db.data["tickets"][target_uid]
        db.data["tickets"][target_uid]["status"] = "closed"
        db.data["active_chats"].pop(target_uid, None)
        db.save()
        await query.message.edit_reply_markup(reply_markup=get_admin_kb(target_uid, True))
        await context.bot.close_forum_topic(SUPPORT_CHAT_ID, ticket["thread_id"])

    elif action == "ban":
        context.user_data.update(
            {'waiting_ban_reason': True, 'ban_target': target_uid, 'ban_msg_id': query.message.message_id})
        await context.bot.send_message(SUPPORT_CHAT_ID, message_thread_id=query.message.message_thread_id,
                                       text="📝 Введите причину бана:")

    elif action == "unban":
        if int(target_uid) in db.data["banned"]:
            db.data["banned"].remove(int(target_uid))
            db.save()
            await query.message.edit_reply_markup(reply_markup=get_admin_kb(target_uid))


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_msg))
    app.run_polling()


if __name__ == '__main__': main()