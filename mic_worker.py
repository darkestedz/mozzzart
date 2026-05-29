import logging
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger("MicrophoneWorker")

class MicrophoneWorker(QThread):
    """
    Background thread that captures live microphone input, applies a simple
    delay-line echo/reverb DSP effect, and routes the processed audio to
    the default speaker output in real-time.

    Used by True Karaoke Mode to let users sing along with the instrumental track.

    Thread Ownership Contract
    -------------------------
    PyAudio / PortAudio uses a global C-library state. ALL PyAudio teardown
    (pa.terminate()) MUST happen from the same thread that called pa.PyAudio().
    Calling pa.terminate() from the main thread (even with try/except) while
    the run() thread is also doing teardown is a data race on PortAudio's
    global state and will corrupt it — causing a crash on the next toggle.

    CORRECT shutdown sequence:
      1. Call stop()          — closes input_stream only, unblocking read() in ~11ms
      2. Call wait(2000)      — blocks until run() finishes its finally block
      3. Do NOT call terminate() — ever. It hard-kills the thread and leaves
         PortAudio's C state corrupt, causing a crash on the next teardown.

    The run() finally block is the SOLE owner of pa.terminate().
    stop() is only responsible for unblocking the audio read loop.
    """
    error_signal = pyqtSignal(str)

    CHANNELS    = 1      # Mono
    RATE        = 44100  # Hz
    
    # --- LOW LATENCY OPTIMIZATIONS ---
    CHUNK       = 512    # Frames per buffer (~11ms blocking read timeout for ultra-low latency)
    DELAY_CHUNKS = 16    # Echo delay ≈ 16 * 512 / 44100 ≈ 0.19s (Compensated for smaller chunks)

    def __init__(self, reverb_intensity=0.35):
        super().__init__()
        self.running          = False
        self.reverb_intensity = max(0.0, min(1.0, reverb_intensity))
        self._paused          = False

        # These are owned exclusively by the run() thread.
        # stop() may touch ONLY input_stream to unblock a blocking read().
        # It must not touch output_stream or pyaudio_instance.
        self.input_stream     = None   # Owned by run() thread
        self.output_stream    = None   # Owned by run() thread
        self.pyaudio_instance = None   # Owned by run() thread

    def set_reverb_intensity(self, value):
        """Thread-safe setter for reverb intensity (0.0 – 1.0)."""
        self.reverb_intensity = max(0.0, min(1.0, value))

    def pause(self):
        """Pauses mic processing without closing streams."""
        self._paused = True

    def resume(self):
        """Resumes mic processing."""
        self._paused = False

    def stop(self):
        """
        Signals the worker to stop gracefully.

        CRITICAL: We do NOT touch input_stream, output_stream, or pyaudio_instance
        here. Closing a stream from the main thread while the run() thread is
        actively inside stream.read() causes a C-level segmentation fault and
        hard-crashes the app — PortAudio cannot handle concurrent close/read.

        The CHUNK read (512 frames @ 44100 Hz) blocks for only ~11ms maximum.
        Setting self.running = False is enough: the loop condition is checked
        after every read() returns naturally, and then run() proceeds to its
        finally block where pa.terminate() and stream.close() execute safely
        from the owning thread.

        Do NOT call QThread.terminate() after this — wait(2000) is sufficient.
        """
        self.running = False
        self._paused = False
        logger.info("MicrophoneWorker.stop(): flag set, waiting for ~11ms read loop to exit natively.")

    def run(self):
        """Main loop: mic capture → echo DSP → speaker output."""
        self.running = True
        self._paused = False

        try:
            import pyaudio
            self.pyaudio_instance = pyaudio.PyAudio()

            logger.info("Opening microphone input stream...")
            self.input_stream = self.pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                frames_per_buffer=self.CHUNK
            )

            logger.info("Opening speaker output stream...")
            self.output_stream = self.pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=self.CHANNELS,
                rate=self.RATE,
                output=True,
                frames_per_buffer=self.CHUNK
            )

            delay_buffer = np.zeros((self.DELAY_CHUNKS, self.CHUNK), dtype=np.int16)
            buffer_index = 0
            logger.info(f"Microphone worker started. Reverb: {self.reverb_intensity:.2f} | Latency: ~11ms")

            while self.running:
                if self._paused:
                    self.msleep(30)
                    continue

                # input_stream may have been set to None by stop()
                if not self.input_stream:
                    break

                try:
                    raw_data    = self.input_stream.read(self.CHUNK, exception_on_overflow=False)
                    audio_chunk = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32)

                    delayed     = delay_buffer[buffer_index].astype(np.float32)
                    mixed       = audio_chunk + (delayed * self.reverb_intensity)
                    mixed       = np.clip(mixed, -32768, 32767).astype(np.int16)

                    delay_buffer[buffer_index] = np.frombuffer(raw_data, dtype=np.int16)
                    buffer_index = (buffer_index + 1) % self.DELAY_CHUNKS

                    if self.output_stream:
                        self.output_stream.write(mixed.tobytes())

                except (IOError, OSError):
                    # input_stream was closed by stop() mid-read, or buffer issue.
                    # Exit the loop cleanly — do not log as error.
                    break

                except Exception as e:
                    logger.warning(f"Unexpected audio error (continuing): {e}")
                    continue

        except ImportError:
            msg = "PyAudio is not installed. Run: pip install pyaudio"
            logger.error(msg)
            self.error_signal.emit(msg)
        except Exception as e:
            msg = f"Microphone worker error: {e}"
            logger.error(msg)
            self.error_signal.emit(msg)
        finally:
            # === SOLE OWNER OF pa.terminate() ===
            # All teardown happens here, in the run() thread, sequentially.
            # No other code path may call pa.terminate().
            logger.info("MicrophoneWorker: cleaning up audio streams...")

            if self.input_stream:
                try:
                    self.input_stream.stop_stream()
                    self.input_stream.close()
                except Exception:
                    pass
                self.input_stream = None

            if self.output_stream:
                try:
                    self.output_stream.stop_stream()
                    self.output_stream.close()
                except Exception:
                    pass
                self.output_stream = None

            if self.pyaudio_instance:
                try:
                    self.pyaudio_instance.terminate()
                except Exception:
                    pass
                self.pyaudio_instance = None

            self.running = False
            logger.info("MicrophoneWorker: shut down cleanly.")
