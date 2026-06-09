"""Telegram alerts for detected opportunities (proposal §4.1, Phase 4).

Message *formatting* is a pure function (:func:`format_alert`) so it can be tested
without a network or a bot token. *Sending* is isolated in :class:`Alerter`. In
the forward-test this runs alert-only — no placement — which is exactly Phase 4.
"""

from __future__ import annotations

import asyncio

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from middler.alert.deeplinks import deep_link
from middler.logging_setup import get_logger
from middler.models import Event, Opportunity
from middler.timeutil import fmt_sydney

log = get_logger(__name__)


def _title(opp: Opportunity) -> str:
    if opp.kind == "arb":
        return "🟢 ARBITRAGE"
    if opp.kind == "back_lay":
        return "🟣 BACK-LAY" if opp.is_risk_free else "🟣 BACK-LAY (value)"
    if opp.is_risk_free:
        return "🟡 RISK-FREE MIDDLE"
    return "🔵 MIDDLE"


def _money(value: float | None) -> str:
    return f"${value:,.2f}" if value is not None else "—"


def format_alert(opp: Opportunity, event: Event | None = None) -> tuple[str, list[tuple[str, str]]]:
    """Render an opportunity into (HTML message, button specs).

    Args:
        opp: The opportunity to render.
        event: The originating event, for richer deep-links (optional).

    Returns:
        ``(html_text, buttons)`` where ``buttons`` is a list of ``(label, url)``.
    """
    sport = event.sport_title if event and event.sport_title else opp.sport_key
    if opp.kind == "back_lay":
        subject = opp.legs[0].outcome_name if opp.legs else "?"
    else:
        subject = f"{opp.home_team or '?'} v {opp.away_team or '?'}"
    lines = [f"<b>{_title(opp)} — {sport} {opp.market_key}</b>", subject, ""]

    if opp.kind == "arb":
        lines.append(f"Back both sides (total {_money(opp.total_stake)}):")
        for leg in opp.legs:
            point = "" if leg.point is None else f" {leg.point:+g}"
            lines.append(f"• <b>{leg.bookmaker}</b> — {leg.outcome_name}{point} @ {leg.price:g} → {_money(leg.stake)}")
        lines.append("")
        lines.append(f"Guaranteed profit <b>{_money(opp.profit)}</b> ({(opp.roi or 0) * 100:.2f}%)")
    elif opp.kind == "back_lay":
        back = next((leg for leg in opp.legs if leg.side == "back"), opp.legs[0])
        lay = next((leg for leg in opp.legs if leg.side == "lay"), opp.legs[-1])
        liability = lay.stake * (lay.price - 1.0)
        lines.append(f"Back <b>{back.bookmaker}</b> @ {back.price:g} → {_money(back.stake)}")
        lines.append(
            f"Lay <b>{lay.bookmaker}</b> @ {lay.price:g} → {_money(lay.stake)} (liability {_money(liability)})"
        )
        lines.append("")
        lines.append(f"Locked profit <b>{_money(opp.profit)}</b> ({(opp.roi or 0) * 100:.2f}%)")
    else:
        lines.append(f"Lands in the gap → <b>both win</b>. Window width {opp.width:g} pt.")
        lines.append(f"Stake split (total {_money(opp.total_stake)}):")
        for leg in opp.legs:
            point = "" if leg.point is None else f" {leg.point:+g}"
            lines.append(f"• <b>{leg.bookmaker}</b> — {leg.outcome_name}{point} @ {leg.price:g} → {_money(leg.stake)}")
        lines.append("")
        lines.append(f"If it hits → <b>{_money(opp.pl_middle)}</b>; otherwise {_money(opp.worst_case)} (worst case)")
        lines.append(
            f"Est. EV {_money(opp.ev)} ({(opp.ev_roi or 0) * 100:.2f}%) · hit-rate {(opp.hit_rate or 0) * 100:.0f}%"
        )

    lines.append("Sharp-verified ✓" if opp.reference_verified else "⚠️ Not sharp-verified — confirm the line by hand")
    lines.append(f"Starts {fmt_sydney(opp.commence_time)}")

    buttons = [(f"Open {leg.bookmaker}", deep_link(leg.bookmaker, event)) for leg in opp.legs]
    return "\n".join(lines), buttons


class Alerter:
    """Sends formatted opportunity alerts to one or more Telegram chats."""

    def __init__(self, token: str, chat_ids: list[int]) -> None:
        """Create an alerter.

        Args:
            token: Telegram bot token (empty disables sending).
            chat_ids: Chat ids to broadcast to.
        """
        self._chat_ids = chat_ids
        self._bot = Bot(token) if token else None

    @property
    def enabled(self) -> bool:
        """True when a token and at least one chat id are configured."""
        return self._bot is not None and bool(self._chat_ids)

    def notify(self, opp: Opportunity, event: Event | None = None) -> None:
        """Send an alert for one opportunity (no-op if not configured)."""
        if not self.enabled:
            log.info("alert (not sent — Telegram not configured): %s %s", opp.kind, opp.event_id)
            return
        text, buttons = format_alert(opp, event)
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, url=url)] for label, url in buttons])
        asyncio.run(self._broadcast(text, markup))

    async def _broadcast(self, text: str, markup: InlineKeyboardMarkup) -> None:
        assert self._bot is not None
        async with self._bot:
            for chat_id in self._chat_ids:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=markup,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
