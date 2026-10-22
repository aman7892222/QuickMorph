# QuickMorph — right-click any file → PDF

**View as PDF** or **Convert to PDF** straight from the right-click menu in Windows Explorer and the macOS Finder.
Markdown (with math and diagrams), notebooks, Word files, CSV, code, logs, images and 80+ other formats become a clean,
paginated PDF in about a second.

- **Zero background load** – nothing runs until you click. No service, no tray icon, no daemon: **0 MB RAM idle**.
- **Light enough for a 4 GB / Core i3 laptop** – it drives the browser you already have instead of bundling one.
  One conversion peaks at **~275 MB RAM** (7 short-lived processes), and selecting 50 files still runs **one browser
  at a time**, so the PC stays responsive.
- **Fast** – ~0.8 s per file once warm, ~1.5 s for the first one (measured on a Ryzen 7 laptop; an older i3 is
  roughly 2–3× slower).
- **Works offline and keeps your files private** – math (KaTeX) and diagrams (Mermaid) are bundled; nothing is uploaded.
- **Safe** – scripts inside documents never run, a document can't read your other files, and an existing PDF that
  QuickMorph didn't make is never overwritten. See [Security](#security).

---

## What it converts

| Category | Extensions |
| :--- | :--- |
| **Markdown & markup** | `.md` `.markdown` `.mdown` `.mkd` `.mdx` `.rst` `.html` `.htm` `.xhtml` |
| **Notebooks & data** | `.ipynb` `.csv` `.tsv` `.json` `.jsonc` `.yaml` `.yml` `.toml` `.xml` |
| **Documents** | `.docx` · and with Pandoc: `.odt` `.rtf` `.epub` `.org` `.tex` |
| **Text & config** | `.txt` `.log` `.text` `.nfo` `.ini` `.cfg` `.conf` `.env` `.properties` · any other text file |
| **Images** | `.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` `.svg` |
| **Source code** | `.py` `.js` `.ts` `.tsx` `.jsx` `.rs` `.go` `.c` `.cpp` `.h` `.cs` `.java` `.kt` `.swift` `.rb` `.php` `.sh` `.ps1` `.sql` `.css` `.scss` `.lua` `.r` `.dart` `.vue` `.svelte` `.tf` … (40+) |

Markdown gets the full GitHub treatment: tables, task lists, footnotes, alerts (`> [!NOTE]`), `<details>`,
KaTeX math (`$E=mc^2$`, while `$5 and $10` stays text), Mermaid diagrams, relative and Obsidian `![[image.png]]`
images. Wide CSVs switch to landscape with a repeating header row. Code gets line numbers and syntax colours.
Long documents get PDF bookmarks from their headings.

---

## Install

You need **Python 3.9+** and **one browser engine** — which nearly every computer already has:

| | Used automatically, in this order |
| --- | --- |
| **Windows** | Microsoft Edge (built into Windows 10/11) → Chrome → Brave → Chromium → Vivaldi → Firefox |
| **macOS** | Chrome → Edge → Brave → Chromium → Vivaldi → **the Mac's built-in WebKit (Safari's engine)** → Firefox |
| **Linux** | Chrome / Chromium / Edge / Brave → Firefox |

So a Mac with only Safari works, and a PC where Edge was removed works with any of the others.

Get the files with the green **Code** button → *Download ZIP* (then unzip), or:

```bash
git clone https://github.com/aman7892222/QuickMorph.git
```

### Windows

1. Download this repository and unzip it.
2. Double-click **`Install.cmd`**. No admin rights needed — it only touches your own user account.
3. Right-click any file → **View as PDF** or **Convert to PDF**.
   On Windows 11 they are under **Show more options** (or **Shift + right-click**).
   Prefer them directly in the menu? Run `Install.cmd --classic-menu`; it takes effect after you sign out and back in.

> QuickMorph never restarts Explorer — your desktop and taskbar are left alone.

### macOS

1. Download and unzip this repository.
2. Open **Terminal** in that folder and run `python3 install.py`
   (or right-click **`Install.command`** → *Open*).
3. In Finder, right-click a file → **Quick Actions** → **View as PDF** / **Convert to PDF**.
   Not listed? *System Settings → Privacy & Security → Extensions → Finder* and tick both.
   The first time, macOS may ask whether Python may access the folder — click *Allow*.

### Linux / command line (all systems)

```bash
python3 install.py
```

then convert from a terminal (`--action view` opens the PDF instead of saving it next to the file):

```bash
python3 -m quickmorph --action save notes.md report.ipynb data.csv
```

### Optional: Pandoc for `.odt` `.rtf` `.epub` `.org` `.tex`

```bash
python install.py --with-pandoc
```

(Or install Pandoc yourself: `winget install pandoc`, `brew install pandoc`, `sudo apt install pandoc`.)

---

## Using it

- **View as PDF** renders into a temp folder and opens your PDF viewer. Previews older than a day are cleaned up.
- **Convert to PDF** writes `name.pdf` next to the file. If a `name.pdf` already exists that QuickMorph didn't make
  (or that came from a different file), it writes `name (1).pdf` instead — your own PDFs are never replaced.
  If the old PDF is open in a viewer, it also picks a new name instead of failing.
- **Select many files** and convert them in one go; they are queued and done one by one.

### Settings (optional)

| Variable | Meaning | Default |
| --- | --- | --- |
| `QUICKMORPH_PAPER` | `A4`, `Letter`, `Legal`, `A3`, `A5` … | Letter in the US/Canada/…, A4 elsewhere |
| `QUICKMORPH_QUIET` | `1` = no "Saved" pop-up | off |
| `QUICKMORPH_BROWSER` | full path to a Chromium-based browser to use | auto-detected |
| `QUICKMORPH_ENGINE` | force `chromium`, `webkit` or `firefox` | best available |
| `QUICKMORPH_MAX_MB` | refuse text files larger than this (keeps weak PCs responsive) | `10` |
| `QUICKMORPH_TIMEOUT` | seconds before giving up on one file | `120` |

Set one on Windows with `setx QUICKMORPH_PAPER Letter`, on macOS with `launchctl setenv QUICKMORPH_PAPER Letter`.

---

## Uninstall

Double-click **`Uninstall.cmd`** (Windows) or run `python3 install.py --uninstall` (macOS/Linux).
It removes the menu entries and QuickMorph's own folder. A Windows 11 classic-menu setting is only removed if
QuickMorph turned it on — if you set it yourself, it stays exactly as it was.

---

## Security

QuickMorph opens files you may have downloaded from anywhere, so it treats every document as untrusted:

- **No document scripts.** Generated pages carry a strict Content-Security-Policy: only QuickMorph's own bundled
  KaTeX/Mermaid may run. `<script>`, `onerror=…` and similar tricks in Markdown, notebooks or Word files are ignored,
  and nothing can be fetched, framed or submitted. Mermaid runs in `strict` mode.
- **No reading your other files.** The browser runs without file-access exceptions, so an `.html` file can't read
  its neighbours (an earlier version allowed that). Pandoc runs with `--sandbox`; docutils ignores `docutils.conf`
  files and file inclusion.
- **No planted programs.** QuickMorph leaves the clicked folder before starting any helper and calls system tools by
  full path, so a `taskkill.exe` or `pandoc.exe` hidden next to a file is never executed.
- **Least privilege.** Installs per user (no admin), never restarts Explorer/Finder, pip installs wheels only
  (no package build scripts run), and the optional Pandoc download is checked against GitHub's SHA-256.
- **Your files are safe.** Writes are atomic; existing PDFs that QuickMorph didn't create are never overwritten.

Found a problem? Please open an issue.

---

## Troubleshooting

- **Nothing happens / menu entry missing after updating Python** – run the installer again; it points the menu at
  the Python you run it with.
- **"No browser engine was found"** – install any of Edge, Chrome, Brave, Chromium, Vivaldi or Firefox.
- **Details of a failed conversion** – see the log: `%LOCALAPPDATA%\QuickMorph\quickmorph.log` (Windows),
  `~/Library/Application Support/QuickMorph/quickmorph.log` (macOS), `~/.local/share/quickmorph/quickmorph.log` (Linux).

---

## Development

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q
```

The end-to-end tests convert every sample and check the PDF text layer for lost content, plus the security
guarantees above. CI runs them on Windows (Edge and Firefox) and macOS (Chrome, built-in WebKit and Firefox,
on the Mac's own Python 3.9). `tools/fetch_vendor.py` refreshes the bundled KaTeX/Mermaid (needs Node's `npm`).

## License

MIT — see [LICENSE](LICENSE). Bundled KaTeX and Mermaid are MIT too; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
