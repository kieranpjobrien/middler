"""Betfair exchange placement — the only auto-placeable leg (proposal §2, §4.5).

The exchange leg can be placed via Betfair's sanctioned ``placeOrders`` API; the
bookmaker leg cannot and is always confirmed by a human. This module is built so
the *decision* to place is a small, pure, fully-tested function
(:func:`evaluate_placement`), while the *act* of placing is isolated and defaults
to a dry run. It will not place a live order unless every guard passes and an
explicit live call is made with resolved Betfair market/selection ids.

Resolving an odds-api event to a Betfair ``market_id``/``selection_id`` (via
``listMarketCatalogue``) is the remaining integration to wire before live use; it
is intentionally not done implicitly, so nothing places money by accident.
"""

from __future__ import annotations

from dataclasses import dataclass

from middler.config import AppConfig, Settings
from middler.logging_setup import get_logger
from middler.models import Opportunity, OpportunityLeg

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PlacementDecision:
    """Whether the Betfair leg of an opportunity may be auto-placed, and why."""

    allowed: bool
    reason: str
    requires_second_confirm: bool = False


def betfair_leg(opp: Opportunity) -> OpportunityLeg | None:
    """Return the opportunity's Betfair exchange leg, if any."""
    return next((leg for leg in opp.legs if leg.bookmaker.lower().startswith("betfair")), None)


def evaluate_placement(opp: Opportunity, settings: Settings, config: AppConfig) -> PlacementDecision:
    """Decide whether the Betfair leg may be auto-placed.

    Hard rules, in order (any failure forbids placement):

    1. The master switch ``PLACEMENT_ENABLED`` must be on.
    2. A Betfair app key must be configured.
    3. The opportunity must be sharp-verified (proposal §4.4 — never auto-place an
       unverified line).
    4. The opportunity must actually contain a Betfair exchange leg.

    Above ``staking.two_step_confirm_above`` a second confirmation is required.

    Args:
        opp: The opportunity under consideration.
        settings: Secrets/host config (master switch, Betfair key).
        config: Operating config (stake thresholds).

    Returns:
        A :class:`PlacementDecision`.
    """
    if not settings.placement_enabled:
        return PlacementDecision(False, "placement disabled (PLACEMENT_ENABLED=false)")
    if not settings.betfair_app_key:
        return PlacementDecision(False, "no Betfair app key configured")
    if not opp.reference_verified:
        return PlacementDecision(False, "line is not sharp-verified — refusing to auto-place")
    if betfair_leg(opp) is None:
        return PlacementDecision(False, "no Betfair exchange leg in this opportunity")
    second = opp.total_stake > config.staking.two_step_confirm_above
    return PlacementDecision(True, "ok", requires_second_confirm=second)


class BetfairExchange:
    """Thin wrapper over Betfair placement. Lazy-imports the optional client."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: object | None = None

    def _login(self) -> object:
        if self._client is not None:
            return self._client
        import betfairlightweight

        s = self._settings
        client = betfairlightweight.APIClient(
            username=s.betfair_username,
            password=s.betfair_password,
            app_key=s.betfair_app_key,
            certs=s.betfair_cert_file or None,
        )
        client.login()
        self._client = client
        return client

    def place_back_order(
        self,
        market_id: str,
        selection_id: int,
        price: float,
        size: float,
        customer_ref: str,
        dry_run: bool = True,
    ) -> dict[str, object]:
        """Place (or simulate) a single BACK limit order on the exchange.

        Args:
            market_id: Betfair market id (resolve via ``listMarketCatalogue``).
            selection_id: Betfair selection id within the market.
            price: Back price (decimal odds).
            size: Stake size in the account currency.
            customer_ref: Idempotency/audit reference.
            dry_run: When True (default) nothing is sent — the intended order is
                logged and returned, so the path can be exercised safely.

        Returns:
            A dict describing the (intended or placed) order.
        """
        order = {
            "market_id": market_id,
            "selection_id": selection_id,
            "side": "BACK",
            "price": price,
            "size": size,
            "customer_ref": customer_ref,
        }
        if dry_run:
            log.info("DRY-RUN Betfair back order: %s", order)
            return {"status": "dry_run", **order}

        from betfairlightweight import filters

        client = self._login()
        limit = filters.limit_order(size=size, price=price, persistence_type="LAPSE")
        instruction = filters.place_instruction(
            order_type="LIMIT", selection_id=selection_id, side="BACK", limit_order=limit
        )
        resp = client.betting.place_orders(  # type: ignore[attr-defined]
            market_id=market_id, instructions=[instruction], customer_ref=customer_ref
        )
        log.info("placed Betfair order ref=%s status=%s", customer_ref, getattr(resp, "status", "?"))
        return {"status": "placed", "ref": customer_ref, **order}
