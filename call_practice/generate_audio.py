#!/usr/bin/env python3
"""
Build daily-practice audio for the Christmas call.

For every card in cards.txt, each EN/RU pair becomes:

    English (English voice)  ->  thinking pause  ->  Russian (Russian voice)

One card (a question plus your whole answer) = one MP3, so a long answer plays
as one continuous story instead of being chopped across files.

The pause is worked out from how long the Russian actually takes to say:

    pause = clamp(PAUSE_BASE + PAUSE_FACTOR * russian_seconds, PAUSE_MIN, PAUSE_MAX)

Defaults: 6 + 1.5 * seconds, never under 8s, never over 25s.
  "Нет."                        (~0.6s)  ->  8s
  "Вы меня слышите?"            (~1.5s)  ->  8.3s
  a normal sentence             (~3s)    -> 10.5s
  a long sentence               (~8s)    -> 18s

Usage
-----
  pip install requests lameenc
  .env (in this folder or the repo root):
      ELEVENLABS_API_KEY=...
      RU_VOICE_ID=...
      EN_VOICE_ID=...

  python generate_audio.py --estimate          # count characters / cost, no API calls
  python generate_audio.py --list-voices       # show voice IDs in your ElevenLabs account
  python generate_audio.py

Every clip is cached in ./cache, so after editing cards.txt a re-run only pays
for the lines you changed.
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
            card.append((pending_en, text))
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
                "speed": self.ru_speed if lang == "ru" else 1.0,
            },
        }
        if "v2_5" in self.model:  # only the v2.5 models accept a language hint
            body["language_code"] = lang
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
        if lang == "ru" and "gpt-4o" in self.model:
            body["instructions"] = ("You are a native Russian speaker from Moscow. "
                                    "Speak natural, clear, conversational Russian at a relaxed pace.")
        r = requests.post("https://api.openai.com/v1/audio/speech",
                          headers={"Authorization": f"Bearer {self.key}"},
                          json=body, timeout=120)
        if r.status_code != 200:
            sys.exit(f"OpenAI error {r.status_code}: {r.text[:500]}")
        return r.content


def cached_tts(engine, text, voice, lang, cache_dir):
    key = json.dumps([engine.name, getattr(engine, "model", ""), voice, lang, text,
                      getattr(engine, "ru_speed", 1.0) if lang == "ru" else 1.0,
                      getattr(engine, "stability", 0)], ensure_ascii=False)
    f = cache_dir / (hashlib.sha1(key.encode()).hexdigest() + ".pcm")
    if f.exists():
        return f.read_bytes(), False
    pcm = engine.tts(text, voice, lang)
    f.write_bytes(pcm)
    return pcm, True


# ---------------------------------------------------------------- audio

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
    ap.add_argument("--pause-base", type=float, default=6.0)
    ap.add_argument("--pause-factor", type=float, default=1.5)
    ap.add_argument("--pause-min", type=float, default=8.0)
    ap.add_argument("--pause-max", type=float, default=25.0)
    ap.add_argument("--section", help="only build sections whose name contains this text")
    ap.add_argument("--estimate", action="store_true", help="count characters, no API calls")
    ap.add_argument("--list-voices", action="store_true")
    a = ap.parse_args()

    # keep each section's real number so --section doesn't renumber folders
    sections = [(i, name, cards) for i, (name, cards) in enumerate(parse_cards(a.cards), 1)]
    if a.section:
        sections = [s for s in sections if a.section.lower() in s[1].lower()]

    if a.estimate:
        en = sum(len(e) for _, _, cards in sections for c in cards for e, _ in c)
        ru = sum(len(strip_stress(r)) for _, _, cards in sections for c in cards for _, r in c)
        ncards = sum(len(c) for _, _, c in sections)
        print(f"{len(sections)} sections, {ncards} cards")
        print(f"characters: English {en:,} + Russian {ru:,} = {en + ru:,}")
        print(f"ElevenLabs credits: multilingual_v2 ~{en + ru:,}, flash_v2_5 ~{(en + ru) // 2:,}")
        print(f"OpenAI gpt-4o-mini-tts: roughly ${(en + ru) / 1e6 * 15:.2f}")
        return

    if a.provider == "elevenlabs":
        key = env("ELEVENLABS_API_KEY", "ELEVEN_LABS_API_KEY", "ELEVENLABS_KEY", "XI_API_KEY") or sys.exit(
            "Put ELEVENLABS_API_KEY=... in your .env first.")
        engine = ElevenLabs(key, a.model or "eleven_multilingual_v2", a.stability, a.ru_speed)
        if a.list_voices:
            return engine.list_voices()
        en_voice = a.en_voice or DEFAULT_EN_VOICE
        ru_voice = a.ru_voice or sys.exit(
            "Pass --ru-voice <ID>. Add a Russian voice from the ElevenLabs Voice Library to "
            "'My Voices', then run --list-voices to get its ID.")
    else:
        key = env("OPENAI_API_KEY") or sys.exit("Put OPENAI_API_KEY=... in your .env first.")
        engine = OpenAI(key, a.model or "gpt-4o-mini-tts")
        en_voice, ru_voice = a.en_voice or "alloy", a.ru_voice or "nova"

    cache_dir = HERE / "cache"
    cache_dir.mkdir(exist_ok=True)
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
            out = save(bytes(pcm), folder / f"{si:02d}-{ci:02d}_{slug(card[0][0])}.mp3")
            tracks.append(out)
            print(f"  {out.relative_to(a.out)}  ({seconds_of(pcm):.0f}s)")
        (folder / "playlist.m3u").write_text(
            "\n".join(t.name for t in tracks) + "\n", encoding="utf-8")
        all_tracks += tracks

    (a.out / "all.m3u").write_text(
        "\n".join(str(t.relative_to(a.out)).replace("\\", "/") for t in all_tracks) + "\n",
        encoding="utf-8")
    print(f"\nDone: {len(all_tracks)} files in {a.out}  ({new_calls} new TTS calls, rest from cache)")


if __name__ == "__main__":
    main()
