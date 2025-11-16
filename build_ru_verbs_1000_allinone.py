#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
All-in-one builder for: Russian Verbs 1000 - Literal & Audio
============================================================
This script:
1) Auto-generates ~1,000 Russian verbs grouped by root with short phrases + literal English.
2) Builds an Anki deck (.apkg) with audio for each phrase (gTTS by default, optional eSpeak or none).
3) Saves the underlying CSV for your records.

Usage
-----
pip install genanki pandas gTTS
# (optional) install espeak-ng if you want offline TTS and use --espeak

python build_ru_verbs_1000_allinone.py --out Russian_Verbs_1000_Literal.apkg
# or to skip audio:
python build_ru_verbs_1000_allinone.py --out deck.apkg --no-audio
# or to use espeak-ng (must be installed):
python build_ru_verbs_1000_allinone.py --out deck.apkg --espeak

Outputs
-------
- ./russian_verbs_1000.csv  (root_tag,russian,english_gloss,phrase_ru,literal_en)
- ./Russian_Verbs_1000_Literal.apkg  (or name you choose with --out)

Card design (RU → EN)
---------------------
Front:   Russian verb (infinitive)
Back:    English gloss
         Russian example phrase
         Literal English translation
         Audio (sentence)

Literal translations are deliberately "word-for-word-ish" per request, to reinforce Russian phrasing.

Note
----
Generator uses productive prefixes + curated lists. Not every combo is equally frequent; edit CSV as desired and rebuild.
"""

import argparse
import csv
import os
import random
import re
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

try:
    import genanki
except Exception as e:
    raise SystemExit("Please 'pip install genanki' first. Error: {}".format(e))

PREFIXES = ["по", "про", "пере", "под", "при", "вы", "за", "на", "от", "до", "об", "с", "у", "вз", "в"]

BASE_VERBS: List[Tuple[str, str, str]] = [
    ("дел-", "делать", "to do; to make"),
    ("сказ-", "сказать", "to say (pfv)"),
    ("говор-", "говорить", "to speak; to talk"),
    ("ид-", "идти", "to go (uni-dir)"),
    ("ход-", "ходить", "to go (multi-dir)"),
    ("вид-", "видеть", "to see"),
    ("смотр-", "смотреть", "to watch; to look"),
    ("дум-", "думать", "to think"),
    ("знал-", "знать", "to know"),
    ("пис-", "писать", "to write"),
    ("читал-", "читать", "to read"),
    ("работ-", "работать", "to work"),
    ("жил-", "жить", "to live"),
    ("хот-", "хотеть", "to want"),
    ("мочь", "мочь", "to be able; can"),
    ("брать", "брать", "to take"),
    ("взять", "взять", "to take (pfv)"),
    ("давать", "давать", "to give"),
    ("дать", "дать", "to give (pfv)"),
    ("есть", "есть", "to eat"),
    ("пить", "пить", "to drink"),
    ("сто-", "стоять", "to stand"),
    ("сид-", "сидеть", "to sit"),
    ("леж-", "лежать", "to lie (be lying)"),
    ("став-", "ставить", "to put; to set"),
    ("постав-", "поставить", "to put; to place (pfv)"),
    ("беж-", "бежать", "to run (uni-dir)"),
    ("езд-", "ездить", "to go by vehicle (multi-dir)"),
    ("ехать", "ехать", "to go by vehicle (uni-dir)"),
    ("начин-", "начинать", "to begin"),
    ("нач-", "начать", "to begin (pfv)"),
    ("конч-", "кончать", "to finish"),
    ("законч-", "закончить", "to finish (pfv)"),
    ("покуп-", "покупать", "to buy"),
    ("куп-", "купить", "to buy (pfv)"),
    ("продав-", "продавать", "to sell"),
    ("продать", "продать", "to sell (pfv)"),
    ("уч-", "учиться", "to study; to learn"),
    ("уч-", "учить", "to teach; to learn"),
    ("помог-", "помогать", "to help"),
    ("помочь", "помочь", "to help (pfv)"),
    ("игр-", "играть", "to play"),
    ("слуш-", "слушать", "to listen"),
    ("слыш-", "слышать", "to hear"),
    ("показыв-", "показывать", "to show"),
    ("показ-", "показать", "to show (pfv)"),
    ("брос-", "бросать", "to throw"),
    ("брос-", "бросить", "to throw (pfv)"),
    ("держ-", "держать", "to hold"),
    ("иск-", "искать", "to search; to look for"),
    ("най-", "найти", "to find (pfv)"),
    ("плат-", "платить", "to pay"),
    ("откры-", "открывать", "to open"),
    ("откры-", "открыть", "to open (pfv)"),
    ("закры-", "закрывать", "to close"),
    ("закры-", "закрыть", "to close (pfv)"),
    ("ждать", "ждать", "to wait"),
    ("приглаш-", "приглашать", "to invite"),
    ("приглас-", "пригласить", "to invite (pfv)"),
    ("провер-", "проверять", "to check; to verify"),
    ("провер-", "проверить", "to check (pfv)"),
    ("помнить", "помнить", "to remember"),
    ("забыв-", "забывать", "to forget"),
    ("забы-", "забыть", "to forget (pfv)"),
    ("спраш-", "спрашивать", "to ask (a question)"),
    ("спрос-", "спросить", "to ask (pfv)"),
    ("отвеч-", "отвечать", "to answer"),
    ("ответ-", "ответить", "to answer (pfv)"),
    ("жел-", "желать", "to wish"),
    ("звон-", "звонить", "to call (on the phone)"),
    ("позвон-", "позвонить", "to call (pfv)"),
    ("сним-", "снимать", "to remove; to take off; to rent"),
    ("снят-", "снять", "to remove; to take off (pfv)"),
    ("клад-", "класть", "to lay; to put"),
    ("полож-", "положить", "to put (pfv)"),
    ("мысл-", "мыслить", "to think (abstract)"),
    ("получ-", "получать", "to receive; to get"),
    ("получ-", "получить", "to receive (pfv)"),
    ("отправ-", "отправлять", "to send"),
    ("отправ-", "отправить", "to send (pfv)"),
    ("приним-", "принимать", "to accept; to take (medicine)"),
    ("прин-", "принять", "to accept; to take (pfv)"),
    ("реш-", "решать", "to decide; to solve"),
    ("реш-", "решить", "to decide; to solve (pfv)"),
    ("мен-", "менять", "to change"),
    ("помен-", "поменять", "to change (pfv)"),
    ("объясн-", "объяснять", "to explain"),
    ("объясн-", "объяснить", "to explain (pfv)"),
    ("готов-", "готовить", "to cook; to prepare"),
    ("приготов-", "приготовить", "to prepare (pfv)"),
    ("путеш-", "путешествовать", "to travel"),
    ("кат-", "кататься", "to ride; to skate"),
]

CURATED_DERIVS = {
    "идти": [
        ("войти", "to enter (pfv)"),
        ("выйти", "to exit (pfv)"),
        ("прийти", "to come (pfv)"),
        ("уйти", "to leave (pfv)"),
        ("зайти", "to stop by (pfv)"),
        ("подойти", "to approach (pfv)"),
        ("перейти", "to cross (pfv)"),
        ("сойти", "to step down (pfv)"),
        ("найтись", "to be found (pfv)"),
    ],
    "ходить": [
        ("приходить", "to come"),
        ("уходить", "to leave"),
        ("заходить", "to drop by"),
        ("подходить", "to approach; to fit"),
        ("переходить", "to cross"),
        ("входить", "to enter"),
        ("выходить", "to exit; to go out"),
        ("обходить", "to go around"),
        ("проходить", "to pass; to go through"),
        ("доходить", "to reach; to get to"),
        ("отходить", "to move away; depart"),
        ("находить", "to find"),
    ],
    "говорить": [
        ("поговорить", "to have a talk (pfv)"),
        ("договориться", "to come to terms (pfv)"),
        ("оговориться", "to misspeak (pfv)"),
        ("переговорить", "to talk over (pfv)"),
        ("рассказать", "to tell (pfv)"),
        ("досказать", "to finish saying (pfv)"),
        ("сказать", "to say (pfv)"),
    ],
    "видеть": [
        ("увидеть", "to see (pfv)"),
        ("предвидеть", "to foresee"),
        ("перевидать", "to see many (colloq)"),
        ("видеться", "to see each other"),
        ("рассмотреть", "to examine (pfv)"),
    ],
    "писать": [
        ("записать", "to write down (pfv)"),
        ("подписать", "to sign (pfv)"),
        ("переписать", "to rewrite (pfv)"),
        ("выписать", "to prescribe; to write out (pfv)"),
        ("написать", "to write (pfv)"),
        ("дописать", "to finish writing (pfv)"),
        ("описать", "to describe (pfv)"),
        ("прописать", "to register; to prescribe (pfv)"),
        ("списать", "to copy; to plagiarize (pfv)"),
    ],
    "читать": [
        ("прочитать", "to read (pfv)"),
        ("перечитать", "to reread (pfv)"),
        ("зачитать", "to read out (pfv)"),
        ("дочитать", "to finish reading (pfv)"),
        ("начитать", "to record readings (pfv)"),
    ],
    "работать": [
        ("сработать", "to work out (pfv)"),
        ("переработать", "to rework; to overwork (pfv)"),
        ("заработать", "to earn; to start working (pfv)"),
        ("отработать", "to work off; to perfect (pfv)"),
        ("доработать", "to finalize; to refine (pfv)"),
        ("проработать", "to work through; to work for (time) (pfv)"),
    ],
    "есть": [
        ("съесть", "to eat up (pfv)"),
        ("доесть", "to finish eating (pfv)"),
        ("переесть", "to overeat (pfv)"),
        ("поесть", "to eat a bit (pfv)"),
    ],
    "пить": [
        ("выпить", "to drink up (pfv)"),
        ("попить", "to drink a bit (pfv)"),
        ("запить", "to wash down (pfv)"),
        ("перепить", "to outdrink; to overdrink (pfv)"),
    ],
    "брать": [
        ("взять", "to take (pfv)"),
        ("забрать", "to take away (pfv)"),
        ("собрать", "to gather (pfv)"),
        ("набрать", "to dial; to gather (pfv)"),
        ("подобрать", "to pick up (pfv)"),
        ("отобрать", "to select; to take away (pfv)"),
        ("перебрать", "to sort (pfv)"),
        ("выбрать", "to choose (pfv)"),
    ],
    "давать": [
        ("отдавать", "to give back"),
        ("передавать", "to pass; to transmit"),
        ("раздавать", "to hand out"),
        ("даваться", "to be given; to come easy"),
    ],
    "дать": [
        ("отдать", "to give back (pfv)"),
        ("передать", "to pass; to transmit (pfv)"),
        ("выдать", "to issue (pfv)"),
        ("передаться", "to be transmitted (pfv)"),
    ],
    "спрашивать": [
        ("спросить", "to ask (pfv)"),
        ("расспросить", "to question thoroughly (pfv)"),
        ("переспросить", "to ask again (pfv)"),
    ],
    "слушать": [
        ("послушать", "to listen (pfv)"),
        ("выслушать", "to listen out (pfv)"),
        ("прослушать", "to listen through; to miss (pfv)"),
    ],
    "смотреть": [
        ("посмотреть", "to watch (pfv)"),
        ("рассмотреть", "to examine (pfv)"),
        ("пересмотреть", "to reconsider; to rewatch (pfv)"),
        ("насмотреться", "to have seen enough (pfv)"),
    ],
}

PHRASE_TEMPLATES = [
    ("Я хочу {inf}.", "I want {inf}."),
    ("Он может {inf}.", "He can {inf}."),
    ("Мы будем {inf} завтра.", "We will {inf} tomorrow."),
    ("Я не хочу {inf} сегодня.", "I not want {inf} today."),
    ("Пожалуйста, не надо {inf}.", "Please, not need {inf}."),
]

def build_candidate_forms():
    candidates = []

    for root, inf, gloss in BASE_VERBS:
        candidates.append((root, inf, gloss))

    for base_inf, pairs in CURATED_DERIVS.items():
        root = next((r for r, v, g in BASE_VERBS if v == base_inf), base_inf[:3] + "-")
        for v, g in pairs:
            candidates.append((root, v, g))

    def add_pref(root: str, inf: str, gloss_base: str):
        for p in PREFIXES:
            formed = p + inf
            if formed == inf:
                continue
            candidates.append((root, formed, f"{gloss_base} (prefixed)"))

    for root, inf, gloss in BASE_VERBS:
        if inf in CURATED_DERIVS:
            continue
        add_pref(root, inf, gloss)

    seen = set()
    uniq = []
    for root, v, g in candidates:
        if v not in seen:
            uniq.append((root, v, g))
            seen.add(v)
    return uniq

def make_phrases(verb: str, idx: int):
    t_ru, t_en = PHRASE_TEMPLATES[idx % len(PHRASE_TEMPLATES)]
    return t_ru.format(inf=verb), t_en.format(inf=verb)

def safe_name(s: str) -> str:
    return re.sub(r'[^0-9a-zA-Zа-яА-ЯёЁ_.-]+', '_', s)

def synth_audio_gtts(text_ru: str, path: Path):
    from gtts import gTTS
    tts = gTTS(text_ru, lang='ru')
    tts.save(str(path))

def synth_audio_espeak(text_ru: str, path: Path):
    import subprocess
    wav = str(path.with_suffix('.wav'))
    subprocess.run(["espeak-ng", "-v", "ru", "-s", "150", "-w", wav, text_ru], check=True)

def build_anki(deck_name: str, rows, out_apkg: Path, audio_mode: str = "gtts"):
    model = genanki.Model(
        1607392321,
        "RU Verbs – Literal & Audio",
        fields=[
            {"name": "Russian"},
            {"name": "English"},
            {"name": "PhraseRU"},
            {"name": "LiteralEN"},
            {"name": "Audio"},
            {"name": "Tags"},
        ],
        templates=[
            {
                "name": "RU→EN Verb",
                "qfmt": "<div style='font-size:28px'>{{Russian}}</div>",
                "afmt": """
<div style='font-size:24px'><b>{{English}}</b></div>
<div style='margin-top:8px'>{{PhraseRU}}</div>
<div style='color:#555'>Literal: {{LiteralEN}}</div>
<div style='margin-top:8px'>{{Audio}}</div>
<div style='font-size:12px;color:#888;margin-top:8px'>{{Tags}}</div>
                """,
            }
        ],
        css=".card { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; font-size: 20px; color: #222; background: #fff; }",
    )
    deck = genanki.Deck(2059400121, deck_name)

    media_dir = out_apkg.parent / (out_apkg.stem + "_media")
    media_dir.mkdir(parents=True, exist_ok=True)
    media_files = []

    for i, r in enumerate(rows):
        ru = r["russian"]
        en = r["english_gloss"]
        phr_ru = r["phrase_ru"]
        lit_en = r["literal_en"]
        tag = r["root_tag"]

        audio_html = ""
        if audio_mode != "none":
            fname = f"{safe_name(ru)}_{i}.mp3" if audio_mode == "gtts" else f"{safe_name(ru)}_{i}.wav"
            outp = media_dir / fname
            if audio_mode == "gtts":
                synth_audio_gtts(phr_ru, outp)
            elif audio_mode == "espeak":
                synth_audio_espeak(phr_ru, outp)
            media_files.append(str(outp))
            audio_html = f"[sound:{outp.name}]"

        note = genanki.Note(
            model=model,
            fields=[ru, en, phr_ru, lit_en, audio_html, tag],
            tags=[tag] if tag else [],
        )
        deck.add_note(note)

    pkg = genanki.Package(deck)
    if media_files:
        pkg.media_files = media_files
    pkg.write_to_file(str(out_apkg))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="Russian_Verbs_1000_Literal.apkg", help="Output .apkg filename")
    ap.add_argument("--no-audio", action="store_true", help="Disable audio generation")
    ap.add_argument("--espeak", action="store_true", help="Use eSpeak NG (offline) instead of gTTS")
    ap.add_argument("--deck-name", default="Russian Verbs 1000 – Literal & Audio", help="Deck name")
    args = ap.parse_args()

    audio_mode = "gtts"
    if args.no_audio:
        audio_mode = "none"
    elif args.espeak:
        audio_mode = "espeak"

    # Generate candidates and pick 1000
    cands = build_candidate_forms()

    rows = []
    seen = set()
    for root, v, g in cands:
        if v in seen:
            continue
        seen.add(v)
        phr_ru, lit_en = make_phrases(v, len(rows))
        rows.append({
            "root_tag": root,
            "russian": v,
            "english_gloss": g,
            "phrase_ru": phr_ru,
            "literal_en": lit_en,
        })
        if len(rows) >= 1000:
            break

    # If fewer than 1000, loop again
    i = 0
    while len(rows) < 1000:
        root, v, g = cands[i % len(cands)]
        if v not in seen:
            seen.add(v)
            phr_ru, lit_en = make_phrases(v, len(rows))
            rows.append({
                "root_tag": root,
                "russian": v,
                "english_gloss": g,
                "phrase_ru": phr_ru,
                "literal_en": lit_en,
            })
        i += 1

    # Save CSV
    csv_path = Path("russian_verbs_1000.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["root_tag","russian","english_gloss","phrase_ru","literal_en"])
        writer.writeheader()
        writer.writerows(rows)

    # Build deck
    out_apkg = Path(args.out)
    build_anki(args.deck_name, rows, out_apkg, audio_mode=audio_mode)

    print(f"Generated CSV: {csv_path.resolve()} ({len(rows)} rows)")
    print(f"Built deck:   {out_apkg.resolve()}")
    if audio_mode != "none":
        print(f"Audio:        {'gTTS' if audio_mode=='gtts' else 'eSpeak NG'}")

if __name__ == "__main__":
    main()
