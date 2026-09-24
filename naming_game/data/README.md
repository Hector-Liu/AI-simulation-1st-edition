# Label screening data

- `english_words.txt` — all 3–6 letter alphabetic entries of `/usr/share/dict/web2` (macOS, Webster's Second International, public domain), lower-cased. Snapshot bundled so label screening is reproducible on any machine.
- `first_names.txt` — `/usr/share/dict/propernames` (macOS, public domain), lower-cased.
- `brands.txt` — small hand-curated list of short brand names. Known limitation: not exhaustive, and words in languages other than English are not screened.
- `label_sets.json` — the **frozen** label sets (SPEC §5.3, R4). Never regenerate once runs exist.
