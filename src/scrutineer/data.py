from pathlib import Path

import pandas as pd


def find_journey_files(data_dir):
    """Return all journey CSV files below data_dir (plain or gzip-compressed),
    leaving out the metadata table."""
    return sorted(
        p for p in Path(data_dir).rglob("*")
        if p.name.endswith((".csv", ".csv.gz")) and not p.name.startswith("metaData")
    )


def load_journey(path):
    """Load one driving mission as a DataFrame, without changing any values."""
    df = pd.read_csv(path)
    if "time_iso" in df.columns:
        df["time_iso"] = pd.to_datetime(df["time_iso"], utc=True)
    return df