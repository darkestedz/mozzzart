import os
import sys
import json
import logging
import time
import subprocess
import tempfile
import shutil
from PyQt6.QtCore import QThread, pyqtSignal
import utils

logger = logging.getLogger("KaraokeEngine")

_WHISPER_MODEL_CACHE = None

class KaraokeProcessorWorker(QThread):
    """
    Background worker thread that processes audio tracks to isolate vocals
    and transcribe word-level synchronized lyrics.
    Supports a snappy Mock Mode for testing, and an advanced PyTorch pipeline
    using Demucs + stable-ts.
    """
    progress_signal = pyqtSignal(str, float)       # Emits: status_message, percentage
    finished_signal = pyqtSignal(str, str)         # Emits: song_path, lrc_json_path
    error_signal = pyqtSignal(str, str)            # Emits: song_path, error_message

    def __init__(self, song_path, use_mock=True, language=None, download_instruments=True, instrumental_only=False, music_root_dir=None):
        super().__init__()
        self.song_path = song_path
        self.use_mock = use_mock
        self.language = language  # Whisper language override (None = auto-detect)
        self.download_instruments = download_instruments  # Save instrumental stems
        self.instrumental_only = instrumental_only  # Skip Whisper, only extract instrumental
        self.music_root_dir = music_root_dir  # Root music dir for the instrumentals/ subfolder
        self.song_dir = os.path.dirname(song_path)
        self.song_name = os.path.splitext(os.path.basename(song_path))[0]
        
        # Smart Hardware Detection
        import torch
        if torch.cuda.is_available():
            self.processing_device = "cuda"
            logger.info("🚀 NVIDIA GPU (CUDA) detected! AI processing will run at maximum speed.")
        else:
            self.processing_device = "cpu"
            logger.warning("⚠️ No CUDA GPU detected. Falling back to CPU. AI processing will be significantly slower.")
        
    def run(self):
        # Run at low priority so audio playback never starves
        self.setPriority(QThread.Priority.LowPriority)
        logger.info(f"Karaoke processing started for {self.song_name} (Mock Mode: {self.use_mock})")
        
        # Determine output file path (identically named JSON next to song)
        output_json_path = os.path.splitext(self.song_path)[0] + ".json"
        
        try:
            if self.use_mock:
                self.run_mock_pipeline(output_json_path)
            else:
                # Exclusively execute local ML pipeline (Demucs + Whisper stable-ts)
                self.run_ml_pipeline(output_json_path)
        except Exception as e:
            logger.error(f"Karaoke processing failed for {self.song_name}: {e}")
            self.error_signal.emit(self.song_path, str(e))

    def run_mock_pipeline(self, dest_json_path):
        """Generates realistic word-synchronized dummy lyrics for testing within 5 seconds."""
        steps = [
            ("Initializing audio stems...", 10),
            ("Extracting vocal frequencies...", 40),
            ("Aligning word-level timing offsets...", 70),
            ("Writing sync lyric database...", 90)
        ]
        
        for msg, pct in steps:
            self.progress_signal.emit(msg, pct)
            time.sleep(1.0)  # Total 4 seconds duration to feel realistic and snappy

        # Generate custom mock lyrics based on the song name
        clean_title = self.song_name.replace("_", " ").replace("-", " ")
        words_in_title = clean_title.split()
        title_tag = " ".join([w.capitalize() for w in words_in_title])

        # Get track duration (we'll fetch from a temporary player or assume 180 seconds)
        duration = 180.0
        try:
            # Use wave module for WAV files - no pygame conflict
            import wave
            if self.song_path.lower().endswith(".wav"):
                with wave.open(self.song_path, 'rb') as wf:
                    duration = wf.getnframes() / float(wf.getframerate())
            else:
                # For MP3, use mutagen if available, else default
                try:
                    from mutagen.mp3 import MP3
                    audio = MP3(self.song_path)
                    duration = audio.info.length
                except ImportError:
                    pass  # Fall through to default 180s
        except Exception:
            pass

        # Create structured, word-by-word synced lyrics
        lyrics_data = []
        
        # Intro
        lyrics_data.append({
            "text": "🎶 (Instrumental Intro) 🎶",
            "start": 0.0,
            "end": 8.0,
            "words": [{"word": "🎶", "start": 0.0, "end": 2.0}, {"word": "(Instrumental", "start": 2.0, "end": 4.0}, {"word": "Intro)", "start": 4.0, "end": 6.0}, {"word": "🎶", "start": 6.0, "end": 8.0}]
        })
        
        # Verses & Chorus loop until track duration
        lines = [
            f"Welcome to this portable player session",
            f"We are playing a beautiful masterpiece",
            f"Titled {title_tag}",
            f"Feel the music deep inside your heart",
            f"Now get ready for the grand chorus",
            f"Sing it out loud with all your passion",
            f"This is your karaoke moment",
            f"Let the rhythm wash away your worries",
            f"Thank you for listening to this track",
            f"Music brings us all together as one"
        ]

        current_time = 8.0
        line_index = 0
        
        while current_time < (duration - 15.0):
            line_text = lines[line_index % len(lines)]
            words = line_text.split()
            word_dur = 4.0 / len(words)
            
            line_start = current_time
            line_words = []
            for i, w in enumerate(words):
                w_start = current_time + (i * word_dur)
                w_end = w_start + word_dur - 0.05
                line_words.append({
                    "word": w,
                    "start": round(w_start, 2),
                    "end": round(w_end, 2)
                })
                
            line_end = current_time + 4.0
            lyrics_data.append({
                "text": line_text,
                "start": round(line_start, 2),
                "end": round(line_end, 2),
                "words": line_words
            })
            
            current_time += 6.0  # 4 seconds lyric + 2 seconds gap
            line_index += 1

        # Outro
        lyrics_data.append({
            "text": "🎵 (Outro - Thank you for singing!) 🎵",
            "start": round(current_time, 2),
            "end": round(duration, 2),
            "words": [{"word": "🎵", "start": round(current_time, 2), "end": round(current_time + 1, 2)}, {"word": "Thank", "start": round(current_time + 1, 2), "end": round(current_time + 2, 2)}, {"word": "you!", "start": round(current_time + 2, 2), "end": round(duration, 2)}]
        })

        # Save to file
        with open(dest_json_path, 'w', encoding='utf-8') as f:
            json.dump({"lyrics": lyrics_data, "instrumental_path": None}, f, indent=4, ensure_ascii=False)

        self.progress_signal.emit("Karaoke lyrics compiled successfully!", 100)
        self.finished_signal.emit(self.song_path, dest_json_path)

    def run_ml_pipeline(self, dest_json_path):
        """Runs the true ML pipeline: Demucs vocal separation followed by stable-ts Whisper alignment."""
        temp_dir = tempfile.mkdtemp()
        try:
            logger.info(f"Starting Demucs on [{self.song_name}]")
            # Step 1: Vocal Separation with Demucs
            self.progress_signal.emit("Initializing Demucs Vocal Isolation...", 10)
            logger.info("Running Demucs separation via subprocess (shell=False)...")
            
            # Since demucs is installed in python, we call python -m demucs
            # This is 100% portable and avoids space/bracket parsing issues in Windows shell
            cmd = [
                sys.executable,
                "-m",
                "demucs",
                "--two-stems=vocals",
                "-d", getattr(self, 'processing_device', 'cpu'),  # Dynamically routes to CUDA or CPU
                "-o", temp_dir,
                self.song_path
            ]
            
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            # Execute Demucs subprocess safely without shell=True
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                shell=False,
                env=env
            )
            
            # Read stdout to update progress
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                logger.info(f"Demucs: {line.strip()}")
                if "Selected jobs" in line or "Separating" in line:
                    self.progress_signal.emit("Isolating vocals (Demucs)...", 25)
                    
            process.wait()
            if process.returncode != 0:
                raise Exception(f"Demucs stem separation failed with return code {process.returncode}")
                
            logger.info(f"Demucs Complete for [{self.song_name}]")
            self.progress_signal.emit("Vocal stem isolated successfully!", 50)
            
            # Locate the separated vocal and instrumental files
            # Demucs structure is typically: temp_dir/htdemucs/[song_name]/vocals.wav & no_vocals.wav
            vocal_file = None
            instrumental_file = None
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    if file.lower() == "vocals.wav":
                        vocal_file = os.path.join(root, file)
                    elif file.lower() == "no_vocals.wav":
                        instrumental_file = os.path.join(root, file)
                if vocal_file and instrumental_file:
                    break
                    
            if not vocal_file or not os.path.exists(vocal_file):
                raise FileNotFoundError("Could not locate Demucs vocals output file.")

            # Step 1B: Save stems to the dedicated instrumentals/ subfolder
            # This firewall folder keeps WAV stems out of the main music library.
            # Output dir: {music_root_dir}/instrumentals/  (or fallback to song_dir)
            base_dir = self.music_root_dir if self.music_root_dir else self.song_dir
            instrumentals_dir = os.path.join(base_dir, "instrumentals")
            os.makedirs(instrumentals_dir, exist_ok=True)
            logger.info(f"Instrumentals output directory: {instrumentals_dir}")

            instrumental_dest_path = None
            vocal_dest_path = None

            if self.download_instruments:
                # Save instrumental stem: {SongName}_instrumental.wav
                if instrumental_file and os.path.exists(instrumental_file):
                    instr_name = f"{self.song_name}_instrumental.wav"
                    instrumental_dest_path = os.path.join(instrumentals_dir, instr_name)
                    try:
                        shutil.copy2(instrumental_file, instrumental_dest_path)
                        logger.info(f"Instrumental stem saved to: {instrumental_dest_path}")
                        self.progress_signal.emit("Instrumental track saved!", 54)
                    except Exception as e:
                        logger.warning(f"Failed to save instrumental stem: {e}")
                        instrumental_dest_path = None
                else:
                    logger.warning("Demucs did not produce a no_vocals.wav file.")

                # Save vocal stem: {SongName}_vocal.wav
                if vocal_file and os.path.exists(vocal_file):
                    vocal_name = f"{self.song_name}_vocal.wav"
                    vocal_dest_path = os.path.join(instrumentals_dir, vocal_name)
                    try:
                        shutil.copy2(vocal_file, vocal_dest_path)
                        logger.info(f"Vocal stem saved to: {vocal_dest_path}")
                        self.progress_signal.emit("Vocal guide track saved!", 57)
                    except Exception as e:
                        logger.warning(f"Failed to save vocal stem: {e}")
                        vocal_dest_path = None

            # If instrumental_only mode, skip Whisper transcription entirely
            if self.instrumental_only:
                logger.info(f"Instrumental-only mode: skipping Whisper transcription for [{self.song_name}]")
                self.progress_signal.emit("Instrumental extraction complete (lyrics skipped).", 90)
                
                # Update existing JSON with both stem paths if it exists
                if os.path.isfile(dest_json_path):
                    try:
                        with open(dest_json_path, 'r', encoding='utf-8') as f:
                            existing_data = json.load(f)
                        existing_data["instrumental_path"] = instrumental_dest_path
                        existing_data["vocal_path"] = vocal_dest_path
                        with open(dest_json_path, 'w', encoding='utf-8') as f:
                            json.dump(existing_data, f, indent=4, ensure_ascii=False)
                    except Exception as e:
                        logger.warning(f"Failed to update existing JSON with stem paths: {e}")
                else:
                    # No JSON exists — create minimal one
                    with open(dest_json_path, 'w', encoding='utf-8') as f:
                        json.dump({
                            "lyrics": [],
                            "instrumental_path": instrumental_dest_path,
                            "vocal_path": vocal_dest_path
                        }, f, indent=4, ensure_ascii=False)
                
                self.progress_signal.emit("Instrumental extraction complete!", 100)
                self.finished_signal.emit(self.song_path, dest_json_path)
                return  # Exit early — no Whisper needed

            # Step 2: Timestamped STT with stable-ts (Whisper)
            global _WHISPER_MODEL_CACHE
            
            if _WHISPER_MODEL_CACHE is None:
                self.progress_signal.emit("Loading Whisper large-v3 model into RAM (first time only)...", 60)
                logger.info("Loading stable-ts alignment package (large-v3)...")
                import stable_whisper
                models_dir = utils.get_models_dir()
                
                # Ensure we know which device to load the model onto
                target_device = getattr(self, 'processing_device', 'cpu')
                
                _WHISPER_MODEL_CACHE = stable_whisper.load_model(
                    'large-v3', 
                    download_root=models_dir, 
                    device=target_device  # Dynamically routes Whisper layers to the correct hardware
                )
                logger.info("Whisper model loaded and globally cached.")
            else:
                self.progress_signal.emit("Using cached Whisper large-v3 model...", 60)
                logger.info("Reusing globally cached Whisper model for faster processing.")
                
            model = _WHISPER_MODEL_CACHE
            
            self.progress_signal.emit("Transcribing vocal tracks (large-v3)...", 75)
            
            # Log and apply language override
            if self.language:
                logger.info(f"Transcribing [{self.song_name}] with forced language: {self.language}")
                result = model.transcribe(vocal_file, language=self.language)
            else:
                logger.info(f"Transcribing [{self.song_name}] with auto-detect language mode.")
                result = model.transcribe(vocal_file)
            logger.info("Vocal transcription completed successfully.")
            
            self.progress_signal.emit("Formatting synchronized lyrics...", 90)
            
            # Convert stable-ts result into our karaoke JSON format
            lyrics_data = []
            
            # stable-ts results contain segments, each segment has words
            for segment in result.segments:
                line_text = segment.text.strip()
                line_start = segment.start
                line_end = segment.end
                
                line_words = []
                # Check if segment has words
                if hasattr(segment, 'words') and segment.words:
                    for w in segment.words:
                        line_words.append({
                            "word": w.word.strip(),
                            "start": round(w.start, 2),
                            "end": round(w.end, 2)
                        })
                else:
                    # Fallback if words aren't separate: treat full segment as one word
                    line_words.append({
                        "word": line_text,
                        "start": round(line_start, 2),
                        "end": round(line_end, 2)
                    })
                    
                lyrics_data.append({
                    "text": line_text,
                    "start": round(line_start, 2),
                    "end": round(line_end, 2),
                    "words": line_words
                })
                
            # If no lyrics transcribed, generate a single empty line
            if not lyrics_data:
                lyrics_data.append({
                    "text": "(Instrumental Track)",
                    "start": 0.0,
                    "end": 10.0,
                    "words": [{"word": "(Instrumental", "start": 0.0, "end": 5.0}, {"word": "Track)", "start": 5.0, "end": 10.0}]
                })

            # Save the compiled json file with both stem paths
            with open(dest_json_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "lyrics": lyrics_data,
                    "instrumental_path": instrumental_dest_path,
                    "vocal_path": vocal_dest_path
                }, f, indent=4, ensure_ascii=False)
                
            self.progress_signal.emit("Karaoke lyrics compiled successfully!", 100)
            self.finished_signal.emit(self.song_path, dest_json_path)

        finally:
            # Clean up the Demucs temporary files
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
