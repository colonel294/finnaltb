import html
from typing import Optional, List

from telegram import Message, Chat, Update, Bot, User
from telegram import ParseMode, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import MessageHandler, Filters, CommandHandler, run_async
from telegram.utils.helpers import mention_markdown, mention_html, escape_markdown

import tg_bot.modules.sql.welcome_sql as sql
from tg_bot import dispatcher, OWNER_ID, LOGGER
from tg_bot.modules.helper_funcs.chat_status import user_admin
from tg_bot.modules.helper_funcs.misc import build_keyboard, revert_buttons
from tg_bot.modules.helper_funcs.msg_types import get_welcome_type
from tg_bot.modules.helper_funcs.string_handling import markdown_parser, \
    escape_invalid_curly_brackets
from tg_bot.modules.log_channel import loggable

VALID_WELCOME_FORMATTERS = ['first', 'last', 'fullname', 'username', 'id', 'count', 'chatname', 'mention']

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


# do not async
def send(update, message, keyboard, backup_message):
    try:
        msg = update.effective_message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    except IndexError:
        msg = update.effective_message.reply_text(markdown_parser(backup_message +
                                                                  "\nنکته: پیغام فعلی  "
                                                                  "بخاطر مشکلات کد موشن قابل استفاده نیست "
                                                                  "ممکنه از قسمت اسم شخص باشه."),
                                                  parse_mode=ParseMode.MARKDOWN)
    except KeyError:
        msg = update.effective_message.reply_text(markdown_parser(backup_message +
                                                                  "\nنکته:پیغام فعلی "
                                                                  "بخاطر بد جایگذاری دستورات قابل استفاده نیس "
                                                                  "لطفا دوباره چک کن!"),
                                                  parse_mode=ParseMode.MARKDOWN)
    except BadRequest as excp:
        if excp.message == "Button_url_invalid":
            msg = update.effective_message.reply_text(markdown_parser(backup_message +
                                                                      "\nنکته : دکمه ایی که طراحی کردی  "
                                                                      "لینکش ایراد داره لطفا چک کن."),
                                                      parse_mode=ParseMode.MARKDOWN)
        elif excp.message == "Unsupported url protocol":
            msg = update.effective_message.reply_text(markdown_parser(backup_message +
                                                                      "\nنکته: دکمه ایی که طراحی کردی"
                                                                      "شامل لینکی هست که تلگرام  "
                                                                      "ساپورت نمیکنه،لطفا چک کن."),
                                                      parse_mode=ParseMode.MARKDOWN)
        elif excp.message == "Wrong url host":
            msg = update.effective_message.reply_text(markdown_parser(backup_message +
                                                                      "\nنکته: لینکی که وارد کردی خرابه. "
                                                                      "لطفا چک کن."),
                                                      parse_mode=ParseMode.MARKDOWN)
            LOGGER.warning(message)
            LOGGER.warning(keyboard)
            LOGGER.exception("Could not parse! got invalid url host errors")
        else:
            msg = update.effective_message.reply_text(markdown_parser(backup_message +
                                                                      "\nنکته : یه ارور ناشناخته ثبت شد برام "
                                                                      "لطفا دوباره چک کن."),
                                                      parse_mode=ParseMode.MARKDOWN)
            LOGGER.exception()

    return msg


@run_async
def new_member(bot: Bot, update: Update):
    chat = update.effective_chat  # type: Optional[Chat]

    should_welc, cust_welcome, welc_type = sql.get_welc_pref(chat.id)
    if should_welc:
        sent = None
        new_members = update.effective_message.new_chat_members
        for new_mem in new_members:
            # Give the owner a special welcome
            if new_mem.id == OWNER_ID:
                update.effective_message.reply_text("امپراطور وارد میشود ،احترام بگذارید😍😚")
                continue

            # Don't welcome yourself
            elif new_mem.id == bot.id:
                continue

            else:
                # If welcome message is media, send with appropriate function
                if welc_type != sql.Types.TEXT and welc_type != sql.Types.BUTTON_TEXT:
                    ENUM_FUNC_MAP[welc_type](chat.id, cust_welcome)
                    return
                # else, move on
                first_name = new_mem.first_name or "PersonWithNoName"  # edge case of empty name - occurs for some bugs.

                if cust_welcome:
                    if new_mem.last_name:
                        fullname = "{} {}".format(first_name, new_mem.last_name)
                    else:
                        fullname = first_name
                    count = chat.get_members_count()
                    mention = mention_markdown(new_mem.id, first_name)
                    if new_mem.username:
                        username = "@" + escape_markdown(new_mem.username)
                    else:
                        username = mention

                    valid_format = escape_invalid_curly_brackets(cust_welcome, VALID_WELCOME_FORMATTERS)
                    res = valid_format.format(first=escape_markdown(first_name),
                                              last=escape_markdown(new_mem.last_name or first_name),
                                              fullname=escape_markdown(fullname), username=username, mention=mention,
                                              count=count, chatname=escape_markdown(chat.title), id=new_mem.id)
                    buttons = sql.get_welc_buttons(chat.id)
                    keyb = build_keyboard(buttons)
                else:
                    res = sql.DEFAULT_WELCOME.format(first=first_name)
                    keyb = []

                keyboard = InlineKeyboardMarkup(keyb)

                sent = send(update, res, keyboard,
                            sql.DEFAULT_WELCOME.format(first=first_name))  # type: Optional[Message]

        prev_welc = sql.get_clean_pref(chat.id)
        if prev_welc:
            try:
                bot.delete_message(chat.id, prev_welc)
            except BadRequest as excp:
                pass

            if sent:
                sql.set_clean_welcome(chat.id, sent.message_id)


@run_async
def left_member(bot: Bot, update: Update):
    chat = update.effective_chat  # type: Optional[Chat]
    should_goodbye, cust_goodbye, goodbye_type = sql.get_gdbye_pref(chat.id)
    if should_goodbye:
        left_mem = update.effective_message.left_chat_member
        if left_mem:
            # Ignore bot being kicked
            if left_mem.id == bot.id:
                return

            # Give the owner a special goodbye
            if left_mem.id == OWNER_ID:
                update.effective_message.reply_text("☹️😢عشقم خدافظ")
                return

            # if media goodbye, use appropriate function for it
            if goodbye_type != sql.Types.TEXT and goodbye_type != sql.Types.BUTTON_TEXT:
                ENUM_FUNC_MAP[goodbye_type](chat.id, cust_goodbye)
                return

            first_name = left_mem.first_name or "PersonWithNoName"  # edge case of empty name - occurs for some bugs.
            if cust_goodbye:
                if left_mem.last_name:
                    fullname = "{} {}".format(first_name, left_mem.last_name)
                else:
                    fullname = first_name
                count = chat.get_members_count()
                mention = mention_markdown(left_mem.id, first_name)
                if left_mem.username:
                    username = "@" + escape_markdown(left_mem.username)
                else:
                    username = mention

                valid_format = escape_invalid_curly_brackets(cust_goodbye, VALID_WELCOME_FORMATTERS)
                res = valid_format.format(first=escape_markdown(first_name),
                                          last=escape_markdown(left_mem.last_name or first_name),
                                          fullname=escape_markdown(fullname), username=username, mention=mention,
                                          count=count, chatname=escape_markdown(chat.title), id=left_mem.id)
                buttons = sql.get_gdbye_buttons(chat.id)
                keyb = build_keyboard(buttons)

            else:
                res = sql.DEFAULT_GOODBYE
                keyb = []

            keyboard = InlineKeyboardMarkup(keyb)

            send(update, res, keyboard, sql.DEFAULT_GOODBYE)


@run_async
@user_admin
def welcome(bot: Bot, update: Update, args: List[str]):
    chat = update.effective_chat  # type: Optional[Chat]
    # if no args, show current replies.
    if len(args) == 0 or args[0].lower() == "noformat":
        noformat = args and args[0].lower() == "noformat"
        pref, welcome_m, welcome_type = sql.get_welc_pref(chat.id)
        update.effective_message.reply_text(
            "پیام خوش آمد این گروه تنظیم شده به: `{}`.\n*پیام خوش آمد "
            "({{}}):*".format(pref),
            parse_mode=ParseMode.MARKDOWN)

        if welcome_type == sql.Types.BUTTON_TEXT:
            buttons = sql.get_welc_buttons(chat.id)
            if noformat:
                welcome_m += revert_buttons(buttons)
                update.effective_message.reply_text(welcome_m)

            else:
                keyb = build_keyboard(buttons)
                keyboard = InlineKeyboardMarkup(keyb)

                send(update, welcome_m, keyboard, sql.DEFAULT_WELCOME)

        else:
            if noformat:
                ENUM_FUNC_MAP[welcome_type](chat.id, welcome_m)

            else:
                ENUM_FUNC_MAP[welcome_type](chat.id, welcome_m, parse_mode=ParseMode.MARKDOWN)

    elif len(args) >= 1:
        if args[0].lower() in ("on", "yes"):
            sql.set_welc_preference(str(chat.id), True)
            update.effective_message.reply_text("آبرو داری میکنم!")

        elif args[0].lower() in ("خاموش", "سکوت"):
            sql.set_welc_preference(str(chat.id), False)
            update.effective_message.reply_text("باعش . دیگه به هیشکی سلام نموکونم")

        else:
            # idek what you're writing, say yes or no
            update.effective_message.reply_text("تو این مورد من فقط off/no یا on/yes رو میفهمم!")


@run_async
@user_admin
def goodbye(bot: Bot, update: Update, args: List[str]):
    chat = update.effective_chat  # type: Optional[Chat]

    if len(args) == 0 or args[0] == "noformat":
        noformat = args and args[0] == "noformat"
        pref, goodbye_m, goodbye_type = sql.get_gdbye_pref(chat.id)
        update.effective_message.reply_text(
            "پیام خدافظی این گپ تنظیم شده به: `{}`.\n*پیام خدافظی "
            "({{}}) :*".format(pref),
            parse_mode=ParseMode.MARKDOWN)

        if goodbye_type == sql.Types.BUTTON_TEXT:
            buttons = sql.get_gdbye_buttons(chat.id)
            if noformat:
                goodbye_m += revert_buttons(buttons)
                update.effective_message.reply_text(goodbye_m)

            else:
                keyb = build_keyboard(buttons)
                keyboard = InlineKeyboardMarkup(keyb)

                send(update, goodbye_m, keyboard, sql.DEFAULT_GOODBYE)

        else:
            if noformat:
                ENUM_FUNC_MAP[goodbye_type](chat.id, goodbye_m)

            else:
                ENUM_FUNC_MAP[goodbye_type](chat.id, goodbye_m, parse_mode=ParseMode.MARKDOWN)

    elif len(args) >= 1:
        if args[0].lower() in ("on", "yes"):
            sql.set_gdbye_preference(str(chat.id), True)
            update.effective_message.reply_text("وقتی برن ناراحت میشم🥺")

        elif args[0].lower() in ("off", "no"):
            sql.set_gdbye_preference(str(chat.id), False)
            update.effective_message.reply_text("اگه برن شیرمو حلالشون نمیکنم.")

        else:
            # idek what you're writing, say yes or no
            update.effective_message.reply_text("تو این مورد من فقط off/no یا on/yes رو میفهمم!")


@run_async
@user_admin
@loggable
def set_welcome(bot: Bot, update: Update) -> str:
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    msg = update.effective_message  # type: Optional[Message]

    text, data_type, content, buttons = get_welcome_type(msg)

    if data_type is None:
        msg.reply_text("برام مشخص کن چی بهشون بگم خو.")
        return ""

    sql.set_custom_welcome(chat.id, content or text, data_type, buttons)
    msg.reply_text("پیام خاص برای افراد خااص ،تنظیم شد!")

    return "<b>{}:</b>" \
           "\n#SET_WELCOME" \
           "\n<b>Admin:</b> {}" \
           "\nSet the welcome message.".format(html.escape(chat.title),
                                               mention_html(user.id, user.first_name))


@run_async
@user_admin
@loggable
def reset_welcome(bot: Bot, update: Update) -> str:
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    sql.set_custom_welcome(chat.id, sql.DEFAULT_WELCOME, sql.Types.TEXT)
    update.effective_message.reply_text("پیام خوش آمد به اون چیزی که من میخوام بگم تغیر کرد!")
    return "<b>{}:</b>" \
           "\n#RESET_WELCOME" \
           "\n<b>Admin:</b> {}" \
           "\nReset the welcome message to default.".format(html.escape(chat.title),
                                                            mention_html(user.id, user.first_name))


@run_async
@user_admin
@loggable
def set_goodbye(bot: Bot, update: Update) -> str:
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    msg = update.effective_message  # type: Optional[Message]
    text, data_type, content, buttons = get_welcome_type(msg)

    if data_type is None:
        msg.reply_text("برام مشخص کن چی بهشون بگم خو.")
        return ""

    sql.set_custom_gdbye(chat.id, content or text, data_type, buttons)
    msg.reply_text("بخان برن یه خدافظی مشتی باشون میکنم!")
    return "<b>{}:</b>" \
           "\n#SET_GOODBYE" \
           "\n<b>Admin:</b> {}" \
           "\nSet the goodbye message.".format(html.escape(chat.title),
                                               mention_html(user.id, user.first_name))


@run_async
@user_admin
@loggable
def reset_goodbye(bot: Bot, update: Update) -> str:
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    sql.set_custom_gdbye(chat.id, sql.DEFAULT_GOODBYE, sql.Types.TEXT)
    update.effective_message.reply_text("پیام خدافظی با خودمه الان!")
    return "<b>{}:</b>" \
           "\n#RESET_GOODBYE" \
           "\n<b>Admin:</b> {}" \
           "\nReset the goodbye message.".format(html.escape(chat.title),
                                                 mention_html(user.id, user.first_name))


@run_async
@user_admin
@loggable
def clean_welcome(bot: Bot, update: Update, args: List[str]) -> str:
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]

    if not args:
        clean_pref = sql.get_clean_pref(chat.id)
        if clean_pref:
            update.effective_message.reply_text("بهتره من پیامای خوشآمد دو روز پیشو پاک کنم.")
        else:
            update.effective_message.reply_text("من در حال حاضر خوش آمد ها رو پاک نمیکنم")
        return ""

    if args[0].lower() in ("on", "yes"):
        sql.set_clean_welcome(str(chat.id), True)
        update.effective_message.reply_text("باش من سعی میکنم پیامای خوش آمد قدیمی تر رو پاک کنم")
        return "<b>{}:</b>" \
               "\n#CLEAN_WELCOME" \
               "\n<b>Admin:</b> {}" \
               "\nHas toggled clean welcomes to <code>ON</code>.".format(html.escape(chat.title),
                                                                         mention_html(user.id, user.first_name))
    elif args[0].lower() in ("off", "no"):
        sql.set_clean_welcome(str(chat.id), False)
        update.effective_message.reply_text("اوکی من پیامای خوش آمد رو پاک نمیکنم.")
        return "<b>{}:</b>" \
               "\n#CLEAN_WELCOME" \
               "\n<b>Admin:</b> {}" \
               "\nHas toggled clean welcomes to <code>OFF</code>.".format(html.escape(chat.title),
                                                                          mention_html(user.id, user.first_name))
    else:
        # idek what you're writing, say yes or no
        update.effective_message.reply_text("تو این مورد من فقط off/no یا on/yes رو میفهمم!")
        return ""


WELC_HELP_TXT = "من برای خوش آمد گویی آپشن هام زیاده . چون بنظرم بخش مهمیه. خوب " \
                " اگه میخوای یه پیام خوش آمد خاص برای ممبرات تعریف کنی زینا میتونی کمک بگیری:\n" \
                " - `{{first}}`: این اسم اول کاربری که اضافه میشه رو تو متن خوش آمد مینویسه\n" \
                " - `{{last}}`: این هم فامیلی یا اسم دوم کاربر رو اضافه میکنه ! " \
                "اگه اسم دوم نداشته باشه . اسم اول انتخاب میشه!.\n" \
                " - `{{fullname}}`: این هم اسم کامل شخص اعم از اول و دومش رو اضافه میکنه " \
                ".\n" \
                " - `{{username}}`: ... آیدی کاربر رو اضافه میکنه!!" \
                "اگه آیدی نداشته باشه اسم اول.\n" \
                " - `{{mention}}`: یه نوع اشاره گر که اسم اول کاربر رو تگ میزنه!.\n" \
                " - `{{id}}`: آیدی عددی <زیاد کاربردی نیس> کاربر رو اضافه میکنه\n" \
                " - `{{count}}`: اشاره میکنه که کاربر چندمین عضو گپه!.\n" \
                " - `{{chatname}}`: نام گپ رو اضافه میکنه.\n" \
                "\nهمه این نشانک ها باید داخل علامت `{{}}` باشن تا درست کار کنن.\n" \
                "من حتی از کلید های لینک دار هم ساپورت میکنم " \
                "برای جذابیت گپ.\n" \
                "برای استفاده از کلید قوانین میتونید از این استفاده کنید: `[قوانین](buttonurl://t.me/{}?start=group_id)`. " \
                "فقط کافیه به جای group_id آیدی عددی گپ رو بزارید که این کار بادستور /id داخل گپ نمایش داده میشه " \
                "و دیگه تموم . یا اصلی میتونی به جای کل اون لینک . لینک چنلتو بزاری  " \
                "\n" \
                "حتی اگه خوشت بیاد میتونی برای کساین که میان گیف . استیکر یا حتی عکس و ویس بفرستی " \
                "فقط کافیه رو اون رسانه ریپلی بزنی و از دستور /setwelcome استفاده کنی.".format(dispatcher.bot.username)


@run_async
@user_admin
def welcome_help(bot: Bot, update: Update):
    update.effective_message.reply_text(WELC_HELP_TXT, parse_mode=ParseMode.MARKDOWN)


# TODO: get welcome data from group butler snap
# def __import_data__(chat_id, data):
#     welcome = data.get('info', {}).get('rules')
#     welcome = welcome.replace('$username', '{username}')
#     welcome = welcome.replace('$name', '{fullname}')
#     welcome = welcome.replace('$id', '{id}')
#     welcome = welcome.replace('$title', '{chatname}')
#     welcome = welcome.replace('$surname', '{lastname}')
#     welcome = welcome.replace('$rules', '{rules}')
#     sql.set_custom_welcome(chat_id, welcome, sql.Types.TEXT)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    welcome_pref, _, _ = sql.get_welc_pref(chat_id)
    goodbye_pref, _, _ = sql.get_gdbye_pref(chat_id)
    return "گپ شما پیام خوش آمدش تنظیم شده به: `{}`.\n" \
           "و پیام خدافظیش: `{}`.".format(welcome_pref, goodbye_pref)


__help__ = """

*فقط ادمینها:*
 - /welcome <on/off>: حالت خوش آمد رو خاموش یا روشن میکنم.
 - /welcome: تنضیمات خوش آمد رو در حال حاضر میگم .
 
 - /goodbye -> تنضیمات خدافظی رو میگم.
 - /setwelcome <متن>:
 یه پیام خوش آمد شخصی و خاص رو که برام نوشتی نشون میدم . اگه میخوای رسانه بفرستم . روش ریپلی کن.
 - /setgoodbye <متن>: 
 یه چیز مثل همون تنظیم خوش آمد ولی اینبار برای خدافظی.
 - /resetwelcome: بازگشت به پیام خوش آمد اصلیم.
 - /resetgoodbye: بازگشت به پیام خدافظی اصلیم.
 - /cleanwelcome <on/off>: وقتی ممبر جدید میاد . من سعی میکنم خوشآمد ممبر قبلی رو پاک کنم.

 - /welcomehelp: اطلاعات بیشتر راجب قابلیت های بیشتر من برای خوش آمد گویی.
"""

__mod_name__ = "سلام علیک"

NEW_MEM_HANDLER = MessageHandler(Filters.status_update.new_chat_members, new_member)
LEFT_MEM_HANDLER = MessageHandler(Filters.status_update.left_chat_member, left_member)
WELC_PREF_HANDLER = CommandHandler("خوش_آمد", welcome, pass_args=True, filters=Filters.group)
GOODBYE_PREF_HANDLER = CommandHandler("goodbye", goodbye, pass_args=True, filters=Filters.group)
SET_WELCOME = CommandHandler("setwelcome", set_welcome, filters=Filters.group)
SET_GOODBYE = CommandHandler("setgoodbye", set_goodbye, filters=Filters.group)
RESET_WELCOME = CommandHandler("resetwelcome", reset_welcome, filters=Filters.group)
RESET_GOODBYE = CommandHandler("resetgoodbye", reset_goodbye, filters=Filters.group)
CLEAN_WELCOME = CommandHandler("cleanwelcome", clean_welcome, pass_args=True, filters=Filters.group)
WELCOME_HELP = CommandHandler("welcomehelp", welcome_help)

dispatcher.add_handler(NEW_MEM_HANDLER)
dispatcher.add_handler(LEFT_MEM_HANDLER)
dispatcher.add_handler(WELC_PREF_HANDLER)
dispatcher.add_handler(GOODBYE_PREF_HANDLER)
dispatcher.add_handler(SET_WELCOME)
dispatcher.add_handler(SET_GOODBYE)
dispatcher.add_handler(RESET_WELCOME)
dispatcher.add_handler(RESET_GOODBYE)
dispatcher.add_handler(CLEAN_WELCOME)
dispatcher.add_handler(WELCOME_HELP)
