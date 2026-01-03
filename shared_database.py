import json
import os
import logging
from datetime import datetime, timedelta
import secrets
import string
import asyncio

logger = logging.getLogger(__name__)


class SharedDatabase:
    def __init__(self, filename="bot_database.json"):
        self.filename = filename
        self.lock = asyncio.Lock()
        self.data = self.load()
        self.last_modified = datetime.now()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Инициализация ключей
                    for key in ["messages", "banned", "protected_users", "admins", "ban_history", "action_history"]:
                        if key not in data:
                            data[key] = []
                    for key in ["users", "subscriptions", "user_states"]:
                        if key not in data:
                            data[key] = {}
                    if "statistics" not in data:
                        data["statistics"] = {"total_messages": 0, "total_users": 0}
                    if "admin_passwords" not in data:
                        data["admin_passwords"] = {}
                    return data
            except Exception as e:
                logger.error(f"Error loading database: {e}")
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
            "statistics": {"total_messages": 0, "total_users": 0}
        }

    def add_action_to_history(self, user_id, action_type, details, admin_id=None):
        """Добавление действия в историю"""
        action = {
            "user_id": int(user_id),
            "action_type": action_type,
            "details": details,
            "admin_id": admin_id,
            "timestamp": datetime.now().isoformat()
        }
        self.data["action_history"].append(action)
        # Храним только последние 1000 действий
        if len(self.data["action_history"]) > 1000:
            self.data["action_history"] = self.data["action_history"][-1000:]

    def get_user_history(self, user_id):
        """Получить историю действий пользователя"""
        user_history = []
        for action in self.data["action_history"]:
            if action["user_id"] == int(user_id):
                user_history.append(action)
        return user_history

    def get_ban_history(self, user_id):
        """Получить историю банов пользователя"""
        ban_history = []
        for ban in self.data["ban_history"]:
            if ban["user_id"] == int(user_id):
                ban_history.append(ban)
        return ban_history

    # [остальные методы остаются без изменений...]

    def ban_user(self, user_id, reason="не указана", until=None, admin_id=None):
        """Бан пользователя с указанием причины и срока"""
        uid = int(user_id)
        if uid not in self.data["banned"]:
            self.data["banned"].append(uid)

            # Добавляем в историю банов
            ban_record = {
                "user_id": uid,
                "reason": reason,
                "admin_id": admin_id,
                "banned_at": datetime.now().isoformat(),
                "until": until,
                "active": True
            }
            self.data["ban_history"].append(ban_record)

            # Добавляем в общую историю действий
            self.add_action_to_history(user_id, "ban", {
                "reason": reason,
                "until": until,
                "admin_id": admin_id
            }, admin_id)

            return True
        return False

    def unban_user(self, user_id, admin_id=None):
        """Разбан пользователя"""
        uid = int(user_id)
        if uid in self.data["banned"]:
            self.data["banned"].remove(uid)

            # Обновляем запись в истории банов
            for ban in self.data["ban_history"]:
                if ban["user_id"] == uid and ban["active"]:
                    ban["active"] = False
                    ban["unbanned_at"] = datetime.now().isoformat()
                    ban["unbanned_by"] = admin_id
                    break

            # Добавляем в историю действий
            self.add_action_to_history(user_id, "unban", {
                "admin_id": admin_id
            }, admin_id)

            return True
        return False

    def add_protected_user(self, user_id, admin_id=None):
        """Добавление пользователя в защищённые"""
        uid = int(user_id)
        if uid not in self.data["protected_users"]:
            self.data["protected_users"].append(uid)

            # Добавляем в историю действий
            self.add_action_to_history(user_id, "protect_add", {
                "admin_id": admin_id
            }, admin_id)

            return True
        return False

    def remove_protected_user(self, user_id, admin_id=None):
        """Удаление пользователя из защищённых"""
        uid = int(user_id)
        if uid in self.data["protected_users"]:
            self.data["protected_users"].remove(uid)

            # Добавляем в историю действий
            self.add_action_to_history(user_id, "protect_remove", {
                "admin_id": admin_id
            }, admin_id)

            return True
        return False

    def add_subscription(self, user_id, time_str, admin_id=None):
        """Добавление подписки"""
        uid = str(user_id)
        now = datetime.now()

        import re
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

        # Добавляем в историю действий
        self.add_action_to_history(user_id, "vip_add", {
            "until": new_until.isoformat(),
            "days": value if unit in ['', 'd'] else None,
            "admin_id": admin_id
        }, admin_id)

        return new_until

    def remove_subscription(self, user_id, admin_id=None):
        """Удаление подписки"""
        uid = str(user_id)
        if uid in self.data["subscriptions"]:
            del self.data["subscriptions"][uid]

            # Добавляем в историю действий
            self.add_action_to_history(user_id, "vip_remove", {
                "admin_id": admin_id
            }, admin_id)

            return True
        return False

    def add_subscription(self, user_id, time_str):
        uid = str(user_id)
        now = datetime.now()

        import re
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
            return True
        return False

    def remove_protected_user(self, user_id):
        uid = int(user_id)
        if uid in self.data["protected_users"]:
            self.data["protected_users"].remove(uid)
            return True
        return False

    def get_protected_users(self):
        return self.data["protected_users"]

    def is_admin(self, user_id):
        owner_id = int(os.environ.get('OWNER_ID', 0))
        return user_id == owner_id or int(user_id) in self.data["admins"]

    def add_admin(self, user_id, password=None):
        uid = int(user_id)
        if uid not in self.data["admins"]:
            self.data["admins"].append(uid)

            if not password:
                alphabet = string.ascii_letters + string.digits
                password = ''.join(secrets.choice(alphabet) for _ in range(12))

            self.data["admin_passwords"][str(uid)] = password
            return password
        return None

    def remove_admin(self, user_id):
        uid = int(user_id)
        if uid in self.data["admins"]:
            self.data["admins"].remove(uid)
            if str(uid) in self.data["admin_passwords"]:
                del self.data["admin_passwords"][str(uid)]
            return True
        return False

    def get_admin_password(self, user_id):
        return self.data["admin_passwords"].get(str(user_id))

    def set_admin_password(self, user_id, password):
        uid = str(user_id)
        if self.is_admin(int(user_id)):
            self.data["admin_passwords"][uid] = password
            return True
        return False

    def verify_admin(self, user_id, password):
        stored_password = self.get_admin_password(user_id)
        return stored_password == password

    def get_user_info(self, user_id):
        return self.data["users"].get(str(user_id), {})

    def get_all_users(self):
        return self.data["users"]

    def get_all_messages(self):
        return self.data["messages"]

    def search_messages(self, query):
        results = []
        for msg in self.data["messages"]:
            content = str(msg.get('content', '')).lower()
            if query.lower() in content:
                results.append(msg)
        return results

    def ban_user(self, user_id):
        uid = int(user_id)
        if uid not in self.data["banned"]:
            self.data["banned"].append(uid)
            return True
        return False

    def unban_user(self, user_id):
        uid = int(user_id)
        if uid in self.data["banned"]:
            self.data["banned"].remove(uid)
            return True
        return False


# Глобальный экземпляр
shared_db = SharedDatabase()