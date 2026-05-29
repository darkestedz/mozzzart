plan.md - Portable YouTube Audio & Karaoke Player
1. Architecture & Tech Stack Selection
To ensure the application is a portable Windows executable (no installation required) with a modern "Spotify-like" UI, the agent must use the following stack:

Language: Python 3.10+ (compiled to .exe via PyInstaller).

UI Framework: PyQt6 or CustomTkinter. (CustomTkinter is highly recommended for modern, dark-mode, Spotify-style interfaces).

Audio Playback: pygame.mixer or vlc-python (packaged with portable DLLs) or QMediaPlayer (if using PyQt6).

Scraper/Downloader: yt-dlp (invoked as a subprocess or imported module) + ffmpeg (bundled in a local bin/ folder for portability).

Karaoke Engine (Stem Separation + STT): * Separation: demucs or spleeter to split instrumental/vocals.

Transcription/Sync: whisper-timestamped (OpenAI's Whisper modified for word-level syncing).

Data Persistence: A local config.json stored in the same directory as the .exe to save the root folder path, playlist paths, and toggle states (ensuring true portability).

2. Step-by-Step Implementation Plan
Step 1: UI Shell & Core State Management
Task: Build the Spotify-like UI layout (Sidebar for playlists, main view for queues/songs, bottom bar for playback controls).

Task: Implement config.json initialization. If it doesn't exist, create it. Save/load the root music directory.

Task: Build the folder scanner to read .mp3 and .wav files from the root and display them in the main view.

Step 2: Media Player & Playlist Logic
Task: Implement the playback engine (Play, Pause, Next, Random, Auto-play).

Task: Implement asynchronous playback so the UI never freezes while music plays.

Task: Build playlist functionality. Playlists are treated as specific folders within the root directory. Users can send downloaded files to these specific folders.

Step 3: YouTube Scraper & Queue System
Task: Integrate yt-dlp.

Task: Create a dedicated background thread (QThread or threading.Thread) for downloads to prevent UI blocking.

Task: Build a visual queue UI component. As links are pasted, add them to the queue. Update progress bars via yt-dlp hooks. Auto-clear completed items.

Step 4: The Karaoke Engine (Background Processor)
Task: Implement a background worker that scans for .mp3 files without a matching .lrc (lyric) or .json karaoke data file.

Task: Pass the audio through the stem separator to remove instruments.

Task: Pass the clean vocal stem through the timestamped STT model to get word-level timing.

Task: Save the output as a .lrc or custom .json file identically named to the .mp3 in the exact same folder.

Task: Update the UI to display a "Mic Badge" next to songs that have an associated karaoke file.

Step 5: Karaoke UI & Sync Engine
Task: Build the Karaoke View. When toggled, hide the playlist view and display the lyrics.

Task: Implement the sync logic. Use the current playback time of the audio player to highlight the current word/line in the karaoke file.

3. Anticipated Bugs & Preventative Measures
The agent must proactively build defenses against these specific failure points:

Failure Point 1: Thread Blocking (UI Freeze).

Prevention: All heavy tasks (downloading, vocal separation, ML transcription) must run on background worker threads. The agent must use thread-safe signals/queues to pass progress updates back to the main UI thread.

Failure Point 2: Portability & Missing Dependencies.

Prevention: ML models and ffmpeg are usually system-installed. The app must dynamically check for a local bin/ and models/ folder next to the .exe. On the first run, the agent must write an initialization script that downloads ffmpeg.exe and the necessary whisper models directly into the portable folder if they are missing.

Failure Point 3: YouTube Age-Restriction/Cipher Changes.

Prevention: yt-dlp updates frequently. The agent must implement a "Check for yt-dlp Updates" function that downloads the latest yt-dlp binary to the local bin/ folder to future-proof the scraper.

Failure Point 4: Desynced Lyrics.

Prevention: Standard STT struggles with music. The agent must implement vocal isolation first (removing instruments) before sending the audio to the STT algorithm. Furthermore, the agent must use a timestamped-specific library (like stable-ts) rather than standard Whisper.

4. Debugging Methods for the Agent
To ensure flawless execution, the agent must implement the following debugging toolkit:

Verbose File Logging: Implement the logging module immediately. Output app.log in the portable directory. Log every YouTube link parsed, every subprocess exit code (especially for ffmpeg), and ML memory allocation.

Mock Interfaces: Before wiring up the heavy ML models, the agent should create a mock karaoke function that generates a dummy .lrc file after 5 seconds to test the UI sync logic independently of the ML logic.

Exception Catching in Threads: Background threads silently fail if unhandled. The agent must wrap all thread execution blocks in try-except blocks that send the traceback string directly to the app.log and trigger a "Warning" popup in the UI.

5. Live DOM Scrolling & Extraction Pipeline
To bypass Spotify Web API restrictions and solve dynamic CSS letter-spacing, skeleton loader flickers, and DOM virtualization without requiring premium credentials:
- **Unified Headless Browser Pipeline**: Paste a Spotify playlist URL to trigger SpotifyScraperWorker (a background QThread). It boots a headless Chromium instance using Python's playwright library.
- **DOM-Level 'Yank' Micro-Scrolling**: To bypass React focus traps and guarantee interaction with the virtualized container under headless execution, simulated keyboard PageDown inputs and mouse wheels are completely replaced with Playwright's native DOM-level `scroll_into_view_if_needed()`. On each scroll loop iteration, the scraper queries the loaded track rows (`div[data-testid="tracklist-row"]`) and calls `scroll_into_view_if_needed()` on the very last track in the list. This forcefully "yanks" the latest element into focus, triggering Spotify's React intersection observers to load the next chunk of tracks. It falls back to JS `window.scrollBy(0, 1000)` if targeting is obscured, using a robust 1.0-second delay to let dynamic content load cleanly.
- **Assertion Target & Failsafe**: Users can specify an optional *Target Track Count* in the PyQt UI (using a styled `QSpinBox` with special `"Auto"` text support). If a target count is active, the scraper scrolls stubbornly until `len(extracted_tracks) >= target_count`. To prevent infinite loops or app freezing (e.g., if a user inputs the wrong target), an idle scroll counter stops scraping and yields current results if the track count does not increase for 20 consecutive scrolls.
- **Real-Time Data Extraction & Numeric Anchor Filter**: At each scroll increment, Playwright evaluates a lightweight browser-side function to select all visible `div[data-testid="tracklist-row"]` elements in the DOM. To prevent over-fetching and grabbing the "Recommended Songs" section at the bottom, the scraper looks at the index/number column. If the row has a valid numeric track index (e.g., 1, 2, 3), it extracts the Artist and Title; otherwise, it completely ignores the row.
- **Recommended Section Kill Switch**: If the scraper encounters a DOM element containing the text "Recommended", "Recommended Songs", or "Based on this playlist" (e.g., a section header), it immediately triggers a kill switch to break the scroll loop, preventing any recommended-song over-scraping and gracefully terminating extraction.
- **Deduplication & Formatting**: Extracted tracks are formatted as `"[Artist Name] - [Song Title] lyrics"`. Storing them in a Python `set()` automatically eliminates duplicate tracks during active scrolling.
- **Direct Queue Injection**: Once the bottom of the page is reached, the browser is closed. The deduplicated list of track queries is sorted, written to `debug_spotify/parsed_queries.txt` for auditing, prepended with `ytsearch1:`, and injected directly into the `DownloadWorker` queue.
- **Zero Workarounds**: Eliminates PDF generation, file parsing libraries, and complex regex un-spacing logic entirely for an enterprise-grade live scraper.