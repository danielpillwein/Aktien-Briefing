import asyncio
import os
import threading
from datetime import datetime
from html import escape
from typing import List, Tuple

from dotenv import load_dotenv
from loguru import logger
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
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
    search_ticker_candidates,
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
ADD_WAIT_COMPANY, ADD_WAIT_SELECTION, ADD_WAIT_MANUAL_TICKER, ADD_WAIT_MANUAL_NAME, REMOVE_WAIT_SELECTION = range(5)
ADD_CONFIRM_KEYWORDS = {"ja", "ok", "okay", "bestätigen", "bestaetigen", "yes", "y"}
ADD_SELECTION_CALLBACK_PREFIX = "addsel"
MANUAL_NAME_CALLBACK_PREFIX = "addname"
REMOVE_SELECTION_CALLBACK_PREFIX = "remsel"


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


def _reply_target_message(update: Update):
    if update.message:
        return update.message
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message
    return None


async def _reply_and_track(update: Update, text: str) -> None:
    target = _reply_target_message(update)
    if not target:
        return
    msg = await target.reply_text(text)
    if msg:
        register_message_id(msg.message_id)


async def _reply_and_track_html(update: Update, text: str, reply_markup=None) -> None:
    target = _reply_target_message(update)
    if not target:
        return
    msg = await target.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
    if msg:
        register_message_id(msg.message_id)


async def _reply_not_authorized(update: Update) -> None:
    await _reply_and_track_html(update, "⛔ <b>Nicht berechtigt</b>")


async def track_incoming_message_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    try:
        if int(update.effective_chat.id) != ALLOWED_CHAT_ID:
            return
        register_message_id(int(update.message.message_id))
    except Exception:
        # Tracking darf den Bot-Ablauf niemals blockieren.
        return


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
        line = f"{idx}. {ticker} - {name}"
        if highlight_ticker and ticker_raw.upper() == highlight_ticker.upper():
            line = f"<i>🆕 {line}</i>"
        lines.append(line)
    return "\n".join(lines)


def _help_text() -> str:
    return "\n".join(
        [
            "🧭 <b>Command-Hilfe</b>",
            "",
            "📈 <b>Portfolio hinzufügen</b>",
            "<code>/portfolio_add</code>",
            "Startet den Dialog: Unternehmen eingeben, Vorschlag per Buttons wählen oder manuell hinzufügen.",
            "",
            "📉 <b>Portfolio entfernen</b>",
            "<code>/portfolio_remove</code>",
            "Startet den Dialog: Eintrag per Buttons auswählen und entfernen.",
            "",
            "👀 <b>Watchlist hinzufügen</b>",
            "<code>/watchlist_add</code>",
            "Startet den Dialog: Unternehmen eingeben, Vorschlag per Buttons wählen oder manuell hinzufügen.",
            "",
            "🗑️ <b>Watchlist entfernen</b>",
            "<code>/watchlist_remove</code>",
            "Startet den Dialog: Eintrag per Buttons auswählen und entfernen.",
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
    return ADD_WAIT_COMPANY


async def watchlist_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    await _start_add_conversation(update, context, "watchlist")
    return ADD_WAIT_COMPANY


async def portfolio_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    started = await _start_remove_conversation(update, context, "portfolio")
    if not started:
        return ConversationHandler.END
    return REMOVE_WAIT_SELECTION


async def watchlist_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    started = await _start_remove_conversation(update, context, "watchlist")
    if not started:
        return ConversationHandler.END
    return REMOVE_WAIT_SELECTION


def _clear_add_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("add_target_list", None)
    context.user_data.pop("add_company_query", None)
    context.user_data.pop("add_candidates", None)
    context.user_data.pop("add_selected_index", None)
    context.user_data.pop("add_ticker", None)
    context.user_data.pop("add_name_suggestion", None)


def _clear_remove_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("remove_target_list", None)
    context.user_data.pop("remove_items", None)
    context.user_data.pop("remove_selected_index", None)


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
                "Bitte sende den <b>Unternehmensnamen</b> (z. B. <code>Microsoft</code>).",
                "Alternativ: sende <code>manuell</code> oder <code>ganz andere</code>, um direkt mit einem Ticker weiterzumachen.",
            ]
        ),
    )


def _remove_selection_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬆️ Hoch", callback_data=f"{REMOVE_SELECTION_CALLBACK_PREFIX}:up"),
                InlineKeyboardButton("⬇️ Runter", callback_data=f"{REMOVE_SELECTION_CALLBACK_PREFIX}:down"),
            ],
            [
                InlineKeyboardButton("✅ Auswählen", callback_data=f"{REMOVE_SELECTION_CALLBACK_PREFIX}:pick"),
            ],
            [InlineKeyboardButton("🛑 Abbrechen", callback_data=f"{REMOVE_SELECTION_CALLBACK_PREFIX}:cancel")],
        ]
    )


def _manual_name_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Hinzufügen", callback_data=f"{MANUAL_NAME_CALLBACK_PREFIX}:use"),
                InlineKeyboardButton("✏️ Namen selbst festlegen", callback_data=f"{MANUAL_NAME_CALLBACK_PREFIX}:own"),
            ],
            [InlineKeyboardButton("🛑 Abbrechen", callback_data=f"{MANUAL_NAME_CALLBACK_PREFIX}:cancel")],
        ]
    )


def _format_remove_prompt(items: list, title: str, emoji: str, selected_index: int) -> str:
    selected_index = max(0, min(selected_index, max(0, len(items) - 1)))
    lines = [
        f"🗑️ <b>{escape(title)} entfernen</b>",
        f"{emoji} <b>{escape(title)} (Ticker - Name)</b>",
        "<i>Eintrag mit Buttons auswählen</i>",
        "",
    ]
    for idx, item in enumerate(items, start=1):
        ticker = escape(str(item.get("ticker", "")))
        name = escape(str(item.get("name", "")))
        marker = "👉" if (idx - 1) == selected_index else "  "
        lines.append(f"{marker} {_rank_emoji(idx)} <b>{idx}. {ticker}</b> - {name}")
    lines.extend(["", "Steuerung über Buttons: <b>Hoch</b>, <b>Runter</b>, <b>Auswählen</b>."])
    return "\n".join(lines)


async def _start_remove_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE, list_name: str) -> bool:
    _clear_remove_context(context)
    settings = load_settings_file()
    raw_items = settings.get(list_name, [])
    items = [x for x in raw_items if isinstance(x, dict)]

    title = "Portfolio" if list_name == "portfolio" else "Watchlist"
    emoji = "📈" if list_name == "portfolio" else "👀"
    if not items:
        await _reply_and_track_html(update, f"🗑️ <b>{title} entfernen</b>\nKeine Einträge vorhanden.")
        return False

    context.user_data["remove_target_list"] = list_name
    context.user_data["remove_items"] = items
    context.user_data["remove_selected_index"] = 0
    await _reply_and_track_html(
        update,
        _format_remove_prompt(items, title, emoji, selected_index=0),
        reply_markup=_remove_selection_keyboard(),
    )
    return True


def _rank_emoji(position: int) -> str:
    if position == 1:
        return "🥇"
    if position == 2:
        return "🥈"
    if position == 3:
        return "🥉"
    return "▫️"


def _add_selection_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬆️ Hoch", callback_data=f"{ADD_SELECTION_CALLBACK_PREFIX}:up"),
                InlineKeyboardButton("⬇️ Runter", callback_data=f"{ADD_SELECTION_CALLBACK_PREFIX}:down"),
            ],
            [
                InlineKeyboardButton("✅ Auswählen", callback_data=f"{ADD_SELECTION_CALLBACK_PREFIX}:pick"),
                InlineKeyboardButton("✍️ Manuell", callback_data=f"{ADD_SELECTION_CALLBACK_PREFIX}:manual"),
            ],
            [InlineKeyboardButton("🛑 Abbrechen", callback_data=f"{ADD_SELECTION_CALLBACK_PREFIX}:cancel")],
        ]
    )


def _format_candidate_options(company_query: str, candidates: list, selected_index: int) -> str:
    selected_index = max(0, min(selected_index, max(0, len(candidates) - 1)))
    lines = [
        f"🔎 <b>Aktienvorschläge für „{escape(company_query)}“</b>",
        "<i>Nach Relevanz sortiert</i>",
        "",
    ]
    for idx, c in enumerate(candidates, start=1):
        symbol = escape(str(c.get("symbol", "")))
        name = escape(str(c.get("name", "")))
        exchange = escape(str(c.get("exchange", "")))
        qtype = escape(str(c.get("type", "")))
        marker = "👉" if (idx - 1) == selected_index else "  "
        lines.append(f"{marker} {_rank_emoji(idx)} <b>{idx}. {symbol}</b> - {name}")
        meta_parts = []
        if exchange:
            meta_parts.append(f"Börse: {exchange}")
        if qtype:
            meta_parts.append(f"Typ: {qtype}")
        if meta_parts:
            lines.append(f"<i>{' | '.join(meta_parts)}</i>")
        lines.append("")
    lines.append("Steuerung über Buttons: <b>Hoch</b>, <b>Runter</b>, <b>Auswählen</b>.")
    return "\n".join(lines)


def _move_selection(current_index: int, direction: str, total: int) -> int:
    if total <= 0:
        return 0
    if direction == "up":
        return (current_index - 1) % total
    if direction == "down":
        return (current_index + 1) % total
    return current_index


def _wants_manual_flow(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    if normalized in {"manuell", "manual", "andere", "anders", "other", "0"}:
        return True
    return "manuell" in normalized or "ganz andere" in normalized


async def _finalize_add_and_show_list(update: Update, context: ContextTypes.DEFAULT_TYPE, list_name: str, ticker: str, name: str) -> int:
    try:
        result = add_stock(list_name=list_name, ticker=ticker, name=name)
        await _reply_and_track_html(update, _format_add_success(result))
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


async def add_receive_company(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    if not update.message or not update.message.text:
        await _reply_and_track_html(update, _format_validation_error("Bitte sende einen Unternehmensnamen als Text."))
        return ADD_WAIT_COMPANY

    text = update.message.text.strip()
    if _wants_manual_flow(text):
        await _reply_and_track_html(
            update,
            "✍️ <b>Manuelles Hinzufügen</b>\nBitte sende jetzt den <b>Ticker</b> (z. B. <code>MSFT</code>).",
        )
        return ADD_WAIT_MANUAL_TICKER

    candidates = await asyncio.to_thread(search_ticker_candidates, text, 5)
    if not candidates:
        await _reply_and_track_html(
            update,
            "⚠️ <b>Keine passenden Aktien gefunden</b>\nSende einen anderen Unternehmensnamen oder antworte mit <code>manuell</code>.",
        )
        return ADD_WAIT_COMPANY

    context.user_data["add_company_query"] = text
    context.user_data["add_candidates"] = candidates
    context.user_data["add_selected_index"] = 0
    await _reply_and_track_html(
        update,
        _format_candidate_options(text, candidates, selected_index=0),
        reply_markup=_add_selection_keyboard(),
    )
    return ADD_WAIT_SELECTION


async def add_receive_selection_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()

    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END

    if not query:
        return ADD_WAIT_SELECTION

    list_name = context.user_data.get("add_target_list", "")
    company_query = context.user_data.get("add_company_query", "")
    candidates = context.user_data.get("add_candidates", [])
    if not list_name or not isinstance(candidates, list) or not candidates:
        _clear_add_context(context)
        await query.edit_message_text(
            "❌ <b>Dialogstatus verloren</b>\nBitte starte erneut mit /portfolio_add oder /watchlist_add.",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    selected_index = int(context.user_data.get("add_selected_index", 0))
    selected_index = max(0, min(selected_index, len(candidates) - 1))
    action = (query.data or "").split(":", 1)[-1]

    if action in {"up", "down"}:
        selected_index = _move_selection(selected_index, action, len(candidates))
        context.user_data["add_selected_index"] = selected_index
        await query.edit_message_text(
            _format_candidate_options(company_query, candidates, selected_index),
            parse_mode=ParseMode.HTML,
            reply_markup=_add_selection_keyboard(),
        )
        return ADD_WAIT_SELECTION

    if action == "manual":
        context.user_data["add_selected_index"] = selected_index
        await query.edit_message_reply_markup(reply_markup=None)
        await _reply_and_track_html(
            update,
            "✍️ <b>Manuelles Hinzufügen</b>\nBitte sende jetzt den <b>Ticker</b> (z. B. <code>MSFT</code>).",
        )
        return ADD_WAIT_MANUAL_TICKER

    if action == "cancel":
        _clear_add_context(context)
        await query.edit_message_text("🛑 <b>Hinzufügen abgebrochen</b>", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    if action != "pick":
        await query.answer("Unbekannte Aktion", show_alert=False)
        return ADD_WAIT_SELECTION

    await query.edit_message_reply_markup(reply_markup=None)
    selected = candidates[selected_index]
    ticker = normalize_ticker(str(selected.get("symbol", "")))
    name = str(selected.get("name", "")).strip() or ticker
    return await _finalize_add_and_show_list(update, context, list_name, ticker, name)


async def add_receive_selection_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    await _reply_and_track_html(
        update,
        "\n".join(
            [
                "👆 <b>Bitte nutze die Buttons</b> unter der Vorschlagsliste.",
                "Alternativ kannst du dort auf <b>Manuell</b> tippen.",
            ]
        )
    )
    return ADD_WAIT_SELECTION


async def add_receive_manual_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    if not update.message or not update.message.text:
        await _reply_and_track_html(update, _format_validation_error("Bitte sende einen Ticker als Text."))
        return ADD_WAIT_MANUAL_TICKER

    ticker = normalize_ticker(update.message.text.split()[0])
    syntax_ok, syntax_error = validate_ticker_syntax(ticker)
    if not syntax_ok:
        await _reply_and_track_html(update, _format_validation_error(syntax_error))
        return ADD_WAIT_MANUAL_TICKER

    exists_ok, exists_error = validate_ticker_exists_yfinance(ticker)
    if not exists_ok:
        await _reply_and_track_html(update, _format_validation_error(exists_error))
        return ADD_WAIT_MANUAL_TICKER

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
                "Wähle: <b>Hinzufügen</b> (mit Vorschlag) oder <b>Namen selbst festlegen</b>.",
            ]
        ),
        reply_markup=_manual_name_choice_keyboard(),
    )
    return ADD_WAIT_MANUAL_NAME


async def add_receive_manual_name_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()

    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    if not query:
        return ADD_WAIT_MANUAL_NAME

    list_name = context.user_data.get("add_target_list", "")
    ticker = context.user_data.get("add_ticker", "")
    suggested_name = context.user_data.get("add_name_suggestion", ticker)
    if not list_name or not ticker:
        _clear_add_context(context)
        await query.edit_message_text(
            "❌ <b>Dialogstatus verloren</b>\nBitte starte erneut mit /portfolio_add oder /watchlist_add.",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    action = (query.data or "").split(":", 1)[-1]

    if action == "cancel":
        _clear_add_context(context)
        await query.edit_message_text("🛑 <b>Hinzufügen abgebrochen</b>", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    if action == "own":
        await query.edit_message_reply_markup(reply_markup=None)
        await _reply_and_track_html(update, "✏️ Bitte sende jetzt den gewünschten <b>Namen</b> als Text.")
        return ADD_WAIT_MANUAL_NAME

    if action == "use":
        await query.edit_message_reply_markup(reply_markup=None)
        return await _finalize_add_and_show_list(update, context, list_name, ticker, suggested_name)

    await query.answer("Unbekannte Aktion", show_alert=False)
    return ADD_WAIT_MANUAL_NAME


async def add_receive_manual_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    if not update.message or not update.message.text:
        await _reply_and_track_html(update, _format_validation_error("Bitte sende einen Namen als Text."))
        return ADD_WAIT_MANUAL_NAME

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
        return ADD_WAIT_MANUAL_NAME

    return await _finalize_add_and_show_list(update, context, list_name, ticker, name)


async def remove_receive_selection_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()

    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    if not query:
        return REMOVE_WAIT_SELECTION

    list_name = context.user_data.get("remove_target_list", "")
    items = context.user_data.get("remove_items", [])
    selected_index = int(context.user_data.get("remove_selected_index", 0))
    selected_index = max(0, min(selected_index, max(0, len(items) - 1)))
    if not list_name or not isinstance(items, list) or not items:
        _clear_remove_context(context)
        await query.edit_message_text(
            "❌ <b>Dialogstatus verloren</b>\nBitte starte erneut mit /portfolio_remove oder /watchlist_remove.",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    action = (query.data or "").split(":", 1)[-1]

    if action in {"up", "down"}:
        selected_index = _move_selection(selected_index, action, len(items))
        context.user_data["remove_selected_index"] = selected_index
        title = "Portfolio" if list_name == "portfolio" else "Watchlist"
        emoji = "📈" if list_name == "portfolio" else "👀"
        await query.edit_message_text(
            _format_remove_prompt(items, title, emoji, selected_index),
            parse_mode=ParseMode.HTML,
            reply_markup=_remove_selection_keyboard(),
        )
        return REMOVE_WAIT_SELECTION

    if action == "cancel":
        _clear_remove_context(context)
        await query.edit_message_text("🛑 <b>Entfernen abgebrochen</b>", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    if action != "pick":
        await query.answer("Unbekannte Aktion", show_alert=False)
        return REMOVE_WAIT_SELECTION

    await query.edit_message_reply_markup(reply_markup=None)
    selected = items[selected_index]
    ticker = normalize_ticker(str(selected.get("ticker", "")))
    if not ticker:
        await _reply_and_track_html(update, _format_validation_error("Der gewählte Eintrag hat keinen gültigen Ticker."))
        return REMOVE_WAIT_SELECTION

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
    finally:
        _clear_remove_context(context)

    return ConversationHandler.END


async def remove_receive_selection_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    await _reply_and_track_html(
        update,
        "👆 <b>Bitte nutze die Buttons</b> unter der Entfernen-Liste.",
    )
    return REMOVE_WAIT_SELECTION


async def add_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        await _reply_not_authorized(update)
        return ConversationHandler.END
    _clear_add_context(context)
    _clear_remove_context(context)
    await _reply_and_track_html(update, "🛑 <b>Vorgang abgebrochen</b>")
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
        f"🧹 Chat bereinigt (best effort). Gelöscht: {result['deleted']}",
    )


async def _post_init(application: Application) -> None:
    await application.bot.set_my_commands(COMMAND_MENU)


def build_command_application() -> Application:
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(MessageHandler(filters.ALL, track_incoming_message_id), group=-1)
    app.add_handler(CommandHandler("help", help_command))
    add_flow_handler = ConversationHandler(
        entry_points=[
            CommandHandler("portfolio_add", portfolio_add_command),
            CommandHandler("watchlist_add", watchlist_add_command),
        ],
        states={
            ADD_WAIT_COMPANY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_receive_company)],
            ADD_WAIT_SELECTION: [
                CallbackQueryHandler(
                    add_receive_selection_button,
                    pattern=rf"^{ADD_SELECTION_CALLBACK_PREFIX}:",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_receive_selection_text),
            ],
            ADD_WAIT_MANUAL_TICKER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_receive_manual_ticker)],
            ADD_WAIT_MANUAL_NAME: [
                CallbackQueryHandler(
                    add_receive_manual_name_button,
                    pattern=rf"^{MANUAL_NAME_CALLBACK_PREFIX}:",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_receive_manual_name),
            ],
        },
        fallbacks=[CommandHandler("cancel", add_cancel_command)],
        allow_reentry=True,
    )
    app.add_handler(add_flow_handler)
    remove_flow_handler = ConversationHandler(
        entry_points=[
            CommandHandler("portfolio_remove", portfolio_remove_command),
            CommandHandler("watchlist_remove", watchlist_remove_command),
        ],
        states={
            REMOVE_WAIT_SELECTION: [
                CallbackQueryHandler(
                    remove_receive_selection_button,
                    pattern=rf"^{REMOVE_SELECTION_CALLBACK_PREFIX}:",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, remove_receive_selection_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", add_cancel_command)],
        allow_reentry=True,
    )
    app.add_handler(remove_flow_handler)
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
