import logging
import json
import os
import re
import secrets
import string
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, \
    PreCheckoutQueryHandler, filters

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
ADMIN_PANEL_URL = os.getenv("ADMIN_PANEL_URL", "http://localhost:5000")
DB_FILE = "bot_database.json"

STARS_PRICE = 100
RUB_PRICE = 150
SUB_DAYS = 7
TECH_BOT_USERNAME = "svchostt_tech_bot"
REQUISITES = "💳 Карта: `2200 0000 0000 0000` (Получатель: Алексей В.)"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


class Database:
    def __init__(self, filename):
        self.filename = filename
        self.data = self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                    # Инициализация ключей
                    required_keys = {
                        "messages": [],
                        "banned": [],
                        "protected_users": [],
                        "admins": [],
                        "ban_history": [],
                        "action_history": []
                    }
                    for key in required_keys:
                        if key not in data:
                            data[key] = []

                    for key in ["users", "subscriptions", "user_states"]:
                        if key not in data:
                            data[key] = {}

                    if "statistics" not in data:
                        data["statistics"] = {"total_messages": 0, "total_users": 0}
                    if "admin_passwords" not in data:
                        data["admin_passwords"] = {}
                    if "ban_reasons" not in data:
                        data["ban_reasons"] = {}

                    return data
            except:
                return self._create_empty_db()
        return self._create_empty_db()

    def _create_empty_db(self):
        return {
            "users": {},
            "user_states": {},
            "messages": [],
            "banned": [],
            "subscriptions": {},
            "protected_users": [],
            "admins": [],
            "admin_passwords": {},
            "ban_history": [],
            "action_history": [],
            "ban_reasons": {},
            "statistics": {"total_messages": 0, "total_users": 0}
        }

    def save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def has_subscription(self, user_id):
        uid = str(user_id)
        if uid not in self.data["subscriptions"]: return False
        try:
            until = datetime.fromisoformat(self.data["subscriptions"][uid])
            return datetime.now() < until
        except:
            return False

    def remove_subscription(self, user_id):
        uid = str(user_id)
        if uid in self.data["subscriptions"]:
            del self.data["subscriptions"][uid]
            self.save()
            return True
        return False

    def add_subscription(self, user_id, time_str):
        uid = str(user_id)
        now = datetime.now()

        match = re.match(r"(\d+)([smhd]?)", str(time_str).strip().lower())
        if not match:
            return None

        value = int(match.group(1))
        unit = match.group(2)

        if value <= 0:
            self.remove_subscription(user_id)
            return None

        if unit == 's':
            delta = timedelta(seconds=value)
        elif unit == 'm':
            delta = timedelta(minutes=value)
        elif unit == 'h':
            delta = timedelta(hours=value)
        else:
            delta = timedelta(days=value)

        if self.has_subscription(user_id):
            current_until = datetime.fromisoformat(self.data["subscriptions"][uid])
            new_until = current_until + delta
        else:
            new_until = now + delta

        self.data["subscriptions"][uid] = new_until.isoformat()
        self.save()
        return new_until

    def get_info(self, user_id):
        uid = str(user_id)
        u = self.data["users"].get(uid, {})
        un = u.get("username")
        return f"(@{un})" if un else "(без юзера)"

    def is_protected(self, user_id):
        return int(user_id) in self.data["protected_users"]

    def add_protected_user(self, user_id):
        uid = int(user_id)
        if uid not in self.data["protected_users"]:
            self.data["protected_users"].append(uid)
            self.save()
            return True
        return False

    def remove_protected_user(self, user_id):
        uid = int(user_id)
        if uid in self.data["protected_users"]:
            self.data["protected_users"].remove(uid)
            self.save()
            return True
        return False

    def get_protected_users(self):
        return self.data["protected_users"]

    def is_admin(self, user_id):
        return user_id == OWNER_ID or int(user_id) in self.data["admins"]

    def add_admin(self, user_id, password=None):
        uid = int(user_id)
        if uid not in self.data["admins"]:
            self.data["admins"].append(uid)

            if not password:
                password = self._generate_password()

            self.data["admin_passwords"][str(uid)] = password
            self.save()
            return password
        return None

    def remove_admin(self, user_id):
        uid = int(user_id)
        if uid in self.data["admins"]:
            self.data["admins"].remove(uid)
            if str(uid) in self.data["admin_passwords"]:
                del self.data["admin_passwords"][str(uid)]
            self.save()
            return True
        return False

    def get_admin_password(self, user_id):
        return self.data["admin_passwords"].get(str(user_id))

    def set_admin_password(self, user_id, password):
        uid = str(user_id)
        if self.is_admin(int(user_id)):
            self.data["admin_passwords"][uid] = password
            self.save()
            return True
        return False

    def _generate_password(self, length=12):
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def verify_admin(self, user_id, password):
        stored_password = self.get_admin_password(user_id)
        return stored_password == password

    def ban_user(self, user_id, reason="не указана", until=None, admin_id=None):
        uid = int(user_id)
        if uid not in self.data["banned"]:
            self.data["banned"].append(uid)
            self.data["ban_reasons"][str(uid)] = reason

            ban_record = {
                "user_id": uid,
                "reason": reason,
                "admin_id": admin_id,
                "banned_at": datetime.now().isoformat(),
                "until": until,
                "active": True
            }
            self.data["ban_history"].append(ban_record)

            action_record = {
                "user_id": uid,
                "action_type": "ban",
                "details": {"reason": reason, "until": until, "admin_id": admin_id},
                "timestamp": datetime.now().isoformat()
            }
            self.data["action_history"].append(action_record)

            self.save()
            return True
        return False

    def unban_user(self, user_id, admin_id=None):
        uid = int(user_id)
        if uid in self.data["banned"]:
            self.data["banned"].remove(uid)
            if str(uid) in self.data["ban_reasons"]:
                del self.data["ban_reasons"][str(uid)]

            for ban in self.data["ban_history"]:
                if ban["user_id"] == uid and ban["active"]:
                    ban["active"] = False
                    ban["unbanned_at"] = datetime.now().isoformat()
                    ban["unbanned_by"] = admin_id
                    break

            action_record = {
                "user_id": uid,
                "action_type": "unban",
                "details": {"admin_id": admin_id},
                "timestamp": datetime.now().isoformat()
            }
            self.data["action_history"].append(action_record)

            self.save()
            return True
        return False

    def get_ban_history(self, user_id):
        return [ban for ban in self.data["ban_history"] if ban["user_id"] == int(user_id)]

    def get_user_history(self, user_id):
        return [action for action in self.data["action_history"] if action["user_id"] == int(user_id)]


db = Database(DB_FILE)


async def check_subscriptions_task(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    to_remove = []
    for uid, date_str in list(db.data["subscriptions"].items()):
        try:
            until = datetime.fromisoformat(date_str)
            if now >= until:
                to_remove.append(uid)
        except:
            continue

    for uid in to_remove:
        if uid in db.data["subscriptions"]:
            del db.data["subscriptions"][uid]
            try:
                user_id = int(uid)
                await context.bot.send_message(
                    chat_id=user_id,
                    text="⚠️ Срок действия вашей VIP-подписки истек. Продлите её, чтобы сохранить доступ к функциям!"
                )
            except:
                pass
    if to_remove:
        db.save()


async def check_bans_task(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    to_unban = []

    for ban in db.data["ban_history"]:
        if ban["active"] and ban["until"]:
            try:
                until = datetime.fromisoformat(ban["until"])
                if now >= until:
                    to_unban.append(ban["user_id"])
            except:
                continue

    for user_id in to_unban:
        db.unban_user(user_id, admin_id=None)
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ Срок вашего бана истек. Вы снова можете пользоваться ботом."
            )
        except:
            pass


def main_kb(user_id):
    uid = str(user_id)
    if db.has_subscription(user_id):
        until_str = db.data["subscriptions"].get(uid, "")
        try:
            until_dt = datetime.fromisoformat(until_str)
            date_fmt = until_dt.strftime("%d.%m %H:%M")
            sub_txt = f"💎 VIP до {date_fmt}"
        except:
            sub_txt = "💎 Подписка (Активна)"
    else:
        sub_txt = "💳 Купить подписку"

    buttons = [
        [InlineKeyboardButton("🔗 Моя ссылка", callback_data="get_link"),
         InlineKeyboardButton("📊 Статистика", callback_data="get_my_stats")],
        [InlineKeyboardButton(sub_txt, callback_data="sub_menu")],
        [InlineKeyboardButton("🆘 Поддержка", url=f"https://t.me/{TECH_BOT_USERNAME}")]
    ]

    if user_id == OWNER_ID:
        buttons.append([InlineKeyboardButton("👑 Управление админами", callback_data="admin_manage")])

    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in db.data["banned"]: return
    uid = str(user.id)
    if uid not in db.data["users"]:
        db.data["users"][uid] = {"user_id": user.id, "username": user.username, "full_name": user.full_name,
                                 "first_seen": datetime.now().isoformat(), "messages_sent": 0, "messages_received": 0}
    else:
        db.data["users"][uid]["username"] = user.username
        db.data["users"][uid]["full_name"] = user.full_name
    db.save()
    if context.args:
        try:
            target = int(context.args[0])
            if target != user.id:
                db.data["user_states"][uid] = {"state": "waiting_anon", "target_id": target}
                db.save()
                return await update.message.reply_text("✉️ Введите сообщение (текст или медиа):")
        except:
            pass
    await update.message.reply_text(f"👋 Привет, {user.first_name}!", reply_markup=main_kb(user.id))


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data == "back_to_main":
        db.data["user_states"].pop(str(user_id), None)
        await query.edit_message_text("Выберите действие:", reply_markup=main_kb(user_id))

    elif data == "admin_manage" and user_id == OWNER_ID:
        text = "👑 <b>Управление администраторами</b>\n\nВыберите действие:"
        keyboard = [
            [InlineKeyboardButton("➕ Добавить админа", callback_data="admin_add")],
            [InlineKeyboardButton("➖ Удалить админа", callback_data="admin_remove")],
            [InlineKeyboardButton("🔑 Изменить пароль админа", callback_data="admin_change_pass")],
            [InlineKeyboardButton("📋 Список админов", callback_data="admin_list")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
        ]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_add" and user_id == OWNER_ID:
        db.data["user_states"][str(user_id)] = {"state": "waiting_add_admin"}
        db.save()
        await query.edit_message_text(
            "👤 Введите ID пользователя для добавления в администраторы:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="admin_manage")]
            ])
        )

    elif data == "admin_remove" and user_id == OWNER_ID:
        db.data["user_states"][str(user_id)] = {"state": "waiting_remove_admin"}
        db.save()
        await query.edit_message_text(
            "👤 Введите ID администратора для удаления:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="admin_manage")]
            ])
        )

    elif data == "admin_change_pass" and user_id == OWNER_ID:
        db.data["user_states"][str(user_id)] = {"state": "waiting_change_pass"}
        db.save()
        await query.edit_message_text(
            "🔑 Введите в формате: <code>ID:НОВЫЙ_ПАРОЛЬ</code>\n\nПример: <code>12345678:MyNewPass123</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="admin_manage")]
            ])
        )

    elif data == "admin_list" and user_id == OWNER_ID:
        admins_list = db.data["admins"]
        text = "👑 <b>Список администраторов</b>\n\n"
        if admins_list:
            for admin_id in admins_list:
                user_info = db.data["users"].get(str(admin_id), {})
                username = user_info.get('username', 'неизвестно')
                full_name = user_info.get('full_name', 'неизвестно')
                password = db.get_admin_password(admin_id)
                text += f"• <b>ID:</b> <code>{admin_id}</code>\n"
                text += f"  <b>Имя:</b> {full_name}\n"
                text += f"  <b>Юзер:</b> @{username}\n"
                text += f"  <b>Пароль:</b> <code>{password}</code>\n\n"
        else:
            text += "Нет дополнительных администраторов.\n\n"
        text += f"<b>Владелец:</b> <code>{OWNER_ID}</code> (Вы)"
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin_manage")]
            ])
        )

    elif data == "get_link":
        link = f"https://t.me/{context.bot.username}?start={user_id}"
        await query.edit_message_text(
            f"🔗 Ваша ссылка для получения сообщений:\n`{link}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
            ])
        )

    elif data == "get_my_stats":
        u = db.data["users"].get(str(user_id), {})
        sent = u.get("messages_sent", 0)
        received = u.get("messages_received", 0)
        await query.edit_message_text(
            f"📊 Ваша статистика:\n✉️ Отправлено: {sent}\n📥 Получено: {received}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
            ])
        )

    elif data == "sub_menu":
        if db.has_subscription(user_id):
            received = [m for m in db.data["messages"] if str(m.get('to')) == str(user_id)]
            if not received:
                return await query.edit_message_text(
                    "💎 VIP активен. Входящих сообщений пока нет.",
                    reply_markup=main_kb(user_id)
                )
            text = "<b>📥 Ваши последние входящие:</b>\n\n"
            buttons = []
            for i, m in enumerate(received[-8:]):
                s_id = m.get('from')
                content = str(m.get('content', '[Медиа]'))
                text += f"{i + 1}. {content}\n"
                buttons.append([InlineKeyboardButton(f"🔎 Кто прислал №{i + 1}?", callback_data=f"reveal_{s_id}")])
            buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")])
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await query.edit_message_text(
                f"👑 <b>Подписка на {SUB_DAYS} дней</b>\n\nVIP-статус позволяет видеть, кто прислал вам сообщение.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"🌟 Stars ({STARS_PRICE})", callback_data="buy_stars"),
                     InlineKeyboardButton(f"💳 Рубли ({RUB_PRICE}₽)", callback_data="buy_rub")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
                ]),
                parse_mode="HTML"
            )

    elif data.startswith("reveal_"):
        if not db.has_subscription(user_id):
            await query.message.reply_text(
                "⚠️ Купите VIP, чтобы узнать автора.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Купить", callback_data="sub_menu")]
                ])
            )
        else:
            sender_id = data.split("_")[1]
            if db.is_protected(int(sender_id)):
                await query.message.reply_text(
                    "🔒 <b>Этот пользователь защищён.</b>\nАвтор сообщения не может быть раскрыт.",
                    parse_mode="HTML"
                )
            else:
                u = db.data["users"].get(sender_id, {})
                await query.message.reply_text(
                    f"👤 <b>Отправитель:</b>\nИмя: {u.get('full_name')}\nЮзер: @{u.get('username')}\nID: <code>{sender_id}</code>",
                    parse_mode="HTML"
                )

    elif data == "buy_stars":
        await context.bot.send_invoice(
            chat_id=user_id,
            title="VIP Подписка",
            description=f"Доступ к раскрытию авторов на {SUB_DAYS} дн.",
            payload=f"sub_{user_id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice("VIP", STARS_PRICE)]
        )

    elif data == "buy_rub":
        await query.edit_message_text(
            f"💳 <b>Оплата рублями</b>\n\n{REQUISITES}\n\nПосле оплаты отправьте чек администратору: @{TECH_BOT_USERNAME}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="sub_menu")]
            ])
        )


async def admin_web(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == OWNER_ID or db.is_admin(user.id):
        admin_panel_url = os.getenv("ADMIN_PANEL_URL", "http://localhost:5000")
        if db.is_admin(user.id):
            password = db.get_admin_password(user.id)
            text = (
                f"🌐 <b>Веб-админка</b>\n\n"
                f"🔗 Ссылка: {admin_panel_url}\n"
                f"🔑 Ваш пароль: <code>{password}</code>\n\n"
                f"<i>Используйте эти данные для входа</i>"
            )
        else:
            password = db.get_admin_password(OWNER_ID)
            if not password:
                password = db.set_admin_password(OWNER_ID, db._generate_password())
                text = (
                    f"🌐 <b>Веб-админка</b>\n\n"
                    f"🔗 Ссылка: {admin_panel_url}\n"
                    f"🔑 Ваш пароль сгенерирован: <code>{password}</code>\n\n"
                    f"<i>Используйте эти данные для входа</i>"
                )
            else:
                text = (
                    f"🌐 <b>Веб-админка</b>\n\n"
                    f"🔗 Ссылка: {admin_panel_url}\n"
                    f"🔑 Ваш пароль: <code>{password}</code>\n\n"
                    f"<i>Используйте эти данные для входа</i>"
                )
        await update.message.reply_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text("❌ У вас нет доступа к админ-панели.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid_s = str(user.id)
    msg = update.message
    state_data = db.data["user_states"].get(uid_s)
    if not state_data: return
    state = state_data.get("state")

    if user.id == OWNER_ID:
        if state == "waiting_add_admin":
            try:
                target_id = int(msg.text)
                if target_id == OWNER_ID:
                    return await msg.reply_text("❌ Вы уже являетесь владельцем бота.")
                if str(target_id) not in db.data["users"]:
                    return await msg.reply_text("❌ Пользователь с таким ID не найден в базе данных.")
                password = db.add_admin(target_id)
                if password:
                    try:
                        await context.bot.send_message(
                            target_id,
                            f"👑 Вы назначены администратором бота!\n\n"
                            f"🌐 Ссылка на веб-админку: {ADMIN_PANEL_URL}\n"
                            f"🔑 Ваш пароль для входа: <code>{password}</code>\n\n"
                            f"⚠️ Сохраните пароль в надежном месте!\n"
                            f"Для входа используйте команду /admin_web",
                            parse_mode="HTML"
                        )
                        user_info = db.data["users"].get(str(target_id), {})
                        username = user_info.get('username', 'неизвестно')
                        await msg.reply_text(
                            f"✅ Администратор добавлен!\n\n"
                            f"👤 Пользователь: @{username} (ID: {target_id})\n"
                            f"🔑 Пароль: <code>{password}</code>\n\n"
                            f"Сообщение с данными отправлено пользователю.",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Failed to send message to admin: {e}")
                        await msg.reply_text(
                            f"✅ Администратор добавлен, но не удалось отправить сообщение пользователю.\n\n"
                            f"🔑 Пароль: <code>{password}</code>\n\n"
                            f"Передайте пароль пользователю вручную.",
                            parse_mode="HTML"
                        )
                else:
                    await msg.reply_text("❌ Этот пользователь уже является администратором.")
                db.data["user_states"].pop(uid_s, None)
                db.save()
            except ValueError:
                await msg.reply_text("❌ Ошибка. Введите числовой ID пользователя.")

        elif state == "waiting_remove_admin":
            try:
                target_id = int(msg.text)
                if target_id == OWNER_ID:
                    return await msg.reply_text("❌ Нельзя удалить владельца бота.")
                if db.remove_admin(target_id):
                    user_info = db.data["users"].get(str(target_id), {})
                    username = user_info.get('username', 'неизвестно')
                    try:
                        await context.bot.send_message(
                            target_id,
                            "⚠️ Вы были удалены из списка администраторов бота.",
                            parse_mode="HTML"
                        )
                    except:
                        pass
                    await msg.reply_text(
                        f"✅ Администратор @{username} (ID: {target_id}) удален."
                    )
                else:
                    await msg.reply_text("❌ Этот пользователь не является администратором.")
                db.data["user_states"].pop(uid_s, None)
                db.save()
            except ValueError:
                await msg.reply_text("❌ Ошибка. Введите числовой ID пользователя.")

        elif state == "waiting_change_pass":
            try:
                parts = msg.text.split(":", 1)
                if len(parts) != 2:
                    return await msg.reply_text("❌ Неверный формат. Используйте: ID:НОВЫЙ_ПАРОЛЬ")
                target_id = int(parts[0].strip())
                new_password = parts[1].strip()
                if len(new_password) < 4:
                    return await msg.reply_text("❌ Пароль слишком короткий (минимум 4 символа).")
                if len(new_password) > 50:
                    return await msg.reply_text("❌ Пароль слишком длинный (максимум 50 символов).")
                if target_id == OWNER_ID or db.is_admin(target_id):
                    if db.set_admin_password(target_id, new_password):
                        user_info = db.data["users"].get(str(target_id), {})
                        username = user_info.get('username', 'неизвестно')
                        try:
                            if target_id == OWNER_ID:
                                message_text = f"🔑 Ваш пароль для веб-админки обновлен: <code>{new_password}</code>"
                            else:
                                message_text = (
                                    f"🔑 Ваш пароль для веб-админки обновлен администратором.\n"
                                    f"Новый пароль: <code>{new_password}</code>"
                                )
                            await context.bot.send_message(
                                target_id,
                                message_text,
                                parse_mode="HTML"
                            )
                            await msg.reply_text(
                                f"✅ Пароль для @{username} (ID: {target_id}) успешно изменен.\n"
                                f"Новый пароль отправлен пользователю."
                            )
                        except Exception as e:
                            logger.error(f"Failed to send password to user: {e}")
                            await msg.reply_text(
                                f"✅ Пароль изменен, но не удалось отправить его пользователю.\n\n"
                                f"🔑 Новый пароль: <code>{new_password}</code>\n\n"
                                f"Передайте пароль пользователю вручную.",
                                parse_mode="HTML"
                            )
                    else:
                        await msg.reply_text("❌ Ошибка при изменении пароля.")
                else:
                    await msg.reply_text("❌ Этот пользователь не является администратором.")
                db.data["user_states"].pop(uid_s, None)
                db.save()
            except ValueError:
                await msg.reply_text("❌ Ошибка. Неверный формат ID.")
            except Exception as e:
                logger.error(f"Error changing password: {e}")
                await msg.reply_text("❌ Произошла ошибка при изменении пароля.")

    if state == "waiting_anon":
        target_id = state_data["target_id"]
        try:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Кто это?", callback_data=f"reveal_{user.id}")]])
            if msg.text:
                await context.bot.send_message(
                    target_id,
                    f"✉️ <b>Новое анонимное сообщение!</b>\n\n{msg.text}",
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            else:
                await context.bot.copy_message(
                    target_id,
                    user.id,
                    msg.message_id,
                    caption="✉️ <b>Новое анонимное сообщение!</b>",
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            db.data["messages"].append({
                "from": user.id,
                "to": target_id,
                "date": datetime.now().isoformat(),
                "content": msg.text or "[Медиа]"
            })
            db.data["users"][uid_s]["messages_sent"] += 1
            if str(target_id) in db.data["users"]:
                db.data["users"][str(target_id)]["messages_received"] += 1
            db.data["user_states"].pop(uid_s, None)
            db.save()
            await msg.reply_text("✅ Ваше сообщение успешно доставлено!", reply_markup=main_kb(user.id))
        except:
            await msg.reply_text("❌ Не удалось доставить сообщение. Возможно, пользователь заблокировал бота.")


async def setup_owner_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == OWNER_ID:
        if context.args:
            new_password = context.args[0]
            if len(new_password) < 4:
                return await update.message.reply_text("❌ Пароль слишком короткий (минимум 4 символа).")
            if len(new_password) > 50:
                return await update.message.reply_text("❌ Пароль слишком длинный (максимум 50 символов).")
            if db.set_admin_password(OWNER_ID, new_password):
                admin_panel_url = os.getenv("ADMIN_PANEL_URL", "http://localhost:5000")
                text = (
                    f"✅ Пароль владельца успешно изменен!\n\n"
                    f"🌐 Ссылка на веб-админку: {admin_panel_url}\n"
                    f"🔑 Ваш новый пароль: <code>{new_password}</code>\n\n"
                    f"<i>Используйте эти данные для входа</i>"
                )
                await update.message.reply_text(text, parse_mode="HTML")
            else:
                await update.message.reply_text("❌ Ошибка при изменении пароля.")
        else:
            password = db.get_admin_password(OWNER_ID)
            admin_panel_url = os.getenv("ADMIN_PANEL_URL", "http://localhost:5000")
            if password:
                text = (
                    f"🔑 <b>Текущий пароль владельца</b>\n\n"
                    f"🌐 Ссылка: {admin_panel_url}\n"
                    f"🔑 Пароль: <code>{password}</code>\n\n"
                    f"<i>Используйте команду:</i>\n"
                    f"<code>/setup_owner_password НОВЫЙ_ПАРОЛЬ</code>\n"
                    f"<i>для изменения пароля</i>"
                )
            else:
                password = db._generate_password()
                db.set_admin_password(OWNER_ID, password)
                text = (
                    f"🔑 <b>Пароль владельца сгенерирован</b>\n\n"
                    f"🌐 Ссылка: {admin_panel_url}\n"
                    f"🔑 Пароль: <code>{password}</code>\n\n"
                    f"<i>Используйте команду:</i>\n"
                    f"<code>/setup_owner_password НОВЫЙ_ПАРОЛЬ</code>\n"
                    f"<i>для изменения пароля</i>"
                )
            await update.message.reply_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Эта команда доступна только владельцу бота.")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.job_queue.run_repeating(check_subscriptions_task, interval=10, first=10)
    app.job_queue.run_repeating(check_bans_task, interval=60, first=60)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin_web", admin_web))
    app.add_handler(CommandHandler("setup_owner_password", setup_owner_password))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(PreCheckoutQueryHandler(lambda u, c: u.pre_checkout_query.answer(ok=True)))
    app.add_handler(
        MessageHandler(filters.SUCCESSFUL_PAYMENT,
                       lambda u, c: db.add_subscription(u.effective_user.id, f"{SUB_DAYS}d")))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("🤖 Бот запущен...")
    print(f"👑 Владелец: {OWNER_ID}")
    print(f"🌐 Веб-админка: {ADMIN_PANEL_URL}")

    if not db.get_admin_password(OWNER_ID):
        password = db._generate_password()
        db.set_admin_password(OWNER_ID, password)
        print(f"🔑 Автоматически создан пароль для владельца: {password}")

    app.run_polling()


if __name__ == '__main__':
    main()