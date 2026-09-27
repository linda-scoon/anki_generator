#!/usr/bin/env python3
"""
Build daily-practice audio for the Christmas call.

For every card in cards.txt, each EN/RU pair becomes:

    English (English voice)  ->  thinking pause  ->  Russian (Russian voice)
        ->  the same Russian again, slowly, one word at a time, each word
            followed by its literal English meaning (from glossary.txt)

One card (a question plus your whole answer) = one MP3, so a long answer plays
as one continuous story instead of being chopped across files.

The pause is worked out from how long the Russian actually takes to say:

    pause = clamp(PAUSE_BASE + PAUSE_FACTOR * russian_seconds, PAUSE_MIN, PAUSE_MAX)

Defaults: 2 + 0.6 * seconds, never under 3s, never over 12s.
  "Нет."                        (~0.6s)  ->  3s
  a normal sentence             (~3s)    ->  3.8s
  a long sentence               (~8s)    ->  6.8s
  a very long sentence          (~15s)   -> 11s

Usage
-----
  pip install requests lameenc
  .env (in this folder or the repo root):
      ELEVENLABS_API_KEY=...
      RU_VOICE_ID=...
      EN_VOICE_ID=...

  python generate_audio.py --estimate          # what a run would cost, no API calls
  python generate_audio.py --list-voices       # show voice IDs in your ElevenLabs account
  python generate_audio.py --export            # write call_script.md to read / give ChatGPT
  python generate_audio.py

Every clip is cached in ./cache (one file per line). A re-run only pays for
lines that are new or edited, and tells you the cost and asks before spending.
Don't delete ./cache. Changing the voice, model, --ru-speed or --stability
counts as new audio, so those lines are paid for again.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
import wave
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SAMPLE_RATE = 24000          # both providers return 24 kHz, 16-bit, mono PCM
BYTES_PER_SEC = SAMPLE_RATE * 2

# ElevenLabs premade voice used for English if you don't pass --en-voice.
DEFAULT_EN_VOICE = "21m00Tcm4TlvDq8ikWAM"  # "Rachel"


# ---------------------------------------------------------------- .env

def load_env():
    """Read KEY=value lines from .env (this folder, then the repo root).
    Real environment variables win over the file."""
    for f in (HERE / ".env", HERE.parent / ".env"):
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.removeprefix("export ").partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def env(*names):
    return next((os.environ[n] for n in names if os.environ.get(n)), None)


# ---------------------------------------------------------------- cards file

def parse_cards(path):
    """Return [(section, [card, ...]), ...] where card = [(en, ru), ...]."""
    sections, section, card, pending_en = [], None, [], None

    def close_card():
        nonlocal card
        if card:
            if section is None:
                sys.exit(f"{path}: cards found before the first '## Section' line")
            section[1].append(card)
        card = []

    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if line.startswith("//"):
            continue
        if not line:
            close_card()
            continue
        if line.startswith("## "):
            close_card()
            section = (line[3:].strip(), [])
            sections.append(section)
            continue
        tag, _, text = line.partition(":")
        tag, text = tag.strip().upper(), text.strip()
        if tag == "EN":
            if pending_en is not None:
                sys.exit(f"{path}:{n}: EN line with no RU line after the previous EN")
            pending_en = text
        elif tag == "RU":
            if pending_en is None:
                sys.exit(f"{path}:{n}: RU line with no EN line before it")
            card.append((" ".join(pending_en.split()), text))
            pending_en = None
        else:
            sys.exit(f"{path}:{n}: expected 'EN:', 'RU:', '## Section', '//' or a blank line")
    if pending_en is not None:
        sys.exit(f"{path}: last EN line has no RU line")
    close_card()
    return sections


def strip_stress(text):
    """Remove stress marks (combining acute) - TTS voices read them oddly."""
    return unicodedata.normalize("NFC", text.replace("́", ""))


def slug(text, n=40):
    text = strip_stress(text).lower()
    text = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE).strip("_")
    return text[:n].rstrip("_") or "card"


# ---------------------------------------------------------------- TTS

class ElevenLabs:
    name = "elevenlabs"

    def __init__(self, key, model, stability, ru_speed):
        self.key, self.model, self.stability, self.ru_speed = key, model, stability, ru_speed

    def tts(self, text, voice, lang):
        body = {
            "text": text,
            "model_id": self.model,
            "voice_settings": {
                "stability": self.stability,
                "similarity_boost": 0.75,
                "speed": speed_for(self, lang),
            },
        }
        if "v2_5" in self.model:  # only the v2.5 models accept a language hint
            body["language_code"] = lang[:2]
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            params={"output_format": "pcm_24000"},
            headers={"xi-api-key": self.key},
            json=body,
            timeout=120,
        )
        if r.status_code != 200:
            sys.exit(f"ElevenLabs error {r.status_code}: {r.text[:500]}")
        return r.content

    def list_voices(self):
        r = requests.get("https://api.elevenlabs.io/v1/voices",
                         headers={"xi-api-key": self.key}, timeout=60)
        r.raise_for_status()
        for v in r.json()["voices"]:
            labels = ", ".join(f"{k}={val}" for k, val in (v.get("labels") or {}).items())
            print(f"{v['voice_id']}  {v['name']:<28} {labels}")


class OpenAI:
    name = "openai"

    def __init__(self, key, model):
        self.key, self.model = key, model

    def tts(self, text, voice, lang):
        body = {"model": self.model, "voice": voice, "input": text, "response_format": "pcm"}
        if lang.startswith("ru") and "gpt-4o" in self.model:
            body["instructions"] = ("You are a native Russian speaker from Moscow. "
                                    "Speak natural, clear, conversational Russian at a relaxed pace.")
            if lang == "ru-word":
                body["instructions"] += " This is a single word: say it slowly and clearly."
        r = requests.post("https://api.openai.com/v1/audio/speech",
                          headers={"Authorization": f"Bearer {self.key}"},
                          json=body, timeout=120)
        if r.status_code != 200:
            sys.exit(f"OpenAI error {r.status_code}: {r.text[:500]}")
        return r.content


def speed_for(engine, lang):
    """lang is "en", "ru" (full sentence) or "ru-word" (one word, for the slow replay)."""
    if lang == "ru":
        return getattr(engine, "ru_speed", 1.0)
    if lang == "ru-word":
        return getattr(engine, "word_speed", 1.0)
    return 1.0


def words_of(ru):
    """Russian line -> the words to replay slowly, one clip per word (cached across lines)."""
    out = []
    for w in strip_stress(ru).split():
        w = w.strip(".,!?:;«»\"()—–…")
        if w:
            out.append(w)
    return out


def load_glossary(path):
    """glossary.txt -> (default meanings, per-line overrides). See the top of that file."""
    defaults, per_line = {}, {}
    if not path.exists():
        return defaults, per_line
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("@"):
            ru, _, rest = line[1:].rpartition("|")
            words = {}
            for item in rest.split(";"):
                w, _, g = item.partition("=")
                if w.strip():
                    words[w.strip().lower()] = g.strip()
            per_line[strip_stress(ru.strip())] = words
        elif "=" in line:
            w, _, g = line.partition("=")
            defaults[strip_stress(w.strip()).lower()] = g.strip()
        else:
            sys.exit(f"{path}:{n}: expected 'word = meaning' or '@ line | word=meaning'")
    return defaults, per_line


def is_cyrillic(word):
    return any("\u0400" <= ch <= "\u04ff" for ch in word)


def cache_file(engine, text, voice, lang, cache_dir):
    """One file per (line, voice, settings). Same inputs -> same file -> no API call."""
    key = json.dumps([engine.name, getattr(engine, "model", ""), voice, lang, text,
                      speed_for(engine, lang),
                      getattr(engine, "stability", 0)], ensure_ascii=False)
    return cache_dir / (hashlib.sha1(key.encode()).hexdigest() + ".pcm")


def cached_tts(engine, text, voice, lang, cache_dir):
    f = cache_file(engine, text, voice, lang, cache_dir)
    if f.exists():
        return f.read_bytes(), False
    pcm = engine.tts(text, voice, lang)
    tmp = f.with_suffix(".part")      # write-then-rename: a crash never leaves a broken clip
    tmp.write_bytes(pcm)
    tmp.replace(f)
    return pcm, True


# ---------------------------------------------------------------- audio

def trim(pcm, threshold=400):
    """Cut the quiet lead-in/tail a TTS clip has, so single words sit close together."""
    n = len(pcm) // 2
    samples = memoryview(pcm).cast("h")
    start = next((i for i in range(n) if abs(samples[i]) > threshold), 0)
    end = next((i for i in range(n - 1, -1, -1) if abs(samples[i]) > threshold), n - 1)
    pad = int(SAMPLE_RATE * 0.05)
    return bytes(pcm[max(0, start - pad) * 2:min(n, end + pad) * 2])


def silence(seconds):
    return b"\x00\x00" * int(SAMPLE_RATE * seconds)


def seconds_of(pcm):
    return len(pcm) / BYTES_PER_SEC


def pause_for(ru_pcm, a):
    return max(a.pause_min, min(a.pause_max, a.pause_base + a.pause_factor * seconds_of(ru_pcm)))


def save(pcm, path):
    try:
        import lameenc
    except ImportError:
        path = path.with_suffix(".wav")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm)
        return path
    enc = lameenc.Encoder()
    enc.set_bit_rate(64)
    enc.set_in_sample_rate(SAMPLE_RATE)
    enc.set_channels(1)
    enc.set_quality(2)
    path.write_bytes(enc.encode(pcm) + enc.flush())
    return path


# ---------------------------------------------------------------- script export

CHATGPT_PROMPT = """\
> **Paste this to ChatGPT (voice mode), then attach this file:**
> You are my Russian colleague on a Christmas video call. Speak only Russian, use вы.
> Ask me the questions from this script, in order, one at a time, and wait for my answer.
> I'm learning my answers like a movie script, so after I answer, tell me in English
> if it didn't match my line, then say my line correctly in Russian once, slowly.
> Don't make up new questions or change my answers.
"""


def export_script(sections, path):
    """The same cards as the audio, as a readable script (stress marks kept)."""
    out = ["# Christmas call - my script", "", CHATGPT_PROMPT,
           "Stress marks (´) show the stressed syllable. Russians don't write them.", ""]
    for i, name, cards in sections:
        out += [f"## {i}. {name}", "", "| English | Русский |", "|---|---|"]
        for card in cards:
            for en, ru in card:
                out.append(f"| {en.replace('|', '/')} | {ru.replace('|', '/')} |")
            out.append("| | |")
        out[-1:] = [""]
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {path}")


# ---------------------------------------------------------------- main

def main():
    load_env()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cards", default=HERE / "cards.txt", type=Path)
    ap.add_argument("--out", default=HERE / "audio", type=Path)
    ap.add_argument("--provider", choices=["elevenlabs", "openai"], default="elevenlabs")
    ap.add_argument("--model", help="elevenlabs: eleven_multilingual_v2 (default, best) or "
                                    "eleven_flash_v2_5 (half price). openai: gpt-4o-mini-tts")
    ap.add_argument("--ru-voice", default=env("RU_VOICE_ID", "ELEVENLABS_RU_VOICE_ID"))
    ap.add_argument("--en-voice", default=env("EN_VOICE_ID", "ELEVENLABS_EN_VOICE_ID"))
    ap.add_argument("--ru-speed", type=float, default=0.9,
                    help="ElevenLabs Russian speaking speed, 0.7-1.2 (default 0.9)")
    ap.add_argument("--stability", type=float, default=0.5)
    ap.add_argument("--ru-repeat", type=int, default=1, help="say each Russian line N times")
    ap.add_argument("--no-words", action="store_true",
                    help="skip the slow word-by-word replay after each Russian line")
    ap.add_argument("--word-speed", type=float, default=0.75,
                    help="speaking speed of the word-by-word replay, 0.7-1.2 (default 0.75)")
    ap.add_argument("--word-gap", type=float, default=0.6, help="seconds between words (default 0.6)")
    ap.add_argument("--no-literal", action="store_true",
                    help="word-by-word replay without the English meaning after each word")
    ap.add_argument("--pause-base", type=float, default=2.0)
    ap.add_argument("--pause-factor", type=float, default=0.6)
    ap.add_argument("--pause-min", type=float, default=3.0)
    ap.add_argument("--pause-max", type=float, default=12.0)
    ap.add_argument("--section", help="only build sections whose name contains this text")
    ap.add_argument("--estimate", action="store_true", help="count characters, no API calls")
    ap.add_argument("--list-voices", action="store_true")
    ap.add_argument("--yes", action="store_true", help="don't ask before spending credits")
    ap.add_argument("--export", action="store_true",
                    help="write call_script.md (the readable script for ChatGPT), no API calls")
    a = ap.parse_args()

    # keep each section's real number so --section doesn't renumber folders
    sections = [(i, name, cards) for i, (name, cards) in enumerate(parse_cards(a.cards), 1)]
    if a.section:
        sections = [s for s in sections if a.section.lower() in s[1].lower()]

    if a.export:
        return export_script(sections, HERE / "call_script.md")

    if a.provider == "elevenlabs":
        key = env("ELEVENLABS_API_KEY", "ELEVEN_LABS_API_KEY", "ELEVENLABS_KEY", "XI_API_KEY")
        engine = ElevenLabs(key, a.model or "eleven_multilingual_v2", a.stability, a.ru_speed)
        en_voice, ru_voice = a.en_voice or DEFAULT_EN_VOICE, a.ru_voice
    else:
        key = env("OPENAI_API_KEY")
        engine = OpenAI(key, a.model or "gpt-4o-mini-tts")
        en_voice, ru_voice = a.en_voice or "alloy", a.ru_voice or "nova"

    engine.word_speed = a.word_speed

    def slow_words(ru):
        ws = [] if a.no_words else words_of(ru)
        return ws if len(ws) > 1 else []   # one-word lines ("Нет.") need no replay

    glossary, per_line = load_glossary(HERE / "glossary.txt")
    missing = set()

    def meaning(ru, word):
        """Literal English for one word of this line, or None (Latin words, --no-literal)."""
        if a.no_literal or not is_cyrillic(word):
            return None
        w = word.lower()
        g = per_line.get(strip_stress(ru), {}).get(w) or glossary.get(w)
        if not g:
            missing.add(w)
            return None
        return g.replace("-", " ")

    if a.list_voices:
        if not key or a.provider != "elevenlabs":
            sys.exit("--list-voices needs ELEVENLABS_API_KEY in your .env")
        return engine.list_voices()

    cache_dir = HERE / "cache"
    cache_dir.mkdir(exist_ok=True)

    # Work out, before spending anything, which clips are not in the cache yet.
    lines = [(en, "en", en_voice) for _, _, cards in sections for c in cards for en, _ in c]
    lines += [(strip_stress(ru), "ru", ru_voice) for _, _, cards in sections for c in cards for _, ru in c]
    lines += [(w, "ru-word", ru_voice) for _, _, cards in sections for c in cards for _, ru in c
              for w in slow_words(ru)]
    lines += [(m, "en", en_voice) for _, _, cards in sections for c in cards for _, ru in c
              for w in slow_words(ru) if (m := meaning(ru, w))]
    todo = {}
    for text, lang, voice in lines:
        f = cache_file(engine, text, voice, lang, cache_dir) if voice else None
        if f is None or not f.exists():
            todo[(text, lang)] = len(text)
    new_chars = sum(todo.values())
    ncards = sum(len(c) for _, _, c in sections)
    print(f"{len(sections)} sections, {ncards} cards, {len(set(lines))} unique clips "
          f"(sentences + single words for the slow replay)")
    print(f"Already generated: {len(set(lines)) - len(todo)} clips (free)")
    print(f"To generate now:   {len(todo)} clips, {new_chars:,} characters")
    if a.provider == "elevenlabs":
        rate = 0.5 if "flash" in engine.model or "turbo" in engine.model else 1
        print(f"Cost: ~{int(new_chars * rate):,} ElevenLabs credits ({engine.model})")
    if not ru_voice:
        print("(RU_VOICE_ID not set, so Russian lines are counted as not generated yet)")
    if missing:
        print(f"No meaning in glossary.txt for {len(missing)} words (said without one): "
              + ", ".join(sorted(missing)))
    if a.estimate:
        return

    if todo:
        if not key:
            sys.exit(f"Put the API key for {a.provider} in your .env first.")
        if not ru_voice:
            sys.exit("Put RU_VOICE_ID=... in your .env. Add a Russian voice from the ElevenLabs "
                     "Voice Library to 'My Voices', then run --list-voices to get its ID.")
        if not a.yes and input("Go ahead? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("Cancelled - nothing was spent.")

    a.out.mkdir(parents=True, exist_ok=True)
    all_tracks, new_calls = [], 0

    for si, name, cards in sections:
        folder = a.out / f"{si:02d}_{slug(name, 30)}"
        folder.mkdir(exist_ok=True)
        tracks = []
        for ci, card in enumerate(cards, 1):
            pcm = bytearray(silence(0.5))
            for en, ru in card:
                en_pcm, n1 = cached_tts(engine, en, en_voice, "en", cache_dir)
                ru_pcm, n2 = cached_tts(engine, strip_stress(ru), ru_voice, "ru", cache_dir)
                new_calls += n1 + n2
                pcm += en_pcm + silence(pause_for(ru_pcm, a))
                for r in range(a.ru_repeat):
                    pcm += ru_pcm + silence(1.0 if r < a.ru_repeat - 1 else 1.8)
                ws = slow_words(ru)
                if ws:
                    for w in ws:
                        w_pcm, n3 = cached_tts(engine, w, ru_voice, "ru-word", cache_dir)
                        new_calls += n3
                        pcm += trim(w_pcm)
                        m = meaning(ru, w)
                        if m:
                            m_pcm, n4 = cached_tts(engine, m, en_voice, "en", cache_dir)
                            new_calls += n4
                            pcm += silence(0.25) + trim(m_pcm)
                        pcm += silence(a.word_gap)
                    pcm += silence(1.8 - a.word_gap)
            out = save(bytes(pcm), folder / f"{si:02d}-{ci:02d}_{slug(card[0][0])}.mp3")
            tracks.append(out)
            print(f"  {out.relative_to(a.out)}  ({seconds_of(pcm):.0f}s)")
        (folder / "playlist.m3u").write_text(
            "\n".join(t.name for t in tracks) + "\n", encoding="utf-8")
        all_tracks += tracks

    if not a.section:
        # Drop MP3s left over from cards/sections that were renamed or moved.
        keep = {t.resolve() for t in all_tracks}
        for old in list(a.out.glob("*/*.mp3")) + list(a.out.glob("*/*.wav")):
            if old.resolve() not in keep:
                old.unlink()
        for d in a.out.iterdir():
            if d.is_dir() and not any(d.glob("*.mp3")) and not any(d.glob("*.wav")):
                for f in d.iterdir():
                    f.unlink()
                d.rmdir()
        (a.out / "all.m3u").write_text(
            "\n".join(str(t.relative_to(a.out)).replace("\\", "/") for t in all_tracks) + "\n",
            encoding="utf-8")
    print(f"\nDone: {len(all_tracks)} files in {a.out}  ({new_calls} new TTS calls, rest from cache)")


if __name__ == "__main__":
    main()
