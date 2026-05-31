"""
updater.py — External OTA Updater for MozZzart Player

This script is launched by the main application as a separate process when an
update is downloaded. It waits for the main app to exit, extracts the update
ZIP over the application directory, and relaunches the app.

Usage (called by main.py, NOT by the user):
    python updater.py <zip_path> <main_app_pid>

CRITICAL EXCLUSION ZONES:
    - config.json    → User preferences and credentials
    - Music/         → User's music library
    - bin/           → Heavy portable binaries (VLC, FFmpeg, yt-dlp)
    - models/        → AI model cache (Demucs, Whisper)
    - app.log        → Runtime log file
"""

import os
import sys
import time
import zipfile
import subprocess


def main():
    if len(sys.argv) < 3:
        print("[updater] Usage: python updater.py <zip_path> <main_app_pid>")
        sys.exit(1)

    zip_path = sys.argv[1]
    main_pid = int(sys.argv[2])

    print(f"[updater] Waiting for main app (PID {main_pid}) to exit...")

    # Wait up to 15 seconds for the main process to die
    for _ in range(30):
        try:
            # os.kill with signal 0 checks if the process exists (doesn't actually kill)
            os.kill(main_pid, 0)
            time.sleep(0.5)
        except OSError:
            # Process is gone
            break
    else:
        print("[updater] Warning: Main app did not exit within 15 seconds. Proceeding anyway.")

    # Pause an extra 3 seconds for file handles to fully release
    time.sleep(3)

    app_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"[updater] Extracting update to: {app_dir}")

    # Exclusion zones — these paths must NEVER be overwritten
    exclusion_zones = {
        "config.json",
        "app.log",
    }
    exclusion_prefixes = (
        "Music/", "Music\\",
        "bin/", "bin\\",
        "models/", "models\\",
    )

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for member in zf.namelist():
                # GitHub zipballs have a top-level directory (e.g., "repo-tag/")
                # Strip the first path component to extract files at the root level
                parts = member.split("/", 1)
                if len(parts) < 2 or not parts[1]:
                    continue  # Skip the root directory entry itself
                relative_path = parts[1]

                # Check exclusion zones
                if relative_path in exclusion_zones:
                    print(f"[updater] SKIPPED (exclusion zone): {relative_path}")
                    continue
                if any(relative_path.startswith(prefix) for prefix in exclusion_prefixes):
                    print(f"[updater] SKIPPED (exclusion prefix): {relative_path}")
                    continue

                # Extract the file
                dest_path = os.path.join(app_dir, relative_path)

                # Handle directories
                if member.endswith("/"):
                    os.makedirs(dest_path, exist_ok=True)
                    continue

                # Ensure parent directory exists
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)

                # Write file
                with zf.open(member) as src, open(dest_path, 'wb') as dst:
                    dst.write(src.read())

        print("[updater] Update extracted successfully!")
    except Exception as e:
        print(f"[updater] ERROR during extraction: {e}")
        sys.exit(1)

    # Clean up the downloaded zip
    try:
        os.remove(zip_path)
        print(f"[updater] Cleaned up temp zip: {zip_path}")
    except Exception:
        pass

    # Relaunch the application
    print("[updater] Relaunching MozZzart Player...")
    is_frozen = getattr(sys, 'frozen', False)
    if is_frozen:
        if sys.platform == "win32":
            main_executable = os.path.join(app_dir, "MozZzartPlayer.exe")
        else:
            main_executable = os.path.join(app_dir, "MozZzartPlayer")
        print(f"[updater] Launching compiled player: {main_executable}")
        subprocess.Popen([main_executable], cwd=app_dir)
    else:
        main_py = os.path.join(app_dir, "main.py")
        print(f"[updater] Launching dev player: {sys.executable} {main_py}")
        subprocess.Popen([sys.executable, main_py], cwd=app_dir)
        
    print("[updater] Done. Exiting updater.")
    sys.exit(0)


if __name__ == "__main__":
    main()
