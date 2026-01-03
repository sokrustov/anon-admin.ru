import asyncio
import threading
from telegram import Bot
from telegram.error import TelegramError
from bot_integration import telegram_sender
import time
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, send_file
from flask_session import Session
import json
import os
import html
from datetime import datetime, timedelta
from functools import wraps
import logging

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here-change-in-production')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
Session(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_FILE = "bot_database.json"


class AdminDatabase:
    def __init__(self, filename):
        self.filename = filename
        self.data = self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                    required_keys = {
                        "users": {},
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

                    for key, default_value in required_keys.items():
                        if key not in data:
                            data[key] = default_value

                    return data
            except Exception as e:
                logger.error(f"Error loading database: {e}")
                return self._create_empty_db()
        return self._create_empty_db()

    def _create_empty_db(self):
        return {
            "users": {},
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

    def verify_admin(self, user_id, password):
        try:
            user_id_str = str(user_id)
            owner_id = int(os.environ.get('OWNER_ID', 0))
            if int(user_id) == owner_id:
                stored_password = self.data["admin_passwords"].get(user_id_str)
                if stored_password and stored_password == password:
                    return True
                return False

            if int(user_id) not in self.data["admins"]:
                return False

            stored_password = self.data["admin_passwords"].get(user_id_str)
            if stored_password and stored_password == password:
                return True

            return False

        except Exception as e:
            logger.error(f"Error verifying admin {user_id}: {e}")
            return False

    def is_admin(self, user_id):
        try:
            owner_id = int(os.environ.get('OWNER_ID', 0))
            return int(user_id) == owner_id or int(user_id) in self.data["admins"]
        except:
            return False

    def get_user_info(self, user_id):
        return self.data["users"].get(str(user_id), {})

    def get_all_users(self):
        return self.data["users"]

    def get_all_messages(self):
        return self.data["messages"]

    def add_subscription(self, user_id, days, admin_id=None, reason=None):
        uid = str(user_id)
        now = datetime.now()
        delta = timedelta(days=int(days))

        if uid in self.data["subscriptions"]:
            current_until = datetime.fromisoformat(self.data["subscriptions"][uid])
            new_until = current_until + delta
        else:
            new_until = now + delta

        self.data["subscriptions"][uid] = new_until.isoformat()

        action_record = {
            "user_id": int(user_id),
            "action_type": "vip_add",
            "details": {
                "until": new_until.isoformat(),
                "days": days,
                "admin_id": admin_id,
                "reason": reason
            },
            "timestamp": datetime.now().isoformat()
        }
        self.data["action_history"].append(action_record)

        self.save()
        return new_until

    def remove_subscription(self, user_id, admin_id=None, reason=None):
        uid = str(user_id)
        if uid in self.data["subscriptions"]:
            del self.data["subscriptions"][uid]

            action_record = {
                "user_id": int(user_id),
                "action_type": "vip_remove",
                "details": {"admin_id": admin_id, "reason": reason},
                "timestamp": datetime.now().isoformat()
            }
            self.data["action_history"].append(action_record)

            self.save()
            return True
        return False

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

    def unban_user(self, user_id, admin_id=None, reason=None):
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
                    ban["unban_reason"] = reason
                    break

            action_record = {
                "user_id": uid,
                "action_type": "unban",
                "details": {"admin_id": admin_id, "reason": reason},
                "timestamp": datetime.now().isoformat()
            }
            self.data["action_history"].append(action_record)

            self.save()
            return True
        return False

    def add_protected_user(self, user_id, admin_id=None, reason=None):
        uid = int(user_id)
        if uid not in self.data["protected_users"]:
            self.data["protected_users"].append(uid)

            action_record = {
                "user_id": uid,
                "action_type": "protect_add",
                "details": {"admin_id": admin_id, "reason": reason},
                "timestamp": datetime.now().isoformat()
            }
            self.data["action_history"].append(action_record)

            self.save()
            return True
        return False

    def remove_protected_user(self, user_id, admin_id=None, reason=None):
        uid = int(user_id)
        if uid in self.data["protected_users"]:
            self.data["protected_users"].remove(uid)

            action_record = {
                "user_id": uid,
                "action_type": "protect_remove",
                "details": {"admin_id": admin_id, "reason": reason},
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

    def send_notification(self, user_id, message):
        try:
            if telegram_sender.send_message_sync(user_id, message):
                logger.info(f"Уведомление отправлено пользователю {user_id}")
                return True
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
        return False

    def broadcast_message(self, message_text):
        sent_count = 0
        total_users = 0

        for user_id_str in self.data["users"]:
            try:
                user_id = int(user_id_str)
                if user_id in self.data["banned"]:
                    continue

                total_users += 1

                if telegram_sender.send_message_sync(user_id, message_text):
                    sent_count += 1
                    logger.info(f"Сообщение отправлено пользователю {user_id}")

                time.sleep(0.05)

            except Exception as e:
                logger.error(f"Критическая ошибка отправки пользователю {user_id_str}: {e}")
                continue

        logger.info(f"Рассылка завершена. Отправлено {sent_count} из {total_users} пользователей")
        return sent_count

    def search_messages(self, query):
        results = []
        for msg in self.data["messages"]:
            content = str(msg.get('content', '')).lower()
            if query.lower() in content:
                results.append(msg)
        return results

    def get_admin_number(self, admin_id):
        """Получить номер администратора (начиная с 1 для владельца)"""
        owner_id = int(os.environ.get('OWNER_ID', 0))
        if admin_id == owner_id:
            return "#1 (Владелец)"

        if admin_id in self.data["admins"]:
            index = self.data["admins"].index(admin_id)
            return f"#{index + 2}"

        return "Неизвестно"


db = AdminDatabase(DB_FILE)

TELEGRAM_BOT_TOKEN = os.environ.get('BOT_TOKEN')
telegram_bot = None

if TELEGRAM_BOT_TOKEN:
    try:
        telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)
    except Exception as e:
        logger.error(f"Ошибка инициализации Telegram бота: {e}")


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


@app.context_processor
def inject_db():
    return dict(db=db)


@app.route('/')
@login_required
def index():
    stats = db.data["statistics"]
    total_users = len(db.data["users"])
    total_messages = len(db.data["messages"])
    total_banned = len(db.data["banned"])
    total_subscriptions = len(db.data["subscriptions"])

    recent_messages = list(reversed(db.data["messages"]))[:5]

    recent_users = []
    for uid, user in list(db.data["users"].items())[-5:]:
        recent_users.append({
            'id': uid,
            'username': user.get('username', 'N/A'),
            'full_name': user.get('full_name', 'N/A'),
            'is_vip': uid in db.data["subscriptions"],
            'is_banned': int(uid) in db.data["banned"]
        })

    return render_template('dashboard.html',
                           total_users=total_users,
                           total_messages=total_messages,
                           total_banned=total_banned,
                           total_subscriptions=total_subscriptions,
                           recent_messages=recent_messages,
                           recent_users=recent_users)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        password = request.form.get('password')

        if user_id and password:
            try:
                user_id_int = int(user_id)

                logger.info(f"Login attempt: user_id={user_id_int}, password={password}")

                if db.verify_admin(user_id_int, password):
                    session['admin_id'] = user_id_int
                    user_info = db.get_user_info(str(user_id_int))
                    session['admin_name'] = user_info.get('full_name', f'Admin {user_id_int}')

                    owner_id = int(os.environ.get('OWNER_ID', 0))
                    session['is_owner'] = (user_id_int == owner_id)

                    flash('✅ Успешный вход!', 'success')
                    logger.info(f"Login successful for user {user_id_int}")
                    return redirect(url_for('index'))
                else:
                    logger.warning(f"Login failed for user {user_id_int}")
                    flash('❌ Неверный ID пользователя или пароль', 'danger')
            except Exception as e:
                logger.error(f"Login error for user {user_id}: {e}")
                flash('❌ Ошибка при входе. Проверьте введенные данные.', 'danger')
        else:
            flash('⚠️ Заполните все поля', 'warning')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('👋 Вы вышли из системы', 'info')
    return redirect(url_for('login'))


@app.route('/users')
@login_required
def users():
    all_users = db.get_all_users()
    users_list = []

    for uid, user in all_users.items():
        users_list.append({
            'id': uid,
            'username': user.get('username', 'N/A'),
            'full_name': user.get('full_name', 'N/A'),
            'first_seen': user.get('first_seen', 'N/A'),
            'messages_sent': user.get('messages_sent', 0),
            'messages_received': user.get('messages_received', 0),
            'is_vip': uid in db.data["subscriptions"],
            'is_banned': int(uid) in db.data["banned"],
            'is_protected': int(uid) in db.data["protected_users"],
            'is_admin': db.is_admin(int(uid)),
            'vip_until': db.data["subscriptions"].get(uid, None)
        })

    return render_template('users.html', users=users_list)


@app.route('/user/<user_id>')
@login_required
def user_detail(user_id):
    user_info = db.get_user_info(user_id)
    if not user_info:
        flash('❌ Пользователь не найден', 'danger')
        return redirect(url_for('users'))

    user_history = db.get_user_history(user_id)
    ban_history = db.get_ban_history(user_id)

    user_messages = []
    for msg in db.data["messages"]:
        if str(msg.get('from')) == user_id or str(msg.get('to')) == user_id:
            user_messages.append(msg)

    return render_template('user_detail.html',
                           user=user_info,
                           user_id=user_id,
                           is_vip=user_id in db.data["subscriptions"],
                           is_banned=int(user_id) in db.data["banned"],
                           is_protected=int(user_id) in db.data["protected_users"],
                           is_admin=db.is_admin(int(user_id)),
                           vip_until=db.data["subscriptions"].get(user_id),
                           user_history=user_history,
                           ban_history=ban_history,
                           messages=user_messages[:50])


@app.route('/messages')
@login_required
def messages():
    filter_type = request.args.get('filter', 'all')
    all_messages = db.get_all_messages()

    if filter_type != 'all':
        now = datetime.now()
        filtered_messages = []

        for msg in all_messages:
            if not msg.get('date'):
                continue

            try:
                msg_date = datetime.fromisoformat(msg['date'].replace('Z', '+00:00'))

                if filter_type == 'today':
                    if msg_date.date() == now.date():
                        filtered_messages.append(msg)
                elif filter_type == 'week':
                    week_ago = now - timedelta(days=7)
                    if msg_date >= week_ago:
                        filtered_messages.append(msg)
                elif filter_type == 'month':
                    month_ago = now - timedelta(days=30)
                    if msg_date >= month_ago:
                        filtered_messages.append(msg)
            except:
                continue

        all_messages = filtered_messages

    all_messages = list(reversed(all_messages))
    return render_template('messages.html', messages=all_messages)


@app.route('/broadcast', methods=['GET', 'POST'])
@login_required
def broadcast():
    if request.method == 'POST':
        message = request.form.get('message')
        if message:
            try:
                from threading import Thread

                def send_broadcast():
                    count = db.broadcast_message(message)
                    logger.info(f"Рассылка завершена: {count} сообщений отправлено")

                thread = Thread(target=send_broadcast)
                thread.daemon = True
                thread.start()

                flash(f'✅ Рассылка запущена! Сообщение будет отправлено {len(db.data["users"])} пользователям.',
                      'success')
                return redirect(url_for('broadcast'))

            except Exception as e:
                logger.error(f"Ошибка при запуске рассылки: {e}")
                flash(f'❌ Ошибка при запуске рассылки: {str(e)}', 'danger')
        else:
            flash('⚠️ Введите текст сообщения', 'warning')

    return render_template('broadcast.html')


@app.route('/manage_user/<user_id>', methods=['POST'])
@login_required
def manage_user(user_id):
    action = request.form.get('action')
    admin_id = session.get('admin_id')
    reason = request.form.get('reason', '')

    try:
        if action == 'ban':
            ban_reason = request.form.get('ban_reason', 'не указана')
            ban_type = request.form.get('ban_type', 'permanent')
            until = None

            if ban_type == 'temporary':
                days = int(request.form.get('days', 7))
                until = (datetime.now() + timedelta(days=days)).isoformat()

            if db.ban_user(user_id, ban_reason, until, admin_id):
                user_info = db.get_user_info(user_id)

                notification_msg = f"🚫 <b>Вы были забанены в боте!</b>\n\n"
                notification_msg += f"<b>Причина:</b> {ban_reason}\n"
                if until:
                    until_date = datetime.fromisoformat(until).strftime("%d.%m.%Y %H:%M")
                    notification_msg += f"<b>Срок бана:</b> до {until_date}\n"
                else:
                    notification_msg += f"<b>Срок бана:</b> навсегда\n"
                notification_msg += f"\nДля разблокировки обратитесь в поддержку: @svchostt_tech_bot"

                db.send_notification(int(user_id), notification_msg)
                flash('✅ Пользователь забанен', 'success')
            else:
                flash('⚠️ Пользователь уже забанен', 'warning')

        elif action == 'unban':
            unban_reason = request.form.get('unban_reason', 'не указана')
            if db.unban_user(user_id, admin_id, unban_reason):
                notification_msg = "✅ <b>Вы были разблокированы в боте!</b>\n\nТеперь вы снова можете пользоваться всеми функциями."
                db.send_notification(int(user_id), notification_msg)
                flash('✅ Пользователь разбанен', 'success')
            else:
                flash('⚠️ Пользователь не забанен', 'warning')

        elif action == 'protect':
            protect_reason = request.form.get('protect_reason', 'не указана')
            if db.add_protected_user(user_id, admin_id, protect_reason):
                notification_msg = "🛡 <b>Вам выдана защита от раскрытия!</b>\n\nТеперь другие пользователи не смогут узнать, что именно вы отправили им анонимное сообщение."
                db.send_notification(int(user_id), notification_msg)
                flash('✅ Пользователь добавлен в защищённые', 'success')
            else:
                flash('⚠️ Пользователь уже защищён', 'warning')

        elif action == 'unprotect':
            unprotect_reason = request.form.get('unprotect_reason', 'не указана')
            if db.remove_protected_user(user_id, admin_id, unprotect_reason):
                notification_msg = "🛡 <b>С вас снята защита от раскрытия!</b>\n\nТеперь другие пользователи с VIP подпиской могут видеть, что именно вы отправили им анонимное сообщение."
                db.send_notification(int(user_id), notification_msg)
                flash('✅ Пользователь удалён из защищённых', 'success')
            else:
                flash('⚠️ Пользователь не защищён', 'warning')

        elif action == 'add_vip':
            days = request.form.get('days', 7)
            vip_reason = request.form.get('vip_reason', 'не указана')
            try:
                until = db.add_subscription(user_id, int(days), admin_id, vip_reason)
                date_str = until.strftime("%d.%m.%Y %H:%M:%S")

                notification_msg = f"💎 <b>Вам выдана VIP подписка!</b>\n\n"
                notification_msg += f"<b>Срок действия:</b> до {date_str}\n"
                notification_msg += f"<b>Преимущества:</b>\n"
                notification_msg += "• Видите, кто отправил вам анонимные сообщения\n"
                notification_msg += "• Доступ к истории входящих сообщений\n"
                notification_msg += "• Приоритетная поддержка"

                db.send_notification(int(user_id), notification_msg)
                flash(f'✅ VIP подписка добавлена до {date_str}', 'success')
            except:
                flash('❌ Ошибка при добавлении подписки', 'danger')

        elif action == 'remove_vip':
            remove_vip_reason = request.form.get('remove_vip_reason', 'не указана')
            if db.remove_subscription(user_id, admin_id, remove_vip_reason):
                notification_msg = "❌ <b>Ваша VIP подписка была отменена!</b>\n\nВы больше не можете видеть отправителей анонимных сообщений."
                db.send_notification(int(user_id), notification_msg)
                flash('✅ VIP подписка удалена', 'success')
            else:
                flash('⚠️ У пользователя нет подписки', 'warning')

        else:
            flash('❌ Неизвестное действие', 'danger')

    except Exception as e:
        logger.error(f"Error managing user: {e}")
        flash('❌ Ошибка при выполнении действия', 'danger')

    return redirect(url_for('user_detail', user_id=user_id))


@app.route('/search', methods=['GET', 'POST'])
@login_required
def search():
    results = []
    query = ''

    if request.method == 'POST':
        query = request.form.get('query', '')
        search_type = request.form.get('type', 'messages')

        if search_type == 'messages':
            results = db.search_messages(query)
        elif search_type == 'users':
            for uid, user in db.data["users"].items():
                if (query in uid or
                        query.lower() in user.get('username', '').lower() or
                        query.lower() in user.get('full_name', '').lower()):
                    results.append({
                        'id': uid,
                        'username': user.get('username', 'N/A'),
                        'full_name': user.get('full_name', 'N/A'),
                        'type': 'user'
                    })

    return render_template('search.html', query=query, results=results,
                           search_type=request.form.get('type', 'messages'))


@app.route('/settings')
@login_required
def settings():
    is_owner = session.get('is_owner', False)

    admins = []
    for admin_id in db.data["admins"]:
        user_info = db.get_user_info(admin_id)
        admins.append({
            'id': admin_id,
            'username': user_info.get('username', 'N/A'),
            'full_name': user_info.get('full_name', 'N/A')
        })

    return render_template('settings.html', is_owner=is_owner, admins=admins)


@app.route('/admins')
@login_required
def admins():
    if not session.get('is_owner'):
        flash('❌ Эта страница доступна только владельцу бота', 'danger')
        return redirect(url_for('index'))

    owner_id = int(os.environ.get('OWNER_ID', 0))
    admin_id = session.get('admin_id')

    admins_list = []

    owner_info = db.get_user_info(str(owner_id))
    admins_list.append({
        'id': owner_id,
        'username': owner_info.get('username', 'N/A'),
        'full_name': owner_info.get('full_name', 'N/A'),
        'password': db.data["admin_passwords"].get(str(owner_id), 'не установлен'),
        'is_owner': True,
        'can_remove': False,
        'admin_number': "#1"
    })

    for idx, admin_id in enumerate(db.data["admins"]):
        user_info = db.get_user_info(str(admin_id))
        admins_list.append({
            'id': admin_id,
            'username': user_info.get('username', 'N/A'),
            'full_name': user_info.get('full_name', 'N/A'),
            'password': db.data["admin_passwords"].get(str(admin_id), 'не установлен'),
            'is_owner': False,
            'can_remove': True,
            'admin_number': f"#{idx + 2}"
        })

    return render_template('admins.html', admins=admins_list)


@app.route('/remove_admin/<int:admin_id>', methods=['POST'])
@login_required
def remove_admin(admin_id):
    if not session.get('is_owner'):
        return jsonify({'success': False, 'message': 'Только владелец может удалять администраторов'})

    owner_id = int(os.environ.get('OWNER_ID', 0))
    if admin_id == owner_id:
        return jsonify({'success': False, 'message': 'Нельзя удалить владельца'})

    try:
        db.data["admins"].remove(admin_id)
        if str(admin_id) in db.data["admin_passwords"]:
            del db.data["admin_passwords"][str(admin_id)]

        try:
            telegram_sender.send_message_sync(
                admin_id,
                "⚠️ <b>Вы были удалены из списка администраторов бота!</b>\n\n"
                "Ваш доступ к веб-админке был отозван владельцем."
            )
        except:
            pass

        db.save()
        return jsonify({'success': True, 'message': f'Администратор {admin_id} удален'})
    except Exception as e:
        logger.error(f"Error removing admin: {e}")
        return jsonify({'success': False, 'message': f'Ошибка при удалении: {str(e)}'})


@app.route('/api/stats')
@login_required
def api_stats():
    stats = {
        'total_users': len(db.data["users"]),
        'total_messages': len(db.data["messages"]),
        'total_banned': len(db.data["banned"]),
        'total_subscriptions': len(db.data["subscriptions"]),
        'total_protected': len(db.data["protected_users"]),
        'total_admins': len(db.data["admins"])
    }
    return jsonify(stats)


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(e):
    return render_template('500.html'), 500


if __name__ == '__main__':
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)

    print(f"🌐 Веб-админка запущена на http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)