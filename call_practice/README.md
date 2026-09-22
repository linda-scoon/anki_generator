# Christmas call — daily listening practice

Each MP3 = one question + your answer:
**English → pause (you say it in Russian) → Russian**.
Pause = `6 + 1.5 × (length of the Russian audio in seconds)`, min 8s, max 25s.

## Run (Windows)

```
pip install -r requirements.txt
set ELEVENLABS_API_KEY=your_key
python generate_audio.py --estimate        # cost check, no API calls
python generate_audio.py --list-voices     # get your voice IDs
python generate_audio.py --ru-voice RUSSIAN_ID --en-voice ENGLISH_ID
```

Output: `audio/<section>/*.mp3`, a `playlist.m3u` per section and `audio/all.m3u`.

1. In ElevenLabs → Voice Library, filter Language = Russian, pick a native voice, "Add to My Voices".
2. `--list-voices` shows its ID.

Useful flags: `--section russian` (build one section), `--ru-speed 0.8` (slower Russian),
`--ru-repeat 2` (hear the Russian twice), `--model eleven_flash_v2_5` (half the credits),
`--provider openai` (uses `OPENAI_API_KEY`).

Edit `cards.txt` and re-run — only changed lines cost credits (clips are cached in `cache/`).
