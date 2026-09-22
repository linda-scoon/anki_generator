# Christmas call — daily listening practice

Each MP3 = one question + your answer:
**English → pause (you say it in Russian) → Russian**.
Pause = `6 + 1.5 × (length of the Russian audio in seconds)`, min 8s, max 25s.

## Run (Windows)

```
pip install -r requirements.txt
python generate_audio.py --estimate        # cost check, no API calls
python generate_audio.py --list-voices     # get your voice IDs
python generate_audio.py
```

`.env` (in `call_practice/` or the repo root):

```
ELEVENLABS_API_KEY=your_key
RU_VOICE_ID=russian_voice_id
EN_VOICE_ID=english_voice_id
```

Output: `audio/<section>/*.mp3`, a `playlist.m3u` per section and `audio/all.m3u`.

1. In ElevenLabs → Voice Library, filter Language = Russian, pick a native voice, "Add to My Voices".
2. `--list-voices` shows its ID.

Useful flags: `--section russian` (build one section), `--ru-speed 0.8` (slower Russian),
`--ru-repeat 2` (hear the Russian twice), `--model eleven_flash_v2_5` (half the credits),
`--provider openai` (uses `OPENAI_API_KEY`).

## The written script

`call_script.md` is the same script as a readable English | Russian table, with a
ChatGPT role-play prompt at the top. After editing `cards.txt`, refresh it (free):

```
python generate_audio.py --export
```

## Not paying twice

Each line's audio is saved once in `cache/`. Every run first prints how many lines are
new and what they'll cost, then asks `Go ahead? [y/N]` before calling ElevenLabs.
A re-run with nothing changed costs 0, and after an edit you only pay for the edited lines.

- Don't delete `cache/`.
- Changing the voice, `--model`, `--ru-speed` or `--stability` counts as new audio.
