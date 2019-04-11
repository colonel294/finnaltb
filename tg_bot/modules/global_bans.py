import html
from io import BytesIO
from typing import Optional, List

from telegram import Message, Update, Bot, User, Chat, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import run_async, CommandHandler, MessageHandler, Filters, RegexHandler
from tgram import TgramRobot, run_polling
from telegram.utils.helpers import mention_html

import tg_bot.modules.sql.global_bans_sql as sql
from tg_bot import dispatcher, OWNER_ID, SUDO_USERS, SUPPORT_USERS, STRICT_GBAN
from tg_bot.modules.helper_funcs.chat_status import user_admin, is_user_admin
from tg_bot.modules.helper_funcs.extraction import extract_user, extract_user_and_text
from tg_bot.modules.helper_funcs.filters import CustomFilters
from tg_bot.modules.helper_funcs.misc import send_to_list
from tg_bot.modules.sql.users_sql import get_all_chats

__help__ == """*Join Hider Bot*
This bot removes messages about new user joined or left the chat.
*Commands*
/help - display this help message
*How to Use*
- Add bot as ADMIN to the chat group
- Allow bot to delete messages, any other admin permissions are not required
*Questions, Feedback*
Email: lorien @ lorien . name
*Open Source*
The source code is available at [github.com/lorien/joinhider_bot](https://github.com/lorien/joinhider_bot)
*My Other Projects*
[@daysandbox_bot](https://t.me/daysandbox_bot) - bot that fights with spam messages in chat groups
[@nosticker_bot](https://t.me/nosticker_bot) - bot to delete stickers posted to group
[@coinsignal_robot](https://t.me/coinsignal_robot) - bot to be notified when price of specific coin reaches the level you have set, also you can use this bot just to see price of coins.
[@watchdog_robot](https://t.me/watchdog_robot) - bot to delete stickers, file attachments, links, photos, videos and many other types of messages
[@lang_blocker_bot](https://t.me/lang_blocker_bot) - bot to delete messages in particular languages configured by chat administrator 
"""


class InvalidCommand(Exception):
    pass


class JoinhiderBot(TgramRobot):

    def before_start_processing(self):
        self.db = connect_db()

    def build_user_name(self, user):
        return user.username or ('#%d' % user.id)

    def remember_user(self, msg):
        update = {
            '_id': msg.from_user.id,
            'seen_date': datetime.utcnow(),
            'data': msg.from_user.to_dict(),
        }
        update_insert = {
            'first_seen_date': datetime.utcnow(),
        }
        self.db.user.find_one_and_update(
            {'_id': update['_id']},
            {'$set': update, '$setOnInsert': update_insert},
            upsert=True,
        )

    def handle_start_help(self, bot, update):
        msg = update.effective_message
        if msg.chat.type == 'private':
            self.remember_user(msg)
            bot.send_message(
                chat_id=msg.chat.id,
                text=HELP,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )

    def handle_new_chat_members(self, bot, update):
        msg = update.effective_message
        try:
            bot.delete_message(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
            )
        except Exception as ex:
            if 'Message to delete not found' in str(ex):
                logging.error('Failed to delete msg: %s', ex)
                return
            elif "Message can't be deleted" in str(ex):
                logging.error('Failed to delete msg: %s', ex)
                return
            else:
                raise
        for user in msg.new_chat_members:
            self.db.chat.find_one_and_update(
                {'chat_id': msg.chat.id},
                {
                    '$set': {
                        'chat_username': msg.chat.username,
                        'active_date': datetime.utcnow(),
                    },
                    '$setOnInsert': {
                        'date': datetime.utcnow(),
                    },
                },
                upsert=True,
            )
            self.db.joined_user.find_one_and_update(
                {
                    'chat_id': msg.chat.id,
                    'user_id': user.id,
                },
                {'$set': {
                    'chat_username': msg.chat.username,
                    'user_username': user.username,
                    'date': datetime.utcnow(),
                }},
                upsert=True,
            )
            logging.debug('Removed join message for user %s at chat %d' % (
                self.build_user_name(user),
                msg.chat.id
            ))

    def handle_left_chat_member(self, bot, update):
        msg = update.effective_message
        try:
            bot.delete_message(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
            )
        except Exception as ex:
            if 'Message to delete not found' in str(ex):
                logging.error('Failed to delete join message: %s' % ex)
                return
            elif "Message can't be deleted" in str(ex):
                logging.error('Failed to delete msg: %s', ex)
                return
            else:
                raise
        user = msg.left_chat_member
        self.db.chat.find_one_and_update(
            {'chat_id': msg.chat.id},
            {
                '$set': {
                    'chat_username': msg.chat.username,
                    'active_date': datetime.utcnow(),
                },
                '$setOnInsert': {
                    'date': datetime.utcnow(),
                },
            },
            upsert=True,
        )
        self.db.left_user.find_one_and_update(
            {
                'chat_id': msg.chat.id,
                'user_id': user.id,
            },
            {'$set': {
                'chat_username': msg.chat.username,
                'user_username': user.username,
                'date': datetime.utcnow(),
            }},
            upsert=True,
        )
        logging.debug('Removed left message for user %s at chat %d' % (
            self.build_user_name(user),
            msg.chat.id
        ))

    def handle_stat(self, bot, update):
        msg = update.effective_message
        if msg.chat.type != 'private':
            return
        else:
            start = datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            stat = []
            for _ in range(7):
                end = start + timedelta(days=1)
                chat_count = self.db.chat.count({
                    'active_date': {
                        '$gte': start,
                        '$lt': end,
                    }
                })
                user_count = self.db.joined_user.count({
                    'date': {
                        '$gte': start,
                        '$lt': end,
                    }
                })
                stat.insert(0, (chat_count, user_count))
                start -= timedelta(days=1)
            out = '*Recent 7 days stats*\n'
            out += '\n'
            out += 'Chats:\n'
            out += '  %s\n' % ' | '.join([str(x[0]) for x in stat])
            out += 'Users:\n'
            out += '  %s\n' % ' | '.join([str(x[1]) for x in stat])
            bot.send_message(
                chat_id=msg.chat.id,
                text=out,
                parse_mode=ParseMode.MARKDOWN
            )

    def register_handlers(self, dispatcher):
        dispatcher.add_handler(CommandHandler(
            ['start', 'help'], self.handle_start_help
        ))
        dispatcher.add_handler(MessageHandler(
            Filters.status_update.new_chat_members, self.handle_new_chat_members
        ))
        dispatcher.add_handler(MessageHandler(
            Filters.status_update.left_chat_member, self.handle_left_chat_member
        ))
        dispatcher.add_handler(MessageHandler(
            Filters.status_update.left_chat_member, self.handle_left_chat_member
        ))
        dispatcher.add_handler(CommandHandler(
            ['stat'], self.handle_stat
        ))


__mod_name__ = "پاک کن"

