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

_CSV_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
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

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(InstrumentMapper, cls).__new__(cls, *args, **kwargs)
            cls._instance._init_state()
        return cls._instance

    def _init_state(self) -> None:
        if getattr(self, "_initialized", False):
            return
        # Equity lookup:  symbol (uppercase) → instrument_key
        self._equity_cache: Dict[str, str] = {}
        # Index lookup: index name (uppercase) → instrument_key
        self._index_cache: Dict[str, str] = {}
        # FO lookup: composite key → instrument_key
        self._fo_cache: Dict[str, str] = {}

        self._last_loaded: Optional[datetime] = None
        self._initialized = True

    # ────────────────────────────────────────────────────────────────────
    # Loading & caching
    # ────────────────────────────────────────────────────────────────────

    def _is_cache_stale(self) -> bool:
        """Return True if the cache has never been loaded or has expired."""
        if self._last_loaded is None:
            return True
        return datetime.utcnow() - self._last_loaded > timedelta(hours=_CACHE_TTL_HOURS)

    def load_instruments(self) -> None:
        """
        Download and cache the Upstox instrument master file (CSV).

        Builds three lookup dictionaries:
        - ``_equity_cache``:  ``SYMBOL`` → ``NSE_EQ|ISIN``
        - ``_index_cache``:   ``INDEX NAME`` → ``NSE_INDEX|...``
        - ``_fo_cache``:      composite key → ``NSE_FO|...``
        """
        import csv
        
        logger.info("Loading instrument master from CSV to save memory ...")

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
                with httpx.Client(timeout=120.0, follow_redirects=True, headers=headers) as client:
                    resp = client.get(_CSV_URL)
                    resp.raise_for_status()

                    raw_bytes = resp.content
                    try:
                        decompressed = gzip.decompress(raw_bytes)
                    except gzip.BadGzipFile:
                        decompressed = raw_bytes
                        
                    # Aggressive GC
                    del raw_bytes
                    csv_text = decompressed.decode('utf-8')
                    del decompressed

                    reader = csv.DictReader(io.StringIO(csv_text))
                    
                    self._equity_cache.clear()
                    self._index_cache.clear()
                    self._fo_cache.clear()

                    for row in reader:
                        inst_key = row.get("instrument_key", "")
                        symbol = row.get("tradingsymbol", "").upper().strip()
                        name = row.get("name", "").upper().strip()
                        inst_type = row.get("instrument_type", "").upper()
                        
                        if not inst_key or not symbol:
                            continue

                        # NSE EQ
                        if inst_key.startswith("NSE_EQ|"):
                            self._equity_cache[symbol] = inst_key
                            
                        # NSE INDEX
                        elif inst_key.startswith("NSE_INDEX|"):
                            self._index_cache[symbol] = inst_key
                            if name:
                                self._index_cache[name] = inst_key
                                
                        # NSE FO
                        elif inst_key.startswith("NSE_FO|"):
                            expiry = row.get("expiry", "")
                            strike_str = row.get("strike", "0")
                            try:
                                strike = float(strike_str) if strike_str else 0.0
                            except ValueError:
                                strike = 0.0
                                
                            option_type = row.get("option_type", "").upper()

                            if option_type in ("CE", "PE"):
                                expiry_norm = self._normalise_date(expiry)
                                composite = self._make_option_composite(
                                    name or symbol,
                                    expiry_norm,
                                    strike,
                                    option_type,
                                )
                                self._fo_cache[composite] = inst_key
                            elif inst_type in ("FUTIDX", "FUTSTK"):
                                expiry_norm = self._normalise_date(expiry)
                                composite = f"FUT|{name or symbol}|{expiry_norm}"
                                self._fo_cache[composite] = inst_key

                    logger.info(
                        "Loaded %d equity, %d index, %d FO instruments.",
                        len(self._equity_cache), len(self._index_cache), len(self._fo_cache)
                    )
                    
                    del csv_text
                    self._last_loaded = datetime.utcnow()
                    return

            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as exc:
                backoff = _BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "CSV download failed (%s): %s  [attempt %d/%d, retry in %.1fs]",
                    _CSV_URL, exc, attempt, _MAX_RETRIES, backoff,
                )
                time.sleep(backoff)
            except Exception as e:
                logger.error(f"Unexpected error parsing CSV: {e}")
                time.sleep(2)

        logger.error("Could not load instrument master CSV after %d retries", _MAX_RETRIES)

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
