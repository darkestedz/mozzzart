import os
import wave
import struct
import pygame
import logging
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger("PlayerEngine")


# ==============================================================================
# WAV Fast-Slicing Helper
# ==============================================================================
# pygame.mixer.Channel.play() has no start-time parameter — it always plays
# from frame 0. To achieve accurate mid-song karaoke activation and seek,
# we trim the WAV file IN MEMORY using Python's built-in wave module, then
# hand the trimmed buffer directly to pygame.mixer.Sound. This costs one
# pass over the audio data but requires zero disk I/O after the initial
# file open, making it fast enough for real-time use.
#
# Limitation: works only with PCM WAV files (which Demucs always outputs).
# MP3 files are handled separately by pygame.mixer.music (streaming engine).
# ==============================================================================

def load_sliced_sound(filepath, start_time_sec):
    """
    Opens a WAV file and returns a pygame.mixer.Sound that begins at
    start_time_sec, with no temporary files created on disk.

    Args:
        filepath      (str)   : Absolute path to a PCM WAV file.
        start_time_sec (float): Start offset in seconds.

    Returns:
        pygame.mixer.Sound — sliced to start at the given offset, or
        a full-length Sound if start_time_sec <= 0 or seek is impossible.
    """
    try:
        with wave.open(filepath, 'rb') as wav:
            frame_rate   = wav.getframerate()
            n_channels   = wav.getnchannels()
            samp_width   = wav.getsampwidth()
            total_frames = wav.getnframes()

            start_frame = int(start_time_sec * frame_rate)
            start_frame = max(0, min(start_frame, total_frames - 1))

            if start_frame > 0:
                wav.setpos(start_frame)

            frames_to_read = total_frames - start_frame
            raw_data = wav.readframes(frames_to_read)

        # Rebuild a minimal WAV header so pygame can parse the buffer
        # (pygame.mixer.Sound(buffer=...) needs raw PCM bytes matching
        #  the mixer's own sample format, which is easiest to guarantee
        #  by embedding the full RIFF/WAV header in the buffer.)
        data_size    = len(raw_data)
        byte_rate    = frame_rate * n_channels * samp_width
        block_align  = n_channels * samp_width
        riff_size    = 36 + data_size

        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF', riff_size, b'WAVE',
            b'fmt ', 16,
            1,            # PCM format
            n_channels,
            frame_rate,
            byte_rate,
            block_align,
            samp_width * 8,
            b'data', data_size
        )
        return pygame.mixer.Sound(buffer=header + raw_data)

    except Exception as e:
        logger.warning(f"load_sliced_sound failed ({filepath} @ {start_time_sec:.2f}s): {e}. Falling back to full Sound.")
        return pygame.mixer.Sound(filepath)


# ==============================================================================
# AudioPlayer
# ==============================================================================

class AudioPlayer(QObject):
    """
    Asynchronous playback engine wrapping pygame.mixer.
    Provides standard audio controls and emits thread-safe PyQt6 signals.

    Dual-Channel Mixer (True Karaoke Mode):
      - Channel 0 (pygame.mixer.Channel(0)): Instrumental stem — always 100% volume
      - Channel 1 (pygame.mixer.Channel(1)): Vocal guide stem — adjustable volume (default 10%)
      Both channels are populated via load_sliced_sound() for frame-accurate start offsets.
    """
    state_changed    = pyqtSignal(str)    # Emits: "playing", "paused", "stopped"
    track_finished   = pyqtSignal()       # Emits when the track finishes playing
    position_updated = pyqtSignal(float)  # Emits current playback position in seconds
    duration_resolved = pyqtSignal(float) # Emits length of loaded track in seconds
    seeked           = pyqtSignal(float)  # Emits new position instantly on manual seek action

    def __init__(self):
        super().__init__()
        try:
            pygame.mixer.pre_init(44100, -16, 2, 1024)
            pygame.mixer.init()
            pygame.mixer.set_num_channels(8)
            logger.info("pygame.mixer initialized successfully.")
        except Exception as e:
            logger.critical(f"Failed to initialize pygame.mixer: {e}")
            raise e

        self.current_track = None
        self.track_duration = 0.0
        self.is_paused = False
        self.elapsed_accumulator = 0.0
        self._is_active = False

        # Dual-channel karaoke mixer state
        self._karaoke_mode          = False
        self._ch_instrumental       = None   # pygame.mixer.Channel(0)
        self._ch_vocal              = None   # pygame.mixer.Channel(1)
        self._vocal_volume          = 0.10
        self._karaoke_start_offset  = 0.0
        self._last_vocal_path       = None   # Stored for seek operations

    # ------------------------------------------------------------------
    # State Cleanup
    # ------------------------------------------------------------------

    def clear_karaoke_channels(self):
        """
        Force-stops ALL RAM-buffered channels to release the audio device.
        Must be called before loading a new standard track OR before
        restoring standard playback after Karaoke Mode ends.
        Without this, Sound buffers linger in the mixer and corrupt output.
        """
        logger.info("clear_karaoke_channels: releasing all buffered channels.")
        try:
            pygame.mixer.stop()        # Stops every active Channel at once
        except Exception:
            pass
        try:
            pygame.mixer.music.stop()  # Also stop the streaming music engine
        except Exception:
            pass
        self._ch_instrumental = None
        self._ch_vocal        = None
        self._karaoke_mode    = False

    # ------------------------------------------------------------------
    # Standard single-track playback
    # ------------------------------------------------------------------

    def load_track(self, file_path):
        """Loads an audio file into the streaming engine and calculates its duration."""
        if not os.path.isfile(file_path):
            logger.error(f"Cannot load file, path does not exist: {file_path}")
            return False

        # CRITICAL: release all buffered channels before the streaming engine
        # claims the audio device, otherwise pygame raises a mixer conflict.
        self.clear_karaoke_channels()

        try:
            pygame.mixer.music.unload()
        except Exception:
            pass

        try:
            pygame.mixer.music.load(file_path)
            self.current_track       = file_path
            self.is_paused           = False
            self.elapsed_accumulator = 0.0

            self.track_duration = self._resolve_duration(file_path)
            self.duration_resolved.emit(self.track_duration)
            logger.info(f"Loaded track: {file_path} (Duration: {self.track_duration:.2f}s)")
            return True
        except Exception as e:
            logger.error(f"Failed to load track {file_path}: {e}")
            return False

    def play(self, start_time=0.0):
        """Plays the currently loaded streaming track from start_time (seconds)."""
        if not self.current_track:
            logger.warning("No track loaded to play.")
            return
        try:
            pygame.mixer.music.play(start=start_time)
            self.elapsed_accumulator = start_time
            self.is_paused           = False
            self._is_active          = True
            self.state_changed.emit("playing")
            logger.info(f"Playing track from {start_time:.2f}s")
        except Exception as e:
            logger.error(f"Failed to play track: {e}")

    def pause(self):
        """Pauses playback (both streaming engine and karaoke channels)."""
        # FIX: Capture exact time before Pygame resets get_pos() to 0
        self._pause_time = self.get_current_position()
        self.is_paused = True
        
        if self._karaoke_mode:
            self._pause_karaoke_channels()
        elif self._is_active:
            pygame.mixer.music.pause()

        if self._is_active:
            self.state_changed.emit("paused")
            logger.info("Playback paused.")

    def resume(self):
        """Resumes playback (both streaming engine and karaoke channels)."""
        if self._karaoke_mode:
            self._resume_karaoke_channels()
        elif self._is_active and self.is_paused:
            pygame.mixer.music.unpause()

        if self._is_active and self.is_paused:
            self.is_paused = False
            self.state_changed.emit("playing")
            logger.info("Playback resumed.")

    def stop(self):
        """Stops all playback and resets state."""
        self.clear_karaoke_channels()
        try:
            pygame.mixer.music.stop()
            self.is_paused           = False
            self._is_active          = False
            self.elapsed_accumulator = 0.0
            self.state_changed.emit("stopped")
            logger.info("Playback stopped.")
        except Exception as e:
            logger.error(f"Error stopping playback: {e}")

    def seek(self, position_seconds):
        """Seeks to a specific position in seconds."""
        if not self.current_track:
            return

        position_seconds = max(0.0, min(position_seconds, self.track_duration - 0.5))
        logger.info(f"Seeking to {position_seconds:.2f}s...")
        was_playing = self.is_playing()

        if self._karaoke_mode:
            # In karaoke mode, re-slice both WAV stems at the new position
            # so both channels restart in sync at the correct frame.
            self._seek_karaoke_channels(position_seconds, was_playing)
            self.seeked.emit(position_seconds)
        else:
            try:
                pygame.mixer.music.load(self.current_track)
                pygame.mixer.music.play(start=position_seconds)
                self.elapsed_accumulator = position_seconds

                if not was_playing:
                    pygame.mixer.music.pause()
                    self.is_paused = True
                    self.state_changed.emit("paused")
                else:
                    self.is_paused = False
                    self.state_changed.emit("playing")

                self.seeked.emit(position_seconds)
            except Exception as e:
                logger.error(f"Failed to seek: {e}")

    def set_volume(self, volume_percent):
        """Sets the streaming music volume. volume_percent: 0–100."""
        val = max(0.0, min(100.0, volume_percent)) / 100.0
        try:
            pygame.mixer.music.set_volume(val)
            if self._karaoke_mode and self._ch_instrumental:
                self._ch_instrumental.set_volume(val)
        except Exception as e:
            logger.error(f"Failed to set volume: {e}")

    def is_playing(self):
        """Returns True if audio is actively playing (not paused or stopped)."""
        return self._is_active and not self.is_paused

    def get_current_position(self):
        """Returns playback position in seconds."""
        if not getattr(self, '_is_active', True):
            return 0.0
            
        # FIX: If paused, get_pos() returns 0. Return the frozen cache instead.
        if getattr(self, 'is_paused', False) and hasattr(self, '_pause_time'):
            return self._pause_time

        if self._karaoke_mode:
            # Channels have no get_pos(); we track position via elapsed_accumulator
            # + wall-clock ms from the silent reference music stream.
            pos_ms = pygame.mixer.music.get_pos()
            if pos_ms < 0:
                return self.elapsed_accumulator
            return self._karaoke_start_offset + (pos_ms / 1000.0)

        pos_ms = pygame.mixer.music.get_pos()
        if pos_ms < 0:
            return self.elapsed_accumulator
        return self.elapsed_accumulator + (pos_ms / 1000.0)

    def update_polling(self):
        """Called periodically (~100ms) to emit position and detect track end."""
        if not self._is_active:
            return

        current_pos = self.get_current_position()
        self.position_updated.emit(current_pos)

        finished = False
        if self._karaoke_mode:
            ch0_busy = self._ch_instrumental and self._ch_instrumental.get_busy()
            finished = not ch0_busy and not self.is_paused
        else:
            finished = not pygame.mixer.music.get_busy() and not self.is_paused

        if finished:
            logger.info("Track playback finished naturally.")
            
            # CRITICAL FIX: If we just finished a Karaoke track, we MUST 
            # reset the state machine so the next track loads cleanly as a standard MP3.
            if self._karaoke_mode:
                self.clear_karaoke_channels()
                # Reset the _karaoke_mode flag explicitly
                self._karaoke_mode = False 
                
            self.stop()
            self.track_finished.emit()

    # ------------------------------------------------------------------
    # Dual-Channel Karaoke Mixer
    # ------------------------------------------------------------------

    def start_karaoke_mixer(self, instrumental_path, vocal_path, start_time=0.0, vocal_volume=0.10):
        """
        Activates the dual-channel karaoke mixer using the WAV Fast-Slice method.

        Channel 0: instrumental stem at 1.0 (100%) volume.
        Channel 1: vocal guide stem at vocal_volume (default 10%).

        Both channels receive a memory-sliced Sound that begins at start_time,
        guaranteeing frame-accurate synchronization regardless of when the
        user activates Karaoke Mode during playback.
        """
        if not os.path.isfile(instrumental_path):
            logger.error(f"Instrumental file not found: {instrumental_path}")
            return False
        if not os.path.isfile(vocal_path):
            logger.error(f"Vocal guide file not found: {vocal_path}")
            return False

        # Step 1: Full device release before switching to channel-based engine
        self.clear_karaoke_channels()

        try:
            self._ch_instrumental = pygame.mixer.Channel(0)
            self._ch_vocal        = pygame.mixer.Channel(1)

            # Step 2: Slice both WAV files in memory at the exact start offset
            logger.info(f"Slicing WAV stems at {start_time:.3f}s...")
            snd_instrumental = load_sliced_sound(instrumental_path, start_time)
            snd_vocal        = load_sliced_sound(vocal_path, start_time)

            # Step 3: Set volumes
            self._ch_instrumental.set_volume(1.0)
            self._ch_vocal.set_volume(vocal_volume)
            self._vocal_volume = vocal_volume

            # Step 4: Store state for later seek/deactivation
            self.current_track    = instrumental_path
            self._last_vocal_path = vocal_path

            # Step 5: Resolve full-file duration (not the sliced duration)
            self.track_duration = self._resolve_duration(instrumental_path)
            self.duration_resolved.emit(self.track_duration)

            # Step 6: Launch a silent reference music stream so get_pos() works
            # This stream is muted (volume=0) and acts only as a clock.
            pygame.mixer.music.load(instrumental_path)
            pygame.mixer.music.play(start=start_time)
            pygame.mixer.music.set_volume(0.0)

            # Step 7: Start both channels simultaneously — they begin at frame 0
            # of their pre-sliced buffers, which corresponds to start_time in the
            # original file.
            self._ch_instrumental.play(snd_instrumental)
            self._ch_vocal.play(snd_vocal)

            self._karaoke_start_offset = start_time
            self.elapsed_accumulator   = start_time
            self._karaoke_mode         = True
            self._is_active            = True
            self.is_paused             = False

            self.state_changed.emit("playing")
            logger.info(
                f"Karaoke dual-channel mixer started | "
                f"offset={start_time:.3f}s | vocal_vol={vocal_volume:.2f}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start karaoke mixer: {e}")
            self.clear_karaoke_channels()
            return False

    def stop_karaoke_mixer(self):
        """Stops the dual-channel mixer and releases the audio device."""
        self.clear_karaoke_channels()
        logger.info("Karaoke dual-channel mixer stopped.")

    def resume_regular_mode(self, original_filepath, start_time_sec):
        """
        Cleanly rebuilds the streaming music engine after Karaoke Mode ends.

        Why reload instead of unpause?
        --------------------------------
        After pygame.mixer.Channel playback and clear_karaoke_channels(), the
        pygame.mixer.music streaming engine is in an undefined internal state —
        its buffer pointer may be corrupt, the audio device may have been briefly
        held by PyAudio, or the stream may simply be stale. Calling unpause() or
        play() on a stale stream risks silence, distortion, or a hard freeze.

        The only guaranteed fix is a full stream rebuild:
          1. clear_karaoke_channels() — nuclear device release (mixer.stop + music.stop)
          2. music.load()            — remounts the file from disk, resetting all state
          3. music.play(start=t)     — seeks to the exact timestamp in one atomic call
          4. Internal flags updated  — _is_active=True, is_paused=False

        Args:
            original_filepath (str)  : Absolute path to the original MP3/WAV.
            start_time_sec    (float): Song position in seconds to resume from.
        """
        logger.info(f"resume_regular_mode: rebuilding stream for [{original_filepath}] at {start_time_sec:.3f}s")

        # Step 1: Full device release
        self.clear_karaoke_channels()

        if not original_filepath or not os.path.isfile(original_filepath):
            logger.error(f"resume_regular_mode: file not found — {original_filepath}")
            return

        try:
            # === MIXER HARD REBOOT ===
            # When PyAudio terminates its PortAudio session, it invalidates the
            # shared OS audio endpoint (WASAPI/DirectSound device handle) that
            # SDL_mixer was using. Calling music.load() on a disconnected mixer
            # produces silence — the write succeeds but goes nowhere.
            #
            # The only guaranteed recovery is destroying and recreating the entire
            # pygame.mixer subsystem so SDL claims a fresh OS device handle.
            try:
                pygame.mixer.quit()
                pygame.mixer.pre_init(44100, -16, 2, 1024)
                pygame.mixer.init()
                pygame.mixer.set_num_channels(8)
                logger.info("resume_regular_mode: pygame.mixer hard reboot complete.")
            except Exception as e:
                logger.error(f"resume_regular_mode: mixer reboot failed: {e}")

            # Load the original file into the fresh mixer
            pygame.mixer.music.load(original_filepath)

            # Play from the exact timestamp
            pygame.mixer.music.play(start=start_time_sec)

            # Update internal engine state
            self.current_track       = original_filepath
            self.elapsed_accumulator = start_time_sec
            self._is_active          = True
            self.is_paused           = False

            self.state_changed.emit("playing")
            logger.info(f"resume_regular_mode: streaming engine rebuilt successfully at {start_time_sec:.3f}s")

        except Exception as e:
            logger.error(f"resume_regular_mode failed: {e}")

    def set_vocal_guide_volume(self, volume_float):
        """Sets the vocal guide (Channel 1) volume live. Range: 0.0–1.0."""
        self._vocal_volume = max(0.0, min(1.0, volume_float))
        if self._ch_vocal:
            self._ch_vocal.set_volume(self._vocal_volume)
        logger.debug(f"Vocal guide volume → {self._vocal_volume:.2f}")

    def _pause_karaoke_channels(self):
        """Internal: pause both karaoke channels."""
        if self._ch_instrumental:
            self._ch_instrumental.pause()
        if self._ch_vocal:
            self._ch_vocal.pause()
        try:
            pygame.mixer.music.pause()
        except Exception:
            pass

    def _resume_karaoke_channels(self):
        """Internal: unpause both karaoke channels."""
        if self._ch_instrumental:
            self._ch_instrumental.unpause()
        if self._ch_vocal:
            self._ch_vocal.unpause()
        try:
            pygame.mixer.music.unpause()
        except Exception:
            pass

    def _seek_karaoke_channels(self, position_seconds, was_playing):
        """
        Seeks the karaoke mixer by re-slicing both WAV stems at the new position.

        Because pygame.mixer.Sound has no seek capability, we:
          1. Stop both channels (releases their current Sound buffers).
          2. Call load_sliced_sound() for each stem at the new offset.
          3. Restart both channels with the freshly sliced buffers.
          4. Restart the silent reference clock stream at the same offset.
        """
        vocal_path = self._last_vocal_path
        instr_path = self.current_track

        if not instr_path or not os.path.isfile(instr_path):
            logger.error("Karaoke seek: instrumental path missing.")
            return
        if not vocal_path or not os.path.isfile(vocal_path):
            logger.error("Karaoke seek: vocal path missing.")
            return

        # Stop existing channel playback
        if self._ch_instrumental:
            self._ch_instrumental.stop()
        if self._ch_vocal:
            self._ch_vocal.stop()

        try:
            # Re-slice both stems at the new position
            logger.info(f"Re-slicing WAV stems for seek to {position_seconds:.3f}s...")
            snd_i = load_sliced_sound(instr_path, position_seconds)
            snd_v = load_sliced_sound(vocal_path, position_seconds)

            # Restart the silent reference clock
            pygame.mixer.music.load(instr_path)
            pygame.mixer.music.play(start=position_seconds)
            pygame.mixer.music.set_volume(0.0)

            # Play both freshly sliced sounds simultaneously
            self._ch_instrumental.play(snd_i)
            self._ch_vocal.play(snd_v)
            self._ch_vocal.set_volume(self._vocal_volume)

        except Exception as e:
            logger.error(f"Karaoke seek failed: {e}")

        self._karaoke_start_offset = position_seconds
        self.elapsed_accumulator   = position_seconds

        if not was_playing:
            self._pause_karaoke_channels()
            self.is_paused = True
            self.state_changed.emit("paused")
        else:
            self.is_paused = False
            self.state_changed.emit("playing")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _resolve_duration(self, file_path):
        """Resolves track duration in seconds using wav metadata or pygame Sound."""
        if file_path.lower().endswith(".wav"):
            try:
                with wave.open(file_path, 'rb') as w:
                    return w.getnframes() / float(w.getframerate())
            except Exception as e:
                logger.warning(f"WAV duration fallback: {e}")

        try:
            sound = pygame.mixer.Sound(file_path)
            return sound.get_length()
        except Exception as e:
            logger.warning(f"Sound duration fallback failed: {e}")

        return 180.0
