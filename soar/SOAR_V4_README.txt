SOAR System V4 — FIXED EN + SPACING

Fixes vs V3:
- Example English lines are now real translations (not just the mold gloss).
- Spacing fixes for “что …” so you don’t get “чтоона”.

Files:
1) soar_molds_250_v4.csv
2) soar_system_lessons_001_125_v4.csv
3) build_soar_system_250_multideck_v4.py

Build:
  pip install genanki gTTS
  python build_soar_system_250_multideck_v4.py --csv soar_system_lessons_001_125_v4.csv --out out/Soar_System_V4_250_multideck.apkg
