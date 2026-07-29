"""
Parses inbox-cards.csv and reply-cards.csv (project root) into a single
structured deck: data/deck.json

Both CSVs share the same two-column shape:
    card_number,text
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"

INBOX_CSV = ROOT / "inbox-cards.csv"
REPLY_CSV = ROOT / "reply-cards.csv"
OUT_PATH = DATA_DIR / "deck.json"


def parse_csv(path: Path, id_prefix: str) -> list:
    cards = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            text = row["text"].strip()
            if not text:
                continue
            cards.append({"id": f"{id_prefix}-{row['card_number'].strip()}", "text": text})
    return cards


def main():
    inbox_cards = parse_csv(INBOX_CSV, "I")
    reply_cards = parse_csv(REPLY_CSV, "R")
    deck = {"inbox": inbox_cards, "replies": reply_cards}
    OUT_PATH.write_text(json.dumps(deck, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(inbox_cards)} inbox cards, {len(reply_cards)} reply cards -> {OUT_PATH}")


if __name__ == "__main__":
    main()
