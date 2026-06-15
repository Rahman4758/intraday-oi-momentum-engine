import pandas as pd

def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """
    Calculate the Exponential Moving Average (EMA) for a pandas Series.
    """
    return series.ewm(span=period, adjust=False).mean()
