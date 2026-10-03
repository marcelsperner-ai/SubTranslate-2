import json
import os
import re

MIN_LETTERS = 8


def _lines(text):
    cleaned = re.sub(r"<[^>]+>", "", text or "")
    result = set()
    for line in cleaned.splitlines():
        normalized = re.sub(r"[\W_]+", " ", line, flags=re.UNICODE).strip().casefold()
        if sum(ch.isalpha() for ch in normalized) >= MIN_LETTERS:
            result.add(normalized)
    return result


def find_duplicate_suspects(source_texts, translated_texts):
    """Liefert Indexpaare (i, j), deren Übersetzung eine Zeile teilt, die Quellen aber nicht."""
    sources = [_lines(text) for text in source_texts]
    targets = [_lines(text) for text in translated_texts]
    pairs = []
    for i in range(len(targets)):
        for j in range(i + 1, len(targets)):
            if targets[i] & targets[j] and not sources[i] & sources[j]:
                pairs.append((i, j))
    return pairs


def review_path(outputs_dir, srt_name):
    return os.path.join(outputs_dir, "debug", srt_name.replace(".srt", "_review.json"))


def load_review_items(path):
    try:
        with open(path, encoding="utf-8") as review_file:
            return json.load(review_file)
    except (OSError, ValueError):
        return []


def save_review_items(path, items):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as review_file:
        json.dump(items, review_file, ensure_ascii=False, indent=1)
    os.replace(tmp_path, path)


def add_review_items(path, pairs, offset):
    """Fügt Verdachtspaare mit absoluten 1-basierten Cue-Nummern hinzu."""
    if not pairs:
        return 0
    items = load_review_items(path)
    known = {(item["cues"][0], item["cues"][1]) for item in items}
    added = 0
    for i, j in pairs:
        cues = [offset + i + 1, offset + j + 1]
        if tuple(cues) not in known:
            items.append({"cues": cues, "status": "open"})
            added += 1
    save_review_items(path, items)
    return added


def count_open(path):
    return sum(1 for item in load_review_items(path) if item.get("status") == "open")
