"""Persistence for categories and categorised transactions."""
import json
import os

import pandas as pd

CATEGORY_FILE = "categories.json"
OVERRIDES_FILE = "overrides.json"
TRANSACTIONS_FILE = "transactions.csv"
KEY_COLUMNS = ["Date", "Description", "Paid out"]


# Category name -> plain-English description that tells Jev what belongs there.
# Descriptions are deliberately general (no merchant names) so new merchants still match.
DEFAULT_CATEGORIES = {
    "Uncategorised": "Does not clearly fit any other category",
    "ISA": "Transfers into ISAs, Lifetime ISAs or other savings and investment pots",
    "Travel": "Public transport, taxis, ride-hailing, trains, flights and other travel costs",
    "Groceries": "Supermarkets and food shops for cooking at home",
    "Eating Out": "Restaurants, cafes, bars, pubs, takeaways and food delivery",
    "Shopping": "Clothes, electronics, household goods and general retail or online shopping",
    "Bills & Utilities": "Energy, water, broadband, mobile phone, council tax and insurance",
    "Rent & Housing": "Rent, mortgage payments and home maintenance",
    "Subscriptions": "Recurring streaming, software, app and membership payments",
    "Entertainment": "Cinema, events, gaming, hobbies and leisure activities",
    "Health & Fitness": "Pharmacy, medical costs, gym memberships and sports",
    "Cash & Transfers": "Cash withdrawals and payments to individuals or other accounts",
    "Fees & Charges": "Bank fees, interest charges and fines",
}


def load_categories() -> dict:
    if os.path.exists(CATEGORY_FILE):
        with open(CATEGORY_FILE, "r") as f:
            categories = json.load(f)
        # Older versions stored a keyword list per category; convert to descriptions.
        return {
            name: (value if isinstance(value, str) else DEFAULT_CATEGORIES.get(name, ""))
            for name, value in categories.items()
        }
    return dict(DEFAULT_CATEGORIES)


def save_categories(categories: dict) -> None:
    with open(CATEGORY_FILE, "w") as f:
        json.dump(categories, f, indent=2)


def load_overrides() -> dict:
    """Manual corrections: exact transaction description -> category."""
    if os.path.exists(OVERRIDES_FILE):
        with open(OVERRIDES_FILE, "r") as f:
            return json.load(f)
    return {}


def save_overrides(overrides: dict) -> None:
    with open(OVERRIDES_FILE, "w") as f:
        json.dump(overrides, f, indent=2)


def load_saved_transactions() -> pd.DataFrame | None:
    if not os.path.exists(TRANSACTIONS_FILE):
        return None
    try:
        df = pd.read_csv(TRANSACTIONS_FILE, parse_dates=["Date"])
    except pd.errors.EmptyDataError:  # file was emptied by hand to clear the history
        return None
    if df.empty:
        return None
    return df.reset_index(drop=True)


def save_transactions(df: pd.DataFrame) -> None:
    df.to_csv(TRANSACTIONS_FILE, index=False)


def new_rows_only(new_df: pd.DataFrame, saved_df: pd.DataFrame | None) -> pd.DataFrame:
    """Drop rows from an upload that were already saved (e.g. overlapping statements)."""
    if saved_df is None or saved_df.empty:
        return new_df
    saved_keys = set(map(tuple, saved_df[KEY_COLUMNS].astype(str).values))
    new_keys = map(tuple, new_df[KEY_COLUMNS].astype(str).values)
    return new_df[[key not in saved_keys for key in new_keys]]
