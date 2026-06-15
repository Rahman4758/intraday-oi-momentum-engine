"""
NSE website data fetcher — F&O list, bhavcopy, delivery data.

All requests go through an ``httpx.Client`` that first visits the NSE
homepage to acquire session cookies (``nsit``, ``nseappid``, ``bm_*``),
mimicking a regular browser.  This is required because NSE's API endpoints
reject cookie-less requests with a 403.
"""

import csv
import io
import logging
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

_NSE_BASE = "https://www.nseindia.com"
_NSE_ARCHIVES = "https://nsearchives.nseindia.com"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0


class NSEDataService:
    """
    Scrapes publicly available data from www.nseindia.com and its archives.

    Usage::

        nse = NSEDataService()
        fno_symbols = nse.fetch_fno_list()
        bhav = nse.fetch_bhavcopy(date(2026, 6, 12))
    """

    def __init__(self) -> None:
        self.session = httpx.Client(
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": f"{_NSE_BASE}/",
            },
            timeout=httpx.Timeout(30.0, connect=15.0),
            follow_redirects=True,
        )
        self._session_initialised = False
        self._init_session()

    # ────────────────────────────────────────────────────────────────────
    # Session management
    # ────────────────────────────────────────────────────────────────────

    def _init_session(self) -> None:
        """
        Visit the NSE homepage to collect session cookies.

        NSE blocks API requests that lack the cookies set by the initial
        page load.  We hit the root URL, let the server set all cookies,
        and then reuse them for subsequent API calls.
        """
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = self.session.get(
                    f"{_NSE_BASE}/",
                    headers={"Accept": "text/html"},
                )
                if resp.status_code == 200:
                    self._session_initialised = True
                    logger.info(
                        "NSE session initialised (cookies: %d).",
                        len(self.session.cookies),
                    )
                    return
                logger.warning(
                    "NSE homepage returned %d [attempt %d/%d].",
                    resp.status_code, attempt, _MAX_RETRIES,
                )
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning(
                    "NSE session init failed: %s [attempt %d/%d].",
                    exc, attempt, _MAX_RETRIES,
                )
            time.sleep(_BACKOFF_BASE * attempt)

        logger.error("Could not initialise NSE session after %d attempts.", _MAX_RETRIES)

    def _ensure_session(self) -> None:
        """Re-initialise the session if cookies have expired or were never set."""
        if not self._session_initialised or len(self.session.cookies) == 0:
            self._init_session()

    def _get_json(self, url: str) -> Any:
        """
        Fetch a JSON endpoint from NSE with retries.

        Returns the parsed JSON (usually a ``dict``) or ``None`` on failure.
        """
        self._ensure_session()

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = self.session.get(url)
                if resp.status_code == 200:
                    return resp.json()

                # NSE occasionally returns 403 when cookies expire mid-session
                if resp.status_code == 403:
                    logger.warning("NSE returned 403; re-initialising session.")
                    self._init_session()
                    continue

                logger.warning(
                    "NSE %s returned %d [attempt %d/%d].",
                    url, resp.status_code, attempt, _MAX_RETRIES,
                )
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning(
                    "NSE request failed: %s [attempt %d/%d].",
                    exc, attempt, _MAX_RETRIES,
                )
            except Exception as exc:
                logger.error("Unexpected error fetching %s: %s", url, exc)
                break

            time.sleep(_BACKOFF_BASE * attempt)

        logger.error("Failed to fetch %s after %d attempts.", url, _MAX_RETRIES)
        return None

    # ────────────────────────────────────────────────────────────────────
    # F&O stock list
    # ────────────────────────────────────────────────────────────────────

    def fetch_fno_list(self) -> List[str]:
        """
        Download the list of stocks permitted for Futures & Options trading.

        Returns
        -------
        list[str]
            Trading symbols sorted alphabetically, e.g.
            ``["RELIANCE", "TCS", "INFY", ...]``.
        """
        url = f"{_NSE_BASE}/api/master-quote"
        data = self._get_json(url)

        if data and isinstance(data, dict):
            # The endpoint returns a dict keyed by symbol
            symbols = sorted(data.keys())
            logger.info("Fetched %d F&O symbols from master-quote.", len(symbols))
            return symbols

        # Fallback: try the equity-derivatives endpoint
        logger.info("master-quote unavailable; trying equity-derivatives page.")
        fallback_url = f"{_NSE_BASE}/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
        data = self._get_json(fallback_url)

        if data and isinstance(data, dict):
            entries = data.get("data", [])
            symbols = sorted(
                entry["symbol"]
                for entry in entries
                if "symbol" in entry and entry.get("symbol") != "NIFTY 50"
            )
            logger.info("Fetched %d F&O symbols from fallback.", len(symbols))
            return symbols

        logger.error("Could not fetch F&O list from any source.")
        return []

    # ────────────────────────────────────────────────────────────────────
    # Bhavcopy (end-of-day settlement data)
    # ────────────────────────────────────────────────────────────────────

    def fetch_bhavcopy(self, target_date: date) -> pd.DataFrame:
        """
        Download the equity bhavcopy CSV for the given date.

        The bhavcopy contains settlement prices, traded volumes, delivery
        quantities, and delivery percentages for all listed securities.

        Parameters
        ----------
        target_date : datetime.date
            Trading date to fetch.

        Returns
        -------
        pd.DataFrame
            Parsed bhavcopy with cleaned column names.  Returns an empty
            DataFrame if the file is unavailable (e.g. market holiday).
        """
        date_str = target_date.strftime("%d%m%Y")
        url = (
            f"{_NSE_ARCHIVES}/products/content/"
            f"sec_bhavdata_full_{date_str}.csv"
        )
        logger.info("Fetching bhavcopy for %s from %s", target_date.isoformat(), url)

        self._ensure_session()

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = self.session.get(url)
                if resp.status_code == 200:
                    df = pd.read_csv(io.StringIO(resp.text))
                    # Clean column names (NSE adds trailing spaces)
                    df.columns = [c.strip() for c in df.columns]
                    # Clean symbol column
                    if "SYMBOL" in df.columns:
                        df["SYMBOL"] = df["SYMBOL"].str.strip()
                    logger.info(
                        "Parsed bhavcopy: %d rows for %s.",
                        len(df), target_date.isoformat(),
                    )
                    return df

                if resp.status_code == 404:
                    logger.info(
                        "Bhavcopy not found for %s (likely a holiday).",
                        target_date.isoformat(),
                    )
                    return pd.DataFrame()

                logger.warning(
                    "Bhavcopy fetch returned %d [attempt %d/%d].",
                    resp.status_code, attempt, _MAX_RETRIES,
                )
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning(
                    "Bhavcopy fetch failed: %s [attempt %d/%d].",
                    exc, attempt, _MAX_RETRIES,
                )
            time.sleep(_BACKOFF_BASE * attempt)

        logger.error(
            "Failed to fetch bhavcopy for %s after %d attempts.",
            target_date.isoformat(), _MAX_RETRIES,
        )
        return pd.DataFrame()

    # ────────────────────────────────────────────────────────────────────
    # Delivery data for a single stock
    # ────────────────────────────────────────────────────────────────────

    def get_delivery_data(
        self,
        symbol: str,
        target_date: date,
    ) -> Dict[str, Any]:
        """
        Extract delivery percentage and volume for a specific stock from
        the bhavcopy.

        Parameters
        ----------
        symbol : str
            NSE trading symbol (e.g. ``"RELIANCE"``).
        target_date : datetime.date
            Trading date.

        Returns
        -------
        dict
            Keys::

                {
                    "symbol": str,
                    "date": str (ISO),
                    "traded_qty": int,
                    "deliverable_qty": int,
                    "delivery_pct": float,   # 0-100
                }

            Returns empty dict if data is not found.
        """
        bhav = self.fetch_bhavcopy(target_date)
        if bhav.empty:
            return {}

        # Normalise for lookup
        symbol_upper = symbol.strip().upper()
        mask = bhav["SYMBOL"] == symbol_upper

        # If bhavcopy has a series column, filter to EQ series
        if "SERIES" in bhav.columns:
            eq_mask = bhav["SERIES"].str.strip() == "EQ"
            mask = mask & eq_mask

        rows = bhav.loc[mask]
        if rows.empty:
            logger.warning(
                "No bhavcopy entry for %s on %s.", symbol_upper, target_date.isoformat(),
            )
            return {}

        row = rows.iloc[0]

        # Column names vary slightly between NSE data releases
        traded_qty = int(row.get("TTL_TRD_QNTY", row.get("TOTAL_TRADED_QUANTITY", 0)))
        deliverable_qty = int(row.get("DELIV_QTY", row.get("DELIVERABLE_QTY", 0)))
        delivery_pct = float(row.get("DELIV_PER", row.get("DELIVERY_PERCENTAGE", 0)))

        result = {
            "symbol": symbol_upper,
            "date": target_date.isoformat(),
            "traded_qty": traded_qty,
            "deliverable_qty": deliverable_qty,
            "delivery_pct": delivery_pct,
        }
        logger.debug("Delivery data for %s: %s", symbol_upper, result)
        return result

    # ────────────────────────────────────────────────────────────────────
    # Cleanup
    # ────────────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the HTTP session."""
        self.session.close()
        logger.info("NSEDataService session closed.")

    def __enter__(self) -> "NSEDataService":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
