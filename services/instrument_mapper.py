"""
Instrument mapper — translates trading symbols to Upstox instrument keys.

On first use (or when the cache is stale) the full Upstox instrument master
file is downloaded, decompressed, and parsed into in-memory lookup dictionaries
for O(1) symbol → instrument-key resolution.
"""

import gzip
import io
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_INSTRUMENT_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
_FO_INSTRUMENT_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE_FO.json.gz"
_CACHE_TTL_HOURS = 12  # re-download if older than this
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0


class InstrumentMapper:
    """
    Maps human-readable symbols to Upstox instrument keys.

    The mapper maintains an in-memory cache that is lazily loaded on first
    access and refreshed when the cache age exceeds ``_CACHE_TTL_HOURS``.

    Usage::

        mapper = InstrumentMapper()
        key = mapper.get_equity_key("RELIANCE")
        # => "NSE_EQ|INE002A01018"
    """

    def __init__(self) -> None:
        # Equity lookup:  symbol (uppercase) → instrument_key
        self._equity_cache: Dict[str, str] = {}
        # Index lookup: index name (uppercase) → instrument_key
        self._index_cache: Dict[str, str] = {}
        # FO lookup: composite key → instrument_key
        self._fo_cache: Dict[str, str] = {}
        # We NO LONGER store raw instrument lists to save memory.
        # self._nse_instruments: List[Dict[str, Any]] = []
        # self._fo_instruments: List[Dict[str, Any]] = []

        self._last_loaded: Optional[datetime] = None

    # ────────────────────────────────────────────────────────────────────
    # Loading & caching
    # ────────────────────────────────────────────────────────────────────

    def _is_cache_stale(self) -> bool:
        """Return True if the cache has never been loaded or has expired."""
        if self._last_loaded is None:
            return True
        return datetime.utcnow() - self._last_loaded > timedelta(hours=_CACHE_TTL_HOURS)

    @staticmethod
    def _download_gz_json(url: str) -> List[Dict[str, Any]]:
        """
        Download a ``.json.gz`` file and return the parsed JSON list.

        Retries up to ``_MAX_RETRIES`` times with exponential back-off.
        """
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                with httpx.Client(timeout=60.0, follow_redirects=True, headers=headers) as client:
                    resp = client.get(url)
                    resp.raise_for_status()

                    # Decompress gzip content
                    raw_bytes = resp.content
                    try:
                        decompressed = gzip.decompress(raw_bytes)
                    except gzip.BadGzipFile:
                        # Some CDN configurations serve uncompressed despite .gz extension
                        decompressed = raw_bytes

                    data = json.loads(decompressed)
                    if isinstance(data, list):
                        return data
                    logger.warning("Instrument master is not a list — got %s", type(data))
                    return []

            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as exc:
                backoff = _BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "Instrument download failed (%s): %s  [attempt %d/%d, retry in %.1fs]",
                    url, exc, attempt, _MAX_RETRIES, backoff,
                )
                time.sleep(backoff)

        logger.error("Could not download instrument master from %s", url)
        return []

    def load_instruments(self) -> None:
        """
        Download and cache the Upstox instrument master files.

        Builds three lookup dictionaries:
        - ``_equity_cache``:  ``SYMBOL`` → ``NSE_EQ|ISIN``
        - ``_index_cache``:   ``INDEX NAME`` → ``NSE_INDEX|...``
        - ``_fo_cache``:      composite key → ``NSE_FO|...``
        """
        logger.info("Loading instrument master files …")

        # ── NSE equities + indices ──────────────────────────────────────
        nse_data = self._download_gz_json(_INSTRUMENT_URL)

        self._equity_cache.clear()
        self._index_cache.clear()

        for inst in nse_data:
            inst_key = inst.get("instrument_key", "")
            symbol = inst.get("trading_symbol", "").upper().strip()
            instrument_type = inst.get("instrument_type", "").upper()
            exchange = inst.get("exchange", "").upper()
            name = inst.get("name", "").upper().strip()

            if not inst_key or not symbol:
                continue

            if inst_key.startswith("NSE_EQ|"):
                self._equity_cache[symbol] = inst_key
            elif inst_key.startswith("NSE_INDEX|"):
                self._index_cache[symbol] = inst_key
                # Also map by name for flexible lookups
                if name:
                    self._index_cache[name] = inst_key

        logger.info(
            "Loaded %d equity and %d index instruments.",
            len(self._equity_cache),
            len(self._index_cache),
        )
        del nse_data  # Free memory immediately

        # ── NSE F&O ────────────────────────────────────────────────────
        fo_data = self._download_gz_json(_FO_INSTRUMENT_URL)
        self._fo_cache.clear()

        for inst in fo_data:
            inst_key = inst.get("instrument_key", "")
            symbol = inst.get("trading_symbol", "").upper().strip()
            expiry = inst.get("expiry", "")
            strike = inst.get("strike_price", inst.get("strike", 0))
            option_type = inst.get("option_type", "").upper()
            instrument_type = inst.get("instrument_type", "").upper()

            if not inst_key:
                continue

            # Build composite lookup key for options
            if option_type in ("CE", "PE"):
                # Normalise expiry to YYYY-MM-DD if possible
                expiry_norm = self._normalise_date(expiry)
                composite = self._make_option_composite(
                    inst.get("name", symbol).upper().strip(),
                    expiry_norm,
                    float(strike),
                    option_type,
                )
                self._fo_cache[composite] = inst_key
            elif instrument_type in ("FUTIDX", "FUTSTK"):
                # Future contracts
                expiry_norm = self._normalise_date(expiry)
                composite = f"FUT|{inst.get('name', symbol).upper().strip()}|{expiry_norm}"
                self._fo_cache[composite] = inst_key

        logger.info("Loaded %d F&O instruments.", len(self._fo_cache))
        del fo_data  # Free memory immediately
        self._last_loaded = datetime.utcnow()

    @staticmethod
    def _normalise_date(raw: str) -> str:
        """
        Attempt to normalise a date string to ``YYYY-MM-DD``.

        Handles common formats returned by the Upstox instrument master.
        Returns the original string if parsing fails.
        """
        if not raw:
            return ""
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d-%b-%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(raw[:10], fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        # If it already looks like YYYY-MM-DD, return as-is
        return raw[:10]

    @staticmethod
    def _make_option_composite(
        underlying: str, expiry: str, strike: float, option_type: str,
    ) -> str:
        """Build the deterministic composite key for an option contract."""
        # Normalise strike: remove trailing .0 for whole numbers
        strike_str = f"{strike:g}"
        return f"OPT|{underlying}|{expiry}|{strike_str}|{option_type}"

    def _ensure_loaded(self) -> None:
        """Load instruments if the cache is stale or uninitialised."""
        if self._is_cache_stale():
            self.load_instruments()

    # ────────────────────────────────────────────────────────────────────
    # Public lookup methods
    # ────────────────────────────────────────────────────────────────────

    def get_equity_key(self, symbol: str) -> str:
        """
        Resolve an NSE equity trading symbol to its Upstox instrument key.

        Parameters
        ----------
        symbol : str
            Trading symbol, e.g. ``"RELIANCE"``.

        Returns
        -------
        str
            Instrument key, e.g. ``"NSE_EQ|INE002A01018"``.

        Raises
        ------
        KeyError
            If the symbol is not found in the instrument master.
        """
        self._ensure_loaded()
        key = symbol.strip().upper()
        if key not in self._equity_cache:
            raise KeyError(
                f"Equity symbol '{symbol}' not found in instrument master. "
                f"Available count: {len(self._equity_cache)}"
            )
        return self._equity_cache[key]

    def get_index_key(self, index_name: str) -> str:
        """
        Resolve an NSE index name to its Upstox instrument key.

        Parameters
        ----------
        index_name : str
            Index name, e.g. ``"Nifty 50"`` or ``"NIFTY 50"``.

        Returns
        -------
        str
            Instrument key, e.g. ``"NSE_INDEX|Nifty 50"``.

        Raises
        ------
        KeyError
            If the index is not found.
        """
        self._ensure_loaded()
        key = index_name.strip().upper()
        if key not in self._index_cache:
            raise KeyError(
                f"Index '{index_name}' not found in instrument master. "
                f"Available indices: {list(self._index_cache.keys())[:20]}"
            )
        return self._index_cache[key]

    def get_option_key(
        self,
        symbol: str,
        expiry: str,
        strike: float,
        option_type: str,
    ) -> str:
        """
        Resolve an option contract to its Upstox instrument key.

        Parameters
        ----------
        symbol : str
            Underlying symbol, e.g. ``"RELIANCE"`` or ``"NIFTY"``.
        expiry : str
            Expiry date in ``YYYY-MM-DD`` format.
        strike : float
            Strike price, e.g. ``2500.0``.
        option_type : str
            ``"CE"`` or ``"PE"``.

        Returns
        -------
        str
            Instrument key, e.g. ``"NSE_FO|..."``

        Raises
        ------
        KeyError
            If the contract is not found.
        """
        self._ensure_loaded()
        composite = self._make_option_composite(
            symbol.strip().upper(),
            self._normalise_date(expiry),
            strike,
            option_type.strip().upper(),
        )
        if composite not in self._fo_cache:
            raise KeyError(
                f"Option contract not found: {composite}. "
                f"Check symbol, expiry, strike, and option_type."
            )
        return self._fo_cache[composite]

    def get_future_key(
        self,
        symbol: str,
        expiry: str,
    ) -> str:
        """
        Resolve a futures contract to its Upstox instrument key.

        Parameters
        ----------
        symbol : str
            Underlying symbol, e.g. ``"RELIANCE"`` or ``"NIFTY"``.
        expiry : str
            Expiry date in ``YYYY-MM-DD`` format.

        Returns
        -------
        str
            Instrument key for the futures contract.

        Raises
        ------
        KeyError
            If the contract is not found.
        """
        self._ensure_loaded()
        composite = f"FUT|{symbol.strip().upper()}|{self._normalise_date(expiry)}"
        if composite not in self._fo_cache:
            raise KeyError(
                f"Futures contract not found: {composite}. "
                f"Check symbol and expiry."
            )
        return self._fo_cache[composite]

    def search_symbols(self, query: str, limit: int = 20) -> List[Dict[str, str]]:
        """
        Search for instruments matching a partial symbol or name.

        Parameters
        ----------
        query : str
            Partial symbol or name (case-insensitive).
        limit : int, optional
            Maximum results to return (default 20).

        Returns
        -------
        list[dict]
            Each dict has ``symbol``, ``instrument_key``, ``type``
            (``"equity"`` or ``"index"``).
        """
        self._ensure_loaded()
        query_upper = query.strip().upper()
        results: List[Dict[str, str]] = []

        for sym, key in self._equity_cache.items():
            if query_upper in sym:
                results.append({"symbol": sym, "instrument_key": key, "type": "equity"})
                if len(results) >= limit:
                    return results

        for name, key in self._index_cache.items():
            if query_upper in name:
                results.append({"symbol": name, "instrument_key": key, "type": "index"})
                if len(results) >= limit:
                    return results

        return results
