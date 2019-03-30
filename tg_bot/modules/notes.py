import re
from io import BytesIO
from typing import Optional, List

from telegram import MAX_MESSAGE_LENGTH, ParseMode, InlineKeyboardMarkup
from telegram import Message, Update, Bot
from telegram.error import BadRequest
from telegram.ext import CommandHandler, RegexHandler
from telegram.ext.dispatcher import run_async
from telegram.utils.helpers import escape_markdown

import tg_bot.modules.sql.notes_sql as sql
from tg_bot import dispatcher, MESSAGE_DUMP, LOGGER
from tg_bot.modules.disable import DisableAbleCommandHandler
from tg_bot.modules.helper_funcs.chat_status import user_admin
from tg_bot.modules.helper_funcs.misc import build_keyboard, revert_buttons
from tg_bot.modules.helper_funcs.msg_types import get_note_type

FILE_MATCHER = re.compile(r"^###file_id(!photo)?###:(.*?)(?:\s|$)")

ENUM_FUNC_MAP = {
    sql.Types.TEXT.value: dispatcher.bot.send_message,
    sql.Types.BUTTON_TEXT.value: dispatcher.bot.send_message,
    sql.Types.STICKER.value: dispatcher.bot.send_sticker,
    sql.Types.DOCUMENT.value: dispatcher.bot.send_document,
    sql.Types.PHOTO.value: dispatcher.bot.send_photo,
    sql.Types.AUDIO.value: dispatcher.bot.send_audio,
    sql.Types.VOICE.value: dispatcher.bot.send_voice,
    sql.Types.VIDEO.value: dispatcher.bot.send_video
}


# Do not async
def get(bot, update, notename, show_none=True, no_format=False):
    chat_id = update.effective_chat.id
    note = sql.get_note(chat_id, notename)
    message = update.effective_message  # type: Optional[Message]

    if note:
        # If we're replying to a message, reply to that message (unless it's an error)
        if message.reply_to_message:
            reply_id = message.reply_to_message.message_id
        else:
            reply_id = message.message_id

        if note.is_reply:
            if MESSAGE_DUMP:
                try:
                    bot.forward_message(chat_id=chat_id, from_chat_id=MESSAGE_DUMP, message_id=note.value)
                except BadRequest as excp:
                    if excp.message == "Message to forward not found":
                        message.reply_text("پیامی که نشونم داده بودی رو گم کردم😶 "
                                           "از لیست پاکش میکنم.")
                        sql.rm_note(chat_id, notename)
                    else:
                        raise
            else:
                try:
                    bot.forward_message(chat_id=chat_id, from_chat_id=chat_id, message_id=note.value)
                except BadRequest as excp:
                    if excp.message == "Message to forward not found":
                        message.reply_text("عه فک کنم کسی که صاحب فایل بود دیلیت زده "
                                           "لطفا دوباره از اول"
                                           "برام تعریف کن این قسمتو . تا اون موقع "
                                           "من  این بخشو از لیست پاک میکنم")
                        sql.rm_note(chat_id, notename)
                    else:
                        raise
        else:
            text = note.value
            keyb = []
            parseMode = ParseMode.MARKDOWN
            buttons = sql.get_buttons(chat_id, notename)
            if no_format:
                parseMode = None
                text += revert_buttons(buttons)
            else:
                keyb = build_keyboard(buttons)

            keyboard = InlineKeyboardMarkup(keyb)

            try:
                if note.msgtype in (sql.Types.BUTTON_TEXT, sql.Types.TEXT):
                    bot.send_message(chat_id, text, reply_to_message_id=reply_id,
                                     parse_mode=parseMode, disable_web_page_preview=True,
                                     reply_markup=keyboard)
                else:
                    ENUM_FUNC_MAP[note.msgtype](chat_id, note.file, caption=text, reply_to_message_id=reply_id,
                                                parse_mode=parseMode, disable_web_page_preview=True,
                                                reply_markup=keyboard)

            except BadRequest as excp:
                if excp.message == "Entity_mention_user_invalid":
                    message.reply_text("اومم بنظر میاد میخوای یه شخصو بهم معرفی کنی که من تا حالا ندیدمش "
                                       "اگه واقعا لازمه که اون شخصو من اضافه کنم . اول یه پیام ازش فوروارد کن "
                                       "تا بتونم تگش کنم!")
                elif FILE_MATCHER.match(note.value):
                    message.reply_text("اومم ما رباتا نمیتونیم از اموال هم اسکی بریم . زشته! "
                                       "اگه واقعا نیازه . یا از فور پیشرفته استفاده کن یا دوباره برام  "
                                       "آپلود کن که لو نریم🤪.")
                    sql.rm_note(chat_id, notename)
                else:
                    message.reply_text("فرمت این فایل برای من مجاز نیست . حق ندارم اینو نگه دارم! "
                                       "با @colonel294 ارتباط برقرار کن واسه دلیلش!")
                    LOGGER.exception("Could not parse message #%s in chat %s", notename, str(chat_id))
                    LOGGER.warning("Message was: %s", str(note.value))
        return
    elif show_none:
        message.reply_text("این هشتگ دیگه وجود نداره!")


@run_async
def cmd_get(bot: Bot, update: Update, args: List[str]):
    if len(args) >= 2 and args[1].lower() == "noformat":
        get(bot, update, args[0], show_none=True, no_format=True)
    elif len(args) >= 1:
        get(bot, update, args[0], show_none=True)
    else:
        update.effective_message.reply_text("Get rekt")


@run_async
def hash_get(bot: Bot, update: Update):
    message = update.effective_message.text
    fst_word = message.split()[0]
    no_hash = fst_word[1:]
    get(bot, update, no_hash, show_none=False)


@run_async
@user_admin
def save(bot: Bot, update: Update):
    chat_id = update.effective_chat.id
    msg = update.effective_message  # type: Optional[Message]

    note_name, text, data_type, content, buttons = get_note_type(msg)

    if data_type is None:
        msg.reply_text("حاجی هیچ هشتگی ندارمم!")
        return
    
    if len(text.strip()) == 0:
        text = note_name
        
    sql.add_note_to_db(chat_id, note_name, text, data_type, buttons=buttons, file=content)

    msg.reply_text(
        "حله هشتگ {note_name} اضافه شد.\nبا دستور /get {note_name}, یا #{note_name} میتونی محتواشو بگیری".format(note_name=note_name))

    if msg.reply_to_message and msg.reply_to_message.from_user.is_bot:
        if text:
            msg.reply_text("متاسفانه ما رباتا نمیتونی از ربات دیگه ایی اسکی بریم . زشته, "
                           "برا همین من نمیتونم هشتگتو قبول کنم!. "
                           "\nاگه میخوای که این فایل رو برام تعریف کنی باید از طرف خودت یا هرکسی که "
                           "ربات نیست برام فوروارد یشه!.")
        else:
            msg.reply_text("متاسفانه ما رباتا نمیتونی از ربات دیگه ایی اسکی بریم . زشته, "
                           "برا همین من نمیتونم هشتگتو قبول کنم!. "
                           "\nاگه میخوای که این فایل رو برام تعریف کنی باید از طرف خودت یا هرکسی که "
                           "ربات نیست برام فوروارد یشه!.")
        return


@run_async
@user_admin
def clear(bot: Bot, update: Update, args: List[str]):
    chat_id = update.effective_chat.id
    if len(args) >= 1:
        notename = args[0]

        if sql.rm_note(chat_id, notename):
            update.effective_message.reply_text("هشتگتو ورداشتم عجقم😎.")
        else:
            update.effective_message.reply_text("این هشتگ تو دیتابیس من نیس!")


@run_async
def list_notes(bot: Bot, update: Update):
    chat_id = update.effective_chat.id
    note_list = sql.get_all_chat_notes(chat_id)

    msg = "*هشتگ های این گپ:*\n"
    for note in note_list:
        note_name = escape_markdown(" - {}\n".format(note.name))
        if len(msg) + len(note_name) > MAX_MESSAGE_LENGTH:
            update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            msg = ""
        msg += note_name

    if msg == "*هشتگ های این گپ:*\n":
        update.effective_message.reply_text("هشتگی داخل این گپ نیس!")

    elif len(msg) != 0:
        update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


def __import_data__(chat_id, data):
    failures = []
    for notename, notedata in data.get('extra', {}).items():
        match = FILE_MATCHER.match(notedata)

        if match:
            failures.append(notename)
            notedata = notedata[match.end():].strip()
            if notedata:
                sql.add_note_to_db(chat_id, notename[1:], notedata, sql.Types.TEXT)
        else:
            sql.add_note_to_db(chat_id, notename[1:], notedata, sql.Types.TEXT)

    if failures:
        with BytesIO(str.encode("\n".join(failures))) as output:
            output.name = "failed_imports.txt"
            dispatcher.bot.send_document(chat_id, document=output, filename="failed_imports.txt",
                                         caption="این فایل یا عکس ها رو نمیتونم پردازش کنم "
                                                 "چون از طرف یه ربات دیگه هستن و تلگرام اجازه بهم نمیده "
                                                 "ببخشید ولی در این مورد کاری ازم ساخته نیس!!")


def __stats__():
    return "{} notes, across {} chats.".format(sql.num_notes(), sql.num_chats())


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    notes = sql.get_all_chat_notes(chat_id)
    return "تعداد{} هشتگ داخل این گپ موجوده".format(len(notes))


__help__ = """
 - /get <نام هشتگ>: 
 محتوای که برای این نام هشتگ نوشته شده رو نشونت میدم
 - #<نام هشتگ>: 
 دستورش دقیقا مثل بالایی عمل میکنه
 - /notes or /saved: لیست همه هشتگ های سیو شده داخل گپ



*فقط ادمینها:*
 - /save <محتوا> <نام هشتگ>:
 محتوایی که میخوای رو نگه میدارم تا وقتی که هشتگ رو کسی نوشت براش ارسال کنم ، توجه داشته باش هشگ بدون فاصلس 
 میدونم که نباید اینو بگم ولی همه که مثل تو باهوش نیستن😄
 - /save <نام هشتگ>: 
 پیامی که روش ریپلی بزنی رو به عنوان محتوا ذخیره میکنم!
 - /clear <نام هشتگ>: 
 هشتگ مورد نظر رو از بین میبرم!
"""

__mod_name__ = "هشتگ"

GET_HANDLER = CommandHandler("get", cmd_get, pass_args=True)
HASH_GET_HANDLER = RegexHandler(r"^#[^\s]+", hash_get)

SAVE_HANDLER = CommandHandler("save", save)
DELETE_HANDLER = CommandHandler("clear", clear, pass_args=True)

LIST_HANDLER = DisableAbleCommandHandler(["notes", "saved"], list_notes, admin_ok=True)

dispatcher.add_handler(GET_HANDLER)
dispatcher.add_handler(SAVE_HANDLER)
dispatcher.add_handler(LIST_HANDLER)
dispatcher.add_handler(DELETE_HANDLER)
dispatcher.add_handler(HASH_GET_HANDLER)
