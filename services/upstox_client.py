"""
Upstox API client — REST + WebSocket wrapper with rate-limiting and retries.

This module wraps the Upstox v2 REST API (via httpx) and the official Python
SDK's ``MarketDataStreamerV3`` for WebSocket streaming.  Every public method
includes:

* Per-endpoint rate limiting (configurable ``min_interval``)
* Automatic retry with exponential back-off for transient errors
* Structured logging of every request/response cycle
"""

import gzip
import io
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import numpy as np
import pandas as pd
import upstox_client
from upstox_client.rest import ApiException

from config.settings import settings

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────
_BASE_URL = "https://api.upstox.com/v2"
_DEFAULT_MIN_INTERVAL = 0.35  # seconds between requests to same endpoint
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds; doubles on each retry
_QUOTE_BATCH_SIZE = 500  # max instrument keys per quote request


class UpstoxService:
    """
    Unified gateway to Upstox market-data APIs.

    Instantiate once and share across the application::

        from services.upstox_client import UpstoxService
        upstox = UpstoxService()
        candles = upstox.get_intraday_candles("NSE_EQ|INE002A01018")
    """

    def __init__(self) -> None:
        self.access_token: str = settings.UPSTOX_ACCESS_TOKEN
        if not self.access_token:
            logger.error("UPSTOX_ACCESS_TOKEN is empty — API calls will fail.")

        # SDK configuration (used only for WebSocket streamer)
        self.configuration = upstox_client.Configuration()
        self.configuration.access_token = self.access_token
        self.api_client = upstox_client.ApiClient(self.configuration)

        # httpx client for REST calls
        self._http = httpx.Client(
            base_url=_BASE_URL,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )

        # Per-endpoint rate-limit tracker: endpoint → last_request_epoch
        self._last_request_time: Dict[str, float] = {}

        logger.info("UpstoxService initialised.")

    # ────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ────────────────────────────────────────────────────────────────────

    def _rate_limit(self, endpoint: str, min_interval: float = _DEFAULT_MIN_INTERVAL) -> None:
        """
        Block until at least *min_interval* seconds have elapsed since
        the last request to *endpoint*.
        """
        now = time.monotonic()
        last = self._last_request_time.get(endpoint, 0.0)
        wait = min_interval - (now - last)
        if wait > 0:
            logger.debug("Rate-limiting %s — sleeping %.3f s", endpoint, wait)
            time.sleep(wait)
        self._last_request_time[endpoint] = time.monotonic()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        min_interval: float = _DEFAULT_MIN_INTERVAL,
    ) -> Any:
        """
        Execute an HTTP request with rate-limiting and exponential back-off.

        Returns the parsed JSON body (``response.json()``).

        Raises
        ------
        httpx.HTTPStatusError
            After exhausting all retries on non-retriable status codes.
        """
        for attempt in range(1, _MAX_RETRIES + 1):
            self._rate_limit(path, min_interval)
            try:
                resp = self._http.request(
                    method, path, params=params, json=json_body,
                )

                # ── 429  Too Many Requests → back off ──────────────────
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", _BACKOFF_BASE * attempt))
                    logger.warning(
                        "Rate-limited on %s (429). Retry-After=%.1f s  [attempt %d/%d]",
                        path, retry_after, attempt, _MAX_RETRIES,
                    )
                    time.sleep(retry_after)
                    continue

                # ── 401  Unauthorized → token may have expired ─────────
                if resp.status_code == 401:
                    logger.error(
                        "Unauthorized (401) on %s — access token may have expired.",
                        path,
                    )
                    resp.raise_for_status()

                # ── 5xx  Server errors → retry ─────────────────────────
                if resp.status_code >= 500:
                    backoff = _BACKOFF_BASE * (2 ** (attempt - 1))
                    logger.warning(
                        "Server error %d on %s. Retrying in %.1f s  [attempt %d/%d]",
                        resp.status_code, path, backoff, attempt, _MAX_RETRIES,
                    )
                    time.sleep(backoff)
                    continue

                resp.raise_for_status()
                return resp.json()

            except httpx.TimeoutException:
                backoff = _BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "Timeout on %s. Retrying in %.1f s  [attempt %d/%d]",
                    path, backoff, attempt, _MAX_RETRIES,
                )
                time.sleep(backoff)
            except httpx.ConnectError as exc:
                backoff = _BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "Connection error on %s: %s. Retrying in %.1f s  [attempt %d/%d]",
                    path, exc, backoff, attempt, _MAX_RETRIES,
                )
                time.sleep(backoff)

        # Exhausted retries
        logger.error("All %d retries exhausted for %s %s", _MAX_RETRIES, method, path)
        raise httpx.HTTPStatusError(
            message=f"Failed after {_MAX_RETRIES} retries: {method} {path}",
            request=httpx.Request(method, path),
            response=httpx.Response(status_code=503),
        )

    # ────────────────────────────────────────────────────────────────────
    # Historical & intraday candles
    # ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _candles_to_dataframe(candles: List[List]) -> pd.DataFrame:
        """
        Convert the raw candles array from Upstox API into a DataFrame.

        Upstox returns each candle as:
        ``[timestamp, open, high, low, close, volume, oi]``
        """
        if not candles:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])

        df = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume", "oi"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(np.float64)
        df["volume"] = df["volume"].astype(np.int64)
        df["oi"] = df["oi"].astype(np.int64)
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    def get_historical_candles(
        self,
        instrument_key: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV candles.

        Parameters
        ----------
        instrument_key : str
            Upstox instrument key, e.g. ``"NSE_EQ|INE002A01018"``.
        interval : str
            Candle interval — ``"1minute"``, ``"30minute"``, ``"day"``,
            ``"week"``, ``"month"``.
        from_date : str
            Start date in ``YYYY-MM-DD`` format.
        to_date : str
            End date in ``YYYY-MM-DD`` format.

        Returns
        -------
        pd.DataFrame
            Columns: timestamp, open, high, low, close, volume, oi.
        """
        path = f"/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}"
        logger.info("Fetching historical candles: %s", path)

        data = self._request("GET", path)
        candles = data.get("data", {}).get("candles", [])
        df = self._candles_to_dataframe(candles)
        logger.info("Received %d historical candles for %s", len(df), instrument_key)
        return df

    def get_intraday_candles(
        self,
        instrument_key: str,
        interval: str = "1minute",
    ) -> pd.DataFrame:
        """
        Fetch today's intraday candles.

        Parameters
        ----------
        instrument_key : str
            Upstox instrument key.
        interval : str, optional
            Candle interval (default ``"1minute"``).

        Returns
        -------
        pd.DataFrame
            Columns: timestamp, open, high, low, close, volume, oi.
        """
        path = f"/historical-candle/intraday/{instrument_key}/{interval}"
        logger.info("Fetching intraday candles: %s", path)

        data = self._request("GET", path)
        candles = data.get("data", {}).get("candles", [])
        df = self._candles_to_dataframe(candles)
        logger.info("Received %d intraday candles for %s", len(df), instrument_key)
        return df

    def get_intraday_candles_raw(
        self,
        instrument_key: str,
        interval: str = "1minute",
    ) -> List[List[Any]]:
        """
        Fetch today's intraday candles as a raw list to save memory (No Pandas).

        Returns
        -------
        list[list]
            Sorted ascending by time. Each inner list:
            [timestamp, open, high, low, close, volume, oi]
        """
        path = f"/historical-candle/intraday/{instrument_key}/{interval}"
        logger.debug("Fetching raw intraday candles: %s", path)

        data = self._request("GET", path)
        candles = data.get("data", {}).get("candles", [])
        
        # Upstox returns descending by timestamp usually, we need ascending.
        # Format from upstox: ["2023-10-25T15:29:00+05:30", 19200.0, 19201.5, 19198.0, 19200.5, 50000, 0]
        parsed_candles = []
        for c in candles:
            # c = [timestamp_str, open, high, low, close, vol, oi]
            if len(c) >= 7:
                parsed_candles.append([
                    c[0],               # timestamp
                    float(c[1]),        # open
                    float(c[2]),        # high
                    float(c[3]),        # low
                    float(c[4]),        # close
                    int(c[5]),          # volume
                    int(c[6])           # oi
                ])
                
        # Sort by timestamp ascending
        parsed_candles.sort(key=lambda x: x[0])
        logger.debug("Received %d raw intraday candles for %s", len(parsed_candles), instrument_key)
        return parsed_candles

    # ────────────────────────────────────────────────────────────────────
    # Option chain
    # ────────────────────────────────────────────────────────────────────

    def get_option_chain(
        self,
        instrument_key: str,
        expiry_date: str,
    ) -> List[Dict[str, Any]]:
        """
        Fetch the option chain for a stock / index.

        Parameters
        ----------
        instrument_key : str
            Underlying instrument key (e.g. ``"NSE_INDEX|Nifty 50"``).
        expiry_date : str
            Expiry date in ``YYYY-MM-DD`` format.

        Returns
        -------
        list[dict]
            Each dict contains::

                {
                    "strike_price": float,
                    "call_oi": int,
                    "put_oi": int,
                    "call_premium": float,
                    "put_premium": float,
                    "call_iv": float,
                    "put_iv": float,
                    "pcr": float,
                }
        """
        path = "/option/chain"
        params = {
            "instrument_key": instrument_key,
            "expiry_date": expiry_date,
        }
        logger.info(
            "Fetching option chain for %s expiry %s", instrument_key, expiry_date,
        )

        data = self._request("GET", path, params=params)
        raw_chain = data.get("data", [])
        if not raw_chain:
            logger.warning("Empty option chain returned for %s", instrument_key)
            return []

        result: List[Dict[str, Any]] = []
        for entry in raw_chain:
            call_data = entry.get("call_options", {})
            put_data = entry.get("put_options", {})
            call_md = call_data.get("market_data", {})
            put_md = put_data.get("market_data", {})
            call_greeks = call_data.get("option_greeks", {})
            put_greeks = put_data.get("option_greeks", {})

            strike = float(entry.get("strike_price", 0))
            call_oi = int(call_md.get("oi", 0))
            put_oi = int(put_md.get("oi", 0))
            call_premium = float(call_md.get("ltp", 0))
            put_premium = float(put_md.get("ltp", 0))
            call_iv = float(call_greeks.get("iv", 0))
            put_iv = float(put_greeks.get("iv", 0))
            pcr = (put_oi / call_oi) if call_oi > 0 else 0.0

            result.append({
                "strike_price": strike,
                "call_oi": call_oi,
                "put_oi": put_oi,
                "call_premium": call_premium,
                "put_premium": put_premium,
                "call_iv": call_iv,
                "put_iv": put_iv,
                "pcr": round(pcr, 4),
            })

        logger.info(
            "Parsed %d strikes from option chain for %s", len(result), instrument_key,
        )
        return result

    # ────────────────────────────────────────────────────────────────────
    # Market quotes
    # ────────────────────────────────────────────────────────────────────

    def get_market_quote(
        self,
        instrument_keys: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fetch snapshot quotes for one or more instruments.

        Parameters
        ----------
        instrument_keys : list[str]
            Upstox instrument keys (batched automatically if > 500).

        Returns
        -------
        dict
            ``{instrument_key: {ltp, open, high, low, close, volume, oi, change_pct}}``
        """
        all_quotes: Dict[str, Dict[str, Any]] = {}

        # Batch into groups of _QUOTE_BATCH_SIZE
        for start in range(0, len(instrument_keys), _QUOTE_BATCH_SIZE):
            batch = instrument_keys[start : start + _QUOTE_BATCH_SIZE]
            keys_csv = ",".join(batch)

            data = self._request(
                "GET",
                "/market-quote/quotes",
                params={"instrument_key": keys_csv},
            )
            quotes_data = data.get("data", {})

            for inst_key, quote_info in quotes_data.items():
                ohlc = quote_info.get("ohlc") or {}
                ltp = float(quote_info.get("last_price") or 0.0)
                prev_close = float(ohlc.get("close") or 0.0)
                change_pct = (
                    ((ltp - prev_close) / prev_close * 100)
                    if prev_close != 0
                    else 0.0
                )
                
                quote_dict = {
                    "ltp": ltp,
                    "open": float(ohlc.get("open") or 0.0),
                    "high": float(ohlc.get("high") or 0.0),
                    "low": float(ohlc.get("low") or 0.0),
                    "close": prev_close,
                    "volume": int(quote_info.get("volume") or 0),
                    "oi": int(quote_info.get("oi") or 0),
                    "change_pct": round(change_pct, 2),
                }
                
                # The API returns keys like NSE_EQ:BAJAJFINSV instead of the ISIN token.
                # Store the quote under multiple keys to ensure the caller can find it.
                token = quote_info.get("instrument_token")
                symbol = quote_info.get("symbol")
                
                all_quotes[inst_key] = quote_dict
                if token:
                    all_quotes[token] = quote_dict
                if symbol:
                    all_quotes[symbol] = quote_dict

        logger.info("Fetched quotes for %d instruments.", len(all_quotes))
        return all_quotes

    def get_index_quotes(self) -> Dict[str, Dict[str, Any]]:
        """
        Convenience method to fetch Nifty 50, Bank Nifty, India VIX, and
        major sector-index quotes.

        Returns
        -------
        dict
            Same structure as ``get_market_quote`` keyed by index name.
        """
        index_keys = {
            "NIFTY_50": "NSE_INDEX|Nifty 50",
            "BANK_NIFTY": "NSE_INDEX|Nifty Bank",
            "INDIA_VIX": "NSE_INDEX|India VIX",
            "NIFTY_IT": "NSE_INDEX|Nifty IT",
            "NIFTY_PHARMA": "NSE_INDEX|Nifty Pharma",
            "NIFTY_FIN_SERVICE": "NSE_INDEX|Nifty Financial Services",
            "NIFTY_AUTO": "NSE_INDEX|Nifty Auto",
            "NIFTY_METAL": "NSE_INDEX|Nifty Metal",
            "NIFTY_ENERGY": "NSE_INDEX|Nifty Energy",
            "NIFTY_FMCG": "NSE_INDEX|Nifty FMCG",
            "NIFTY_REALTY": "NSE_INDEX|Nifty Realty",
        }
        raw = self.get_market_quote(list(index_keys.values()))

        result: Dict[str, Dict[str, Any]] = {}
        for name, inst_key in index_keys.items():
            if inst_key in raw:
                result[name] = raw[inst_key]
        return result

    # ────────────────────────────────────────────────────────────────────
    # Expiry dates
    # ────────────────────────────────────────────────────────────────────

    def get_expiry_dates(self, instrument_key: str) -> List[str]:
        """
        Get available option expiry dates for an underlying.

        Parameters
        ----------
        instrument_key : str
            Underlying instrument key.

        Returns
        -------
        list[str]
            ISO-formatted expiry dates sorted ascending.
        """
        data = self._request(
            "GET",
            "/option/contract",
            params={"instrument_key": instrument_key},
        )
        expiries_raw = data.get("data", [])

        # The API may return a flat list of date strings or nested objects
        expiries: List[str] = []
        for item in expiries_raw:
            if isinstance(item, str):
                expiries.append(item)
            elif isinstance(item, dict) and "expiry" in item:
                expiries.append(item["expiry"])

        expiries.sort()
        logger.info(
            "Found %d expiry dates for %s", len(expiries), instrument_key,
        )
        return expiries

    # ────────────────────────────────────────────────────────────────────
    # WebSocket streaming
    # ────────────────────────────────────────────────────────────────────

    def get_websocket_url(self) -> str:
        """
        Obtain an authorised WebSocket URL from the Upstox API.

        The URL is single-use and must be consumed within a short window.

        Returns
        -------
        str
            The ``wss://`` URL for market-data streaming.
        """
        data = self._request("GET", "/feed/market-data-feed/authorize")
        ws_url = data.get("data", {}).get("authorizedRedirectUri", "")
        if not ws_url:
            logger.error("Failed to obtain WebSocket URL from authorise response.")
            raise RuntimeError("No WebSocket URL in authorise response.")
        logger.info("WebSocket URL obtained.")
        return ws_url

    def create_streamer(
        self,
        instrument_keys: List[str],
        mode: str = "full",
    ) -> upstox_client.MarketDataStreamerV3:
        """
        Create a configured ``MarketDataStreamerV3`` instance.

        Parameters
        ----------
        instrument_keys : list[str]
            Instruments to subscribe to.
        mode : str, optional
            Subscription mode — ``"full"``, ``"quote"``, or ``"ltpc"``
            (default ``"full"``).

        Returns
        -------
        upstox_client.MarketDataStreamerV3
            Ready-to-use streamer; call ``.connect()`` to start.
        """
        streamer = upstox_client.MarketDataStreamerV3(
            api_client=self.api_client,
            instrument_keys=instrument_keys,
            mode=mode,
        )
        logger.info(
            "MarketDataStreamerV3 created for %d instruments (mode=%s).",
            len(instrument_keys),
            mode,
        )
        return streamer

    # ────────────────────────────────────────────────────────────────────
    # Cleanup
    # ────────────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the underlying HTTP client and release resources."""
        self._http.close()
        logger.info("UpstoxService HTTP client closed.")

    def __enter__(self) -> "UpstoxService":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
