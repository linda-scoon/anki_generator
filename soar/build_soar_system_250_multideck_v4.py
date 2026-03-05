#!/usr/bin/env python3
"""
SOAR System V4 — multi-deck builder with per-example audio (gTTS).

Creates subdecks:
  Soar System::Lesson 001 ... Lesson 125

Supports variable number of examples per mold by scanning CSV columns like:
  m1_ex1_ru, m1_ex2_ru, ... and m2_exN_ru

Usage:
  pip install genanki gTTS
  python build_soar_system_250_multideck_v4.py --csv soar_system_lessons_001_125_v4.csv --out out/Soar_System_V4_250_multideck.apkg
"""

import csv
import re
from pathlib import Path

import genanki
from gtts import gTTS


def safe_name(s: str) -> str:
    s = s.strip()
    s = re.sub(r'\s+', ' ', s)
    return re.sub(r'[^0-9a-zA-Zа-яА-ЯёЁ_.-]+', '_', s)


def synth_audio(text_ru: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gTTS(text_ru, lang='ru').save(str(out_path))


def deck_id_for_lesson(base_id: int, lesson: int) -> int:
    return base_id + lesson


def iter_example_indexes(row: dict, prefix: str):
    idxs = set()
    for k in row.keys():
        m = re.match(rf"{prefix}_ex(\d+)_ru$", k)
        if m:
            idxs.add(int(m.group(1)))
    for i in sorted(idxs):
        yield i


def build_multideck(csv_path: Path, out_apkg: Path, deck_root_name: str = "Soar System") -> None:
    # New IDs so it doesn't collide with previous deck imports
    model = genanki.Model(
        1902422121,
        "SOAR System V4 – Lesson (2 molds) + Example Audio (250)",
        fields=[
            {"name": "Title"},
            {"name": "Mold1RU"},
            {"name": "Mold1EN"},
            {"name": "Mold2RU"},
            {"name": "Mold2EN"},
            {"name": "ExamplesHTML"},
            {"name": "Exercise"},
            {"name": "Tags"},
        ],
        templates=[
            {
                "name": "Lesson Card",
                "qfmt": "{{Title}}<br><br><b>{{Mold1RU}}</b><br>{{Mold2RU}}",
                "afmt": "{{FrontSide}}<hr id=answer>"
                        "<b>Meanings</b><br>"
                        "{{Mold1EN}}<br>{{Mold2EN}}<br><br>"
                        "{{ExamplesHTML}}<br><br>"
                        "<b>Do</b><br><pre style='white-space:pre-wrap'>{{Exercise}}</pre><br>"
                        "<span style='color:gray'>{{Tags}}</span>",
            }
        ],
    )

    decks = {}
    base_deck_id = 1902423000

    media_files = []
    media_dir = out_apkg.parent / "_soar_media_v4"
    media_dir.mkdir(parents=True, exist_ok=True)

    def build_examples(row: dict, prefix: str, label_ru: str, lesson: int) -> str:
        lines = [f"<b>{label_ru}</b><br>"]
        ex_num = 0
        for i in iter_example_indexes(row, prefix):
            ex_ru = row.get(f"{prefix}_ex{i}_ru", "").strip()
            ex_en = row.get(f"{prefix}_ex{i}_en", "").strip()
            if not ex_ru:
                continue
            ex_num += 1
            audio_filename = f"L{lesson:03d}_{prefix.upper()}_E{ex_num}_{safe_name(ex_ru)[:32]}.mp3"
            audio_path = media_dir / audio_filename
            if not audio_path.exists():
                synth_audio(ex_ru, audio_path)
            media_files.append(str(audio_path))
            audio_tag = f"[sound:{audio_filename}]"
            lines.append(
                f"{ex_num}. {ex_ru}<br>{audio_tag}<br>"
                f"<span style='color:gray'>{ex_en}</span><br><br>"
            )
        return "".join(lines)

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lesson = int(row["lesson"])
            deck_name = f"{deck_root_name}::Lesson {lesson:03d}"
            if lesson not in decks:
                decks[lesson] = genanki.Deck(deck_id_for_lesson(base_deck_id, lesson), deck_name)

            title = f"Lesson {lesson:03d}"
            m1ru = row["mold1_ru"].strip()
            m1en = row["mold1_en"].strip()
            m2ru = row["mold2_ru"].strip()
            m2en = row["mold2_en"].strip()
            exercise = row.get("exercise", "").strip()
            tags = row.get("tags", f"SoarSystem::L{lesson:03d}").strip()

            examples_html = build_examples(row, "m1", m1ru, lesson) + "<hr>" + build_examples(row, "m2", m2ru, lesson)

            note = genanki.Note(
                model=model,
                fields=[title, m1ru, m1en, m2ru, m2en, examples_html, exercise, tags],
                tags=[tags],
            )
            decks[lesson].add_note(note)

    pkg = genanki.Package(list(decks.values()))
    pkg.media_files = media_files
    pkg.write_to_file(str(out_apkg))
    print(f"Wrote: {out_apkg}")
    print(f"Decks created: {len(decks)} (one per lesson)")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="soar_system_lessons_001_125_v4.csv", help="Input lessons CSV path")
    p.add_argument("--out", default="Soar_System_V4_250_multideck.apkg", help="Output .apkg path")
    p.add_argument("--name", default="Soar System", help="Root deck name (subdecks will be created)")
    args = p.parse_args()

    build_multideck(Path(args.csv), Path(args.out), deck_root_name=args.name)
