"""
fetch_odds.py — Backward-compatible wrappers around odds_cache.fetch_odds().

All existing importers (cache_warmer, views, engines) continue to work
unchanged.  The actual caching / failover logic lives in odds_cache.py.
"""
import odds_cache

REGION = 'us'


def _games(sport_key: str) -> list:
    """Convenience: return just the games list (no meta)."""
    games, _ = odds_cache.fetch_odds(sport_key)
    return games


# ── Public sport functions ─────────────────────────────────────────────────

def get_nba_odds() -> list:
    return _games("basketball_nba")


def get_mlb_odds() -> list:
    return _games("baseball_mlb")


def get_ncaa_odds() -> list:
    return _games("baseball_ncaa")


def get_ncaab_odds() -> list:
    return _games("basketball_ncaab")


# ── Utility helpers (unchanged) ────────────────────────────────────────────

def get_market_line(game, market_key='totals', preferred_book='betmgm'):
    """Searches for Totals or other point-based markets."""
    for book in game.get('bookmakers', []):
        if book['key'] == preferred_book:
            for market in book.get('markets', []):
                if market['key'] == market_key:
                    outcomes = market.get('outcomes', [])
                    if outcomes:
                        return outcomes[0].get('point', 0.0)

    for book in game.get('bookmakers', []):
        for market in book.get('markets', []):
            if market['key'] == market_key:
                outcomes = market.get('outcomes', [])
                if outcomes:
                    return outcomes[0].get('point', 0.0)
    return 0.0


def get_vegas_moneyline(game, target_team, preferred_book='betmgm'):
    """Hunts for the H2H Moneyline price."""
    for book in game.get('bookmakers', []):
        if book['key'] == preferred_book:
            for market in book.get('markets', []):
                if market['key'] == 'h2h':
                    for out in market.get('outcomes', []):
                        if out['name'] == target_team:
                            return out.get('price')

    for book in game.get('bookmakers', []):
        for market in book.get('markets', []):
            if market['key'] == 'h2h':
                for out in market.get('outcomes', []):
                    if out['name'] == target_team:
                        return out.get('price')
    return None


def get_vegas_spread(game, target_team, preferred_book='betmgm'):
    """Hunts for the Runline/Spread point."""
    for book in game.get('bookmakers', []):
        if book['key'] == preferred_book:
            for market in book.get('markets', []):
                if market['key'] == 'spreads':
                    for out in market.get('outcomes', []):
                        if out['name'] == target_team:
                            return out.get('point')

    for book in game.get('bookmakers', []):
        for market in book.get('markets', []):
            if market['key'] == 'spreads':
                for out in market.get('outcomes', []):
                    if out['name'] == target_team:
                        return out.get('point')
    return None
