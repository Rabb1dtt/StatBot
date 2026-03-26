# -*- coding: utf-8 -*-
import argparse
import asyncio
import os
import sys
from typing import Any, Dict, List

# ensure project root is on sys.path when running from tools/
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fotmob_client import FotmobClient
import cyrtranslit


def collect_stat_items(obj: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if isinstance(obj, dict):
        if "items" in obj and isinstance(obj["items"], list):
            items.extend(obj["items"])
        for v in obj.values():
            items.extend(collect_stat_items(v))
    elif isinstance(obj, list):
        for v in obj:
            items.extend(collect_stat_items(v))
    return items


def summarize_items(items: List[Dict[str, Any]]) -> List[str]:
    seen = {}
    for item in items:
        key = str(item.get("localizedTitleId") or "").strip()
        title = str(item.get("title") or "").strip()
        if not key and not title:
            continue
        label = f"{key} | {title}".strip(" |")
        if label not in seen:
            seen[label] = {
                "format": item.get("statFormat"),
                "example": item.get("statValue"),
            }
    rows = []
    for label, meta in sorted(seen.items()):
        rows.append(f"{label}  (format={meta['format']}, example={meta['example']})")
    return rows


async def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect available FotMob stats for a player.")
    parser.add_argument("query", help="Player name (e.g., 'Kylian Mbappe' or 'Киллиан Мбаппе')")
    args = parser.parse_args()

    client = FotmobClient()
    await client.start()
    candidates = []
    candidates.extend(await client.search_players(args.query))
    translit = cyrtranslit.to_latin(args.query, "ru")
    if translit.lower() != args.query.lower():
        candidates.extend(await client.search_players(translit))

    if not candidates:
        print("Player not found.")
        await client.close()
        return

    # pick top by score if present
    candidates.sort(key=lambda c: c.get("score", 0), reverse=True)
    resolved = candidates[0]

    data = await client.fetch_player_data(int(resolved["id"]))
    first_season_stats = data.get("firstSeasonStats") or {}

    items = collect_stat_items(first_season_stats)
    print(f"Player: {resolved.get('name')} ({resolved.get('id')})")
    print(f"Position: {data.get('positionDescription')}")
    print(f"Items found: {len(items)}")
    print("\nAvailable stat keys/titles:")
    for line in summarize_items(items):
        print(line)

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
