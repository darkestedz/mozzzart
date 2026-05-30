"""
bundle_vlc.py — Universal VLC Runtime Bundler for MozZzart Player

Automates the extraction of system-installed VLC binaries into the local
bin/vlc/ folder, creating a fully self-contained portable distribution.

Usage:
    python bundle_vlc.py

Supports Windows, macOS, and Linux.
"""

import os
import sys
import shutil


def bundle_vlc_runtime():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dest_dir = os.path.join(base_dir, "bin", "vlc")
    os.makedirs(dest_dir, exist_ok=True)
    print(f"[*] Targeting local distribution directory: {dest_dir}")

    if sys.platform == "win32":
        vlc_source = None
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    key = winreg.OpenKey(hive, r"SOFTWARE\VideoLAN\VLC")
                    vlc_source = winreg.QueryValueEx(key, "InstallDir")[0]
                    winreg.CloseKey(key)
                    if os.path.exists(vlc_source):
                        break
                except FileNotFoundError:
                    continue
        except Exception:
            pass
        if not vlc_source:
            candidate = os.path.join(os.environ.get("ProgramFiles", ""), "VideoLAN", "VLC")
            if os.path.exists(candidate):
                vlc_source = candidate
        if not vlc_source or not os.path.exists(vlc_source):
            print("[!] Error: Could not detect standard Windows VLC installation.")
            return

        for f in ["libvlc.dll", "libvlccore.dll"]:
            if os.path.exists(os.path.join(vlc_source, f)):
                shutil.copy2(os.path.join(vlc_source, f), os.path.join(dest_dir, f))
        dest_plugins = os.path.join(dest_dir, "plugins")
        if os.path.exists(dest_plugins):
            shutil.rmtree(dest_plugins)
        shutil.copytree(os.path.join(vlc_source, "plugins"), dest_plugins)
        print("[+] Windows portability bundle generated successfully!")

    elif sys.platform == "darwin":
        vlc_source_lib = "/Applications/VLC.app/Contents/MacOS/lib"
        vlc_source_plugins = "/Applications/VLC.app/Contents/MacOS/plugins"
        if not os.path.exists(vlc_source_lib):
            print("[!] Error: Could not locate VLC.app in /Applications folder.")
            return
        shutil.copy2(os.path.join(vlc_source_lib, "libvlc.dylib"), os.path.join(dest_dir, "libvlc.dylib"))
        shutil.copy2(os.path.join(vlc_source_lib, "libvlccore.dylib"), os.path.join(dest_dir, "libvlccore.dylib"))
        dest_plugins = os.path.join(dest_dir, "plugins")
        if os.path.exists(dest_plugins):
            shutil.rmtree(dest_plugins)
        shutil.copytree(vlc_source_plugins, dest_plugins)
        print("[+] macOS portability bundle generated successfully!")

    elif sys.platform.startswith("linux"):
        search_paths = ["/usr/lib/x86_64-linux-gnu", "/usr/lib", "/usr/local/lib"]
        found_lib = None
        for path in search_paths:
            if os.path.isfile(os.path.join(path, "libvlc.so")):
                found_lib = path
                break
        if not found_lib:
            print("[!] Error: System libvlc.so not found. Run 'sudo apt install vlc' first.")
            return
        shutil.copy2(os.path.join(found_lib, "libvlc.so"), os.path.join(dest_dir, "libvlc.so"))
        if os.path.isfile(os.path.join(found_lib, "libvlccore.so")):
            shutil.copy2(os.path.join(found_lib, "libvlccore.so"), os.path.join(dest_dir, "libvlccore.so"))

        found_plugins = None
        for p in ["/usr/lib/x86_64-linux-gnu/vlc/plugins", "/usr/lib/vlc/plugins"]:
            if os.path.exists(p):
                found_plugins = p
                break
        dest_plugins = os.path.join(dest_dir, "plugins")
        if os.path.exists(dest_plugins):
            shutil.rmtree(dest_plugins)
        if found_plugins:
            shutil.copytree(found_plugins, dest_plugins)
        print("[+] Linux portability bundle generated successfully!")


if __name__ == "__main__":
    bundle_vlc_runtime()
