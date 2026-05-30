"""
player_engine_vlc.py — libVLC Audio Playback Engine for MozZzart Player

Drop-in replacement for player_engine.py (pygame.mixer).
Uses python-vlc (C-level libVLC bindings) for audio playback.

Key architectural decisions:
  - Two vlc.MediaPlayer instances for dual-stem karaoke (instrumental + vocal guide)
  - VLC event callbacks write to local variables (C-thread safe air-gap pattern)
  - The existing 100ms QTimer poll reads those variables and emits PyQt signals safely
  - All outgoing time values normalized from VLC milliseconds → float seconds
  - All incoming time values converted from float seconds → VLC milliseconds
  - MediaPlayerPlaying event used for deferred seek (no 50ms QTimer.singleShot hack)
"""

import sys
import os
import logging

# ── Cross-Platform VLC Library Discovery ─────────────────────────────────────
# python-vlc dynamically loads libvlc at import time via ctypes.CDLL().
# On Windows, it searches CWD first (fails), then PATH. We must inject the
# VLC install directory into PATH *before* importing the vlc module.
# On macOS, we set DYLD_LIBRARY_PATH and VLC_PLUGIN_PATH for the .dylib lookup.

if sys.platform == "win32":
    # Strategy: Registry → common "Program Files" paths → give up with a clear error
    _vlc_dir = None

    # 1. Try Windows Registry (most reliable — works for all install locations)
    try:
        import winreg
        for _hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                _key = winreg.OpenKey(_hive, r"SOFTWARE\VideoLAN\VLC")
                _vlc_dir = winreg.QueryValueEx(_key, "InstallDir")[0]
                winreg.CloseKey(_key)
                if os.path.isfile(os.path.join(_vlc_dir, "libvlc.dll")):
                    break
                _vlc_dir = None
            except FileNotFoundError:
                continue
    except Exception:
        pass

    # 2. Fallback: scan standard install directories
    if not _vlc_dir:
        for _candidate in [
            os.path.join(os.environ.get("ProgramFiles", ""), "VideoLAN", "VLC"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "VideoLAN", "VLC"),
            os.path.join(os.environ.get("ProgramW6432", ""), "VideoLAN", "VLC"),
        ]:
            if _candidate and os.path.isfile(os.path.join(_candidate, "libvlc.dll")):
                _vlc_dir = _candidate
                break

    if _vlc_dir:
        # Inject into PATH so ctypes.CDLL can find libvlc.dll and its dependencies
        os.environ["PATH"] = _vlc_dir + ";" + os.environ.get("PATH", "")
        # Also set PYTHON_VLC_LIB_PATH for newer python-vlc versions
        os.environ["PYTHON_VLC_LIB_PATH"] = os.path.join(_vlc_dir, "libvlc.dll")

        # Architecture mismatch guard: 64-bit Python + 32-bit VLC (or vice versa)
        import struct
        _py_bits = struct.calcsize("P") * 8
        _is_x86_vlc = "x86" in _vlc_dir.lower() or "program files (x86)" in _vlc_dir.lower()
        if _py_bits == 64 and _is_x86_vlc:
            print(
                f"\n{'='*70}\n"
                f"  [!] ARCHITECTURE MISMATCH DETECTED\n"
                f"  Your Python is {_py_bits}-bit but VLC is 32-bit.\n"
                f"  VLC path: {_vlc_dir}\n\n"
                f"  FIX: Install 64-bit VLC from https://www.videolan.org/vlc/\n"
                f"       (Choose 'Installer for 64bit version')\n"
                f"{'='*70}\n"
            )

elif sys.platform == "darwin":
    # macOS Dynamic Library Linking Guards
    vlc_plugin_path = "/Applications/VLC.app/Contents/MacOS/plugins"
    if os.path.isdir(vlc_plugin_path):
        os.environ["VLC_PLUGIN_PATH"] = vlc_plugin_path
    vlc_lib = "/Applications/VLC.app/Contents/MacOS/lib"
    if os.path.isdir(vlc_lib):
        os.environ["DYLD_LIBRARY_PATH"] = vlc_lib + ":" + os.environ.get("DYLD_LIBRARY_PATH", "")

import time
import vlc
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger("VlcPlayerEngine")


# ==============================================================================
# VLC AudioPlayer — Drop-in replacement for pygame AudioPlayer
# ==============================================================================

class AudioPlayer(QObject):
    """
    Asynchronous playback engine wrapping libVLC.
    Provides standard audio controls and emits thread-safe PyQt6 signals.

    Dual-Player Karaoke Mode:
      - _player_main : Instrumental stem (or standard single-track playback)
      - _player_vocal: Vocal guide stem — adjustable volume (default 10%)
      Both players are synchronized via set_time() for frame-accurate seeking.

    C-Thread Safety (Air-Gap Pattern):
      VLC event callbacks fire on a native C thread (NOT the Qt event loop).
      Emitting pyqtSignals directly from VLC callbacks can cause X11/Wayland
      segfaults on Linux. Instead, VLC callbacks write to local variables
      (_vlc_pos_ms, _vlc_ended), and the existing 100ms update_polling()
      QTimer reads them safely from the Qt thread before emitting signals.
    """

    # Exact same 5 signals as the pygame version — no main.py changes needed
    state_changed     = pyqtSignal(str)    # Emits: "playing", "paused", "stopped"
    track_finished    = pyqtSignal()       # Emits when track finishes naturally
    position_updated  = pyqtSignal(float)  # Emits current position in seconds
    duration_resolved = pyqtSignal(float)  # Emits track length in seconds
    seeked            = pyqtSignal(float)  # Emits new position on manual seek

    def __init__(self):
        super().__init__()

        # Create a single VLC instance with no video output and quiet logging
        self._vlc_instance = vlc.Instance("--no-video", "--quiet", "--no-xlib")

        # Primary player: standard playback + instrumental stem in karaoke mode
        self._player_main = self._vlc_instance.media_player_new()

        # Secondary player: vocal guide stem (karaoke mode only)
        self._player_vocal = self._vlc_instance.media_player_new()

        # ── Public state (matches pygame engine's interface exactly) ──
        self.current_track    = None    # str | None — 16 read sites in main.py
        self.track_duration   = 0.0     # float seconds
        self.is_paused        = False   # bool — 2 read sites via getattr
        self._is_active       = False

        # ── Karaoke mixer state ──
        self._karaoke_mode         = False
        self._vocal_volume         = 0.10    # 0.0–1.0, mapped to VLC 0–100
        self._last_vocal_path      = None    # str | None — 1 read site (web broadcast)
        self._karaoke_start_offset = 0.0

        # ── C-Thread Air-Gap Variables ──
        # Written by VLC native C thread callbacks, read by Qt timer (100ms poll)
        self._vlc_pos_ms   = 0       # Latest position in milliseconds
        self._vlc_ended    = False   # End-of-track flag
        self._pause_time   = 0.0     # Frozen position cache for pause

        # ── Deferred seek (replaces the 50ms QTimer.singleShot hack) ──
        self._pending_seek       = None    # int | None — ms to seek once main media is ready
        self._vocal_pending_seek = None    # int | None — ms to seek once vocal media is ready

        # Attach VLC event listeners to the main player (time changed and end reached)
        self._attach_events(self._player_main)

        logger.info("VLC AudioPlayer initialized successfully.")

    # ------------------------------------------------------------------
    # VLC Event Attachment
    # ------------------------------------------------------------------

    def _attach_events(self, player):
        """Attach native VLC event callbacks to the main media player instance."""
        em = player.event_manager()
        em.event_attach(vlc.EventType.MediaPlayerTimeChanged,  self._on_time_changed)
        em.event_attach(vlc.EventType.MediaPlayerEndReached,   self._on_end_reached)

    # ------------------------------------------------------------------
    # VLC Callbacks (C-Thread — NO signal emission / VLC control here!)
    # ------------------------------------------------------------------

    def _on_time_changed(self, event):
        """Called on VLC's native C thread. Write to air-gap variable only."""
        pos = self._player_main.get_time()
        if pos >= 0:
            self._vlc_pos_ms = pos

    def _on_end_reached(self, event):
        """Called on VLC's native C thread. Set flag for Qt poll to process."""
        self._vlc_ended = True

    # ------------------------------------------------------------------
    # State Cleanup
    # ------------------------------------------------------------------

    def clear_karaoke_channels(self):
        """
        Force-stops ALL playback to release the audio device.
        Must be called before loading a new standard track OR before
        restoring standard playback after Karaoke Mode ends.

        CRITICAL: VLC fires event callbacks on a native C thread. If we call
        player.stop() while a C callback is mid-flight (e.g. MediaPlayerTimeChanged),
        the internal mutex deadlocks and the process segfaults.
        A 50ms sleep after stop() lets the C thread drain its pending callbacks.
        """
        logger.info("clear_karaoke_channels: releasing all VLC players.")

        # Cancel any pending deferred seeks before stopping
        self._pending_seek = None
        self._vocal_pending_seek = None

        try:
            logger.info("clear_karaoke_channels: stopping vocal player...")
            self._player_vocal.stop()
            logger.info("clear_karaoke_channels: vocal player stopped.")
        except Exception as e:
            logger.error(f"clear_karaoke_channels: error stopping vocal player: {e}")
        try:
            logger.info("clear_karaoke_channels: stopping main player...")
            self._player_main.stop()
            logger.info("clear_karaoke_channels: main player stopped.")
        except Exception as e:
            logger.error(f"clear_karaoke_channels: error stopping main player: {e}")

        # Let VLC's C-thread drain pending callbacks before reusing players.
        # Without this, set_media()/play() immediately after stop() can
        # collide with a still-running callback and segfault.
        time.sleep(0.05)

        self._karaoke_mode = False

    # ------------------------------------------------------------------
    # Standard single-track playback
    # ------------------------------------------------------------------

    def load_track(self, file_path):
        """Loads an audio file and resolves its duration."""
        if not os.path.isfile(file_path):
            logger.error(f"Cannot load file, path does not exist: {file_path}")
            return False

        # Release any active karaoke channels before loading a new track
        self.clear_karaoke_channels()

        try:
            media = self._vlc_instance.media_new(file_path)
            self._player_main.set_media(media)
            self.current_track = file_path
            self.is_paused = False
            self._vlc_ended = False
            self._vlc_pos_ms = 0

            # Resolve duration by parsing the media metadata
            media.parse_with_options(vlc.MediaParseFlag.local, timeout=5000)
            duration_ms = media.get_duration()
            if duration_ms > 0:
                self.track_duration = duration_ms / 1000.0
            else:
                self.track_duration = 180.0  # Fallback
            self.duration_resolved.emit(self.track_duration)

            logger.info(f"Loaded track: {file_path} (Duration: {self.track_duration:.2f}s)")
            return True
        except Exception as e:
            logger.error(f"Failed to load track {file_path}: {e}")
            return False

    def play(self, start_time=0.0):
        """Plays the currently loaded track from start_time (seconds)."""
        if not self.current_track:
            logger.warning("No track loaded to play.")
            return
        try:
            # Set deferred seek — _on_playing will apply it once media is ready
            self._pending_seek = int(start_time * 1000) if start_time > 0 else None
            self._vlc_ended = False
            self._player_main.play()
            self._pause_time = start_time
            self._vlc_pos_ms = int(start_time * 1000)
            self.is_paused = False
            self._is_active = True
            self.state_changed.emit("playing")
            logger.info(f"Playing track from {start_time:.2f}s")
        except Exception as e:
            logger.error(f"Failed to play track: {e}")

    def pause(self):
        """Pauses playback (both main and vocal players)."""
        # Capture exact position before pausing
        self._pause_time = self.get_current_position()
        self.is_paused = True

        self._player_main.set_pause(1)
        if self._karaoke_mode:
            self._player_vocal.set_pause(1)

        if self._is_active:
            self.state_changed.emit("paused")
            logger.info("Playback paused.")

    def resume(self):
        """Resumes playback (both main and vocal players)."""
        if self._is_active and self.is_paused:
            self._player_main.set_pause(0)
            if self._karaoke_mode:
                self._player_vocal.set_pause(0)
            self.is_paused = False
            self.state_changed.emit("playing")
            logger.info("Playback resumed.")

    def stop(self):
        """Stops all playback and resets state."""
        self.clear_karaoke_channels()
        self.is_paused = False
        self._is_active = False
        self._vlc_pos_ms = 0
        self._vlc_ended = False
        self.state_changed.emit("stopped")
        logger.info("Playback stopped.")

    def seek(self, position_seconds):
        """Seeks to a specific position in seconds."""
        if not self.current_track:
            return

        position_seconds = max(0.0, min(position_seconds, self.track_duration - 0.5))
        ms = int(position_seconds * 1000)
        logger.info(f"Seeking to {position_seconds:.2f}s...")

        was_playing = self.is_playing()

        # VLC native seek — no WAV re-slicing needed
        self._player_main.set_time(ms)
        if self._karaoke_mode:
            self._player_vocal.set_time(ms)

        self._vlc_pos_ms = ms
        self._pause_time = position_seconds

        if not was_playing:
            self.is_paused = True
            self.state_changed.emit("paused")
        else:
            self.is_paused = False
            self.state_changed.emit("playing")

        self.seeked.emit(position_seconds)

    def set_volume(self, volume_percent):
        """Sets the main player volume. volume_percent: 0–100 (same as pygame interface)."""
        vol = int(max(0, min(100, volume_percent)))
        try:
            self._player_main.audio_set_volume(vol)
        except Exception as e:
            logger.error(f"Failed to set volume: {e}")

    def is_playing(self):
        """Returns True if audio is actively playing (not paused or stopped)."""
        return self._is_active and not self.is_paused

    def get_current_position(self):
        """Returns playback position in seconds (float)."""
        if not self._is_active:
            return 0.0

        # If paused, return the frozen cache
        if self.is_paused:
            return self._pause_time

        # Read from the air-gap variable (written by VLC C thread)
        if self._vlc_pos_ms >= 0:
            return self._vlc_pos_ms / 1000.0

        return 0.0

    def update_polling(self):
        """
        Called periodically (~100ms) to emit position and detect track end.
        This is the Qt-thread-safe side of the air-gap pattern — it reads
        variables written by VLC's native C callbacks and emits signals safely.
        """
        if not self._is_active:
            return

        # Safe deferred seek on Qt thread
        if self._pending_seek is not None:
            if self._player_main.is_playing():
                seek_ms = self._pending_seek
                self._pending_seek = None
                self._player_main.set_time(seek_ms)
                logger.info(f"Deferred main seek to {seek_ms}ms applied in update_polling.")

        if self._karaoke_mode and self._vocal_pending_seek is not None:
            if self._player_vocal.is_playing():
                seek_ms = self._vocal_pending_seek
                self._vocal_pending_seek = None
                self._player_vocal.set_time(seek_ms)
                logger.info(f"Deferred vocal seek to {seek_ms}ms applied in update_polling.")

        # Emit position update from the air-gap variable
        if not self.is_paused and self._vlc_pos_ms >= 0:
            self.position_updated.emit(self._vlc_pos_ms / 1000.0)

        # Detect track end (flag set by VLC C-thread callback)
        if self._vlc_ended and not self.is_paused:
            logger.info("Track playback finished naturally.")
            self._vlc_ended = False

            if self._karaoke_mode:
                self._player_vocal.stop()
                self._karaoke_mode = False

            self.stop()
            self.track_finished.emit()

    # ------------------------------------------------------------------
    # Dual-Player Karaoke Mixer
    # ------------------------------------------------------------------

    def start_karaoke_mixer(self, instrumental_path, vocal_path, start_time=0.0, vocal_volume=0.10):
        """
        Activates the dual-player karaoke mixer.

        _player_main  → instrumental stem at 100% volume.
        _player_vocal → vocal guide stem at vocal_volume (default 10%).

        VLC seeks natively — no WAV slicing, no silent reference clock,
        no in-memory RIFF header reconstruction.
        """
        if not os.path.isfile(instrumental_path):
            logger.error(f"Instrumental file not found: {instrumental_path}")
            return False
        if not os.path.isfile(vocal_path):
            logger.error(f"Vocal guide file not found: {vocal_path}")
            return False

        # Step 1: Full device release before switching to karaoke mode
        self.clear_karaoke_channels()

        try:
            # Step 2: Load media into both players
            media_instr = self._vlc_instance.media_new(instrumental_path)
            media_vocal = self._vlc_instance.media_new(vocal_path)
            self._player_main.set_media(media_instr)
            self._player_vocal.set_media(media_vocal)

            # Step 3: Store state for later seek/deactivation
            self.current_track    = instrumental_path
            self._last_vocal_path = vocal_path
            self._vocal_volume    = vocal_volume

            # Step 4: Resolve duration from instrumental media
            media_instr.parse_with_options(vlc.MediaParseFlag.local, timeout=5000)
            duration_ms = media_instr.get_duration()
            if duration_ms > 0:
                self.track_duration = duration_ms / 1000.0
            else:
                self.track_duration = 180.0
            self.duration_resolved.emit(self.track_duration)

            # Step 5: Set deferred seek for both players
            seek_ms = int(start_time * 1000) if start_time > 0 else None
            self._pending_seek = seek_ms

            # Step 6: Start both players
            self._player_main.play()
            self._player_vocal.play()

            # Step 7: Set volumes — VLC uses 0–100 integer range
            self._player_main.audio_set_volume(100)
            self._player_vocal.audio_set_volume(int(vocal_volume * 100))

            # Step 8: Apply deferred seek to vocal player via air-gap variable.
            # The persistent _on_vocal_playing callback (attached at __init__) will
            # consume this value once the vocal media is buffered and playing.
            # No dynamic event_attach/event_detach — those are unsafe from C-threads.
            self._vocal_pending_seek = seek_ms

            self._karaoke_start_offset = start_time
            self._karaoke_mode         = True
            self._is_active            = True
            self.is_paused             = False
            self._vlc_ended            = False
            self._vlc_pos_ms           = int(start_time * 1000)
            self._pause_time           = start_time

            self.state_changed.emit("playing")
            logger.info(
                f"Karaoke dual-player mixer started | "
                f"offset={start_time:.3f}s | vocal_vol={vocal_volume:.2f}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start karaoke mixer: {e}")
            self.clear_karaoke_channels()
            return False

    def stop_karaoke_mixer(self):
        """Stops the dual-player mixer and releases both players."""
        self.clear_karaoke_channels()
        logger.info("Karaoke dual-player mixer stopped.")

    def resume_regular_mode(self, original_filepath, start_time_sec):
        """
        Cleanly transitions from Karaoke Mode back to standard single-track playback.

        Unlike the pygame version, VLC does NOT require a full mixer hard reboot.
        VLC manages its own audio device lifecycle, so we simply:
          1. Stop the vocal player
          2. Load the original file into the main player
          3. Play + seek to the exact timestamp
        """
        logger.info(f"resume_regular_mode: rebuilding stream for [{original_filepath}] at {start_time_sec:.3f}s")

        # Step 1: Release karaoke state
        self.clear_karaoke_channels()

        if not original_filepath or not os.path.isfile(original_filepath):
            logger.error(f"resume_regular_mode: file not found — {original_filepath}")
            return

        try:
            # Step 2: Load the original file
            media = self._vlc_instance.media_new(original_filepath)
            self._player_main.set_media(media)

            # Step 3: Set deferred seek and play
            self._pending_seek = int(start_time_sec * 1000) if start_time_sec > 0 else None
            self._vlc_ended = False
            self._player_main.play()

            # Step 4: Update internal state
            self.current_track = original_filepath
            self._pause_time   = start_time_sec
            self._vlc_pos_ms   = int(start_time_sec * 1000)
            self._is_active    = True
            self.is_paused     = False

            self.state_changed.emit("playing")
            logger.info(f"resume_regular_mode: VLC stream rebuilt successfully at {start_time_sec:.3f}s")

        except Exception as e:
            logger.error(f"resume_regular_mode failed: {e}")

    def set_vocal_guide_volume(self, volume_float):
        """Sets the vocal guide player volume. Range: 0.0–1.0 → VLC 0–100."""
        self._vocal_volume = max(0.0, min(1.0, volume_float))
        try:
            self._player_vocal.audio_set_volume(int(self._vocal_volume * 100))
        except Exception:
            pass
        logger.debug(f"Vocal guide volume → {self._vocal_volume:.2f}")

    # ------------------------------------------------------------------
    # Future-Proof Video Handle Routing
    # ------------------------------------------------------------------

    def set_video_widget(self, video_frame):
        """
        Attaches a Qt widget as the video output surface (cross-platform).
        Prepared for future video playback features.
        """
        if sys.platform.startswith('linux'):
            self._player_main.set_xwindow(int(video_frame.winId()))
        elif sys.platform == "win32":
            self._player_main.set_hwnd(int(video_frame.winId()))
        elif sys.platform == "darwin":
            self._player_main.set_nsobject(int(video_frame.winId()))

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _resolve_duration(self, file_path):
        """Resolves track duration in seconds using VLC media parsing."""
        try:
            media = self._vlc_instance.media_new(file_path)
            media.parse_with_options(vlc.MediaParseFlag.local, timeout=5000)
            duration_ms = media.get_duration()
            if duration_ms > 0:
                return duration_ms / 1000.0
        except Exception as e:
            logger.warning(f"VLC duration resolution failed: {e}")
        return 180.0  # Fallback
