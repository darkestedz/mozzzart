import os
import logging
import time
import random
from PyQt6.QtCore import QThread, pyqtSignal
import yt_dlp
import utils

logger = logging.getLogger("PlayerDownloader")

class DownloadWorker(QThread):
    """
    Background worker thread for bulk fetching audio from a list of YouTube links.
    Handles parallel dry-run metadata resolution and sequential audio downloading
    and conversion to avoid CPU/network bottlenecks.
    """
    # Emits list of resolved video titles: [{'idx': idx, 'title': title, 'url': url}]
    metadata_resolved_signal = pyqtSignal(list)
    
    # Emits dict with keys: 'idx' (int), 'percent' (float), 'speed' (str), 'eta' (str), 'status' (str)
    progress_signal = pyqtSignal(dict)
    
    # Emits when a single track finishes: idx (int), title (str), local_file_path (str)
    track_finished_signal = pyqtSignal(int, str, str)
    
    # Emits when a single track fails: idx (int), error_msg (str)
    track_error_signal = pyqtSignal(int, str)
    
    # Emits when the entire queue has completed processing
    all_finished_signal = pyqtSignal()

    def __init__(self, urls_list, output_dir):
        super().__init__()
        self.urls_list = urls_list
        self.output_dir = output_dir
        self.resolved_tracks = []
        self._is_cancelled = False
        self.active_idx = -1
        self.cancelled_indices = set()

    def cancel_idx(self, idx):
        """Cancels a specific index in the queue."""
        self.cancelled_indices.add(idx)

    def run(self):
        # Run at low priority so audio playback is never starved
        self.setPriority(QThread.Priority.LowPriority)
        logger.info(f"Starting bulk download thread for {len(self.urls_list)} URLs")
        
        # Ensure dependencies exist
        if not utils.has_dependencies():
            logger.warning("Ffmpeg or yt-dlp missing locally, attempting self-setup...")
            try:
                utils.setup_dependencies()
            except Exception as e:
                # Dispatch setup failure to all tracks
                for idx in range(len(self.urls_list)):
                    self.track_error_signal.emit(idx, f"Local dependencies missing and auto-setup failed: {e}")
                self.all_finished_signal.emit()
                return

        ffmpeg_path = utils.get_ffmpeg_path()
        ytdlp_path = utils.get_ytdlp_path()
        
        # Phase 1: Dry-Run Meta-Fetcher for all URLs (fast, concurrent-like metadata fetch)
        logger.info("Starting dry-run metadata extraction loop...")
        self.resolved_tracks = []
        
        ydl_meta_opts = {
            'quiet': True,
            'nocheckcertificate': True,
            'extract_flat': True, # extremely fast extraction without downloading formats
        }
        
        for idx, url in enumerate(self.urls_list):
            if self._is_cancelled:
                self.all_finished_signal.emit()
                return
                
            title = "Resolving link..."
            resolved_url = url
            try:
                with yt_dlp.YoutubeDL(ydl_meta_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if url.startswith("ytsearch") and info and info.get('entries'):
                        entry = info['entries'][0]
                        title = entry.get('title', f"YouTube Track {idx + 1}")
                        video_id = entry.get('id')
                        if video_id:
                            resolved_url = f"https://www.youtube.com/watch?v={video_id}"
                    else:
                        title = info.get('title', f"YouTube Track {idx + 1}")
            except Exception as e:
                logger.error(f"Failed to extract metadata for {url}: {e}")
                title = f"Unable to resolve URL ({url[:30]}...)"
                
            self.resolved_tracks.append({
                "idx": idx,
                "title": title,
                "url": resolved_url
            })
            
        # Emit all resolved titles immediately to populate the UI list
        self.metadata_resolved_signal.emit(self.resolved_tracks)
        
        # Phase 2: Sequential byte downloading and conversion
        logger.info("Starting sequential payload downloads...")
        
        for track in self.resolved_tracks:
            idx = track["idx"]
            url = track["url"]
            title = track["title"]
            self.active_idx = idx
            
            if self._is_cancelled:
                break
                
            if idx in self.cancelled_indices:
                self.track_error_signal.emit(idx, "Cancelled")
                continue
                
            # If metadata resolution failed completely, skip downloading and emit error
            if "Unable to resolve URL" in title:
                self.track_error_signal.emit(idx, "Invalid YouTube link or extraction timed out.")
                continue

            # Apply random rate-limiting delay between downloads to prevent IP blocks
            if idx > 0 and not self._is_cancelled:
                delay = random.uniform(1.5, 3.5)
                logger.info(f"Applying safety rate-limit delay of {delay:.2f} seconds before downloading track {idx}...")
                self.progress_signal.emit({
                    "idx": self.active_idx,
                    "percent": 0.0,
                    "speed": "Cooldown",
                    "eta": f"{delay:.1f}s",
                    "status": "Waiting..."
                })
                # Sleep in small responsive increments to remain cancellable
                start_sleep = time.time()
                while time.time() - start_sleep < delay:
                    if self._is_cancelled or self.active_idx in self.cancelled_indices:
                        break
                    time.sleep(0.1)

            if self._is_cancelled:
                break

            if self.active_idx in self.cancelled_indices:
                self.track_error_signal.emit(idx, "Cancelled")
                continue

            # We need a progress hook to capture the downloaded percentage for this active track
            def ytdlp_progress_hook(d):
                if self._is_cancelled or self.active_idx in self.cancelled_indices:
                    raise Exception("Download cancelled by user.")
                    
                if d['status'] == 'downloading':
                    # Parse progress percentage
                    total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded_bytes = d.get('downloaded_bytes', 0)
                    
                    percent = 0.0
                    if total_bytes > 0:
                        percent = (downloaded_bytes / total_bytes) * 100.0
                    else:
                        percent_str = d.get('_percent_str', '0%').replace('%', '').strip()
                        try:
                            percent = float(percent_str)
                        except ValueError:
                            percent = 0.0

                    # Formulate human-readable speed
                    speed_bytes = d.get('speed', 0)
                    speed_str = "0 KB/s"
                    if speed_bytes:
                        if speed_bytes > 1024 * 1024:
                            speed_str = f"{speed_bytes / (1024 * 1024):.2f} MB/s"
                        else:
                            speed_str = f"{speed_bytes / 1024:.1f} KB/s"

                    # Formulate human-readable ETA
                    eta = d.get('eta', 0)
                    eta_str = f"{eta}s" if eta else "Unknown"
                    if eta:
                        mins, secs = divmod(eta, 60)
                        eta_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

                    self.progress_signal.emit({
                        "idx": self.active_idx,
                        "percent": percent,
                        "speed": speed_str,
                        "eta": eta_str,
                        "status": "Downloading"
                    })
                elif d['status'] == 'finished':
                    self.progress_signal.emit({
                        "idx": self.active_idx,
                        "percent": 100.0,
                        "speed": "0 KB/s",
                        "eta": "0s",
                        "status": "Converting"
                    })

            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(self.output_dir, '%(title)s.%(ext)s'),
                'ffmpeg_location': ffmpeg_path,
                'progress_hooks': [ytdlp_progress_hook],
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'nocheckcertificate': True,
                'quiet': True,
                'no_warnings': True,
            }

            try:
                # Trigger single track download
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

                # Locate output file
                expected_filename = f"{title}.mp3"
                dest_filepath = os.path.join(self.output_dir, expected_filename)
                
                # Double check paths and fallbacks
                if not os.path.exists(dest_filepath):
                    mp3_files = [os.path.join(self.output_dir, f) for f in os.listdir(self.output_dir) if f.endswith(".mp3")]
                    if mp3_files:
                        dest_filepath = max(mp3_files, key=os.path.getmtime)
                        title = os.path.splitext(os.path.basename(dest_filepath))[0]
                    else:
                        raise FileNotFoundError("Could not locate post-processed MP3 audio file.")

                logger.info(f"Download finished for track {idx}: {title} -> {dest_filepath}")
                self.track_finished_signal.emit(idx, title, dest_filepath)

            except Exception as e:
                logger.error(f"Download failed for track {idx} ({url}): {e}")
                self.track_error_signal.emit(idx, str(e))

        logger.info("Bulk queue downloads complete.")
        self.all_finished_signal.emit()

    def cancel(self):
        """Cancels the download loop."""
        self._is_cancelled = True
