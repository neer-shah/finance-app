"""Transaction categorisation with Jev (TypeSafe System One), plus your manual corrections.

Jev is asked one Choice question per unique description, following the "Classification
Using Confidence" pattern: the answer is only trusted when its confidence is high enough,
otherwise the transaction stays Uncategorised for the user to fix by hand.
"""
import asyncio
import json
import os

import pandas as pd
from dotenv import load_dotenv

load_dotenv()  # picks up TYPESAFE_API_KEY from .env

CACHE_FILE = "jev_cache.json"   
CONFIDENCE_THRESHOLD = 0.7
MAX_CONCURRENT_REQUESTS = 8
UNCATEGORISED = "Uncategorised"


def jev_available() -> bool:
    return bool(os.environ.get("TYPESAFE_API_KEY"))


def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict) -> None:
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


def _build_criteria(categories: dict) -> dict:
    """Category descriptions tell Jev what belongs in each category."""
    return {name: description or None for name, description in categories.items()}


async def _ask_jev(descriptions: list[str], criteria: dict) -> dict:
    from typesafe_sdk import AsyncTypeSafeClient, Choice

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def classify(client, description):
        async with semaphore:
            response = await client.system_one(
                state={"document": f"Bank transaction description: {description}"},
                questions={
                    "category": Choice(
                        instructions="Which spending category does this bank transaction belong to?",
                        criteria=criteria,
                    )
                },
            )
        answer = response.choices["category"]
        return description, {"category": answer.choice, "confidence": answer.confidence}

    async with AsyncTypeSafeClient() as client:
        results = await asyncio.gather(
            *(classify(client, d) for d in descriptions), return_exceptions=True
        )

    # Failed calls are skipped so they stay Uncategorised and are retried next time.
    return {r[0]: r[1] for r in results if not isinstance(r, Exception)}


def categorise_with_jev(descriptions: list[str], categories: dict) -> dict:
    """Return {description: {"category", "confidence"}} for each description, using a cache."""
    cache = _load_cache()
    criteria = _build_criteria(categories)
    # Re-ask if a cached category has since been deleted.
    todo = [d for d in set(descriptions) if d not in cache or cache[d]["category"] not in criteria]

    if todo and jev_available():
        cache.update(asyncio.run(_ask_jev(todo, criteria)))
        _save_cache(cache)

    return {d: cache[d] for d in descriptions if d in cache}


def categorise_transactions(
    df: pd.DataFrame, categories: dict, overrides: dict | None = None, use_jev: bool = True
) -> pd.DataFrame:
    """Add Category / Source / Confidence columns.

    Source is "manual" (a saved correction of yours), "jev" or "none".
    """
    df = df.copy()
    df["Category"] = UNCATEGORISED
    df["Source"] = "none"
    df["Confidence"] = pd.NA

    # 1. Your past manual corrections always win.
    overrides = {d.lower().strip(): c for d, c in (overrides or {}).items() if c in categories}
    matched = df["Description"].str.lower().str.strip().map(overrides)
    df.loc[matched.notna(), "Category"] = matched[matched.notna()]
    df.loc[matched.notna(), "Source"] = "manual"

    # 2. Jev handles everything else.
    if use_jev:
        unmatched = df["Source"] == "none"
        results = categorise_with_jev(df.loc[unmatched, "Description"].tolist(), categories)
        for idx in df.index[unmatched]:
            result = results.get(df.at[idx, "Description"])
            if result:
                df.at[idx, "Confidence"] = result["confidence"]
                if result["confidence"] >= CONFIDENCE_THRESHOLD and result["category"] != UNCATEGORISED:
                    df.at[idx, "Category"] = result["category"]
                    df.at[idx, "Source"] = "jev"

    return df
