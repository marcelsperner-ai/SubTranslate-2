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


_COLOR_RE = re.compile(r'<font\s+color="([^"]+)"', re.IGNORECASE)
_FONT_TAG_RE = re.compile(r'</?font[^>]*>', re.IGNORECASE)


def restore_colors(source, translated):
    """Setzt die font-Farben des Originals wieder ein, wenn die Übersetzung abweicht.

    Rückgabe: (Text, geändert). Nicht eindeutig zuordenbare Fälle bleiben unverändert.
    """
    source_colors = _COLOR_RE.findall(source)
    if not source_colors or _COLOR_RE.findall(translated) == source_colors:
        return translated, False
    plain_lines = [line.strip() for line in _FONT_TAG_RE.sub("", translated).splitlines() if line.strip()]
    source_lines = [line for line in source.splitlines() if line.strip()]
    if len(plain_lines) == len(source_lines):
        line_colors = [(_COLOR_RE.findall(line) or [None])[0] for line in source_lines]
    elif len(set(source_colors)) == 1:
        line_colors = [source_colors[0]] * len(plain_lines)
    else:
        return translated, False
    rebuilt = [
        f'<font color="{color}">{line}</font>' if color else line
        for line, color in zip(plain_lines, line_colors)
    ]
    return "\n".join(rebuilt), True
