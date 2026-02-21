import asyncio
import os
import threading
from typing import List, Tuple

from dotenv import load_dotenv
from loguru import logger
from telegram import BotCommand, Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from core.briefing_agent import run_briefing_test
from core.scheduler import get_scheduler_status
from utils.notifications import (
    clear_chat_history_best_effort,
    register_message_id,
)
from utils.settings_repository import add_stock, load_settings_file, remove_stock
from utils.ticker_validator import (
    normalize_ticker,
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


async def _reply_not_authorized(update: Update) -> None:
    await _reply_and_track(update, "Nicht berechtigt.")


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


def _format_list(items: list, title: str) -> str:
    if not items:
        return f"{title}: leer"
    lines = [f"{title}:"]
    for idx, item in enumerate(items, start=1):
        lines.append(f"{idx}. {item.get('ticker', '')} - {item.get('name', '')}")
    return "\n".join(lines)


def _help_text() -> str:
    return "\n".join(
        [
            "Verfügbare Commands:",
            "/portfolio_add <TICKER> <NAME>",
            "/portfolio_remove <TICKER>",
            "/watchlist_add <TICKER> <NAME>",
            "/watchlist_remove <TICKER>",
            "/portfolio_list",
            "/watchlist_list",
            "/briefing_now",
            "/next_run",
            "/scheduler_status",
            "/clear_chat",
        ]
    )


async def _handle_add(update: Update, context: ContextTypes.DEFAULT_TYPE, list_name: str, usage: str) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    try:
        ticker, name = parse_add_args(context.args)
    except ValueError:
        await _reply_and_track(update, usage)
        return

    syntax_ok, syntax_error = validate_ticker_syntax(ticker)
    if not syntax_ok:
        await _reply_and_track(update, syntax_error)
        return

    exists_ok, exists_error = validate_ticker_exists_yfinance(ticker)
    if not exists_ok:
        await _reply_and_track(update, exists_error)
        return

    try:
        result = add_stock(list_name=list_name, ticker=ticker, name=name)
        await _reply_and_track(
            update,
            f"✅ {result['ticker']} ({result['name']}) zu {result['list_name']} hinzugefügt.",
        )
    except ValueError as exc:
        await _reply_and_track(update, str(exc))
    except Exception as exc:
        logger.exception(f"Fehler bei {list_name}_add: {exc}")
        await _reply_and_track(update, "Fehler beim Speichern der Änderung.")


async def _handle_remove(update: Update, context: ContextTypes.DEFAULT_TYPE, list_name: str, usage: str) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    try:
        ticker = parse_remove_args(context.args)
    except ValueError:
        await _reply_and_track(update, usage)
        return

    try:
        result = remove_stock(list_name=list_name, ticker=ticker)
        await _reply_and_track(
            update,
            f"✅ {result['ticker']} ({result['name']}) aus {result['list_name']} entfernt.",
        )
    except KeyError as exc:
        await _reply_and_track(update, str(exc))
    except Exception as exc:
        logger.exception(f"Fehler bei {list_name}_remove: {exc}")
        await _reply_and_track(update, "Fehler beim Speichern der Änderung.")


async def portfolio_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_add(update, context, "portfolio", "Usage: /portfolio_add <TICKER> <NAME>")


async def watchlist_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_add(update, context, "watchlist", "Usage: /watchlist_add <TICKER> <NAME>")


async def portfolio_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_remove(update, context, "portfolio", "Usage: /portfolio_remove <TICKER>")


async def watchlist_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_remove(update, context, "watchlist", "Usage: /watchlist_remove <TICKER>")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return
    await _reply_and_track(update, _help_text())


async def portfolio_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return
    settings = load_settings_file()
    await _reply_and_track(update, _format_list(settings.get("portfolio", []), "Portfolio"))


async def watchlist_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return
    settings = load_settings_file()
    await _reply_and_track(update, _format_list(settings.get("watchlist", []), "Watchlist"))


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
        await _reply_and_track(update, "Scheduler ist nicht aktiv.")
        return

    next_send = status.get("next_send_run") or "unbekannt"
    timezone = status.get("timezone") or "unbekannt"
    await _reply_and_track(update, f"Nächster Versand: {next_send} ({timezone})")


async def scheduler_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return

    status = get_scheduler_status()
    text = "\n".join(
        [
            f"running: {status.get('running')}",
            f"timezone: {status.get('timezone')}",
            f"configured_send_time: {status.get('configured_send_time')}",
            f"next_prepare_run: {status.get('next_prepare_run')}",
            f"next_send_run: {status.get('next_send_run')}",
        ]
    )
    await _reply_and_track(update, text)


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
    app.add_handler(CommandHandler("portfolio_add", portfolio_add_command))
    app.add_handler(CommandHandler("watchlist_add", watchlist_add_command))
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
