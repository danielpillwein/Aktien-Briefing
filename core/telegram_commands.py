import asyncio
import os
import threading
from datetime import datetime
from html import escape
from typing import List, Tuple

from dotenv import load_dotenv
from loguru import logger
from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from core.briefing_agent import run_briefing_test
from core.scheduler import get_scheduler_status
from utils.notifications import (
    clear_chat_history_best_effort,
    register_message_id,
)
from utils.settings_repository import add_stock, load_settings_file, remove_stock
from utils.ticker_validator import (
    normalize_ticker,
    suggest_name_from_yfinance,
    validate_ticker_exists_yfinance,
    validate_ticker_syntax,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID_RAW = os.getenv("TELEGRAM_CHAT_ID", "")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN fehlt in .env!")


def _parse_allowed_chat_id(chat_id_raw: str) -> int:
    try:
        return int(str(chat_id_raw).strip())
    except Exception as exc:
        raise RuntimeError("TELEGRAM_CHAT_ID fehlt oder ist ungültig.") from exc


ALLOWED_CHAT_ID = _parse_allowed_chat_id(TELEGRAM_CHAT_ID_RAW)
_MANUAL_BRIEFING_LOCK = threading.Lock()
_MANUAL_BRIEFING_RUNNING = False
ADD_WAIT_TICKER, ADD_WAIT_NAME = range(2)
ADD_CONFIRM_KEYWORDS = {"ja", "ok", "okay", "bestätigen", "bestaetigen", "yes", "y"}


COMMAND_MENU = [
    BotCommand("help", "Zeigt alle verfügbaren Commands"),
    BotCommand("portfolio_add", "Aktie zum Portfolio hinzufügen"),
    BotCommand("portfolio_remove", "Aktie aus Portfolio entfernen"),
    BotCommand("watchlist_add", "Aktie zur Watchlist hinzufügen"),
    BotCommand("watchlist_remove", "Aktie aus Watchlist entfernen"),
    BotCommand("portfolio_list", "Zeigt Portfolio"),
    BotCommand("watchlist_list", "Zeigt Watchlist"),
    BotCommand("briefing_now", "Startet sofort ein Briefing"),
    BotCommand("next_run", "Zeigt nächsten Versandzeitpunkt"),
    BotCommand("scheduler_status", "Zeigt Scheduler-Status"),
    BotCommand("clear_chat", "Löscht Chat-Nachrichten (best effort)"),
]


def _is_authorized(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and int(chat.id) == ALLOWED_CHAT_ID)


async def _reply_and_track(update: Update, text: str) -> None:
    if not update.message:
        return
    msg = await update.message.reply_text(text)
    if msg:
        register_message_id(msg.message_id)


async def _reply_and_track_html(update: Update, text: str) -> None:
    if not update.message:
        return
    msg = await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    if msg:
        register_message_id(msg.message_id)


async def _reply_not_authorized(update: Update) -> None:
    await _reply_and_track_html(update, "⛔ <b>Nicht berechtigt</b>")


def parse_add_args(args: List[str]) -> Tuple[str, str]:
    if len(args) < 2:
        raise ValueError("Usage: /<command> <TICKER> <NAME>")
    ticker = normalize_ticker(args[0])
    name = " ".join(args[1:]).strip()
    if not ticker or not name:
        raise ValueError("Usage: /<command> <TICKER> <NAME>")
    return ticker, name


def parse_remove_args(args: List[str]) -> str:
    if len(args) != 1:
        raise ValueError("Usage: /<command> <TICKER>")
    ticker = normalize_ticker(args[0])
    if not ticker:
        raise ValueError("Usage: /<command> <TICKER>")
    return ticker


def _list_label(list_name: str) -> str:
    if list_name == "portfolio":
        return "📈 Portfolio"
    if list_name == "watchlist":
        return "👀 Watchlist"
    return escape(list_name)


def _format_usage_error(title: str, usage: str) -> str:
    return "\n".join(
        [
            f"⚠️ <b>{escape(title)}</b>",
            f"Syntax: <code>{escape(usage)}</code>",
        ]
    )


def _format_validation_error(message: str) -> str:
    return "\n".join(
        [
            "⚠️ <b>Eingabe ungültig</b>",
            escape(message),
        ]
    )


def _format_add_success(result: dict) -> str:
    target = _list_label(result.get("list_name", ""))
    ticker = escape(str(result.get("ticker", "")))
    name = escape(str(result.get("name", "")))
    return "\n".join(
        [
            "✅ <b>Aktie hinzugefügt</b>",
            f"Ziel: {target}",
            f"Wert: {ticker} - {name}",
        ]
    )


def _format_remove_success(result: dict) -> str:
    target = _list_label(result.get("list_name", ""))
    ticker = escape(str(result.get("ticker", "")))
    name = escape(str(result.get("name", "")))
    return "\n".join(
        [
            "✅ <b>Aktie entfernt</b>",
            f"Quelle: {target}",
            f"Wert: {ticker} - {name}",
        ]
    )


def _format_storage_error() -> str:
    return "❌ <b>Fehler beim Speichern der Änderung</b>"


def _format_list(items: list, title: str, emoji: str, highlight_ticker: str = "") -> str:
    heading = f"{emoji} <b>{escape(title)} (Ticker - Name)</b>"
    if not items:
        return f"{heading}\nKeine Einträge."
    lines = [heading]
    for idx, item in enumerate(items, start=1):
        ticker_raw = str(item.get("ticker", ""))
        ticker = escape(ticker_raw)
        name = escape(str(item.get("name", "")))
        marker = " 🆕" if highlight_ticker and ticker_raw.upper() == highlight_ticker.upper() else ""
        lines.append(f"{idx}. {ticker} - {name}{marker}")
    return "\n".join(lines)


def _help_text() -> str:
    return "\n".join(
        [
            "🧭 <b>Command-Hilfe</b>",
            "",
            "📈 <b>Portfolio hinzufügen</b>",
            "<code>/portfolio_add</code>",
            "Startet den Dialog: zuerst Ticker, dann Name (Vorschlag aus yfinance).",
            "",
            "📉 <b>Portfolio entfernen</b>",
            "<code>/portfolio_remove &lt;TICKER&gt;</code>",
            "Entfernt eine Aktie aus dem Portfolio.",
            "",
            "👀 <b>Watchlist hinzufügen</b>",
            "<code>/watchlist_add</code>",
            "Startet den Dialog: zuerst Ticker, dann Name (Vorschlag aus yfinance).",
            "",
            "🗑️ <b>Watchlist entfernen</b>",
            "<code>/watchlist_remove &lt;TICKER&gt;</code>",
            "Entfernt eine Aktie aus der Watchlist.",
            "",
            "📋 <b>Portfolio anzeigen</b>",
            "<code>/portfolio_list</code>",
            "Zeigt alle Portfolio-Aktien (Ticker - Name).",
            "",
            "📝 <b>Watchlist anzeigen</b>",
            "<code>/watchlist_list</code>",
            "Zeigt alle Watchlist-Aktien (Ticker - Name).",
            "",
            "🚀 <b>Briefing sofort starten</b>",
            "<code>/briefing_now</code>",
            "Startet sofort ein manuelles Briefing.",
            "",
            "⏭️ <b>Nächsten Versand anzeigen</b>",
            "<code>/next_run</code>",
            "Zeigt Datum/Uhrzeit des nächsten geplanten Versands.",
            "",
            "⚙️ <b>Scheduler-Status</b>",
            "<code>/scheduler_status</code>",
            "Zeigt Status, Zeitzone und nächste Laufzeiten.",
            "",
            "🧹 <b>Chat bereinigen</b>",
            "<code>/clear_chat</code>",
            "Löscht Chat-Nachrichten best effort.",
        ]
    )


def _format_dt(value: str) -> str:
    if not value:
        return "unbekannt"
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%d.%m.%Y %H:%M Uhr")
    except Exception:
        return value


async def _handle_add(update: Update, context: ContextTypes.DEFAULT_TYPE, list_name: str, usage: str) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    try:
        ticker, name = parse_add_args(context.args)
    except ValueError:
        await _reply_and_track_html(
            update,
            _format_usage_error("Ungültige Parameter", usage),
        )
        return

    syntax_ok, syntax_error = validate_ticker_syntax(ticker)
    if not syntax_ok:
        await _reply_and_track_html(update, _format_validation_error(syntax_error))
        return

    exists_ok, exists_error = validate_ticker_exists_yfinance(ticker)
    if not exists_ok:
        await _reply_and_track_html(update, _format_validation_error(exists_error))
        return

    try:
        result = add_stock(list_name=list_name, ticker=ticker, name=name)
        await _reply_and_track_html(
            update,
            _format_add_success(result),
        )
    except ValueError as exc:
        await _reply_and_track_html(update, _format_validation_error(str(exc)))
    except Exception as exc:
        logger.exception(f"Fehler bei {list_name}_add: {exc}")
        await _reply_and_track_html(update, _format_storage_error())


async def _handle_remove(update: Update, context: ContextTypes.DEFAULT_TYPE, list_name: str, usage: str) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    try:
        ticker = parse_remove_args(context.args)
    except ValueError:
        await _reply_and_track_html(
            update,
            _format_usage_error("Ungültige Parameter", usage),
        )
        return

    try:
        result = remove_stock(list_name=list_name, ticker=ticker)
        settings = load_settings_file()
        title = "Portfolio" if result["list_name"] == "portfolio" else "Watchlist"
        emoji = "📈" if result["list_name"] == "portfolio" else "👀"
        await _reply_and_track_html(update, _format_list(settings.get(result["list_name"], []), title, emoji))
    except KeyError as exc:
        await _reply_and_track_html(update, _format_validation_error(str(exc)))
    except Exception as exc:
        logger.exception(f"Fehler bei {list_name}_remove: {exc}")
        await _reply_and_track_html(update, _format_storage_error())


async def portfolio_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    await _start_add_conversation(update, context, "portfolio")
    return ADD_WAIT_TICKER


async def watchlist_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    await _start_add_conversation(update, context, "watchlist")
    return ADD_WAIT_TICKER


async def portfolio_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_remove(update, context, "portfolio", "/portfolio_remove <TICKER>")


async def watchlist_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_remove(update, context, "watchlist", "/watchlist_remove <TICKER>")


def _clear_add_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("add_target_list", None)
    context.user_data.pop("add_ticker", None)
    context.user_data.pop("add_name_suggestion", None)


async def _start_add_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE, list_name: str) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    _clear_add_context(context)
    context.user_data["add_target_list"] = list_name
    target_label = _list_label(list_name)
    await _reply_and_track_html(
        update,
        "\n".join(
            [
                f"🧩 <b>{target_label} hinzufügen</b>",
                "Bitte sende jetzt den <b>Ticker</b> (z. B. <code>MSFT</code>).",
            ]
        ),
    )


async def add_receive_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    if not update.message or not update.message.text:
        await _reply_and_track_html(update, _format_validation_error("Bitte sende einen Ticker als Text."))
        return ADD_WAIT_TICKER

    ticker = normalize_ticker(update.message.text.split()[0])

    syntax_ok, syntax_error = validate_ticker_syntax(ticker)
    if not syntax_ok:
        await _reply_and_track_html(update, _format_validation_error(syntax_error))
        await _reply_and_track_html(update, "Bitte sende einen gültigen Ticker.")
        return ADD_WAIT_TICKER

    exists_ok, exists_error = validate_ticker_exists_yfinance(ticker)
    if not exists_ok:
        await _reply_and_track_html(update, _format_validation_error(exists_error))
        await _reply_and_track_html(update, "Bitte sende einen anderen Ticker.")
        return ADD_WAIT_TICKER

    suggested_name = suggest_name_from_yfinance(ticker)
    context.user_data["add_ticker"] = ticker
    context.user_data["add_name_suggestion"] = suggested_name

    await _reply_and_track_html(
        update,
        "\n".join(
            [
                "✅ <b>Ticker geprüft</b>",
                f"Ticker: <b>{escape(ticker)}</b>",
                f"Vorschlag: <b>{escape(suggested_name)}</b>",
                "Sende jetzt den gewünschten <b>Namen</b> oder antworte mit <code>ja</code>, um den Vorschlag zu übernehmen.",
            ]
        ),
    )
    return ADD_WAIT_NAME


async def add_receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    if not update.message or not update.message.text:
        await _reply_and_track_html(update, _format_validation_error("Bitte sende einen Namen als Text."))
        return ADD_WAIT_NAME

    list_name = context.user_data.get("add_target_list", "")
    ticker = context.user_data.get("add_ticker", "")
    suggested_name = context.user_data.get("add_name_suggestion", ticker)

    if not list_name or not ticker:
        _clear_add_context(context)
        await _reply_and_track_html(update, "❌ <b>Dialogstatus verloren</b>\nBitte starte erneut mit /portfolio_add oder /watchlist_add.")
        return ConversationHandler.END

    raw_name = update.message.text.strip()
    if raw_name.lower() in ADD_CONFIRM_KEYWORDS:
        name = suggested_name
    else:
        name = raw_name

    if not name:
        await _reply_and_track_html(update, _format_validation_error("Name darf nicht leer sein."))
        return ADD_WAIT_NAME

    try:
        result = add_stock(list_name=list_name, ticker=ticker, name=name)
        settings = load_settings_file()
        title = "Portfolio" if result["list_name"] == "portfolio" else "Watchlist"
        emoji = "📈" if result["list_name"] == "portfolio" else "👀"
        await _reply_and_track_html(
            update,
            _format_list(
                settings.get(result["list_name"], []),
                title,
                emoji,
                highlight_ticker=result["ticker"],
            ),
        )
    except ValueError as exc:
        await _reply_and_track_html(update, _format_validation_error(str(exc)))
    except Exception as exc:
        logger.exception(f"Fehler bei {list_name}_add: {exc}")
        await _reply_and_track_html(update, _format_storage_error())
    finally:
        _clear_add_context(context)

    return ConversationHandler.END


async def add_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    _clear_add_context(context)
    await _reply_and_track_html(update, "🛑 <b>Hinzufügen abgebrochen</b>")
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return
    await _reply_and_track_html(update, _help_text())


async def portfolio_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return
    settings = load_settings_file()
    await _reply_and_track_html(update, _format_list(settings.get("portfolio", []), "Portfolio", "📈"))


async def watchlist_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return
    settings = load_settings_file()
    await _reply_and_track_html(update, _format_list(settings.get("watchlist", []), "Watchlist", "👀"))


def _set_manual_briefing_running(value: bool) -> None:
    global _MANUAL_BRIEFING_RUNNING
    with _MANUAL_BRIEFING_LOCK:
        _MANUAL_BRIEFING_RUNNING = value


def _is_manual_briefing_running() -> bool:
    with _MANUAL_BRIEFING_LOCK:
        return _MANUAL_BRIEFING_RUNNING


async def _run_manual_briefing_job(bot, chat_id: int):
    _set_manual_briefing_running(True)
    try:
        await asyncio.to_thread(run_briefing_test, True)
        msg = await bot.send_message(chat_id=chat_id, text="✅ Manuelles Briefing abgeschlossen.")
        register_message_id(msg.message_id)
    except Exception as exc:
        logger.exception(f"Fehler bei /briefing_now: {exc}")
        msg = await bot.send_message(chat_id=chat_id, text="❌ Fehler beim manuellen Briefing.")
        register_message_id(msg.message_id)
    finally:
        _set_manual_briefing_running(False)


async def briefing_now_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    if _is_manual_briefing_running():
        await _reply_and_track(update, "Ein manuelles Briefing läuft bereits.")
        return

    await _reply_and_track(update, "🚀 Starte manuelles Briefing...")
    chat_id = int(update.effective_chat.id)
    context.application.create_task(_run_manual_briefing_job(context.bot, chat_id))


async def next_run_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    status = get_scheduler_status()
    if not status.get("running"):
        await _reply_and_track_html(update, "⏭️ <b>Nächster Versand</b>\n🔴 Scheduler ist nicht aktiv.")
        return

    next_send = _format_dt(status.get("next_send_run"))
    timezone = escape(status.get("timezone") or "unbekannt")
    await _reply_and_track_html(
        update,
        "\n".join(
            [
                "⏭️ <b>Nächster Versand</b>",
                f"🕒 {next_send}",
                f"🌍 {timezone}",
            ]
        ),
    )


async def scheduler_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    status = get_scheduler_status()
    running = bool(status.get("running"))
    running_text = "🟢 Aktiv" if running else "🔴 Inaktiv"
    timezone = escape(str(status.get("timezone") or "unbekannt"))
    configured_send_time = escape(str(status.get("configured_send_time") or "unbekannt"))
    next_prepare = _format_dt(status.get("next_prepare_run"))
    next_send = _format_dt(status.get("next_send_run"))

    text = "\n".join(
        [
            "⚙️ <b>Scheduler-Status</b>",
            f"{running_text}",
            f"🌍 Zeitzone: {timezone}",
            f"⏰ Geplante Versandzeit: {configured_send_time} Uhr",
            f"🧠 Nächste Vorbereitung: {next_prepare}",
            f"📤 Nächster Versand: {next_send}",
        ]
    )
    await _reply_and_track_html(update, text)


async def clear_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return
    if not update.message or not update.effective_chat:
        return

    chat_id = str(update.effective_chat.id)
    from_message_id = int(update.message.message_id)
    result = await asyncio.to_thread(
        clear_chat_history_best_effort,
        chat_id,
        from_message_id,
        5000,
        60,
    )
    await _reply_and_track(
        update,
        f"🧹 Chat bereinigt (best effort). Gelöscht: {result['deleted']}, Fehlgeschlagen: {result['failed']}",
    )


async def _post_init(application: Application) -> None:
    await application.bot.set_my_commands(COMMAND_MENU)


def build_command_application() -> Application:
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("help", help_command))
    add_flow_handler = ConversationHandler(
        entry_points=[
            CommandHandler("portfolio_add", portfolio_add_command),
            CommandHandler("watchlist_add", watchlist_add_command),
        ],
        states={
            ADD_WAIT_TICKER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_receive_ticker)],
            ADD_WAIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_receive_name)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel_command)],
        allow_reentry=True,
    )
    app.add_handler(add_flow_handler)
    app.add_handler(CommandHandler("portfolio_remove", portfolio_remove_command))
    app.add_handler(CommandHandler("watchlist_remove", watchlist_remove_command))
    app.add_handler(CommandHandler("portfolio_list", portfolio_list_command))
    app.add_handler(CommandHandler("watchlist_list", watchlist_list_command))
    app.add_handler(CommandHandler("briefing_now", briefing_now_command))
    app.add_handler(CommandHandler("next_run", next_run_command))
    app.add_handler(CommandHandler("scheduler_status", scheduler_status_command))
    app.add_handler(CommandHandler("clear_chat", clear_chat_command))
    return app


def run_command_listener_polling() -> None:
    logger.info("🤖 Starte Telegram Command-Listener...")
    app = build_command_application()
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
