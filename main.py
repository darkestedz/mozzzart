import os
import re
import sys
import logging
import json
import ctypes

# ── PyInstaller Windowed Stream Protection ──────────────────────────────────
# In --windowed mode, PyInstaller sets sys.stdout and sys.stderr to None.
# Background ML libraries (like stable_ts and tqdm) frequently attempt to 
# write download progress to the console. We map them to a dummy stream here.
class DummyStream:
    def write(self, data): pass
    def flush(self): pass

if sys.stdout is None:
    sys.stdout = DummyStream()
if sys.stderr is None:
    sys.stderr = DummyStream()
# ── Windows Taskbar Icon Grouping Hook ─────────────────────────────────────
# Forces Windows to treat this process as its own app rather than grouping
# it under 'python.exe', ensuring our custom icon shows in the taskbar.
if sys.platform == "win32":
    try:
        myappid = "darkestedz.mozzzartplayer.player.v5"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception as e:
        print(f"[!] Failed to set explicit AppUserModelID: {e}")
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize, QThread
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QLabel, QPushButton, QSlider, QTableWidget,
    QTableWidgetItem, QLineEdit, QTextEdit, QPlainTextEdit, QProgressBar, QScrollArea,
    QFileDialog, QMessageBox, QFrame, QListWidget, QAbstractItemView,
    QDialog, QHeaderView, QListWidgetItem, QSizePolicy, QSpinBox, QComboBox, QCheckBox,
    QSizeGrip, QProgressDialog, QTabWidget
)
from PyQt6.QtGui import QFont, QIcon, QColor, QPainter, QPen, QImage, QPixmap, QMovie
import qtawesome as qta

# Import modules
import utils
import config
from player_engine_vlc import AudioPlayer, HAS_VLC
from downloader import DownloadWorker
from karaoke_engine import KaraokeProcessorWorker
from mic_worker import MicrophoneWorker
try:
    from web_remote import WebRemoteWorker, get_local_ip
    HAS_WEB_REMOTE = True
except ImportError:
    HAS_WEB_REMOTE = False
    logger.warning("Flask not installed — Web Remote / TV Streaming disabled. Run: pip install flask")
from styles import SPOTIFY_STYLE

# Setup initial logs
utils.configure_logger_to_file()
logger = logging.getLogger("AuraPlayer")

WHISPER_LANGUAGES = [
    "Afrikaans", "Albanian", "Amharic", "Arabic", "Armenian", "Assamese", 
    "Azerbaijani", "Bashkir", "Basque", "Belarusian", "Bengali", "Bosnian", 
    "Breton", "Bulgarian", "Cantonese", "Catalan", "Chinese", "Croatian", 
    "Czech", "Danish", "Dutch", "English", "Estonian", "Faroese", "Finnish", 
    "French", "Galician", "Georgian", "German", "Greek", "Gujarati", 
    "Haitian Creole", "Hausa", "Hawaiian", "Hebrew", "Hindi", "Hungarian", 
    "Icelandic", "Indonesian", "Italian", "Japanese", "Javanese", "Kannada", 
    "Kazakh", "Khmer", "Korean", "Lao", "Latin", "Latvian", "Lingala", 
    "Lithuanian", "Luxembourgish", "Macedonian", "Malagasy", "Malay", 
    "Malayalam", "Maltese", "Maori", "Marathi", "Mongolian", "Myanmar", 
    "Nepali", "Norwegian", "Norwegian Nynorsk", "Occitan", "Pashto", 
    "Persian", "Polish", "Portuguese", "Punjabi", "Romanian", "Russian", 
    "Sanskrit", "Serbian", "Shona", "Sindhi", "Sinhala", "Slovak", 
    "Slovenian", "Somali", "Spanish", "Sundanese", "Swahili", "Swedish", 
    "Tagalog", "Tajik", "Tamil", "Tatar", "Telugu", "Thai", "Tibetan", 
    "Turkish", "Turkmen", "Ukrainian", "Urdu", "Uzbek", "Vietnamese", 
    "Welsh", "Yiddish", "Yoruba"
]

# ── Environment Configuration ─────────────────────────────────────────────
# sys.frozen is automatically set by PyInstaller when the app is compiled.
# If True, we are in the public Production build. If False, we are in Dev mode.
IS_DEV_MODE = not getattr(sys, 'frozen', False)

def get_asset_path(filename):
    """Resolves absolute path to asset files for compiled and developer modes."""
    if os.path.isabs(filename):
        return filename
    if not IS_DEV_MODE:
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    resolved = os.path.join(base_dir, filename)
    if os.path.exists(resolved):
        return resolved
    return os.path.abspath(filename)


class NoScrollComboBox(QComboBox):
    """Custom QComboBox that ignores mouse wheel events to prevent accidental changes while scrolling."""
    def wheelEvent(self, event):
        event.ignore()

class SlashedButton(QPushButton):
    """Custom button that draws a clean diagonal slash directly on top of any MDL2 vector icon when slashed is True."""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._slashed = False
        
    def setSlashed(self, slashed):
        self._slashed = slashed
        self.update()
        
    def paintEvent(self, event):
        super().paintEvent(event)
        if self._slashed:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            # Sleek 2px wide gray slash over the central vector glyph:
            pen = QPen(QColor("#B3B3B3"), 2)
            painter.setPen(pen)
            w, h = self.width(), self.height()
            painter.drawLine(int(w * 0.65), int(h * 0.35), int(w * 0.35), int(h * 0.65))
            painter.end()

class MozartPlayer(QLabel):
    loop_finished = pyqtSignal()

    def __init__(self, gif_path):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        resolved_path = get_asset_path(gif_path)
        self.movie = QMovie(resolved_path)
        self.movie.setCacheMode(QMovie.CacheMode.CacheAll)
        
        # Jump to the first frame to read the GIF's native resolution
        self.movie.jumpToFrame(0)
        native_size = self.movie.currentImage().size()
        
        if not native_size.isEmpty():
            # Scale the GIF down to fit a maximum area of 300x450 without stretching
            scaled_size = native_size.scaled(300, 450, Qt.AspectRatioMode.KeepAspectRatio)
            self.movie.setScaledSize(scaled_size)
            self.setFixedSize(scaled_size) # Hug the layout tightly around the newly scaled GIF
        else:
            # Fallback just in case the image data isn't immediately ready
            self.setFixedSize(250, 450)
            self.setScaledContents(True)

        self.setMovie(self.movie)
        
        # Detect loop completion natively
        self.movie.frameChanged.connect(self._on_frame_changed)

    def _on_frame_changed(self, frame_number):
        # Check if this is the absolute last frame of the GIF
        if self.movie.frameCount() > 1 and frame_number == self.movie.frameCount() - 1:
            self.loop_finished.emit()

    def start(self):
        self.movie.start()

    def stop(self):
        self.movie.stop()
        self.movie.jumpToFrame(0) 

    def update_gif(self, gif_path):
        """Seamlessly hot-swaps the GIF, recalculates scale, and resumes playback."""
        was_playing = (self.movie.state() == QMovie.MovieState.Running)
        self.movie.stop()
        resolved_path = get_asset_path(gif_path)
        self.movie.setFileName(resolved_path)
        self.movie.jumpToFrame(0)
        
        native_size = self.movie.currentImage().size()
        if not native_size.isEmpty():
            scaled_size = native_size.scaled(300, 450, Qt.AspectRatioMode.KeepAspectRatio)
            self.movie.setScaledSize(scaled_size)
            self.setFixedSize(scaled_size)
            
        if was_playing:
            self.movie.start() 

class DropTableWidget(QTableWidget):
    """
    Premium drag-and-drop enabled QTableWidget.
    Accepts .mp3 and .wav audio files dragged in from Windows Explorer
    and emits a list of valid file paths via files_dropped signal.
    Displays a dynamic gold/green overlay hint while files are hovered.
    """
    files_dropped = pyqtSignal(list)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self._drag_active = False

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            valid = any(
                url.toLocalFile().lower().endswith((".mp3", ".wav"))
                for url in urls
            )
            if valid:
                self._drag_active = True
                self.update()
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._drag_active = False
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._drag_active = False
        self.update()
        if event.mimeData().hasUrls():
            paths = [
                url.toLocalFile()
                for url in event.mimeData().urls()
                if url.toLocalFile().lower().endswith((".mp3", ".wav"))
            ]
            if paths:
                self.files_dropped.emit(paths)
                event.acceptProposedAction()
                return
        event.ignore()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drag_active:
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            # Semi-transparent dark overlay
            painter.fillRect(self.viewport().rect(), QColor(0, 0, 0, 140))
            # Gold glowing border
            pen = QPen(QColor("#F0C419"), 3)
            painter.setPen(pen)
            painter.drawRoundedRect(self.viewport().rect().adjusted(4, 4, -4, -4), 8, 8)
            # Center icon + text
            painter.setPen(QColor("#F0C419"))
            font = painter.font()
            font.setPointSize(22)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                self.viewport().rect().adjusted(0, -30, 0, -30),
                Qt.AlignmentFlag.AlignCenter,
                "Drop Audio Files Here"
            )
            font.setPointSize(12)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor("#2D7D46"))
            painter.drawText(
                self.viewport().rect().adjusted(0, 30, 0, 30),
                Qt.AlignmentFlag.AlignCenter,
                ".mp3  •  .wav"
            )
            painter.end()


class DropListWidget(QListWidget):
    """Drag-and-drop enabled QListWidget for external GIF files."""
    files_dropped = pyqtSignal(list)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile().lower().endswith(".gif")]
            if paths:
                self.files_dropped.emit(paths)
                event.acceptProposedAction()
                return
        event.ignore()


class DependencySetupDialog(QDialog):
    """Modern popup dialog that handles the download of portable dependencies on first-run."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("First-Time Setup")
        self.setWindowIcon(QIcon(get_asset_path("logo.png")))
        self.setFixedSize(400, 220)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        self.setStyleSheet("background-color: #121212; color: white;")
        
        layout = QVBoxLayout()
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(10)
        
        self.title_label = QLabel("🎤 MozZzart Player Setup")
        self.title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #F0C419;")
        layout.addWidget(self.title_label)
        
        self.desc_label = QLabel("Downloading portable dependencies (yt-dlp and FFmpeg) for audio conversion and streaming. This happens only once...")
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color: #B3B3B3; font-size: 12px; line-height: 16px; margin-bottom: 10px;")
        layout.addWidget(self.desc_label)
        
        self.status_label = QLabel("Initializing setup...")
        self.status_label.setStyleSheet("font-weight: bold; color: white;")
        layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #222222;
                border-radius: 5px;
                height: 10px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #1DB954;
                border-radius: 5px;
            }
        """)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        self.setLayout(layout)
        
        # Start download process after window displays
        QTimer.singleShot(100, self.start_setup)

    def start_setup(self):
        try:
            class SetupWorker(QThread):
                prog = pyqtSignal(float)
                stat = pyqtSignal(str)
                done = pyqtSignal()
                fail = pyqtSignal(str)
                
                def run(self):
                    try:
                        utils.setup_dependencies(
                            progress_callback=self.prog.emit,
                            status_callback=self.stat.emit
                        )
                        self.done.emit()
                    except Exception as e:
                        self.fail.emit(str(e))
            
            self.worker = SetupWorker()
            self.worker.prog.connect(lambda p: self.progress_bar.setValue(int(p * 100)))
            self.worker.stat.connect(self.status_label.setText)
            self.worker.done.connect(self.accept)
            self.worker.fail.connect(self.on_fail)
            self.worker.start()
        except Exception as e:
            QMessageBox.critical(self, "Setup Error", f"Failed to initialize download pipeline: {e}")
            self.reject()

    def on_fail(self, error_msg):
        QMessageBox.critical(self, "Setup Failed", f"An error occurred while installing dependencies:\n{error_msg}")
        self.reject()


class SpotifyCredentialsDialog(QDialog):
    """Premium dialog prompting the user for Spotify Developer API credentials."""
    def __init__(self, parent=None, client_id="", client_secret=""):
        super().__init__(parent)
        self.setWindowTitle("Spotify Developer Credentials")
        self.setWindowIcon(QIcon(get_asset_path("logo.png")))
        self.setFixedSize(450, 290)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #121212;
                border: 1px solid #1DB954;
                border-radius: 8px;
            }
            QLabel {
                color: #FFFFFF;
                font-family: 'Segoe UI', sans-serif;
            }
            QLineEdit {
                background-color: #1A1A1A;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 8px 12px;
                color: #FFFFFF;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #1DB954;
            }
            QPushButton {
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                font-weight: bold;
                border-radius: 15px;
                padding: 8px 16px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header_lbl = QLabel("🔌 Spotify-to-YouTube Bridge")
        header_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #1DB954;")
        layout.addWidget(header_lbl)
        
        # Instructions
        desc_lbl = QLabel(
            "To download Spotify playlists, you need a free Developer Client ID & Client Secret.\n"
            "1. Visit: developer.spotify.com/dashboard\n"
            "2. Log in and create an App (set redirect URI to http://localhost).\n"
            "3. Copy and paste the credentials below."
        )
        desc_lbl.setStyleSheet("font-size: 11px; color: #B3B3B3; line-height: 15px;")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)
        
        # Client ID Input
        id_layout = QHBoxLayout()
        id_lbl = QLabel("Client ID:")
        id_lbl.setFixedWidth(80)
        self.id_input = QLineEdit()
        self.id_input.setText(client_id)
        self.id_input.setPlaceholderText("Paste Spotify Client ID here...")
        id_layout.addWidget(id_lbl)
        id_layout.addWidget(self.id_input)
        layout.addLayout(id_layout)
        
        # Client Secret Input
        secret_layout = QHBoxLayout()
        secret_lbl = QLabel("Client Secret:")
        secret_lbl.setFixedWidth(80)
        self.secret_input = QLineEdit()
        self.secret_input.setText(client_secret)
        self.secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret_input.setPlaceholderText("Paste Spotify Client Secret here...")
        secret_layout.addWidget(secret_lbl)
        secret_layout.addWidget(self.secret_input)
        layout.addLayout(secret_layout)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #222222;
                color: #FFFFFF;
                border: 1px solid #444444;
            }
            QPushButton:hover {
                background-color: #333333;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_save = QPushButton("Save Credentials")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: #1DB954;
                color: #FFFFFF;
                border: none;
            }
            QPushButton:hover {
                background-color: #1ED760;
            }
        """)
        btn_save.clicked.connect(self.handle_save)
        btn_layout.addWidget(btn_save)
        
        layout.addLayout(btn_layout)
        
    def handle_save(self):
        self.client_id = self.id_input.text().strip()
        self.client_secret = self.secret_input.text().strip()
        if not self.client_id or not self.client_secret:
            QMessageBox.warning(self, "Missing Fields", "Please enter both Client ID and Client Secret.")
            return
        self.accept()


class SpotifyFetchDialog(QDialog):
    """Lightweight modal loading dialog during Spotify metadata extraction."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fetching Spotify Playlist")
        self.setFixedSize(320, 130)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        self.setStyleSheet("background-color: #121212; color: white;")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(12)
        
        self.status_lbl = QLabel("📡 Connecting to Spotify...")
        self.status_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #1DB954;")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_lbl)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #222222;
                border-radius: 4px;
                height: 8px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #1DB954;
                border-radius: 4px;
            }
        """)
        self.progress_bar.setRange(0, 0) # Infinite pulse
        layout.addWidget(self.progress_bar)

    def update_status(self, text):
        self.status_lbl.setText(text)


class SpotifyScraperWorker(QThread):
    """Background worker thread that runs headless Chromium to scrape Spotify playlists in real-time."""
    status = pyqtSignal(str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def __init__(self, playlist_urls, target_count=0):
        super().__init__()
        self.playlist_urls = playlist_urls
        self.target_count = target_count
        
    def run(self):
        try:
            import os
            import time
            from playwright.sync_api import sync_playwright
            
            all_queries = []
            for url in self.playlist_urls:
                self.status.emit("🌐 Starting headless browser...")
                extracted_tracks = set()
                
                with sync_playwright() as p:
                    # Initialize headless Chromium
                    browser = p.chromium.launch(headless=True)
                    
                    context = browser.new_context(
                        viewport={'width': 1280, 'height': 800},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
                    )
                    page = context.new_page()
                    
                    self.status.emit("📡 Navigating to Spotify playlist...")
                    page.goto(url, wait_until="networkidle", timeout=60000)
                    
                    self.status.emit("📜 Scraping tracks (Live DOM scrolling)...")
                    
                    # Scroll down in increments
                    consecutive_no_scroll = 0
                    idle_scrolls = 0
                    last_track_count = 0
                    
                    # Smart scrolling and real-time extraction loop
                    while True:
                        # Target count check
                        if self.target_count > 0 and len(extracted_tracks) >= self.target_count:
                            self.status.emit(f"🎯 Target count of {self.target_count} tracks reached!")
                            break
                            
                        # The 'Yank' Method (Step 1 & 2)
                        track_rows = page.locator('div[data-testid="tracklist-row"]')
                        current_count = track_rows.count()
                        
                        if current_count > 0:
                            try:
                                # Force the browser to yank the very last loaded track onto the screen
                                track_rows.nth(current_count - 1).scroll_into_view_if_needed()
                                page.wait_for_timeout(1000) # Wait 1 second for the network to fetch the next batch
                            except Exception as e:
                                logger.warning(f"DOM scroll targeting failed: {e}")
                                # Fallback to JavaScript window scroll if the element is obscured
                                page.evaluate("window.scrollBy(0, 1000)")
                                page.wait_for_timeout(1000)
                        else:
                            page.evaluate("window.scrollBy(0, 1000)")
                            page.wait_for_timeout(1000)
                        
                        # CRITICAL TIMING: Wait for network idle or wait for loaders to turn to real text
                        try:
                            page.wait_for_load_state('networkidle', timeout=1000)
                        except Exception:
                            pass
                        
                        # Real-time extraction of currently visible rows in the DOM
                        result = page.evaluate("""
                            () => {
                                // 1. Check for Recommended sections to trigger the kill switch
                                let stopScrolling = false;
                                const stopElements = document.querySelectorAll('h2, h3, [class*="Header"], [data-testid*="header"]');
                                for (let el of stopElements) {
                                    if (el.innerText) {
                                        const txt = el.innerText.trim().toLowerCase();
                                        if (txt === "recommended" || txt === "recommended songs" || txt === "based on this playlist") {
                                            stopScrolling = true;
                                            break;
                                        }
                                    }
                                }
                                
                                // Helper to extract track number
                                function getTrackNumber(row) {
                                    const numEl = row.querySelector('span[class*="number"], div[class*="number"], span[class*="index"], div[class*="index"], [class*="row-number"], [aria-colindex="1"]');
                                    if (numEl) {
                                        const txt = numEl.innerText ? numEl.innerText.trim() : "";
                                        if (/^\\d+$/.test(txt)) {
                                            return parseInt(txt, 10);
                                        }
                                    }
                                    
                                    const elements = row.querySelectorAll('span, div, p');
                                    for (let i = 0; i < Math.min(elements.length, 15); i++) {
                                        const el = elements[i];
                                        if (el.closest('a[href*="/track/"], a[href*="/artist/"], [data-testid="internal-track-link"]')) {
                                            continue;
                                        }
                                        const txt = el.innerText ? el.innerText.trim() : "";
                                        if (/^\\d+$/.test(txt)) {
                                            return parseInt(txt, 10);
                                        }
                                    }
                                    return null;
                                }

                                const rows = document.querySelectorAll('div[data-testid="tracklist-row"]');
                                const data = [];
                                rows.forEach(row => {
                                    // Verify row has a valid numeric index (Condition 1 & 2)
                                    const trackNum = getTrackNumber(row);
                                    if (trackNum === null) {
                                        return; // Ignore row (Condition 2)
                                    }
                                    
                                    let titleEl = row.querySelector('a[href*="/track/"], [data-testid="internal-track-link"]');
                                    if (!titleEl) {
                                        titleEl = row.querySelector('div[class*="trackName"], div[class*="title"], div.standalone-ellipsis-one-line');
                                    }
                                    
                                    let artistEls = row.querySelectorAll('a[href*="/artist/"]');
                                    let artist = "";
                                    if (artistEls.length > 0) {
                                        artist = Array.from(artistEls).map(el => el.innerText.trim()).filter(Boolean).join(" ");
                                    } else {
                                        let artistEl = row.querySelector('span[class*="artist"], div[class*="artist"]');
                                        if (artistEl) {
                                            artist = artistEl.innerText.trim();
                                        }
                                    }
                                    
                                    let title = titleEl ? titleEl.innerText.trim() : "";
                                    if (title) {
                                        data.push({ title, artist: artist || "Unknown Artist" });
                                    }
                                });
                                return { tracks: data, stop_scrolling: stopScrolling };
                            }
                        """)
                        
                        visible_tracks = result.get("tracks", [])
                        stop_scrolling = result.get("stop_scrolling", False)
                        
                        # Format and add to set
                        for track in visible_tracks:
                            query = f"{track['artist']} - {track['title']} lyrics"
                            extracted_tracks.add(query)
                            
                        # Kill switch (Condition 3)
                        if stop_scrolling:
                            self.status.emit("🛑 'Recommended' section detected. Stopping scroll loop.")
                            break
                            
                        # Emit status update with current count
                        self.status.emit(f"📜 Live Scraped {len(extracted_tracks)} tracks...")
                        
                        # Infinite Loop Failsafe check (Step 4)
                        if len(extracted_tracks) > last_track_count:
                            last_track_count = len(extracted_tracks)
                            idle_scrolls = 0
                        else:
                            idle_scrolls += 1
                            
                        if idle_scrolls >= 20:
                            self.status.emit(f"⚠️ Scrolling idle for 20 increments. Proceeding with {len(extracted_tracks)} tracks.")
                            break
                            
                        # Scroll bounds checking (standard bottom fallback)
                        new_scroll = page.evaluate("window.scrollY + window.innerHeight")
                        total_height = page.evaluate("document.body.scrollHeight")
                        
                        if new_scroll >= total_height:
                            time.sleep(1.0)
                            total_height = page.evaluate("document.body.scrollHeight")
                            if new_scroll >= total_height:
                                consecutive_no_scroll += 1
                            else:
                                consecutive_no_scroll = 0
                        else:
                            consecutive_no_scroll = 0
                            
                        if consecutive_no_scroll >= 3:
                            # Reached bottom and no more content is loading
                            break
                    
                    # Convert set to sorted list to maintain stable order
                    queries = sorted(list(extracted_tracks))
                    all_queries.extend(queries)
                    
                    # Save queries to local debug directory for inspection
                    try:
                        debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_spotify")
                        os.makedirs(debug_dir, exist_ok=True)
                        
                        queries_path = os.path.join(debug_dir, "parsed_queries.txt")
                        with open(queries_path, "w", encoding="utf-8") as f:
                            for q in queries:
                                f.write(f"{q}\n")
                        logger.info(f"Saved parsed queries to {queries_path}")
                    except Exception as write_err:
                        logger.warning(f"Failed to write debug files: {write_err}")
                        
                    page.close()
                    context.close()
                    browser.close()
                    
            self.finished.emit(all_queries)
            
        except Exception as e:
            logger.exception("Error in SpotifyScraperWorker execution:")
            self.error.emit(str(e))


class MiniPlayerWindow(QWidget):
    """
    Compact floating mini player that appears when the user minimizes the main window.
    Features an expandable, searchable library list that stretches upwards.
    """
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setWindowTitle("MozZzart Mini")
        self.setWindowIcon(QIcon(get_asset_path("logo.png")))
        self.setFixedSize(380, 110)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_start = None
        self.is_expanded = False

        # Root container with dark rounded glass look
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        container = QFrame(self)
        container.setObjectName("MiniContainer")
        container.setStyleSheet("""
            QFrame#MiniContainer {
                background-color: rgba(10, 10, 10, 240);
                border-radius: 14px;
                border: 1.5px solid #F0C419;
            }
        """)
        root.addWidget(container)

        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(16, 10, 16, 10)
        main_layout.setSpacing(6)

        # ── Top row: track info + expand + restore + close ──
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.mini_title = QLabel("No Song Playing")
        self.mini_title.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: bold;")
        self.mini_title.setMaximumWidth(240)
        self.mini_title.setWordWrap(False)
        top_row.addWidget(self.mini_title, stretch=1)

        # Expand upwards button
        self.btn_expand = QPushButton()
        self.btn_expand.setIcon(qta.icon('fa5s.chevron-up', color='#1DB954'))
        self.btn_expand.setIconSize(QSize(13, 13))
        self.btn_expand.setToolTip("Expand Library")
        self.btn_expand.setFixedSize(28, 28)
        self.btn_expand.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background: #1E1E1E; }
        """)
        self.btn_expand.clicked.connect(self.toggle_expand)
        top_row.addWidget(self.btn_expand)

        # Restore (maximize) button
        btn_restore = QPushButton()
        btn_restore.setIcon(qta.icon('fa5s.expand', color='#F0C419'))
        btn_restore.setIconSize(QSize(13, 13))
        btn_restore.setToolTip("Restore Full Player")
        btn_restore.setFixedSize(28, 28)
        btn_restore.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background: #1E1E1E; }
        """)
        btn_restore.clicked.connect(self.main_app.restore_from_mini)
        top_row.addWidget(btn_restore)

        # Close button
        btn_close = QPushButton()
        btn_close.setIcon(qta.icon('fa5s.times', color='#888888'))
        btn_close.setIconSize(QSize(13, 13))
        btn_close.setToolTip("Close MozZzart")
        btn_close.setFixedSize(28, 28)
        btn_close.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background: #330000; color: #FF5555; }
        """)
        btn_close.clicked.connect(QApplication.instance().quit)
        top_row.addWidget(btn_close)

        main_layout.addLayout(top_row)

        # ── Artist label ──
        self.mini_artist = QLabel("MozZzart Engine")
        self.mini_artist.setStyleSheet("color: #888888; font-size: 11px;")
        main_layout.addWidget(self.mini_artist)

        # ── Controls row ──
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)
        ctrl_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        mini_icon_size = QSize(15, 15)
        btn_style = """
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 6px;
                min-width: 32px;
                min-height: 32px;
            }
            QPushButton:hover { background: #1A1A1A; }
            QPushButton:pressed { background: #2A2A2A; }
        """

        self.mini_shuffle = SlashedButton()
        self.mini_shuffle.setIcon(qta.icon('fa5s.random', color='#B3B3B3'))
        self.mini_shuffle.setIconSize(mini_icon_size)
        self.mini_shuffle.setStyleSheet(btn_style)
        self.mini_shuffle.setToolTip("Shuffle")
        self.mini_shuffle.clicked.connect(self.main_app.toggle_shuffle)
        ctrl_row.addWidget(self.mini_shuffle)

        mini_prev = QPushButton()
        mini_prev.setIcon(qta.icon('fa5s.step-backward', color='#B3B3B3'))
        mini_prev.setIconSize(mini_icon_size)
        mini_prev.setStyleSheet(btn_style)
        mini_prev.setToolTip("Previous")
        mini_prev.clicked.connect(self.main_app.play_previous_track)
        ctrl_row.addWidget(mini_prev)

        self.mini_play = QPushButton()
        self.mini_play.setIcon(qta.icon('fa5s.play', color='#0A0A0A'))
        self.mini_play.setIconSize(QSize(16, 16))
        self.mini_play.setFixedSize(40, 40)
        self.mini_play.setToolTip("Play / Pause")
        self.mini_play.setStyleSheet("""
            QPushButton {
                background-color: #F0C419;
                border: none;
                border-radius: 20px;
                min-width: 40px;
                min-height: 40px;
            }
            QPushButton:hover { background-color: #2D7D46; }
            QPushButton:pressed { background-color: #1A5C2E; }
        """)
        self.mini_play.clicked.connect(self.main_app.toggle_playback)
        ctrl_row.addWidget(self.mini_play)

        mini_next = QPushButton()
        mini_next.setIcon(qta.icon('fa5s.step-forward', color='#B3B3B3'))
        mini_next.setIconSize(mini_icon_size)
        mini_next.setStyleSheet(btn_style)
        mini_next.setToolTip("Next")
        mini_next.clicked.connect(self.main_app.play_next_track)
        ctrl_row.addWidget(mini_next)

        self.mini_repeat = SlashedButton()
        self.mini_repeat.setIcon(qta.icon('fa5s.redo-alt', color='#B3B3B3'))
        self.mini_repeat.setIconSize(mini_icon_size)
        self.mini_repeat.setStyleSheet(btn_style)
        self.mini_repeat.setToolTip("Repeat")
        self.mini_repeat.clicked.connect(self.main_app.toggle_repeat)
        ctrl_row.addWidget(self.mini_repeat)

        main_layout.addLayout(ctrl_row)

        # ── EXPANED LIBRARY SECTION ──
        self.library_container = QWidget()
        lib_layout = QVBoxLayout(self.library_container)
        lib_layout.setContentsMargins(0, 10, 0, 0)
        lib_layout.setSpacing(8)

        self.mini_search = QLineEdit()
        self.mini_search.setPlaceholderText("🔍 Search library...")
        self.mini_search.setStyleSheet("""
            QLineEdit {
                background-color: #1A1A1A; 
                border: 1px solid #333; 
                border-radius: 6px; 
                color: white; 
                padding: 6px 10px;
            }
        """)
        self.mini_search.textChanged.connect(self.filter_mini_library)
        lib_layout.addWidget(self.mini_search)

        self.mini_list = QListWidget()
        self.mini_list.setStyleSheet("""
            QListWidget { background-color: #121212; border: 1px solid #222; border-radius: 6px; color: #B3B3B3; outline: none; }
            QListWidget::item { padding: 10px; border-bottom: 1px solid #1E1E1E; }
            QListWidget::item:hover { background-color: #1A1A1A; color: white; }
            QListWidget::item:selected { background-color: #2D7D46; color: white; }
        """)
        self.mini_list.itemDoubleClicked.connect(self.play_mini_list_item)
        lib_layout.addWidget(self.mini_list)

        self.library_container.hide()
        main_layout.addWidget(self.library_container)

        # Marquee scroll timer for long titles
        self.marquee_timer = QTimer(self)
        self.marquee_timer.timeout.connect(self.update_marquee)
        self.full_title_text = ""
        self.padded_title = ""

        # Position bottom-right on screen
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 20, screen.bottom() - self.height() - 20)

    def toggle_expand(self):
        """Expands the mini player UPWARDS to reveal the searchable library list."""
        self.is_expanded = not self.is_expanded
        curr_geom = self.geometry()
        
        if self.is_expanded:
            self.btn_expand.setIcon(qta.icon('fa5s.chevron-down', color='#1DB954'))  # Chevron Down
            self.populate_mini_library()
            self.library_container.show()
            self.setFixedSize(380, 480)
            # Shift Y up by the difference (480 - 110 = 370) so the bottom anchors
            self.move(curr_geom.x(), curr_geom.y() - 370)
        else:
            self.btn_expand.setIcon(qta.icon('fa5s.chevron-up', color='#1DB954'))  # Chevron Up
            self.library_container.hide()
            self.setFixedSize(380, 110)
            # Shift Y down by the difference to collapse neatly back to the taskbar
            self.move(curr_geom.x(), curr_geom.y() + 370)

    def populate_mini_library(self, query=""):
        """Populates the mini list widget, optionally filtered by a search query."""
        self.mini_list.clear()
        query = query.lower()
        if hasattr(self.main_app, 'scanned_songs'):
            for song in self.main_app.scanned_songs:
                if query in song['name'].lower():
                    item = QListWidgetItem(f"{'🎤 ' if song['has_karaoke'] else ''}{song['name']}")
                    # Safely store the path in UserRole to pull for playback
                    item.setData(Qt.ItemDataRole.UserRole, song['path'])
                    self.mini_list.addItem(item)

    def filter_mini_library(self, text):
        self.populate_mini_library(text)

    def play_mini_list_item(self, item):
        """Finds the original song dictionary via the embedded path and loads it."""
        song_path = item.data(Qt.ItemDataRole.UserRole)
        for song in self.main_app.scanned_songs:
            if song["path"] == song_path:
                was_karaoke = getattr(self.main_app, 'karaoke_mode_active', False)
                self.main_app.load_and_play_track(song, auto_karaoke=was_karaoke)
                break

    def sync_state(self):
        """Syncs mini player labels and button states with the main player before showing."""
        cfg = self.main_app.config
        self.update_track_info(self.main_app.lbl_song_title.text(), self.main_app.lbl_song_artist.text())
        # Sync play/pause glyph
        is_playing = getattr(self.main_app.player, 'is_playing', lambda: False)()
        self.update_play_state(is_playing)
        # Sync shuffle
        self.mini_shuffle.setSlashed(not cfg.get("shuffle", False))
        # Sync repeat
        self.mini_repeat.setSlashed(not cfg.get("repeat", False))
        # Update the library list if expanded
        if self.is_expanded:
            self.populate_mini_library(self.mini_search.text())

    def update_track_info(self, title, artist):
        """Called from the main app whenever the playing track changes."""
        self.full_title_text = title
        self.padded_title = f"{title}   \u2022   "
        self.mini_artist.setText(artist)
        if getattr(self.main_app.player, 'is_playing', lambda: False)() and len(self.full_title_text) > 20:
            self.marquee_timer.start(250)
        else:
            self.marquee_timer.stop()
            self.mini_title.setText(self.full_title_text if len(self.full_title_text) <= 25 else self.full_title_text[:25] + "...")

    def update_play_state(self, is_playing):
        """Called from the main app whenever play/pause state changes."""
        self.mini_play.setIcon(qta.icon('fa5s.pause' if is_playing else 'fa5s.play', color='#0A0A0A'))
        if is_playing and getattr(self, 'full_title_text', "") and len(self.full_title_text) > 20:
            self.marquee_timer.start(250)
        else:
            if hasattr(self, 'marquee_timer'):
                self.marquee_timer.stop()
            if hasattr(self, 'full_title_text'):
                self.mini_title.setText(self.full_title_text if len(self.full_title_text) <= 25 else self.full_title_text[:25] + "...")

    def update_marquee(self):
        """Scrolls title text rightward for the marquee effect."""
        if hasattr(self, 'padded_title') and self.padded_title:
            self.padded_title = self.padded_title[-1] + self.padded_title[:-1]
            self.mini_title.setText(self.padded_title[:25])

    # ── Allow dragging the frameless window ──
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_start and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_start)

    def mouseReleaseEvent(self, event):
        self._drag_start = None


class LyricsCorrectionDialog(QDialog):
    """
    Premium modal dialog that allows users to edit and correct a song's lyrics.
    It validates that the corrected lyrics match the original vocal structure
    and fits/aligns the corrected text with the original synchronized timestamps.
    """
    def __init__(self, song, original_lyrics_db, parent=None):
        super().__init__(parent)
        self.song = song
        self.original_lyrics_db = original_lyrics_db
        self.confirmed_lyrics = None
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle(f"Correct Lyrics - {self.song['name']}")
        self.setMinimumSize(600, 500)
        self.resize(650, 550)
        
        # Modern MozZzart Player Style
        self.setStyleSheet("""
            QDialog {
                background-color: #121212;
                border: 1px solid #333333;
                border-radius: 8px;
            }
            QLabel {
                color: #FFFFFF;
                font-family: 'Segoe UI', sans-serif;
            }
            QPlainTextEdit {
                background-color: #1E1E1E;
                color: #FFFFFF;
                border: 1px solid #333333;
                border-radius: 6px;
                font-size: 14px;
                font-family: 'Segoe UI', Consolas, monospace;
                padding: 10px;
            }
            QPushButton {
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                font-weight: bold;
                border-radius: 18px;
                padding: 8px 16px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header Label
        header_lbl = QLabel(f"Edit/Correct Lyrics for: {self.song['name']}")
        header_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #F0C419;")
        layout.addWidget(header_lbl)
        
        desc_lbl = QLabel(
            "Instructions: You can fix typos, spelling errors, or correct full lines. "
            "Our engine will automatically align your corrected text to the vocal timing.\n"
            "If the similarity is low, the timing will be estimated, but you can always force save."
        )
        desc_lbl.setStyleSheet("font-size: 11px; color: #888888; line-height: 16px;")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)
        
        # Current lyrics assembly
        self.text_edit = QPlainTextEdit()
        orig_text = ""
        if self.original_lyrics_db and "lyrics" in self.original_lyrics_db:
            orig_text = "\n".join([line["text"] for line in self.original_lyrics_db["lyrics"]])
        self.text_edit.setPlainText(orig_text)
        layout.addWidget(self.text_edit, stretch=1)
        
        # Similarity display label
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("font-size: 12px; color: #888888; font-weight: bold;")
        layout.addWidget(self.status_lbl)
        
        # Connect textChanged signal to update similarity live
        self.text_edit.textChanged.connect(self.update_similarity_status)
        self.update_similarity_status() # Initial display
        
        # Buttons Row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.btn_smart_correct = QPushButton("✨ Smart Correction")
        self.btn_smart_correct.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_smart_correct.setStyleSheet("""
            QPushButton {
                background-color: #1A1A1A;
                color: #F0C419;
                border: 1px solid #F0C419;
            }
            QPushButton:hover {
                background-color: #F0C419;
                color: #121212;
            }
            QPushButton:disabled {
                background-color: #222222;
                color: #555555;
                border: 1px solid #333333;
            }
        """)
        self.btn_smart_correct.clicked.connect(self.handle_smart_correct)
        
        # Check Gemini API Key
        cfg = {}
        parent = self.parent()
        if parent and hasattr(parent, 'config'):
            cfg = parent.config
        else:
            try:
                import config
                cfg = config.load_config()
            except Exception:
                pass
        self.gemini_api_key = cfg.get("gemini_api_key", "").strip()
        if not self.gemini_api_key:
            self.btn_smart_correct.setEnabled(False)
            self.btn_smart_correct.setToolTip("Please input a Gemini API Key in Settings to unlock Smart Correction.")
            
        btn_layout.addWidget(self.btn_smart_correct)
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #222222;
                color: #FFFFFF;
                border: 1px solid #444444;
            }
            QPushButton:hover {
                background-color: #333333;
                border: 1px solid #555555;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        self.btn_confirm = QPushButton("Confirm")
        self.btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_confirm.setStyleSheet("""
            QPushButton {
                background-color: #2D7D46;
                color: #FFFFFF;
                border: none;
            }
            QPushButton:hover {
                background-color: #399B55;
            }
        """)
        self.btn_confirm.clicked.connect(self.handle_confirm)
        btn_layout.addWidget(self.btn_confirm)
        
        layout.addLayout(btn_layout)
        
    def update_similarity_status(self):
        corrected_text = self.text_edit.toPlainText().strip()
        if not corrected_text:
            self.status_lbl.setText("")
            return
            
        orig_text = ""
        if self.original_lyrics_db and "lyrics" in self.original_lyrics_db:
            orig_text = "\n".join([line["text"] for line in self.original_lyrics_db["lyrics"]])
            
        import re
        import difflib
        
        def clean_to_tokens(text):
            return re.sub(r'[^\w\s]', '', text.lower()).split()
            
        orig_tokens = clean_to_tokens(orig_text)
        corr_tokens = clean_to_tokens(corrected_text)
        
        if not orig_tokens:
            similarity = 1.0
        else:
            sm = difflib.SequenceMatcher(None, orig_tokens, corr_tokens)
            similarity = sm.ratio()
            
        pct = int(similarity * 100)
        if similarity >= 0.65:
            self.status_lbl.setText(f"Similarity: {pct}% (Excellent match - direct alignment)")
            self.status_lbl.setStyleSheet("font-size: 12px; color: #2D7D46; font-weight: bold;")
        elif similarity >= 0.40:
            self.status_lbl.setText(f"Similarity: {pct}% (Good match - will align closely)")
            self.status_lbl.setStyleSheet("font-size: 12px; color: #F0C419; font-weight: bold;")
        else:
            self.status_lbl.setText(f"Similarity: {pct}% (Low match - timing will be estimated where words differ)")
            self.status_lbl.setStyleSheet("font-size: 12px; color: #D32F2F; font-weight: bold;")
            
    def handle_confirm(self):
        corrected_text = self.text_edit.toPlainText().strip()
        if not corrected_text:
            QMessageBox.warning(self, "Empty Lyrics", "Lyrics cannot be blank.")
            return
            
        # Get original text to compare
        orig_text = ""
        if self.original_lyrics_db and "lyrics" in self.original_lyrics_db:
            orig_text = "\n".join([line["text"] for line in self.original_lyrics_db["lyrics"]])
            
        # Similarity check
        import difflib
        import re
        
        def clean_to_tokens(text):
            return re.sub(r'[^\w\s]', '', text.lower()).split()
            
        orig_tokens = clean_to_tokens(orig_text)
        corr_tokens = clean_to_tokens(corrected_text)
        
        if not orig_tokens:
            similarity = 1.0
        else:
            sm = difflib.SequenceMatcher(None, orig_tokens, corr_tokens)
            similarity = sm.ratio()
            
        if similarity < 0.40:
            pct = int(similarity * 100)
            reply = QMessageBox.warning(
                self,
                "Low Lyrics Similarity",
                f"The entered text is only {pct}% similar to the original track's vocals.\n\n"
                "Are you sure you want to proceed and align these lyrics anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
            
        try:
            self.confirmed_lyrics = self.fit_corrected_lyrics(self.original_lyrics_db["lyrics"], corrected_text)
            self.accept()
        except Exception as e:
            logger.error(f"Error fitting lyrics: {e}", exc_info=True)
            
    def handle_smart_correct(self):
        """Uses Gemini AI to correct lyrics typos while preserving line layout structure."""
        if not self.gemini_api_key:
            QMessageBox.warning(self, "No API Key", "Please configure a Gemini API Key in Settings first.")
            return
            
        self.btn_smart_correct.setEnabled(False)
        self.btn_smart_correct.setText("🧠 Processing...")
        if hasattr(self, 'btn_confirm') and self.btn_confirm:
            self.btn_confirm.setEnabled(False)
            
        # Get raw lines and construct structured array payload
        raw_text = self.text_edit.toPlainText()
        raw_lines = [line.strip() for line in raw_text.split("\n")]
        
        # Safe isolation checks
        if not any(raw_lines):
            QMessageBox.warning(self, "Empty Lyrics", "Cannot correct empty lyrics.")
            self.btn_smart_correct.setEnabled(True)
            self.btn_smart_correct.setText("✨ Smart Correction")
            if hasattr(self, 'btn_confirm') and self.btn_confirm:
                self.btn_confirm.setEnabled(True)
            return

        import json
        prompt_payload = json.dumps(raw_lines)
        
        system_instruction = (
            "You are an expert audio transcription editor and lyrics proofreader. "
            "Your task is to correct typographical errors, spelling mistakes, punctuation slips, "
            "and grammatical slips in the provided lyrics. "
            "Crucially, you MUST maintain a strict 1:1 mapping between the input lines and the output lines. "
            "Do NOT add new lines, do NOT delete existing lines, and do NOT merge lines. "
            "Each element in the output JSON array must correspond exactly to the line at the same index in the input JSON array. "
            "Preserve the semantic content and style of the song. Do not censor any words. "
            "Return the corrected lines as a JSON array of strings, for example: "
            '["Line 1 corrected", "Line 2 corrected", "Line 3 corrected"]'
        )
        
        prompt = (
            f"Please correct the following lyrics lines. You must return a JSON array of strings containing exactly "
            f"{len(raw_lines)} strings, corresponding line-by-line to the input lines.\n\nInput lines:\n{prompt_payload}"
        )
        
        self.correction_worker = GeminiLyricsCorrectionWorker(self.gemini_api_key, prompt, system_instruction)
        
        def on_finished(returned_json):
            # Handshake verification:
            if len(returned_json) == len(raw_lines):
                corrected_text = "\n".join(returned_json)
                self.text_edit.setPlainText(corrected_text)
                QMessageBox.information(self, "Success", "Smart Correction applied successfully!")
            else:
                QMessageBox.warning(
                    self, 
                    "Alignment Mismatch", 
                    f"Correction failed: Structural alignment mismatch (expected {len(raw_lines)} lines, got {len(returned_json)}). Please try re-rolling."
                )
            cleanup()
            
        def on_error(error_msg):
            QMessageBox.critical(self, "Correction Failed", f"AI correction error:\n{error_msg}")
            cleanup()
            
        def cleanup():
            self.btn_smart_correct.setEnabled(True)
            self.btn_smart_correct.setText("✨ Smart Correction")
            if hasattr(self, 'btn_confirm') and self.btn_confirm:
                self.btn_confirm.setEnabled(True)
                
        self.correction_worker.finished.connect(on_finished)
        self.correction_worker.error.connect(on_error)
        self.correction_worker.start()

    def fit_corrected_lyrics(self, original_lyrics, corrected_text):
        import difflib
        import re
        
        # Extract all original words with timing
        original_words = []
        for line in original_lyrics:
            words = line.get("words", [])
            if not words:
                line_words_str = line["text"].split()
                if line_words_str:
                    dur = line["end"] - line["start"]
                    w_dur = dur / len(line_words_str)
                    for i, w_str in enumerate(line_words_str):
                        original_words.append({
                            "word": w_str,
                            "start": line["start"] + i * w_dur,
                            "end": line["start"] + (i + 1) * w_dur
                        })
            else:
                for w in words:
                    original_words.append(w)
                    
        # Get clean normalized lists for comparison
        orig_word_tokens = [w["word"].lower().strip(".,!?\"'()[]-") for w in original_words]
        
        # Parse corrected text into line lists
        corrected_lines_raw = corrected_text.split("\n")
        
        # Flat list of all corrected words to align
        corrected_words_all = []
        word_mapping = []
        
        for line_idx, line in enumerate(corrected_lines_raw):
            words_in_line = line.split()
            for word_in_line_idx, w_text in enumerate(words_in_line):
                corrected_words_all.append(w_text)
                word_mapping.append((line_idx, word_in_line_idx, w_text))
                
        corr_word_tokens = [w.lower().strip(".,!?\"'()[]-") for w in corrected_words_all]
        
        # Align using SequenceMatcher opcodes
        matcher = difflib.SequenceMatcher(None, orig_word_tokens, corr_word_tokens)
        opcodes = matcher.get_opcodes()
        
        # Initialize corrected words with None timestamps
        aligned_words = [{"word": w, "start": None, "end": None} for w in corrected_words_all]
        
        for tag, i1, i2, j1, j2 in opcodes:
            if tag == 'equal':
                for offset in range(i2 - i1):
                    orig_idx = i1 + offset
                    corr_idx = j1 + offset
                    if corr_idx < len(aligned_words) and orig_idx < len(original_words):
                        aligned_words[corr_idx]["start"] = original_words[orig_idx]["start"]
                        aligned_words[corr_idx]["end"] = original_words[orig_idx]["end"]
            elif tag == 'replace':
                if i1 < len(original_words) and i2 <= len(original_words) and j1 < len(aligned_words):
                    t_start = original_words[i1]["start"]
                    t_end = original_words[i2-1]["end"]
                    duration = t_end - t_start
                    num_corrected = j2 - j1
                    if num_corrected > 0:
                        w_dur = duration / num_corrected
                        for offset in range(num_corrected):
                            corr_idx = j1 + offset
                            if corr_idx < len(aligned_words):
                                aligned_words[corr_idx]["start"] = round(t_start + offset * w_dur, 2)
                                aligned_words[corr_idx]["end"] = round(t_start + (offset + 1) * w_dur, 2)
            elif tag == 'insert':
                # Handle insert case explicitly inside the loop
                t_prev = original_words[i1 - 1]["end"] if i1 > 0 else 0.0
                t_next = original_words[i1]["start"] if i1 < len(original_words) else (t_prev + (j2 - j1) * 1.5)
                
                # Ensure positive and reasonable duration
                min_dur_per_word = 0.2
                required_dur = (j2 - j1) * min_dur_per_word
                if t_next < t_prev + required_dur:
                    # Expand the interval slightly or center it
                    mid = (t_prev + t_next) / 2.0
                    t_prev = max(0.0, mid - required_dur / 2.0)
                    t_next = t_prev + required_dur
                    
                duration = t_next - t_prev
                w_dur = duration / (j2 - j1)
                for offset in range(j2 - j1):
                    corr_idx = j1 + offset
                    if corr_idx < len(aligned_words):
                        aligned_words[corr_idx]["start"] = round(t_prev + offset * w_dur, 2)
                        aligned_words[corr_idx]["end"] = round(t_prev + (offset + 1) * w_dur, 2)
                                
        # Safety post-pass interpolation for any leftover None (e.g. if original_lyrics was empty)
        for idx in range(len(aligned_words)):
            if aligned_words[idx]["start"] is None:
                # Collect consecutive missing words
                start_missing = idx
                end_missing = idx
                while end_missing < len(aligned_words) and aligned_words[end_missing]["start"] is None:
                    end_missing += 1
                num_missing = end_missing - start_missing
                
                prev_t = None
                if start_missing > 0:
                    prev_t = aligned_words[start_missing - 1]["end"]
                
                next_t = None
                if end_missing < len(aligned_words):
                    next_t = aligned_words[end_missing]["start"]
                    
                if prev_t is not None and next_t is not None:
                    if next_t < prev_t + num_missing * 0.2:
                        next_t = prev_t + num_missing * 0.2
                    interval = next_t - prev_t
                    w_dur = interval / num_missing
                    for k in range(num_missing):
                        aligned_words[start_missing + k]["start"] = round(prev_t + k * w_dur, 2)
                        aligned_words[start_missing + k]["end"] = round(prev_t + (k + 1) * w_dur, 2)
                elif prev_t is not None:
                    w_dur = 0.5
                    for k in range(num_missing):
                        aligned_words[start_missing + k]["start"] = round(prev_t + k * w_dur, 2)
                        aligned_words[start_missing + k]["end"] = round(prev_t + (k + 1) * w_dur, 2)
                elif next_t is not None:
                    w_dur = 0.5
                    start_t = max(0.0, next_t - num_missing * w_dur)
                    for k in range(num_missing):
                        aligned_words[start_missing + k]["start"] = round(start_t + k * w_dur, 2)
                        aligned_words[start_missing + k]["end"] = round(start_t + (k + 1) * w_dur, 2)
                else:
                    for k in range(num_missing):
                        aligned_words[start_missing + k]["start"] = round((start_missing + k) * 1.0, 2)
                        aligned_words[start_missing + k]["end"] = round((start_missing + k + 1) * 1.0, 2)
                    
        # Construct structured lines
        final_lyrics = []
        current_line_idx = -1
        line_words = []
        
        for idx, (l_idx, w_in_l_idx, w_text) in enumerate(word_mapping):
            if l_idx != current_line_idx:
                if line_words:
                    l_start = line_words[0]["start"]
                    l_end = line_words[-1]["end"]
                    l_text = corrected_lines_raw[current_line_idx].strip()
                    final_lyrics.append({
                        "text": l_text,
                        "start": l_start,
                        "end": l_end,
                        "words": line_words
                    })
                current_line_idx = l_idx
                line_words = []
                
            line_words.append({
                "word": w_text,
                "start": aligned_words[idx]["start"],
                "end": aligned_words[idx]["end"]
            })
            
        if line_words:
            l_start = line_words[0]["start"]
            l_end = line_words[-1]["end"]
            l_text = corrected_lines_raw[current_line_idx].strip()
            final_lyrics.append({
                "text": l_text,
                "start": l_start,
                "end": l_end,
                "words": line_words
            })
            
        return {"lyrics": final_lyrics}


class CustomTitleBar(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setFixedHeight(40)
        self.setStyleSheet("background-color: transparent; border-bottom: 1px solid #1E1E1E;")
        
        layout = QHBoxLayout()
        layout.setContentsMargins(15, 0, 15, 0)
        self.setLayout(layout)
        
        # Logo / Title
        title_lbl = QLabel("MozZzart Player")
        title_lbl.setStyleSheet("color: #F0C419; font-weight: bold; font-size: 13px; border: none;")
        layout.addWidget(title_lbl)
        layout.addStretch()
        
        # Window Controls
        btn_style = "QPushButton { color: #888; background: transparent; border: none; font-size: 14px; padding: 5px 10px; border-radius: 4px; } QPushButton:hover { background: #333; color: white; }"
        
        self.btn_min = QPushButton("—")
        self.btn_min.setStyleSheet(btn_style)
        self.btn_min.clicked.connect(self.parent_window.showMinimized)
        layout.addWidget(self.btn_min)
        
        self.btn_max = QPushButton("🔲")
        self.btn_max.setStyleSheet(btn_style)
        self.btn_max.clicked.connect(self.toggle_maximize)
        layout.addWidget(self.btn_max)
        
        self.btn_close = QPushButton("✕")
        self.btn_close.setStyleSheet("QPushButton { color: #888; background: transparent; border: none; font-size: 14px; padding: 5px 10px; border-radius: 4px; } QPushButton:hover { background: #E81123; color: white; }")
        self.btn_close.clicked.connect(self.parent_window.close)
        layout.addWidget(self.btn_close)
        
        self._drag_pos = None

    def toggle_maximize(self):
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
        else:
            self.parent_window.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.parent_window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()


class MozZzartPlayerApp(QMainWindow):
    """Core GUI logic for MozZzart Player & Karaoke."""
    def __init__(self):
        super().__init__()
        
        # ── Media Engine Guard ──
        if not HAS_VLC:
            QMessageBox.critical(
                None, "Media Engine Missing",
                "MozZzart Player could not locate its core media components.\n\n"
                "Please ensure the local 'bin/vlc' folder contains the required shared binaries "
                "for your operating system, or install desktop VLC Media Player from videolan.org."
            )
            sys.exit(1)
        
        self.setWindowTitle("MozZzart Player")
        self.setWindowIcon(QIcon(get_asset_path("logo.png")))
        self.resize(1150, 780)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.setMinimumSize(1024, 720) # Safe explicit minimum size bounds
        self.setStyleSheet(SPOTIFY_STYLE)
        
        # Load Config
        self.config = config.load_config()
        
        # Initialize Global GIF Tracker
        self.config.setdefault("gif_playlist", ["mozart dance.gif"])
        self.current_gif_index = 0
        self.ensure_music_dir_exists()
        
        # Audio Player Init
        self.player = AudioPlayer()
        self.player.main_app = self
        
        # UI State Variables
        self.scanned_songs = []
        self.active_playlist = "Library"  # Tracks subfolders
        self.lyrics_db = None             # Stores JSON parsed lyrics
        self.active_lyric_line_idx = -1   # Scroll management
        self.is_editing_lyrics = False    # Live lyrics edit state
        self.karaoke_queue = []           # Sequential queue for local PyTorch stem isolation
        self.active_karaoke_worker = None # Single active background worker
        
        # True Karaoke Mode state
        self.karaoke_mode_active = False   # Full Karaoke Mode toggle state
        self.original_track_path = None    # Stores original track path for hot-swap back
        self.mic_worker = None             # MicrophoneWorker thread instance
        
        # Bulk Downloader state trackers
        self.download_queue_worker = None
        self.download_progress_widgets = {}
        
        # Initialize Discovery Session Re-roll Cap (v5.8.0)
        self.reroll_count = 10

        # Setup UI
        self.setup_ui_layout()
        
        # Setup Timers & Connections
        self.poll_timer = QTimer()
        self.poll_timer.setInterval(100)
        self.poll_timer.timeout.connect(self.update_playback_polling)
        self.poll_timer.start()
        
        # Playback events connection
        self.player.state_changed.connect(self.on_player_state_changed)
        self.player.duration_resolved.connect(self.on_duration_resolved)
        self.player.track_finished.connect(self.on_track_finished)
        self.player.seeked.connect(self.on_player_seeked) # Instant seek synchronization guard!
        
        # Load initial songs list
        self.scan_music_library()
        self.update_volume_controls()

        
        # Safe 2-second deferred startup auto-run (Amendment 2)
        api_key = self.config.get("gemini_api_key", "").strip()
        if api_key:
            logger.info("Scheduling deferred Gemini Discovery Feed generation in 2 seconds...")
            QTimer.singleShot(2000, self.run_gemini_discovery)
        
        # Start Flask Web Remote / TV Streaming Server
        self.web_remote_enabled = False
        self.config["web_remote_enabled"] = False
        self.web_remote_worker = None
        if HAS_WEB_REMOTE and self.config.get("web_remote_enabled", False):
            self._start_web_remote()
        
        # OTA Update Check (asynchronous, non-blocking)
        QTimer.singleShot(3000, self.check_for_updates)
        
        # Hardware Audio Sync Watchdog — corrects dual-VLC karaoke drift every second
        self.audio_sync_timer = QTimer(self)
        self.audio_sync_timer.timeout.connect(self.player.enforce_karaoke_sync)
        self.audio_sync_timer.start(1000)
        
        logger.info("Aura Player MainWindow initialized successfully.")

    def ensure_music_dir_exists(self):
        """Ensures a valid music root directory is loaded. Includes cross-OS path sanitization."""
        import re
        saved_dir = self.config.get("music_root_dir", "")
        # Cross-OS Config Sanitizer: detect if the saved path belongs to a different OS
        if saved_dir:
            is_windows_path = bool(re.match(r'^[a-zA-Z]:', saved_dir))
            if sys.platform == "win32" and not is_windows_path and not saved_dir.startswith("\\\\"):
                saved_dir = ""  # Unix path on Windows — force reset
            elif sys.platform != "win32" and is_windows_path:
                saved_dir = ""  # Windows path on Unix — force reset
        
        if not saved_dir or not os.path.isdir(saved_dir):
            local_music = os.path.join(utils.get_app_dir(), "Music")
            os.makedirs(local_music, exist_ok=True)
            self.config["music_root_dir"] = local_music
            config.save_config(self.config)
            logger.info(f"Music directory initialized at fallback: {local_music}")

    # ------------------------------------------------------------------
    # OTA Update System
    # ------------------------------------------------------------------

    def check_for_updates(self):
        """Asynchronously checks GitHub Releases for a newer version."""
        try:
            version_file = os.path.join(utils.get_app_dir(), "version.json")
            if not os.path.isfile(version_file):
                logger.info("OTA: version.json not found, skipping update check.")
                return
            with open(version_file, 'r', encoding='utf-8') as f:
                version_data = json.load(f)
            
            current_version = version_data.get("version", "0.0.0")
            repo_url = version_data.get("repo_url", "")
            
            if not repo_url or "YOUR_GITHUB_USERNAME" in repo_url:
                logger.info("OTA: repo_url not configured, skipping update check.")
                return

            class UpdateCheckerWorker(QThread):
                update_available = pyqtSignal(str, str, str)  # tag, zipball_url, body
                
                def __init__(self, url, current_ver):
                    super().__init__()
                    self.url = url
                    self.current_ver = current_ver
                
                def run(self):
                    try:
                        import os
                        if "MOZZZART_OTA_SIM_TAG" in os.environ and "MOZZZART_OTA_SIM_ZIP" in os.environ:
                            tag = os.environ["MOZZZART_OTA_SIM_TAG"]
                            zipball = os.environ["MOZZZART_OTA_SIM_ZIP"]
                            
                            def parse_ver(v):
                                try: return tuple(int(x) for x in v.split("."))
                                except ValueError: return (0, 0, 0)
                                
                            if parse_ver(tag) > parse_ver(self.current_ver):
                                self.update_available.emit(tag, zipball, "Mock Local Simulation Update")
                            return

                        import urllib.request
                        req = urllib.request.Request(
                            self.url,
                            headers={"User-Agent": "MozZzart-Player-OTA/1.0", "Accept": "application/vnd.github.v3+json"}
                        )
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            data = json.loads(resp.read().decode('utf-8'))
                        
                        tag = data.get("tag_name", "").lstrip("v")
                        zipball = data.get("zipball_url", "")
                        body = data.get("body", "")
                        
                        # Compare version strings numerically
                        def parse_ver(v):
                            try:
                                return tuple(int(x) for x in v.split("."))
                            except ValueError:
                                return (0, 0, 0)
                        
                        if parse_ver(tag) > parse_ver(self.current_ver):
                            self.update_available.emit(tag, zipball, body)
                    except Exception as e:
                        logger.warning(f"OTA update check failed: {e}")

            self._update_worker = UpdateCheckerWorker(repo_url, current_version)
            self._update_worker.update_available.connect(self._show_update_available)
            self._update_worker.start()
            logger.info(f"OTA: Checking for updates (current: v{current_version})...")
            
        except Exception as e:
            logger.warning(f"OTA: Update check failed: {e}")

    def _show_update_available(self, tag, zipball_url, body):
        """Shows an 'Update Available' button in the sidebar when a new version is found."""
        self._ota_zipball_url = zipball_url
        self._ota_tag = tag
        
        btn_update = QPushButton(f"  Update to v{tag}")
        btn_update.setIcon(qta.icon('fa5s.cloud-download-alt', color='#1DB954'))
        btn_update.setIconSize(QSize(16, 16))
        btn_update.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_update.setStyleSheet("""
            QPushButton {
                background-color: #1A3A1A;
                color: #1DB954;
                border: 1px solid #1DB954;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: bold;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #1DB954;
                color: #000000;
            }
        """)
        btn_update.clicked.connect(self._trigger_ota_update)
        
        # Insert at the bottom of the sidebar
        if hasattr(self, 'sidebar') and self.sidebar.layout():
            self.sidebar.layout().addWidget(btn_update)
        
        logger.info(f"OTA: Update v{tag} available! Showing update button.")

    def _trigger_ota_update(self):
        """Downloads the update ZIP and launches updater.py to apply it."""
        import tempfile
        import subprocess
        
        zipball_url = getattr(self, '_ota_zipball_url', '')
        tag = getattr(self, '_ota_tag', 'unknown')
        
        if not zipball_url:
            QMessageBox.warning(self, "Update Error", "No update URL available.")
            return

        reply = QMessageBox.question(
            self, "Update MozZzart Player",
            f"A new version (v{tag}) is available.\n\n"
            f"The app will download the update, close, and restart automatically.\n"
            f"Your settings, music library, and VLC binaries will be preserved.\n\n"
            f"Proceed with the update?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Show progress dialog
        progress = QProgressDialog("Downloading update...", "Cancel", 0, 100, self)
        progress.setWindowTitle("MozZzart OTA Update")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()

        try:
            import urllib.request
            
            temp_dir = tempfile.gettempdir()
            zip_path = os.path.join(temp_dir, f"mozzzart_update_{tag}.zip")
            
            req = urllib.request.Request(
                zipball_url,
                headers={"User-Agent": "MozZzart-Player-OTA/1.0"}
            )
            
            with urllib.request.urlopen(req, timeout=120) as response:
                total_size = int(response.info().get('Content-Length', 0))
                bytes_downloaded = 0
                block_size = 8192
                
                with open(zip_path, 'wb') as f:
                    while True:
                        if progress.wasCanceled():
                            logger.info("OTA: Update download cancelled by user.")
                            return
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        f.write(buffer)
                        bytes_downloaded += len(buffer)
                        if total_size > 0:
                            progress.setValue(int(bytes_downloaded / total_size * 100))
                        QApplication.processEvents()
            
            progress.setValue(100)
            progress.setLabelText("Launching updater...")
            QApplication.processEvents()
            
            # Determine the correct updater command based on environment
            if IS_DEV_MODE:
                updater_script = os.path.join(utils.get_app_dir(), "updater.py")
                updater_cmd = [sys.executable, updater_script]
            else:
                # In production, sys.executable points to MozZzartPlayer.exe. 
                # We need to call the adjacent compiled updater binary.
                base_dir = os.path.dirname(sys.executable)
                if sys.platform == "win32":
                    updater_cmd = [os.path.join(base_dir, "updater.exe")]
                else:
                    updater_cmd = [os.path.join(base_dir, "updater")]
            
            # Append arguments
            updater_cmd.extend([zip_path, str(os.getpid())])
            
            logger.info(f"Launching OTA Updater: {updater_cmd}")
            subprocess.Popen(updater_cmd, cwd=utils.get_app_dir())
            
            # Zombie Subprocess on Update Protection:
            # Because we use os._exit(0), Qt's closeEvent is bypassed.
            # We must explicitly terminate the active background karaoke worker's subprocess first.
            if hasattr(self, 'active_karaoke_worker') and self.active_karaoke_worker:
                logger.info("OTA: Terminating active background karaoke worker before exit.")
                if hasattr(self.active_karaoke_worker, 'terminate_process'):
                    self.active_karaoke_worker.terminate_process()
            
            # Exit the main application forcefully so the updater can immediately replace files
            os._exit(0)
            
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Update Failed", f"Failed to download update:\n{e}")
            logger.error(f"OTA: Update download failed: {e}")

    def setup_ui_layout(self):
        """Builds the comprehensive Spotify-like layout."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        central_widget.setObjectName("MainCentralWidget")
        # The RGBA background creates the sleek glass effect
        central_widget.setStyleSheet("QWidget#MainCentralWidget { background-color: rgba(12, 12, 12, 240); border-radius: 10px; border: 1px solid #333; }")
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)
        central_widget.setLayout(main_layout)
        
        # Inject Custom Title Bar
        self.title_bar = CustomTitleBar(self)
        main_layout.addWidget(self.title_bar)
        
        # Top Panel: Sidebar + Main Content Stack
        top_container = QWidget()
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        top_container.setLayout(top_layout)
        
        # 1. Sidebar Panel
        self.sidebar = QFrame()
        self.sidebar.setObjectName("SidebarFrame")
        self.sidebar.setFixedWidth(240)
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(15, 40, 15, 25)
        sidebar_layout.setSpacing(12)
        self.sidebar.setLayout(sidebar_layout)
        
        # Nav Buttons
        self.btn_lib = QPushButton("📚 Your Library")
        self.btn_lib.clicked.connect(lambda: self.show_page(0))
        sidebar_layout.addWidget(self.btn_lib)
        
        self.btn_queue = QPushButton("📥 Grab/Queue")
        self.btn_queue.clicked.connect(lambda: self.show_page(1))
        sidebar_layout.addWidget(self.btn_queue)
        
        self.btn_karaoke_view = QPushButton("🔥 Karaoke Screen")
        self.btn_karaoke_view.clicked.connect(lambda: self.show_page(2))
        sidebar_layout.addWidget(self.btn_karaoke_view)
        
        self.btn_settings = QPushButton("⚙️ Settings")
        self.btn_settings.clicked.connect(lambda: self.show_page(3))
        sidebar_layout.addWidget(self.btn_settings)
        
        # Section Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #1E1E1E; height: 1px; border: none;")
        sidebar_layout.addWidget(line)
        
        # Playlist Label
        playlist_header = QLabel("PLAYLISTS")
        playlist_header.setStyleSheet("font-size: 11px; font-weight: bold; color: #666666; padding-left: 10px; margin-top: 10px;")
        sidebar_layout.addWidget(playlist_header)
        
        # Playlists List
        self.playlist_list = QListWidget()
        self.playlist_list.itemClicked.connect(self.on_playlist_clicked)
        sidebar_layout.addWidget(self.playlist_list)
        
        # New Playlist Button
        self.btn_new_playlist = QPushButton("+ Create Playlist")
        self.btn_new_playlist.setStyleSheet("color: #FFFFFF; font-weight: bold; padding-left: 10px;")
        self.btn_new_playlist.clicked.connect(self.create_new_playlist)
        sidebar_layout.addWidget(self.btn_new_playlist)
        
        top_layout.addWidget(self.sidebar)
        
        # 2. Main Content Window (Stacked Widget)
        self.content_stack = QStackedWidget()
        
        self.setup_library_page()
        self.setup_queue_page()
        self.setup_karaoke_page()
        self.setup_settings_page()
        
        top_layout.addWidget(self.content_stack)
        main_layout.addWidget(top_container, stretch=1)
        
        # 3. Bottom Player Bar
        self.bottom_bar = QFrame()
        self.bottom_bar.setObjectName("BottomPlayerBar")
        self.bottom_bar.setFixedHeight(90) # FIX: Lock height so it can never be crushed
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(20, 5, 20, 5)
        self.bottom_bar.setLayout(bottom_layout)
        
        # Left Segment: Song Info Card
        self.info_panel = QWidget()
        self.info_panel.setFixedWidth(340)
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 5, 0, 5)
        info_layout.setSpacing(2)
        self.info_panel.setLayout(info_layout)
        
        self.lbl_song_title = QLabel("No Song Playing")
        self.lbl_song_title.setObjectName("SongTitleLabel")
        self.lbl_song_title.setWordWrap(False)
        info_layout.addWidget(self.lbl_song_title)
        
        self.lbl_song_artist = QLabel()
        self.lbl_song_artist.setObjectName("ArtistLabel")
        # Load and scale logo
        logo_pixmap = QPixmap(get_asset_path("logo.png")).scaled(120, 30, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.lbl_song_artist.setPixmap(logo_pixmap)
        info_layout.addWidget(self.lbl_song_artist)
        
        bottom_layout.addWidget(self.info_panel)
        
        # Center Segment: Music Playback Controls
        center_controls = QWidget()
        center_layout = QVBoxLayout()
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)
        center_controls.setLayout(center_layout)
        
        # Media Buttons with universal FontAwesome vector icons (qtawesome)
        icon_color = '#B3B3B3'
        icon_size = QSize(18, 18)
        media_buttons = QWidget()
        buttons_layout = QHBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(20)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        media_buttons.setLayout(buttons_layout)
        
        self.btn_shuffle = SlashedButton()
        self.btn_shuffle.setIcon(qta.icon('fa5s.random', color=icon_color))
        self.btn_shuffle.setIconSize(icon_size)
        self.btn_shuffle.setObjectName("NavButton")
        self.btn_shuffle.setToolTip("Shuffle Mode")
        self.btn_shuffle.setSlashed(not self.config["shuffle"])
        self.btn_shuffle.setProperty("active", "true" if self.config["shuffle"] else "false")
        self.btn_shuffle.clicked.connect(self.toggle_shuffle)
        buttons_layout.addWidget(self.btn_shuffle)
        
        self.btn_prev = QPushButton()
        self.btn_prev.setIcon(qta.icon('fa5s.step-backward', color=icon_color))
        self.btn_prev.setIconSize(icon_size)
        self.btn_prev.setObjectName("NavButton")
        self.btn_prev.clicked.connect(self.play_previous_track)
        buttons_layout.addWidget(self.btn_prev)
        
        self.btn_play_pause = QPushButton()
        self.btn_play_pause.setIcon(qta.icon('fa5s.play', color='#F0C419'))
        self.btn_play_pause.setIconSize(QSize(20, 20))
        self.btn_play_pause.setObjectName("PlayButton")
        self.btn_play_pause.clicked.connect(self.toggle_playback)
        buttons_layout.addWidget(self.btn_play_pause)
        
        self.btn_next = QPushButton()
        self.btn_next.setIcon(qta.icon('fa5s.step-forward', color=icon_color))
        self.btn_next.setIconSize(icon_size)
        self.btn_next.setObjectName("NavButton")
        self.btn_next.clicked.connect(self.play_next_track)
        buttons_layout.addWidget(self.btn_next)
        
        self.btn_repeat = SlashedButton()
        self.btn_repeat.setIcon(qta.icon('fa5s.redo-alt', color=icon_color))
        self.btn_repeat.setIconSize(icon_size)
        self.btn_repeat.setObjectName("NavButton")
        self.btn_repeat.setToolTip("Repeat Mode")
        self.btn_repeat.setSlashed(not self.config["repeat"])
        self.btn_repeat.setProperty("active", "true" if self.config["repeat"] else "false")
        self.btn_repeat.clicked.connect(self.toggle_repeat)
        buttons_layout.addWidget(self.btn_repeat)
        
        center_layout.addWidget(media_buttons)
        
        # Playback Timeline Slider
        slider_panel = QWidget()
        slider_layout = QHBoxLayout()
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.setSpacing(12)
        slider_panel.setLayout(slider_layout)
        
        self.lbl_time_curr = QLabel("0:00")
        self.lbl_time_curr.setObjectName("TimeLabel")
        slider_layout.addWidget(self.lbl_time_curr)
        
        self.timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self.timeline_slider.setRange(0, 100)
        self.timeline_slider.setValue(0)
        self.timeline_slider.sliderMoved.connect(self.on_timeline_seek)
        slider_layout.addWidget(self.timeline_slider)
        
        self.lbl_time_max = QLabel("0:00")
        self.lbl_time_max.setObjectName("TimeLabel")
        slider_layout.addWidget(self.lbl_time_max)
        
        center_layout.addWidget(slider_panel)
        bottom_layout.addWidget(center_controls, stretch=1)
        
        # Right Segment: Volume & Screen Extras
        right_panel = QWidget()
        right_panel.setFixedWidth(340)
        right_layout = QHBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        right_layout.addStretch()  # Push volume controls and buttons to the right to eliminate gaps
        right_panel.setLayout(right_layout)
        
        # Toggle Karaoke Panel
        self.btn_mic_toggle = QPushButton("🎤")
        self.btn_mic_toggle.setObjectName("NavButton")
        self.btn_mic_toggle.setToolTip("Open Karaoke Lyrics Panel")
        self.btn_mic_toggle.clicked.connect(lambda: self.show_page(2))
        right_layout.addWidget(self.btn_mic_toggle)
        
        # Sound Volume Slider
        self.lbl_vol_icon = QLabel("🔊")
        self.lbl_vol_icon.setStyleSheet("color: #B3B3B3; font-size: 14px;")
        right_layout.addWidget(self.lbl_vol_icon)
        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.config["volume"])
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        right_layout.addWidget(self.volume_slider)
        
        bottom_layout.addWidget(right_panel)
        main_layout.addWidget(self.bottom_bar)
        # Add invisible resize grip to bottom right
        grip = QSizeGrip(self)
        main_layout.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        
        # Create mini player (hidden initially)
        self.mini_player = MiniPlayerWindow(self)
        self.mini_player.hide()

    def show_page(self, index):
        """Switches main stack display and highlights nav buttons."""
        self.content_stack.setCurrentIndex(index)
        
        # Reset sidebar nav active colors
        self.btn_lib.setStyleSheet("color: #B3B3B3; font-weight: normal;")
        self.btn_queue.setStyleSheet("color: #B3B3B3; font-weight: normal;")
        self.btn_karaoke_view.setStyleSheet("color: #B3B3B3; font-weight: normal;")
        self.btn_settings.setStyleSheet("color: #B3B3B3; font-weight: normal;")
        
        if index != 2:
            if hasattr(self, 'mozart_left'): self.mozart_left.stop()
            if hasattr(self, 'mozart_right'): self.mozart_right.stop()
            if getattr(self, "is_fullscreen", False):
                self.toggle_karaoke_fullscreen()

        if index == 0:
            self.btn_lib.setStyleSheet("color: #F0C419; font-weight: bold; background-color: #1A1A1A;")
            if hasattr(self, 'library_tabs'):
                self.library_tabs.setCurrentIndex(2)
        elif index == 1:
            self.btn_queue.setStyleSheet("color: #F0C419; font-weight: bold; background-color: #1A1A1A;")
        elif index == 2:
            self.btn_karaoke_view.setStyleSheet("color: #F0C419; font-weight: bold; background-color: #1A1A1A;")
            # Also start Mozarts if we are in fullscreen
            if getattr(self, "is_fullscreen", False):
                if hasattr(self, 'mozart_left'): self.mozart_left.start()
                if hasattr(self, 'mozart_right'): self.mozart_right.start()
        elif index == 3:
            self.btn_settings.setStyleSheet("color: #F0C419; font-weight: bold; background-color: #1A1A1A;")

    # ==========================
    # PAGE 1: LIBRARY PAGE SETUP & ACTIONS
    # ==========================
    def setup_library_page(self):
        page = QWidget()
        layout = QVBoxLayout()
        # Increased padding to eliminate cramped feeling
        layout.setContentsMargins(30, 30, 30, 20)
        layout.setSpacing(15)
        page.setLayout(layout)
        
        # Create QTabWidget for premium Library tabs (Step 3)
        self.library_tabs = QTabWidget()
        self.library_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #1E1E1E;
                background-color: #0E0E0E;
                border-radius: 8px;
            }
            QTabBar::tab {
                background-color: #121212;
                color: #B3B3B3;
                padding: 10px 20px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: bold;
                font-size: 13px;
                margin-right: 4px;
            }
            QTabBar::tab:hover {
                background-color: #1A1A1A;
                color: white;
            }
            QTabBar::tab:selected {
                background-color: #0E0E0E;
                color: #F0C419;
                border-bottom: 2px solid #F0C419;
            }
        """)
        self.library_tabs.currentChanged.connect(self.on_library_tab_changed)
        
        # ----------------------------------------------------
        # Tab 1: Discovery Feed
        # ----------------------------------------------------
        tab_discovery = QWidget()
        disc_layout = QVBoxLayout()
        disc_layout.setContentsMargins(20, 20, 20, 20)
        disc_layout.setSpacing(15)
        tab_discovery.setLayout(disc_layout)
        
        # Discovery Controls Row
        disc_controls = QHBoxLayout()
        
        # Genre input
        genre_lbl = QLabel("Genre Filter:")
        genre_lbl.setStyleSheet("color: #B3B3B3; font-weight: bold; font-size: 12px;")
        disc_controls.addWidget(genre_lbl)
        
        self.txt_discovery_genre = QLineEdit()
        self.txt_discovery_genre.setPlaceholderText("e.g. 90s grunge, synthwave, jazz")
        self.txt_discovery_genre.setStyleSheet("""
            QLineEdit {
                background-color: #1C1C1C;
                border: 1px solid #2C2C2C;
                border-radius: 6px;
                padding: 8px 12px;
                color: white;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #F0C419;
            }
        """)
        disc_controls.addWidget(self.txt_discovery_genre, stretch=1)
        
        # Re-roll Button (initialized session counter 10)
        self.btn_reroll_feed = QPushButton(f"Re-roll Feed ({self.reroll_count} Left)")
        self.btn_reroll_feed.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reroll_feed.setStyleSheet("""
            QPushButton {
                background-color: #1A1A1A;
                color: #F0C419;
                border: 1px solid #F0C419;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #F0C419;
                color: black;
            }
            QPushButton:disabled {
                border-color: #444;
                color: #666;
                background-color: #121212;
            }
        """)
        self.btn_reroll_feed.clicked.connect(self.reroll_discovery_feed)
        disc_controls.addWidget(self.btn_reroll_feed)
        
        disc_layout.addLayout(disc_controls)
        
        # Table of Recommendations
        self.table_discovery = QTableWidget()
        self.table_discovery.setColumnCount(3)
        self.table_discovery.setHorizontalHeaderLabels(["Select", "Title", "Artist"])
        self.table_discovery.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table_discovery.setColumnWidth(0, 80)
        self.table_discovery.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_discovery.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_discovery.verticalHeader().setVisible(False)
        self.table_discovery.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_discovery.setStyleSheet("""
            QTableWidget {
                background-color: #121212;
                gridline-color: #1E1E1E;
                color: white;
                border: 1px solid #1E1E1E;
                border-radius: 6px;
            }
            QTableWidget::item {
                padding: 10px;
            }
            QHeaderView::section {
                background-color: #1A1A1A;
                color: #B3B3B3;
                padding: 8px;
                border: none;
                font-weight: bold;
            }
        """)
        disc_layout.addWidget(self.table_discovery)
        
        # Download Selected Button Row
        dl_row = QHBoxLayout()
        self.btn_download_selected = QPushButton("📥 Download Selected Tracks")
        self.btn_download_selected.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_download_selected.setStyleSheet("""
            QPushButton {
                background-color: #2D7D46;
                color: white;
                border-radius: 20px;
                padding: 10px 24px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #399B55;
            }
        """)
        self.btn_download_selected.clicked.connect(self.download_selected_tracks)
        dl_row.addWidget(self.btn_download_selected)
        dl_row.addStretch()
        disc_layout.addLayout(dl_row)
        
        self.library_tabs.addTab(tab_discovery, "🧠 Discovery Feed")
        
        # ----------------------------------------------------
        # Tab 2: Most Listened
        # ----------------------------------------------------
        tab_most_listened = QWidget()
        ml_layout = QVBoxLayout()
        ml_layout.setContentsMargins(20, 20, 20, 20)
        ml_layout.setSpacing(15)
        tab_most_listened.setLayout(ml_layout)
        
        self.table_most_listened = QTableWidget()
        self.table_most_listened.setColumnCount(4)
        self.table_most_listened.setHorizontalHeaderLabels(["Track Name", "Artist", "Play Count", "Last Played"])
        self.table_most_listened.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_most_listened.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_most_listened.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_most_listened.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table_most_listened.verticalHeader().setVisible(False)
        self.table_most_listened.setStyleSheet("""
            QTableWidget {
                background-color: #121212;
                gridline-color: #1E1E1E;
                color: white;
                border: 1px solid #1E1E1E;
                border-radius: 6px;
            }
            QTableWidget::item {
                padding: 10px;
            }
            QHeaderView::section {
                background-color: #1A1A1A;
                color: #B3B3B3;
                padding: 8px;
                border: none;
                font-weight: bold;
            }
        """)
        ml_layout.addWidget(self.table_most_listened)
        
        self.library_tabs.addTab(tab_most_listened, "📈 Most Listened")
        
        # ----------------------------------------------------
        # Tab 3: All Tracks
        # ----------------------------------------------------
        tab_all_tracks = QWidget()
        all_layout = QVBoxLayout()
        all_layout.setContentsMargins(20, 20, 20, 20)
        all_layout.setSpacing(15)
        tab_all_tracks.setLayout(all_layout)
        
        header = QHBoxLayout()
        
        self.lbl_lib_title = QLabel("Scanned Music Library")
        self.lbl_lib_title.setStyleSheet("font-size: 24px; font-weight: bold; color: white;")
        header.addWidget(self.lbl_lib_title)
        
        header.addStretch()
        
        self.btn_add_song = QPushButton("Add Song")
        self.btn_add_song.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_song.setStyleSheet("""
            QPushButton {
                background-color: rgba(30, 30, 30, 0.85);
                color: #F0C419;
                border-radius: 18px;
                padding: 8px 18px;
                font-weight: bold;
                border: 1px solid rgba(240, 196, 25, 0.5);
            }
            QPushButton:hover {
                background-color: rgba(240, 196, 25, 0.15);
                border: 1px solid rgba(240, 196, 25, 0.9);
            }
        """)
        self.btn_add_song.clicked.connect(self.add_song_from_dialog)
        header.addWidget(self.btn_add_song)
        
        self.btn_bulk_karaoke = QPushButton("Bulk Process Karaoke Sync")
        self.btn_bulk_karaoke.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bulk_karaoke.setStyleSheet("""
            QPushButton {
                background-color: rgba(45, 125, 70, 0.85);
                color: white;
                border-radius: 18px;
                padding: 8px 18px;
                font-weight: bold;
                border: 1px solid rgba(57, 155, 85, 0.9);
            }
            QPushButton:hover {
                background-color: rgba(57, 155, 85, 1.0);
            }
        """)
        self.btn_bulk_karaoke.clicked.connect(self.run_bulk_karaoke_processing)
        header.addWidget(self.btn_bulk_karaoke)
        
        self.btn_bulk_toggle = QPushButton("Missing")
        self.btn_bulk_toggle.setCheckable(True)
        self.btn_bulk_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bulk_toggle.setStyleSheet("""
            QPushButton {
                background-color: #2b2b2b;
                color: #b3b3b3;
                border-radius: 18px;
                padding: 8px 18px;
                font-weight: bold;
                border: 1px solid #444;
            }
            QPushButton:checked {
                background-color: #F0C419;
                color: #000000;
                border: 1px solid #D4A017;
            }
        """)
        self.btn_bulk_toggle.toggled.connect(self.on_bulk_toggle_changed)
        header.addWidget(self.btn_bulk_toggle)
        
        # Sort ComboBox
        self.sort_label = QLabel("Sort By:")
        self.sort_label.setStyleSheet("color: #B3B3B3; font-weight: bold; font-size: 12px; margin-left: 10px;")
        header.addWidget(self.sort_label)
        
        self.combo_sort = QComboBox()
        self.combo_sort.addItems(["Alphabetical (A-Z)", "Favorites First", "Newly Added"])
        self.combo_sort.setStyleSheet("""
            QComboBox {
                background-color: #1A1A1A;
                color: white;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 6px 12px;
                min-width: 140px;
                font-weight: bold;
                font-size: 12px;
            }
            QComboBox:hover {
                border: 1px solid #F0C419;
            }
            QComboBox::drop-down {
                border: none;
            }
        """)
        self.combo_sort.currentIndexChanged.connect(self.on_sort_changed)
        header.addWidget(self.combo_sort)
        
        self.search_filter = QLineEdit()
        self.search_filter.setPlaceholderText("🔍 Search tracks by name...")
        self.search_filter.setFixedWidth(220)
        self.search_filter.textChanged.connect(self.filter_library_table)
        header.addWidget(self.search_filter)
        
        all_layout.addLayout(header)
        
        drop_hint = QLabel("💿 Drag & drop .mp3 / .wav files directly onto the table to import them into the active playlist")
        drop_hint.setStyleSheet("color: #555555; font-size: 11px; padding: 4px 0px;")
        drop_hint.setWordWrap(True)
        all_layout.addWidget(drop_hint)
        
        self.table_songs = DropTableWidget()
        self.table_songs.setColumnCount(7)
        self.table_songs.setHorizontalHeaderLabels(["⭐", "Track Name", "Date Added", "Language", "Edit Lyrics", "Lyrics Synced", "Actions"])
        self.table_songs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table_songs.setColumnWidth(0, 40)
        self.table_songs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_songs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table_songs.setColumnWidth(2, 120)
        self.table_songs.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table_songs.setColumnWidth(3, 120)
        self.table_songs.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_songs.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table_songs.setColumnWidth(5, 150)
        self.table_songs.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table_songs.setColumnWidth(6, 200)
        self.table_songs.verticalHeader().setVisible(False)
        self.table_songs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_songs.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_songs.cellDoubleClicked.connect(self.on_table_row_double_click)
        self.table_songs.cellClicked.connect(self.on_library_cell_clicked)
        self.table_songs.files_dropped.connect(self.handle_dropped_files)
        all_layout.addWidget(self.table_songs)
        
        bulk_layout = QHBoxLayout()
        bulk_layout.setContentsMargins(0, 10, 0, 0)
        
        self.lbl_root_status = QLabel("Music Folder: Loaded")
        self.lbl_root_status.setStyleSheet("color: #888888; font-size: 12px;")
        bulk_layout.addWidget(self.lbl_root_status)
        bulk_layout.addStretch()
        
        all_layout.addLayout(bulk_layout)
        
        self.library_tabs.addTab(tab_all_tracks, "🎵 All Tracks")
        self.library_tabs.setCurrentIndex(2)  # Default to All Tracks tab
        layout.addWidget(self.library_tabs)
        
        self.content_stack.addWidget(page)

    def scan_music_library(self):
        """Scans folder for audio and maps them to the table view."""
        root_dir = self.config["music_root_dir"]
        logger.info(f"Scanning music library in: {root_dir}")
        
        target_dir = root_dir
        if self.active_playlist != "Library":
            target_dir = os.path.join(root_dir, self.active_playlist)
            
        self.scanned_songs = []
        self.scan_playlists_list()
        
        if not os.path.isdir(target_dir):
            os.makedirs(target_dir, exist_ok=True)
        
        # === LIBRARY FIREWALL ===
        # The instrumentals/ subfolder contains raw Demucs WAV stems and must
        # NEVER appear in the library UI. Hard-skip it during scanning.
        if "instrumentals" in target_dir.replace("\\", "/").lower():
            logger.info("scan_music_library: skipping instrumentals/ firewall directory.")
            self.populate_library_table(self.scanned_songs)
            return
            
        for file in os.listdir(target_dir):
            # Skip any file that lives inside an instrumentals sub-path
            if "instrumentals" in file.lower():
                continue
            if file.lower().endswith((".mp3", ".wav")):
                full_path = os.path.join(target_dir, file)
                
                # Check for matching JSON lyric file
                json_path = os.path.splitext(full_path)[0] + ".json"
                has_karaoke = os.path.isfile(json_path)
                
                self.scanned_songs.append({
                    "name": os.path.splitext(file)[0],
                    "filename": file,
                    "path": full_path,
                    "type": os.path.splitext(file)[1][1:].upper(),
                    "has_karaoke": has_karaoke
                })
                
        self.lbl_lib_title.setText(f"{self.active_playlist} ({len(self.scanned_songs)} tracks)")
        self.lbl_root_status.setText(f"Root: {root_dir}")
        self.populate_library_table(self.scanned_songs)
        # Keep the web Library tab in sync whenever the playlist changes
        self.broadcast_state_to_web()

    def _get_song_sync_status(self, song_path):
        """Returns 'syncing', 'queued', or 'none' for a given song path."""
        if self.active_karaoke_worker and self.active_karaoke_worker.song_path == song_path:
            return "syncing"
        if any(item[0]["path"] == song_path for item in self.karaoke_queue):
            return "queued"
        return "none"

    def populate_library_table(self, song_list):
        """Populates the table with details and buttons."""
        import analytics
        from PyQt6.QtGui import QColor, QFont
        
        # Work on a copy of the list to prevent unexpected side effects on the master collection
        song_list = list(song_list)
        
        # Apply sorting logic
        if hasattr(self, 'combo_sort'):
            sort_opt = self.combo_sort.currentText()
            if sort_opt == "Favorites First":
                def sort_key(s):
                    is_fav = analytics.is_track_favorite(s["path"])
                    return (0 if is_fav else 1, s["name"].lower())
                self.scanned_songs.sort(key=sort_key)
                song_list.sort(key=sort_key)
            elif sort_opt == "Newly Added":
                def sort_key_new(s):
                    try:
                        import os
                        return -os.path.getctime(s["path"])
                    except Exception:
                        return 0
                self.scanned_songs.sort(key=sort_key_new)
                song_list.sort(key=sort_key_new)
            else:
                self.scanned_songs.sort(key=lambda s: s["name"].lower())
                song_list.sort(key=lambda s: s["name"].lower())
        else:
            self.scanned_songs.sort(key=lambda s: s["name"].lower())
            song_list.sort(key=lambda s: s["name"].lower())

        self.table_songs.setRowCount(len(song_list))
        
        for idx, song in enumerate(song_list):
            self.table_songs.setRowHeight(idx, 50)
            
            # 0. Favorites Column (Index 0)
            is_fav = analytics.is_track_favorite(song["path"])
            fav_char = "★" if is_fav else "☆"
            fav_item = QTableWidgetItem(fav_char)
            fav_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            fav_item.setFlags(fav_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            
            # Use custom QLabel as cell widget so the QSS stylesheet selection/hover rules
            # do not override the yellow (favorited) or white (unfavorited) color of the star!
            fav_label = QLabel(fav_char)
            fav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fav_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            
            font = fav_label.font()
            font.setPointSize(16)
            font.setBold(True)
            fav_label.setFont(font)
            
            if is_fav:
                fav_label.setStyleSheet("color: #F0C419; background-color: transparent;")
            else:
                fav_label.setStyleSheet("color: #FFFFFF; background-color: transparent;")
                
            # Store path and name in item user roles
            fav_item.setData(Qt.ItemDataRole.UserRole, song["path"])
            fav_item.setData(Qt.ItemDataRole.UserRole + 1, song["name"])
            
            self.table_songs.setItem(idx, 0, fav_item)
            self.table_songs.setCellWidget(idx, 0, fav_label)
            
            # 1. Track Name Column (Index 1)
            title_item = QTableWidgetItem("")
            title_item.setFlags(title_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            title_item.setForeground(Qt.GlobalColor.transparent)
            self.table_songs.setItem(idx, 1, title_item)
            
            # Wrap in custom QLabel cell widget to override QSS styles during active pulse highlighting!
            title_label = QLabel(song["name"])
            title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            title_label.setStyleSheet("background-color: transparent;") # Inherit parents style by default
            font = title_item.font()
            title_label.setFont(font)
            self.table_songs.setCellWidget(idx, 1, title_label)
            
            # 2. Date Added Column (Index 2)
            import datetime
            try:
                ctime = os.path.getctime(song["path"])
                added_time = datetime.datetime.fromtimestamp(ctime)
            except Exception:
                added_time = datetime.datetime.now()
            
            date_str = added_time.strftime("%b %d, %Y")  # e.g., "Jan 01, 2026"
            date_item = QTableWidgetItem(date_str)
            date_item.setFlags(date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            date_item.setForeground(QColor("#888888"))
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_songs.setItem(idx, 2, date_item)
            
            # 3. Language Column (Index 3)
            saved_track_lang = analytics.get_track_language(song["path"])
            combo_lang = NoScrollComboBox()
            combo_lang.addItems(["Auto-Detect"] + WHISPER_LANGUAGES)
            
            # Match the active language selection
            if saved_track_lang:
                # Find matching index ignoring case
                match_idx = 0
                for i in range(1, combo_lang.count()):
                    if combo_lang.itemText(i).lower() == saved_track_lang:
                        match_idx = i
                        break
                combo_lang.setCurrentIndex(match_idx)
            else:
                combo_lang.setCurrentIndex(0)
                
            # Premium Dark Style Sheet
            combo_lang.setStyleSheet("""
                QComboBox {
                    background-color: transparent;
                    color: #B3B3B3;
                    border: none;
                    font-weight: bold;
                    font-size: 11px;
                    padding: 4px;
                }
                QComboBox:hover {
                    color: #F0C419;
                }
                QComboBox::drop-down {
                    border: none;
                }
                QComboBox QAbstractItemView {
                    background-color: #181818;
                    color: #B3B3B3;
                    selection-background-color: #282828;
                    selection-color: #F0C419;
                    border: 1px solid #282828;
                }
            """)
            
            # Save selection on change
            def make_lang_saver(path):
                return lambda text: analytics.set_track_language(path, text)
            combo_lang.currentTextChanged.connect(make_lang_saver(song["path"]))
            
            self.table_songs.setCellWidget(idx, 3, combo_lang)
            
            # 4. Edit Lyrics Button (Index 4)
            btn_correct = QPushButton("Edit")
            btn_correct.setCursor(Qt.CursorShape.PointingHandCursor)
            
            if song["has_karaoke"]:
                btn_correct.setEnabled(True)
                btn_correct.setStyleSheet("""
                    QPushButton {
                        color: #2D7D46;
                        background-color: transparent;
                        border: none;
                        font-weight: bold;
                        text-align: left;
                        padding: 0px;
                    }
                    QPushButton:hover {
                        color: #399B55;
                        text-decoration: underline;
                    }
                """)
                btn_correct.clicked.connect(lambda checked, s=song: self.open_lyrics_correction_dialog(s))
            else:
                btn_correct.setEnabled(False)
                btn_correct.setStyleSheet("""
                    QPushButton {
                        color: #444444;
                        background-color: transparent;
                        border: none;
                        font-weight: bold;
                        text-align: left;
                        padding: 0px;
                    }
                """)
                
            self.table_songs.setCellWidget(idx, 4, btn_correct)
            
            # 5. Resolve live sync state for this track (Index 5)
            sync_status = self._get_song_sync_status(song["path"])
            
            btn_badge = QPushButton()
            btn_badge.setCursor(Qt.CursorShape.PointingHandCursor)
            
            btn_instr = QPushButton("🎸")
            
            if sync_status == "syncing":
                btn_badge.setText("Syncing... 0%")
                btn_badge.setStyleSheet("""
                    QPushButton {
                        color: #F0C419;
                        background-color: transparent;
                        border: none;
                        font-weight: bold;
                        text-align: left;
                        padding: 0px;
                    }
                """)
                btn_badge.setEnabled(False)
                btn_badge.setCursor(Qt.CursorShape.ForbiddenCursor)
            elif sync_status == "queued":
                btn_badge.setText("⏳ Queue")
                btn_badge.setStyleSheet("""
                    QPushButton {
                        color: #888888;
                        background-color: transparent;
                        border: none;
                        font-weight: bold;
                        text-align: left;
                        padding: 0px;
                    }
                """)
                btn_badge.setEnabled(False)
                btn_badge.setCursor(Qt.CursorShape.ForbiddenCursor)
            elif song["has_karaoke"]:
                btn_badge.setText("Karaoke Sync")
                btn_badge.setStyleSheet("""
                    QPushButton {
                        color: #F0C419;
                        background-color: transparent;
                        border: none;
                        font-weight: bold;
                        text-align: left;
                        padding: 0px;
                    }
                    QPushButton:hover {
                        color: #FFFFFF;
                        text-decoration: underline;
                    }
                """)
            else:
                btn_badge.setText("❌ No Sync")
                btn_badge.setStyleSheet("""
                    QPushButton {
                        color: #FF5555;
                        background-color: transparent;
                        border: none;
                        font-weight: bold;
                        text-align: left;
                        padding: 0px;
                    }
                    QPushButton:hover {
                        color: #FFFFFF;
                        text-decoration: underline;
                    }
                """)
            
            if sync_status == "none":
                def make_trigger(s, btn, btn_i):
                    def trigger():
                        btn.setText("Syncing... 0%" if not self.karaoke_queue else "⏳ Queue")
                        btn.setStyleSheet("""
                            QPushButton {
                                color: #F0C419;
                                background-color: transparent;
                                border: none;
                                font-weight: bold;
                                text-align: left;
                                padding: 0px;
                            }
                        """)
                        btn.setEnabled(False)
                        btn.setCursor(Qt.CursorShape.ForbiddenCursor)
                        
                        # Also disable instrument button to prevent double-clicks
                        if not self._check_song_has_instrumental(s):
                            btn_i.setEnabled(False)
                            btn_i.setStyleSheet("padding: 4px 8px; font-size: 10px; max-width: 25px; border-radius: 12px; background-color: #222222; color: #888888;")
                            btn_i.setToolTip("Extracting instrumental...")
                            
                        self.trigger_track_karaoke_generation(s, force=True)
                    return trigger
                btn_badge.clicked.connect(make_trigger(song, btn_badge, btn_instr))
            
            self.table_songs.setCellWidget(idx, 5, btn_badge)
            
            # 6. Actions Panel (Index 6)
            actions_layout = QHBoxLayout()
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(5)
            
            btn_play = QPushButton("▶")
            btn_play.setStyleSheet("padding: 4px 8px; font-size: 10px; max-width: 25px; border-radius: 12px; background-color: #222222; color: white;")
            btn_play.clicked.connect(lambda checked, i=idx: self.play_selected_table_row(i))
            actions_layout.addWidget(btn_play)
            
            has_instrumental = self._check_song_has_instrumental(song)
            if has_instrumental:
                btn_instr.setStyleSheet("padding: 4px 8px; font-size: 10px; max-width: 25px; border-radius: 12px; background-color: #222222; color: #2D7D46;")
                btn_instr.setToolTip("Instrumental track available")
            else:
                if sync_status == "syncing" or sync_status == "queued":
                    btn_instr.setStyleSheet("padding: 4px 8px; font-size: 10px; max-width: 25px; border-radius: 12px; background-color: #222222; color: #888888;")
                    btn_instr.setToolTip("Extracting instrumental...")
                    btn_instr.setEnabled(False)
                else:
                    btn_instr.setStyleSheet("padding: 4px 8px; font-size: 10px; max-width: 25px; border-radius: 12px; background-color: #222222; color: #555555;")
                    btn_instr.setToolTip("Extract instrumental track")
                    
                    def make_instr_trigger(s, btn_i, btn_b):
                        def trigger():
                            # Disable both the instrument button and badge immediately
                            btn_i.setEnabled(False)
                            btn_i.setStyleSheet("padding: 4px 8px; font-size: 10px; max-width: 25px; border-radius: 12px; background-color: #222222; color: #888888;")
                            btn_i.setToolTip("Extracting instrumental...")
                            
                            btn_b.setText("Syncing... 0%" if not self.karaoke_queue else "⏳ Queue")
                            btn_b.setStyleSheet("""
                                QPushButton {
                                    color: #F0C419;
                                    background-color: transparent;
                                    border: none;
                                    font-weight: bold;
                                    text-align: left;
                                    padding: 0px;
                                }
                            """)
                            btn_b.setEnabled(False)
                            btn_b.setCursor(Qt.CursorShape.ForbiddenCursor)
                            
                            self.trigger_instrumental_extraction(s)
                        return trigger
                    
                    btn_instr.clicked.connect(make_instr_trigger(song, btn_instr, btn_badge))
            actions_layout.addWidget(btn_instr)
            
            container = QWidget()
            container.setLayout(actions_layout)
            self.table_songs.setCellWidget(idx, 6, container)

    def filter_library_table(self, query):
        """Dynamically filters the library list in real time."""
        query = query.lower()
        filtered = [s for s in self.scanned_songs if query in s["name"].lower()]
        self.populate_library_table(filtered)

    def on_library_cell_clicked(self, row, column):
        """Called when a cell in the main library table is clicked."""
        if column == 0:
            fav_item = self.table_songs.item(row, 0)
            if fav_item:
                track_path = fav_item.data(Qt.ItemDataRole.UserRole)
                song_name = fav_item.data(Qt.ItemDataRole.UserRole + 1)
                if track_path:
                    import analytics
                    from PyQt6.QtGui import QColor
                    artist, title = analytics.parse_track_meta(track_path)
                    is_now_fav = analytics.toggle_favorite(track_path, title, artist)
                    
                    # Update visually in place (both underlying item and QLabel cell widget)
                    if is_now_fav:
                        fav_item.setText("★")
                        fav_item.setForeground(QColor("#F0C419"))
                    else:
                        fav_item.setText("☆")
                        fav_item.setForeground(QColor("#FFFFFF"))
                        
                    fav_label = self.table_songs.cellWidget(row, 0)
                    if not isinstance(fav_label, QLabel):
                        fav_label = QLabel()
                        fav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        fav_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                        font = fav_label.font()
                        font.setPointSize(16)
                        font.setBold(True)
                        fav_label.setFont(font)
                        self.table_songs.setCellWidget(row, 0, fav_label)
                        
                    if is_now_fav:
                        fav_label.setText("★")
                        fav_label.setStyleSheet("color: #F0C419; background-color: transparent;")
                    else:
                        fav_label.setText("☆")
                        fav_label.setStyleSheet("color: #FFFFFF; background-color: transparent;")
                        
                    # If sorted by 'Favorites First', changing active favorites status should trigger a visual sorting update!
                    # But wait: only do this if it was unfavorited so it doesn't interrupt active clicking, or let's just let it stay until manual refresh to prevent popping rows away while clicking! That's the most polished UX.
                    # Yes, keeping it in place is very clean, and next scan/sort refresh will sort correctly.

    def on_sort_changed(self):
        """Re-populates the library table based on the selected sort criteria."""
        query = self.search_filter.text().strip()
        if query:
            self.filter_library_table(query)
        else:
            self.populate_library_table(self.scanned_songs)

    def delete_selected_track(self):
        """Sends the selected track and all its associated stem/JSON files to the Recycle Bin and purges database records."""
        row = self.table_songs.currentRow()
        if row < 0 or row >= self.table_songs.rowCount():
            return
            
        fav_item = self.table_songs.item(row, 0)
        if not fav_item:
            return
            
        track_path = fav_item.data(Qt.ItemDataRole.UserRole)
        song_name = fav_item.data(Qt.ItemDataRole.UserRole + 1)
        
        if not track_path or not os.path.exists(track_path):
            return
            
        # Prompt user for confirmation
        reply = QMessageBox.question(
            self, "Delete Track",
            f"Are you sure you want to send '{song_name}' to the Recycle Bin?\n\nThis will permanently delete the song file and clear all its playlist and play count analytics from the database.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
            
        logger.info(f"User confirmed deletion of: {track_path}")
        
        # Stop playback if the track is currently playing
        if self.player.current_track == track_path or (hasattr(self, 'original_track_path') and self.original_track_path == track_path):
            logger.info("Stopping playback as the currently active track is being deleted.")
            self.player.stop()
            self.btn_play_pause.setIcon(qta.icon('fa5s.play', color='#F0C419'))
            # Reset now playing info visually
            if hasattr(self, 'song_title_label'):
                self.song_title_label.setText("No Track Playing")
            if hasattr(self, 'artist_label'):
                self.artist_label.setText("Select a song to start")
            if hasattr(self, 'timeline_slider'):
                self.timeline_slider.setValue(0)
            if hasattr(self, 'lbl_time_curr'):
                self.lbl_time_curr.setText("0:00")
            if hasattr(self, 'lbl_time_max'):
                self.lbl_time_max.setText("0:00")
                
        # Get associated stems and JSON files to clean them up too
        files_to_delete = [track_path]
        json_path = os.path.splitext(track_path)[0] + ".json"
        if os.path.isfile(json_path):
            files_to_delete.append(json_path)
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                instr_path = data.get("instrumental_path")
                if instr_path and os.path.isfile(instr_path):
                    files_to_delete.append(instr_path)
                vocal_path = data.get("vocal_path")
                if vocal_path and os.path.isfile(vocal_path):
                    files_to_delete.append(vocal_path)
            except Exception as e:
                logger.warning(f"Failed to read associated stems from {json_path}: {e}")
                
        # Send files to Windows Recycle Bin using ctypes to avoid external dependencies
        import ctypes
        from ctypes import wintypes
        
        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", wintypes.LPVOID),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]
            
        FO_DELETE = 3
        FOF_ALLOWUNDO = 0x0040
        FOF_NOCONFIRMATION = 0x0010
        FOF_SILENT = 0x0004
        
        def win_trash(path):
            path_abs = os.path.abspath(path)
            if not os.path.exists(path_abs):
                return True
            path_buffer = path_abs + "\0\0"
            fileop = SHFILEOPSTRUCTW()
            fileop.hwnd = None
            fileop.wFunc = FO_DELETE
            fileop.pFrom = path_buffer
            fileop.pTo = None
            fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
            fileop.fAnyOperationsAborted = False
            fileop.hNameMappings = None
            fileop.lpszProgressTitle = None
            result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileop))
            return result == 0
            
        deletion_success = True
        for path in files_to_delete:
            if os.path.exists(path):
                ok = win_trash(path)
                if ok:
                    logger.info(f"Sent to Recycle Bin: {path}")
                else:
                    logger.warning(f"Failed to send to Recycle Bin: {path}, attempting standard delete.")
                    try:
                        os.remove(path)
                        logger.info(f"Standard deleted: {path}")
                    except Exception as err:
                        logger.error(f"Failed to delete file {path}: {err}")
                        deletion_success = False
                        
        # Delete database persistent records
        import analytics
        db_ok = analytics.delete_track_data(track_path)
        if db_ok:
            logger.info("Cleared database records for deleted track.")
        else:
            logger.error("Failed to clear database records for deleted track.")
            
        # Re-scan the library folder to refresh scanned_songs and library table!
        self.scan_music_library()
                
        QMessageBox.information(
            self, "Track Deleted",
            f"Successfully deleted '{song_name}' and cleared its database records."
        )

    def on_table_row_double_click(self, row, column):
        self.play_selected_table_row(row)

    def play_selected_table_row(self, row):
        """Plays the song corresponding to the selected table row."""
        title_widget = self.table_songs.cellWidget(row, 1)
        if isinstance(title_widget, QLabel):
            song_name = title_widget.text()
        else:
            item = self.table_songs.item(row, 1)
            song_name = item.text() if item else ""
            
        matching_song = None
        for s in self.scanned_songs:
            if s["name"] == song_name:
                matching_song = s
                break
                
        if matching_song:
            self.load_and_play_track(matching_song)

    def handle_dropped_files(self, file_paths):
        """Copies dropped .mp3/.wav files into the active playlist folder and rescans the library."""
        root_dir = self.config["music_root_dir"]
        target_dir = root_dir if self.active_playlist == "Library" else os.path.join(root_dir, self.active_playlist)
        os.makedirs(target_dir, exist_ok=True)

        imported = []
        skipped = []
        for src_path in file_paths:
            filename = os.path.basename(src_path)
            dest_path = os.path.join(target_dir, filename)
            if os.path.abspath(src_path) == os.path.abspath(dest_path):
                skipped.append(filename)
                continue
            try:
                import shutil
                shutil.copy2(src_path, dest_path)
                imported.append(filename)
                logger.info(f"Imported dropped file: {src_path} -> {dest_path}")
            except Exception as e:
                logger.error(f"Failed to copy dropped file {src_path}: {e}")

        if imported:
            logger.info(f"Successfully imported {len(imported)} file(s) via drag-and-drop.")
            self.scan_music_library()
        if skipped:
            logger.info(f"Skipped {len(skipped)} file(s) already in target directory.")

    def add_song_from_dialog(self):
        """Allows users to search directory and add audio files (.mp3, .wav) to the active playlist."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        import shutil
        
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Audio Files to Add",
            "",
            "Audio Files (*.mp3 *.wav)"
        )
        
        if not file_paths:
            return
            
        root_dir = self.config["music_root_dir"]
        target_dir = root_dir if self.active_playlist == "Library" else os.path.join(root_dir, self.active_playlist)
        os.makedirs(target_dir, exist_ok=True)
        
        imported = []
        skipped = []
        for src_path in file_paths:
            filename = os.path.basename(src_path)
            dest_path = os.path.join(target_dir, filename)
            if os.path.abspath(src_path) == os.path.abspath(dest_path):
                skipped.append(filename)
                continue
            try:
                shutil.copy2(src_path, dest_path)
                imported.append(filename)
                logger.info(f"Imported song via button: {src_path} -> {dest_path}")
            except Exception as e:
                logger.error(f"Failed to copy song {src_path}: {e}")
                
        if imported:
            QMessageBox.information(
                self, 
                "Success", 
                f"Successfully added {len(imported)} song(s) to the library."
            )
            self.scan_music_library()
        if skipped:
            QMessageBox.warning(
                self,
                "Warning",
                f"Skipped {len(skipped)} file(s) that were already in the target folder."
            )

    def _check_song_has_instrumental(self, song):
        """Checks if a song already has an extracted instrumental file."""
        json_path = os.path.splitext(song["path"])[0] + ".json"
        if os.path.isfile(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                instr_path = data.get("instrumental_path")
                if instr_path and os.path.isfile(instr_path):
                    return True
            except Exception:
                pass
        return False

    def trigger_instrumental_extraction(self, song):
        """Triggers instrumental extraction for a song. Uses instrumental_only mode if lyrics exist."""
        has_karaoke = song.get("has_karaoke", False)
        if has_karaoke:
            # Option B: song already has lyrics, just extract instrumental
            logger.info(f"Extracting instrumental only for [{song['name']}] (lyrics already exist).")
            self.trigger_track_karaoke_generation(song, force=False, instrumental_only=True)
        else:
            # Option A: no lyrics yet, run full pipeline
            logger.info(f"Running full pipeline for [{song['name']}] (no lyrics, extracting both).")
            self.trigger_track_karaoke_generation(song, force=True)

    # ==========================
    # PLAYLISTS / SUBFOLDERS SCANNER
    # ==========================
    def scan_playlists_list(self):
        root_dir = self.config["music_root_dir"]
        self.playlist_list.clear()
        library_item = self.playlist_list.addItem("📚 Full Library")
        
        if self.active_playlist == "Library":
            self.playlist_list.setCurrentRow(0)
            
        if os.path.isdir(root_dir):
            subdirs = [d for d in os.listdir(root_dir) if os.path.isdir(os.path.join(root_dir, d)) and not d.startswith(".")]
            for idx, subdir in enumerate(subdirs):
                self.playlist_list.addItem(f"📁 {subdir}")
                if self.active_playlist == subdir:
                    self.playlist_list.setCurrentRow(idx + 1)

    def on_playlist_clicked(self, item):
        text = item.text()
        if text == "📚 Full Library":
            self.active_playlist = "Library"
        else:
            self.active_playlist = text.replace("📁 ", "")
            
        if hasattr(self, 'library_tabs'):
            self.library_tabs.setCurrentIndex(2)
            
        logger.info(f"Switched playlist filter to: {self.active_playlist}")
        self.scan_music_library()

    def create_new_playlist(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Playlist", "Enter a name for the new playlist sub-folder:")
        if ok and name.strip():
            playlist_name = name.strip()
            dest_dir = os.path.join(self.config["music_root_dir"], playlist_name)
            try:
                os.makedirs(dest_dir, exist_ok=True)
                self.active_playlist = playlist_name
                self.scan_music_library()
                logger.info(f"Created new playlist directory: {dest_dir}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create playlist folder: {e}")

    # ==========================
    # PAGE 2: YOUTUBE BULK DOWNLOAD QUEUE VIEW
    # ==========================
    def setup_queue_page(self):
        page = QWidget()
        layout = QVBoxLayout()
        # Premium layout margins
        layout.setContentsMargins(30, 30, 30, 20)
        layout.setSpacing(15)
        page.setLayout(layout)
        
        title = QLabel("Bulk YouTube Downloader")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: white; margin-bottom: 5px;")
        layout.addWidget(title)
        
        desc = QLabel("Paste unlimited YouTube link URLs (one link per line) below. MozZzart Player will dry-run scan all video titles, mount them to the queue, and download them sequentially to maximize bandwidth safety.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #B3B3B3; font-size: 12px; line-height: 16px; margin-bottom: 10px;")
        layout.addWidget(desc)
        
        # Download Control Form using multiline scrollable QTextEdit
        form_panel = QFrame()
        form_panel.setObjectName("DownloadFormPanel")
        form_panel.setStyleSheet("QFrame#DownloadFormPanel { background-color: #121212; border: 1px solid #1E1E1E; border-radius: 8px; padding: 15px; }")
        form_layout = QHBoxLayout()
        form_panel.setLayout(form_layout)
        
        # Upgrade to QTextEdit to support scrollable unlimited multiline link pasting
        self.txt_yt_urls = QTextEdit()
        self.txt_yt_urls.setPlaceholderText("🔗 Paste links OR type 'Song Name - Artist' (one per line). Example:\nArthur Nery - Pagsamo")
        self.txt_yt_urls.setMinimumHeight(100)
        self.txt_yt_urls.setMaximumHeight(150)
        self.txt_yt_urls.setStyleSheet("background-color: #1C1C1C; border-radius: 6px; padding: 10px; color: white;")
        form_layout.addWidget(self.txt_yt_urls, stretch=1)
        
        # Vertical control block on the right
        controls_layout = QVBoxLayout()
        controls_layout.setSpacing(10)
        
        # Target Track Count spinbox container
        target_layout = QHBoxLayout()
        target_lbl = QLabel("Target Tracks:")
        target_lbl.setStyleSheet("color: #B3B3B3; font-size: 11px; font-weight: bold;")
        
        self.spin_target_count = QSpinBox()
        self.spin_target_count.setRange(0, 9999)
        self.spin_target_count.setValue(0)
        self.spin_target_count.setSpecialValueText("Auto")
        self.spin_target_count.setStyleSheet("""
            QSpinBox {
                background-color: #1C1C1C;
                border: 1px solid #2C2C2C;
                border-radius: 4px;
                padding: 4px 8px;
                color: white;
                min-width: 80px;
                font-size: 12px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 0px; /* Hide buttons for clean design */
            }
        """)
        target_layout.addWidget(target_lbl)
        target_layout.addWidget(self.spin_target_count)
        
        controls_layout.addLayout(target_layout)
        
        btn_start_dl = QPushButton("🚀 Grab Tracks")
        btn_start_dl.setObjectName("PrimaryButton")
        btn_start_dl.setFixedHeight(40)
        btn_start_dl.clicked.connect(self.trigger_youtube_download)
        controls_layout.addWidget(btn_start_dl)
        
        form_layout.addLayout(controls_layout)
        
        layout.addWidget(form_panel)
        
        # Redesigned premium header with "Clear Completed" button
        monitor_header = QHBoxLayout()
        monitor_lbl = QLabel("BULK DOWNLOAD QUEUE MONITOR")
        monitor_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF; letter-spacing: 0.5px;")
        monitor_header.addWidget(monitor_lbl)
        
        monitor_header.addStretch()
        
        self.btn_clear_queue = QPushButton("🧹 Clear Completed")
        self.btn_clear_queue.setToolTip("Clear finished or cancelled items from the list")
        self.btn_clear_queue.setFixedSize(140, 28)
        self.btn_clear_queue.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_queue.setStyleSheet("""
            QPushButton {
                background-color: #1A1A1A;
                color: #B3B3B3;
                border-radius: 14px;
                font-size: 11px;
                padding: 0px 12px;
                text-align: center;
                border: 1px solid #222222;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2D7D46;
                color: #FFFFFF;
                border: 1px solid #2D7D46;
            }
            QPushButton:pressed {
                background-color: #151515;
            }
        """)
        self.btn_clear_queue.clicked.connect(self.clear_queue_monitor)
        monitor_header.addWidget(self.btn_clear_queue)
        
        layout.addLayout(monitor_header)
        
        # Queue List Container
        self.queue_container = QListWidget()
        self.queue_container.setStyleSheet("""
            QListWidget {
                background-color: #050505;
                border-radius: 8px;
                padding: 12px;
                border: 1px solid #1E1E1E;
            }
            QListWidget::item {
                padding: 0px !important;
                margin-bottom: 10px;
                background-color: transparent;
            }
            QListWidget::item:hover {
                background-color: transparent;
            }
            QListWidget::item:selected {
                background-color: transparent;
            }
        """)
        layout.addWidget(self.queue_container)
        
        self.content_stack.addWidget(page)

    def trigger_youtube_download(self):
        """Initializes downloading in a sequenced background thread."""
        urls_text = self.txt_yt_urls.toPlainText().strip()
        if not urls_text:
            QMessageBox.warning(self, "Empty URLs list", "Please paste one or more YouTube or Spotify link URLs (one per line) first.")
            return
            
        # Parse links line by line
        raw_urls = urls_text.split("\n")
        raw_urls = [u.strip() for u in raw_urls if u.strip()]
        
        youtube_urls = []
        spotify_playlist_urls = []
        
        for u in raw_urls:
            if "spotify.com" in u:
                spotify_playlist_urls.append(u)
            elif u.startswith("http"):
                youtube_urls.append(u)
            else:
                # Treat plain text as a YouTube search query
                if not u.startswith("ytsearch"):
                    youtube_urls.append(f"ytsearch1:{u}")
                else:
                    youtube_urls.append(u)
                    
        if not youtube_urls and not spotify_playlist_urls:
            QMessageBox.warning(self, "Invalid Input", "Please paste valid links or type a song name to search.")
            return
            
        # If we have Spotify playlists, we must fetch their track lists
        if spotify_playlist_urls:
            # Show a modal loading dialog
            fetch_dialog = SpotifyFetchDialog(self)
            
            # Start background live scraper worker thread
            target_count = self.spin_target_count.value()
            scraper_worker = SpotifyScraperWorker(spotify_playlist_urls, target_count=target_count)
            self._spotify_scraper_worker = scraper_worker
            
            def on_scraper_status(status_text):
                fetch_dialog.update_status(status_text)
                
            def on_scraper_finished(search_queries):
                fetch_dialog.accept()
                if not search_queries:
                    QMessageBox.information(self, "No Tracks Found", "No tracks were successfully parsed from the Spotify playlist.")
                    return
                
                # Feed the parsed queries directly into the yt-dlp queue using the ytsearch1: prefix
                resolved_queries = []
                for query in search_queries:
                    # Ensure the query doesn't already start with ytsearch1:
                    if not query.startswith("ytsearch1:"):
                        resolved_queries.append(f"ytsearch1:{query}")
                    else:
                        resolved_queries.append(query)
                
                combined_urls = youtube_urls + resolved_queries
                self.start_download_worker(combined_urls)
                
            def on_scraper_error(err_msg):
                fetch_dialog.reject()
                QMessageBox.critical(self, "Spotify Extraction Error", f"An error occurred while scraping Spotify playlist:\n{err_msg}")
            
            scraper_worker.status.connect(on_scraper_status)
            scraper_worker.finished.connect(on_scraper_finished)
            scraper_worker.error.connect(on_scraper_error)
            
            scraper_worker.start()
            fetch_dialog.exec()
            
        else:
            self.start_download_worker(youtube_urls)

    def start_download_worker(self, urls_list):
        self.txt_yt_urls.clear()
        
        # Target output folder
        root_dir = self.config["music_root_dir"]
        output_dir = root_dir
        if self.active_playlist != "Library":
            output_dir = os.path.join(root_dir, self.active_playlist)
            
        # UI Queue Container Setup
        self.queue_container.clear()
        self.download_progress_widgets.clear()
        self.pending_transcriptions_queue = []
        
        # Instantiate DownloadWorker passing the list of URLs
        self.download_queue_worker = DownloadWorker(urls_list, output_dir)
        
        # Define connection slots
        self.download_queue_worker.metadata_resolved_signal.connect(self.on_metadata_resolved)
        self.download_queue_worker.progress_signal.connect(self.on_download_progress)
        self.download_queue_worker.track_finished_signal.connect(self.on_track_download_finished)
        self.download_queue_worker.track_error_signal.connect(self.on_track_download_error)
        self.download_queue_worker.all_finished_signal.connect(self.on_all_downloads_completed)
        
        # Switch tab view immediately
        self.show_page(1)
        
        # Put worker on CPU loop
        self.download_queue_worker.start()

    def on_metadata_resolved(self, resolved_tracks):
        """Builds beautiful UI progress rows for all resolved links before downloading begins."""
        self.queue_container.clear()
        self.download_progress_widgets.clear()
        
        for track in resolved_tracks:
            idx = track["idx"]
            title = track["title"]
            
            list_item = QListWidgetItem()
            self.queue_container.addItem(list_item)
            
            # Custom list widget row styled as a premium dark card with guaranteed minimum height
            queue_row = QWidget()
            queue_row.setMinimumHeight(105) # Force minimum height so labels can never be squished to 0px!
            queue_row.setStyleSheet("""
                QWidget {
                    background-color: #121212;
                    border: 1px solid #1E1E1E;
                    border-radius: 8px;
                }
                QLabel {
                    border: none;
                    background-color: transparent;
                }
                QProgressBar {
                    border: none;
                }
            """)
            
            row_layout = QVBoxLayout()
            row_layout.setContentsMargins(16, 10, 16, 10)
            row_layout.setSpacing(6)
            queue_row.setLayout(row_layout)
            
            # Top row layout: title and cancel button
            top_layout = QHBoxLayout()
            top_layout.setContentsMargins(0, 0, 0, 0)
            
            title_lbl = QLabel(f"⏳ Pending: {title}")
            title_lbl.setStyleSheet("font-weight: bold; color: #FFFFFF; font-size: 13px;")
            title_lbl.setWordWrap(False)
            top_layout.addWidget(title_lbl, stretch=1)
            
            # Circular hoverable "❌" cancel button
            btn_cancel = QPushButton("❌")
            btn_cancel.setToolTip("Cancel this download")
            btn_cancel.setFixedSize(24, 24)
            btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_cancel.setStyleSheet("""
                QPushButton {
                    background-color: #1A1A1A;
                    color: #FF5555;
                    border-radius: 12px;
                    font-size: 10px;
                    padding: 0px;
                    font-weight: bold;
                    text-align: center;
                }
                QPushButton:hover {
                    background-color: #FF5555;
                    color: #FFFFFF;
                }
                QPushButton:pressed {
                    background-color: #CC3333;
                }
            """)
            btn_cancel.clicked.connect(lambda checked=False, idx=idx: self.cancel_download_item(idx))
            top_layout.addWidget(btn_cancel)
            
            row_layout.addLayout(top_layout)
            
            info_layout = QHBoxLayout()
            stat_lbl = QLabel("Status: Queued")
            stat_lbl.setStyleSheet("color: #888888; font-size: 11px;")
            info_layout.addWidget(stat_lbl)
            
            speed_lbl = QLabel("Speed: -")
            speed_lbl.setStyleSheet("color: #888888; font-size: 11px;")
            info_layout.addWidget(speed_lbl)
            
            eta_lbl = QLabel("ETA: -")
            eta_lbl.setStyleSheet("color: #888888; font-size: 11px;")
            info_layout.addWidget(eta_lbl)
            
            row_layout.addLayout(info_layout)
            
            bar = QProgressBar()
            bar.setValue(0)
            row_layout.addWidget(bar)
            
            list_item.setSizeHint(QSize(100, 125))
            self.queue_container.setItemWidget(list_item, queue_row)
            
            # Keep pointers to update progress fields mapped by index
            self.download_progress_widgets[idx] = {
                "title_label": title_lbl,
                "status_label": stat_lbl,
                "speed_label": speed_lbl,
                "eta_label": eta_lbl,
                "progress_bar": bar,
                "cancel_button": btn_cancel,
                "list_item": list_item
            }

    def on_download_progress(self, prog_dict):
        """Fires repeatedly updating progress rows mapping index metrics."""
        idx = prog_dict["idx"]
        if idx in self.download_progress_widgets:
            w = self.download_progress_widgets[idx]
            
            # If already cancelled, do not let late progress signals overwrite the UI
            if w["status_label"].text() == "[Cancelled]":
                return
                
            resolved_title = self.download_queue_worker.resolved_tracks[idx]["title"] if self.download_queue_worker else "Track"
            
            # Format high-fidelity transition text
            percent = int(prog_dict.get("percent", 0))
            raw_status = prog_dict.get("status", "")
            
            if "Connecting" in raw_status:
                status_text = "[Fetching Metadata...]"
            elif "Downloading" in raw_status:
                status_text = f"[Downloading: {percent}%]"
            elif "Converting" in raw_status:
                status_text = "[Converting via FFmpeg...]"
            else:
                status_text = f"[{raw_status}]"
                
            w["title_label"].setText(f"📥 {resolved_title}")
            w["status_label"].setText(status_text)
            w["status_label"].setStyleSheet("color: #1DB954; font-size: 11px; font-weight: bold;")
            w["speed_label"].setText(f"Speed: {prog_dict['speed']}")
            w["eta_label"].setText(f"ETA: {prog_dict['eta']}")
            w["progress_bar"].setValue(percent)

    def on_track_download_finished(self, idx, title, local_path):
        """Marks track completed inside its queue list item and silently chains ML sync."""
        if idx in self.download_progress_widgets:
            w = self.download_progress_widgets[idx]
            w["title_label"].setText(f"✅ {title}")
            w["status_label"].setText("[Done]")
            w["status_label"].setStyleSheet("color: #1DB954; font-weight: bold; font-size: 11px;")
            w["speed_label"].setText("Speed: N/A")
            w["eta_label"].setText("Saved to library!")
            w["progress_bar"].setValue(100)
            if "cancel_button" in w:
                w["cancel_button"].hide()
            
        self.scan_music_library()
        
        # Buffer the song for sequential auto-transcribing AFTER all downloads are complete!
        song = {
            "name": title,
            "filename": os.path.basename(local_path),
            "path": local_path,
            "type": "MP3",
            "has_karaoke": False
        }
        if not hasattr(self, "pending_transcriptions_queue"):
            self.pending_transcriptions_queue = []
        self.pending_transcriptions_queue.append(song)
        logger.info(f"Buffered finished track for sequential post-transcription: {title}")

    def on_track_download_error(self, idx, err_msg):
        """Marks track error card in red and halts its progress row."""
        if idx in self.download_progress_widgets:
            w = self.download_progress_widgets[idx]
            if "cancel" in err_msg.lower() or err_msg == "Cancelled":
                w["title_label"].setText("❌ Cancelled")
                w["status_label"].setText("[Cancelled]")
                w["status_label"].setStyleSheet("color: #888888; font-weight: bold; font-size: 11px;")
                w["speed_label"].setText("Speed: N/A")
                w["eta_label"].setText("Cancelled by user")
                w["progress_bar"].setValue(0)
            else:
                resolved_title = "Unknown Track"
                if hasattr(self, "download_queue_worker") and self.download_queue_worker:
                    resolved_title = self.download_queue_worker.resolved_tracks[idx]["title"]
                w["title_label"].setText(f"❌ Failed: {resolved_title}")
                w["status_label"].setText(f"[Error: {err_msg[:40]}...]" if len(err_msg) > 40 else f"[Error: {err_msg}]")
                w["status_label"].setStyleSheet("color: #FF5555; font-weight: bold; font-size: 11px;")
                w["speed_label"].setText("Speed: N/A")
                w["eta_label"].setText("Failed!")
                w["progress_bar"].setStyleSheet("QProgressBar::chunk { background-color: #FF5555; }")
            if "cancel_button" in w:
                w["cancel_button"].hide()

    def on_all_downloads_completed(self):
        """Fires when bulk queue has finished resolving sequentially silently."""
        logger.info("Bulk download queue completed processing silently.")
        self.download_queue_worker = None
        
        # Sequentially trigger karaoke auto-transcribe for all buffered successful downloads!
        if hasattr(self, "pending_transcriptions_queue") and self.pending_transcriptions_queue:
            logger.info(f"Downloads completed. Triggering background auto-transcription for {len(self.pending_transcriptions_queue)} tracks...")
            for song in self.pending_transcriptions_queue:
                self.trigger_track_karaoke_generation(song, silent=True)
            self.pending_transcriptions_queue.clear()

    def cancel_download_item(self, idx):
        """User clicked the cancel button for a download item."""
        if hasattr(self, "download_queue_worker") and self.download_queue_worker:
            self.download_queue_worker.cancel_idx(idx)
            
        # Update the UI state immediately to feel extremely responsive
        if idx in self.download_progress_widgets:
            w = self.download_progress_widgets[idx]
            w["title_label"].setText("❌ Cancelled")
            w["status_label"].setText("[Cancelled]")
            w["status_label"].setStyleSheet("color: #888888; font-weight: bold; font-size: 11px;")
            w["speed_label"].setText("Speed: N/A")
            w["eta_label"].setText("Cancelled by user")
            w["progress_bar"].setValue(0)
            if "cancel_button" in w:
                w["cancel_button"].hide()

    def clear_queue_monitor(self):
        """Clears the completed, failed, and cancelled items from the download queue list widget."""
        is_running = hasattr(self, "download_queue_worker") and self.download_queue_worker is not None and self.download_queue_worker.isRunning()
        
        if is_running:
            # Only clear non-active, non-pending items (finished, failed, or cancelled)
            for idx in list(self.download_progress_widgets.keys()):
                is_active = (self.download_queue_worker.active_idx == idx)
                is_cancelled = (idx in self.download_queue_worker.cancelled_indices)
                is_pending = (idx > self.download_queue_worker.active_idx)
                
                if is_cancelled or (not is_active and not is_pending):
                    self.remove_queue_item_by_index(idx)
        else:
            # No active worker, we can clear everything!
            self.queue_container.clear()
            self.download_progress_widgets.clear()

    def remove_queue_item_by_index(self, idx):
        """Removes a specific queue item widget from the list by index."""
        if idx in self.download_progress_widgets:
            item_data = self.download_progress_widgets[idx]
            list_item = item_data["list_item"]
            row = self.queue_container.row(list_item)
            if row >= 0:
                self.queue_container.takeItem(row)
            del self.download_progress_widgets[idx]

    # ==========================
    # PAGE 3: STATE OF THE ART KARAOKE VIEW (WORD-LEVEL SYNCHRONIZATION)
    # ==========================
    def setup_karaoke_page(self):
        page = QWidget()
        layout = QVBoxLayout()
        # Increased spacious padding
        layout.setContentsMargins(30, 30, 30, 20)
        layout.setSpacing(15)
        page.setLayout(layout)
        
        # Glassmorphic header
        header = QHBoxLayout()
        title = QLabel("🎤 Dynamic Karaoke Screen")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #F0C419;")
        header.addWidget(title)
        header.addStretch()
        
        self.btn_full_karaoke = QPushButton("🎤 Full Karaoke Mode")
        self.btn_full_karaoke.setStyleSheet("background-color: #1A1A1A; color: #B3B3B3; padding: 8px 16px; font-weight: bold; border-radius: 4px;")
        self.btn_full_karaoke.clicked.connect(self.toggle_full_karaoke_mode)
        header.addWidget(self.btn_full_karaoke)

        
        self.btn_edit_lyrics = QPushButton("✏️ Edit Lyrics")
        self.btn_edit_lyrics.setStyleSheet("background-color: #1A1A1A; color: #B3B3B3; padding: 8px 16px; font-weight: bold; border-radius: 4px;")
        self.btn_edit_lyrics.setEnabled(False) # Disabled by default until paused
        self.btn_edit_lyrics.clicked.connect(self.toggle_lyrics_edit_mode)
        header.addWidget(self.btn_edit_lyrics)
        
        # Vocal Guide Volume slider (only visible during Karaoke Mode)
        self.vocal_guide_widget = QWidget()
        vg_layout = QHBoxLayout()
        vg_layout.setContentsMargins(0, 0, 0, 0)
        vg_layout.setSpacing(4)
        self.vocal_guide_widget.setLayout(vg_layout)
        
        vg_lbl = QLabel("🎤 Guide Vol:")
        vg_lbl.setStyleSheet("color: #B3B3B3; font-size: 11px; font-weight: bold;")
        vg_layout.addWidget(vg_lbl)
        
        self.slider_vocal_guide = QSlider(Qt.Orientation.Horizontal)
        self.slider_vocal_guide.setRange(0, 100)
        self.slider_vocal_guide.setValue(10)  # Default 10%
        self.slider_vocal_guide.setFixedWidth(110)
        self.slider_vocal_guide.setStyleSheet("""
            QSlider::groove:horizontal { height: 5px; background: #333333; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #1DB954; border-radius: 2px; }
            QSlider::handle:horizontal { background: #FFFFFF; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
        """)
        self.slider_vocal_guide.valueChanged.connect(self.on_guide_vocal_volume_changed)
        vg_layout.addWidget(self.slider_vocal_guide)
        
        self.lbl_vocal_guide_pct = QLabel("10%")
        self.lbl_vocal_guide_pct.setStyleSheet("color: #1DB954; font-size: 11px; font-weight: bold; min-width: 32px;")
        vg_layout.addWidget(self.lbl_vocal_guide_pct)
        
        self.vocal_guide_widget.setVisible(False)  # Hidden until Karaoke Mode is ON
        header.addWidget(self.vocal_guide_widget)
        
        self.btn_back_lib = QPushButton("📚 Back to library")
        self.btn_back_lib.setStyleSheet("background-color: #1A1A1A; color: white; padding: 8px 16px; font-weight: bold; border-radius: 4px;")
        self.btn_back_lib.clicked.connect(lambda: self.show_page(0))
        header.addWidget(self.btn_back_lib)
        
        self.btn_fullscreen = QPushButton("🔲 Fullscreen")
        self.btn_fullscreen.setStyleSheet("background-color: #1A1A1A; color: white; padding: 8px 16px; font-weight: bold; border-radius: 4px;")
        self.btn_fullscreen.clicked.connect(self.toggle_karaoke_fullscreen)
        header.addWidget(self.btn_fullscreen)
        
        layout.addLayout(header)
        
        # Scroll Area for dynamic expansive lyrics display
        self.lyric_scroll = QScrollArea()
        self.lyric_scroll.setWidgetResizable(True)
        
        from PyQt6.QtWidgets import QAbstractScrollArea
        self.lyric_scroll.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.lyric_scroll.setObjectName("LyricScrollArea")
        self.lyric_scroll.setStyleSheet("background-color: #050505; border-radius: 12px; border: 1px solid #1E1E1E;")
        
        self.lyrics_container = QWidget()
        self.lyrics_container.setObjectName("LyricScrollWidget")
        
        # Refactored dynamic viewport expansion parameters
        self.lyrics_layout = QVBoxLayout()
        # High padding constraints allow first and last lyrics to scroll directly to vertical center!
        self.lyrics_layout.setContentsMargins(30, 250, 30, 250)
        self.lyrics_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lyrics_layout.setSpacing(22)
        
        # ULTIMATE FIX: Completely sever the layout's ability to dictate window size
        self.lyrics_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)
        self.lyrics_container.setMinimumSize(0, 0)
        
        # Enforce strict boundaries on the scroll area instead so it absorbs font size changes internally
        self.lyric_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.lyric_scroll.setMinimumHeight(300)
        self.lyrics_container.setLayout(self.lyrics_layout)
        
        self.lyric_scroll.setWidget(self.lyrics_container)
        
        self.karaoke_content_layout = QHBoxLayout()
        
        # Load the pre-keyed transparent GIFs using the first playlist item
        playlist = self.config.get("gif_playlist", ["mozart dance.gif"])
        initial_gif = playlist[0] if playlist else "mozart dance.gif"
        
        self.mozart_left = MozartPlayer(initial_gif)
        self.mozart_right = MozartPlayer(initial_gif)
        self.mozart_left.hide()
        self.mozart_right.hide()
        
        # Connect to the global infinite Cycler
        self.mozart_left.loop_finished.connect(self._trigger_gif_cycle)

        self.karaoke_content_layout.addWidget(self.mozart_left)
        self.karaoke_content_layout.addWidget(self.lyric_scroll, stretch=1)
        self.karaoke_content_layout.addWidget(self.mozart_right)

        layout.addLayout(self.karaoke_content_layout)
        
        self.lbl_next_up = QLabel("Next Up: --")
        self.lbl_next_up.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_next_up.setStyleSheet("color: #888888; font-size: 14px; font-weight: bold; padding: 10px; background-color: #0A0A0A; border-radius: 8px; border: 1px solid #1E1E1E;")
        layout.addWidget(self.lbl_next_up)
        
        self.content_stack.addWidget(page)

    def open_lyrics_correction_dialog(self, song):
        """Opens the lyrics correction dialog for the selected song."""
        json_path = os.path.splitext(song["path"])[0] + ".json"
        if not os.path.isfile(json_path):
            QMessageBox.warning(self, "No Lyrics File", "This song does not have a synchronized lyrics file to correct.")
            return
            
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                original_lyrics_db = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Error Reading File", f"Failed to read the lyrics file:\n{e}")
            return
            
        dialog = LyricsCorrectionDialog(song, original_lyrics_db, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.confirmed_lyrics:
            try:
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(dialog.confirmed_lyrics, f, indent=4, ensure_ascii=False)
                
                QMessageBox.information(
                    self,
                    "Lyrics Corrected",
                    f"Successfully corrected and aligned lyrics for [{song['name']}]!\n"
                    "The karaoke timings have been perfectly preserved and fitted to your edits."
                )
                
                if self.player.current_track and self.player.current_track == song["path"]:
                    self.load_karaoke_lyrics_data(song["path"])
                    
                self.scan_music_library()
            except Exception as e:
                QMessageBox.critical(self, "Error Saving File", f"Failed to save corrected lyrics:\n{e}")

    def load_karaoke_lyrics_data(self, file_path):
        """Loads and parses word-synchronized JSON metadata."""
        self.lyrics_db = None
        self.active_lyric_line_idx = -1
        self.is_editing_lyrics = False
        if hasattr(self, 'btn_edit_lyrics'):
            self.btn_edit_lyrics.setText("✏️ Edit Lyrics")
            self.btn_edit_lyrics.setStyleSheet("background-color: #1A1A1A; color: #B3B3B3; padding: 8px 16px; font-weight: bold; border-radius: 4px;")
            # FIX: Keep button enabled if the player is currently paused
            is_paused = False
            if hasattr(self, 'player') and self.player:
                is_paused = not getattr(self.player, 'is_playing', lambda: False)()
            self.btn_edit_lyrics.setEnabled(is_paused and not getattr(self, 'karaoke_mode_active', False))
        
        # Clear previous labels
        while self.lyrics_layout.count():
            item = self.lyrics_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        json_path = os.path.splitext(file_path)[0] + ".json"
        
        if not os.path.isfile(json_path):
            no_lbl = QLabel("🎤 Synchronized lyrics not found.\nPress 'Sync' in the Library to compile Karaoke lyrics instantly!")
            no_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_lbl.setStyleSheet("font-size: 16px; color: #888888; font-weight: bold; line-height: 25px;")
            self.lyrics_layout.addWidget(no_lbl)
            return

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                self.lyrics_db = json.load(f)
                
            for line_idx, line in enumerate(self.lyrics_db["lyrics"]):
                line_lbl = QLabel(line["text"])
                line_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                line_lbl.setObjectName(f"LyricLine_{line_idx}")
                line_lbl.setStyleSheet("font-size: 24px; font-weight: bold; color: #444444; padding: 12px; background-color: transparent; border: none;")
                line_lbl.setWordWrap(True)
                line_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
                self.lyrics_layout.addWidget(line_lbl)
                
            logger.info(f"Loaded {len(self.lyrics_db['lyrics'])} synchronized lyric lines.")
        except Exception as e:
            logger.error(f"Failed to load lyric database: {e}")
            err_lbl = QLabel(f"⚠️ Error parsing sync lyric file:\n{e}")
            err_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            err_lbl.setStyleSheet("font-size: 14px; color: #FF5555; font-weight: bold;")
            self.lyrics_layout.addWidget(err_lbl)

    def update_karaoke_visuals(self, current_time):
        """Toggles highlights and smooth scrolls active karaoke lyrics using current playback position."""
        if not self.lyrics_db or self.content_stack.currentIndex() != 2:
            return
            
        lyrics = self.lyrics_db["lyrics"]
        active_line_idx = -1
        
        # 1. Resolve which line is currently active
        for idx, line in enumerate(lyrics):
            if line["start"] <= current_time <= line["end"]:
                active_line_idx = idx
                break
            elif idx > 0 and lyrics[idx-1]["end"] < current_time < line["start"]:
                active_line_idx = idx - 1
                break
                
        if active_line_idx == -1 and len(lyrics) > 0:
            if current_time >= lyrics[-1]["end"]:
                active_line_idx = len(lyrics) - 1

        # 2. If active line has changed, update surrounding font colors and center-scroll
        if active_line_idx != self.active_lyric_line_idx:
            self.active_lyric_line_idx = active_line_idx
            
            for idx in range(self.lyrics_layout.count()):
                widget = self.lyrics_layout.itemAt(idx).widget()
                if isinstance(widget, QLabel):
                    if idx == active_line_idx:
                        widget.setStyleSheet("font-size: 32px; font-weight: bold; color: #FFFFFF; padding: 12px; background-color: transparent; border: none;")
                        self.scroll_to_lyric_widget(widget)
                    elif abs(idx - active_line_idx) == 1:
                        widget.setStyleSheet("font-size: 24px; font-weight: bold; color: #888888; padding: 12px; background-color: transparent; border: none;")
                    else:
                        widget.setStyleSheet("font-size: 20px; font-weight: bold; color: #3A3A3A; padding: 12px; background-color: transparent; border: none;")

        # 3. Apply state-of-the-art word-level glowing HTML splits within the active line
        if active_line_idx != -1 and active_line_idx < len(lyrics):
            active_line = lyrics[active_line_idx]
            words = active_line.get("words", [])
            
            if words:
                html_formatted_line = []
                for w in words:
                    if w["start"] <= current_time <= w["end"]:
                        html_formatted_line.append(f"<span style='color: #1DB954; font-size: 34px;'>{w['word']}</span>")
                    elif current_time > w["end"]:
                        html_formatted_line.append(f"<span style='color: #FFFFFF;'>{w['word']}</span>")
                    else:
                        html_formatted_line.append(f"<span style='color: #888888;'>{w['word']}</span>")
                        
                formatted_html = " ".join(html_formatted_line)
                
                widget = self.lyrics_layout.itemAt(active_line_idx).widget()
                if isinstance(widget, QLabel):
                    widget.setText(formatted_html)

    def scroll_to_lyric_widget(self, widget):
        """Applies exact centered auto-scroll physics using relative viewport boundaries."""
        scroll_bar = self.lyric_scroll.verticalScrollBar()
        # Find relative position inside container
        widget_y = widget.geometry().top()
        widget_height = widget.geometry().height()
        viewport_height = self.lyric_scroll.viewport().height()
        
        # Center lyric vertically
        target_value = widget_y - (viewport_height // 2) + (widget_height // 2)
        scroll_bar.setValue(max(0, min(target_value, scroll_bar.maximum())))

    def toggle_lyrics_edit_mode(self):
        if not self.lyrics_db or not self.player.current_track:
            return
        
        # Prevent rapid double-click race conditions
        self.btn_edit_lyrics.setEnabled(False)
        
        if not getattr(self, "is_editing_lyrics", False):
            # --- ENTER EDIT MODE ---
            self.is_editing_lyrics = True
            self.btn_edit_lyrics.setText("💾 Save Lyrics")
            self.btn_edit_lyrics.setStyleSheet("background-color: #F0C419; color: #000000; padding: 8px 16px; font-weight: bold; border-radius: 4px;")
            if hasattr(self, 'btn_full_karaoke'):
                self.btn_full_karaoke.setEnabled(False)

            # Transform QLabels into editable QLineEdits
            for idx in range(self.lyrics_layout.count()):
                item = self.lyrics_layout.itemAt(idx)
                if item and item.widget() and isinstance(item.widget(), QLabel):
                    lbl = item.widget()
                    raw_text = self.lyrics_db["lyrics"][idx]["text"]
                    
                    line_edit = QLineEdit(raw_text)
                    line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    line_edit.setStyleSheet("font-size: 24px; font-weight: bold; color: #FFFFFF; padding: 10px; background-color: #1E1E1E; border: 1px solid #F0C419; border-radius: 8px;")
                    
                    self.lyrics_layout.replaceWidget(lbl, line_edit)
                    lbl.deleteLater()
        else:
            # --- EXIT EDIT MODE & SAVE ---
            self.is_editing_lyrics = False
            self.btn_edit_lyrics.setText("✏️ Edit Lyrics")
            self.btn_edit_lyrics.setStyleSheet("background-color: #1A1A1A; color: #B3B3B3; padding: 8px 16px; font-weight: bold; border-radius: 4px;")
            if hasattr(self, 'btn_full_karaoke'):
                self.btn_full_karaoke.setEnabled(True)

            changed = False
            for idx in range(self.lyrics_layout.count()):
                item = self.lyrics_layout.itemAt(idx)
                if item and item.widget() and isinstance(item.widget(), QLineEdit):
                    edit_widget = item.widget()
                    new_text = edit_widget.text().strip()
                    old_text = self.lyrics_db["lyrics"][idx]["text"]
                    
                    if new_text != old_text:
                        changed = True
                        self.lyrics_db["lyrics"][idx]["text"] = new_text
                        
                        # Proportional Timestamp Splitting (Bypasses diff-match logic)
                        words_str = new_text.split()
                        if words_str:
                            start_t = self.lyrics_db["lyrics"][idx]["start"]
                            end_t = self.lyrics_db["lyrics"][idx]["end"]
                            w_dur = (end_t - start_t) / len(words_str)
                            
                            new_words = []
                            for i, w in enumerate(words_str):
                                new_words.append({
                                    "word": w,
                                    "start": round(start_t + (i * w_dur), 2),
                                    "end": round(start_t + ((i + 1) * w_dur), 2)
                                })
                            self.lyrics_db["lyrics"][idx]["words"] = new_words
                        else:
                            self.lyrics_db["lyrics"][idx]["words"] = []
                            
            if changed:
                json_path = os.path.splitext(self.player.current_track)[0] + ".json"
                try:
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(self.lyrics_db, f, indent=4, ensure_ascii=False)
                    logger.info("Real-time lyrics edits saved successfully.")
                except Exception as e:
                    logger.error(f"Failed to save real-time lyrics edits: {e}")
            
            # Reload visuals natively to restore glowing HTML labels
            self.load_karaoke_lyrics_data(self.player.current_track)
            
            # Also re-sync library table column "Lyrics Synced" just in case it wasn't
            try:
                self.scan_music_library()
            except Exception as e:
                logger.error(f"Error scanning library after live edit save: {e}")
                
            self.update_karaoke_visuals(self.player.get_current_position())
            
        # Re-enable the button safely after layout transition completes
        QApplication.processEvents()
        self.btn_edit_lyrics.setEnabled(True)

    def toggle_karaoke_fullscreen(self):
        if not getattr(self, "is_fullscreen", False):
            # Enter Fullscreen
            self.is_fullscreen = True
            self.sidebar.hide()
            self.bottom_bar.hide()
            self.showFullScreen()
            self.btn_fullscreen.setText("🔲 Exit Fullscreen")
            
            # Show and start dancing Mozarts!
            self.mozart_left.show()
            self.mozart_right.show()
            self.mozart_left.start()
            self.mozart_right.start()
        else:
            # Exit Fullscreen
            self.is_fullscreen = False
            self.sidebar.show()
            self.bottom_bar.show()
            self.showNormal()
            self.btn_fullscreen.setText("🔲 Fullscreen")
            
            # Hide and stop Mozarts to save CPU
            self.mozart_left.hide()
            self.mozart_right.hide()
            self.mozart_left.stop()
            self.mozart_right.stop()
        
        # FIX: Force the Qt layout engine to recalculate and repaint the screen instantly
        QApplication.processEvents()
        self.centralWidget().update()
        
        # If returning to windowed mode, kick the main layout boundaries back into place
        if not self.is_fullscreen:
            # Safely flush layout engine without breaking OS maximized window states
            self.centralWidget().layout().invalidate()
            self.centralWidget().layout().activate()
            QApplication.processEvents()

    def dump_layout_debug(self):
        """Diagnostic probe to dump the exact dimensions and visibility of the layout tree."""
        logger.warning("==================================================")
        logger.warning("🔍 LAYOUT DEBUG PROBE INITIATED")
        logger.warning("==================================================")
        logger.warning(f"1. Main Window: Size={self.size().width()}x{self.size().height()} | Fullscreen={getattr(self, 'is_fullscreen', False)}")
        logger.warning(f"2. Central Widget: Size={self.centralWidget().size().width()}x{self.centralWidget().size().height()}")
        logger.warning(f"3. Content Stack: Size={self.content_stack.size().width()}x{self.content_stack.size().height()}")
        
        if hasattr(self, 'lyric_scroll'):
            logger.warning(f"4. Lyric Scroll Area: Size={self.lyric_scroll.size().width()}x{self.lyric_scroll.size().height()}")
            logger.warning(f"   -> Scroll Container internal SizeHint: {self.lyrics_container.minimumSizeHint().width()}x{self.lyrics_container.minimumSizeHint().height()}")
        
        bb_geom = self.bottom_bar.geometry()
        logger.warning(f"5. Bottom Player Bar:")
        logger.warning(f"   -> Geometry: X={bb_geom.x()}, Y={bb_geom.y()}, W={bb_geom.width()}, H={bb_geom.height()}")
        logger.warning(f"   -> isVisible(): {self.bottom_bar.isVisible()}")
        logger.warning(f"   -> isHidden(): {self.bottom_bar.isHidden()}")
        
        # Calculate if the bottom bar is physically off-screen
        window_height = self.size().height()
        bb_bottom_edge = bb_geom.y() + bb_geom.height()
        if bb_bottom_edge > window_height:
            logger.warning(f"🚨 ALERT: Bottom bar is pushed {bb_bottom_edge - window_height} pixels OFF THE SCREEN!")
        elif not self.bottom_bar.isVisible():
            logger.warning("🚨 ALERT: Bottom bar is inside the screen bounds, but it is explicitly HIDDEN!")
        else:
            logger.warning("✅ Bottom bar appears normal in the layout math.")
            
        logger.warning("==================================================")

    def closeEvent(self, event):
        """Ensures background Demucs subprocesses are hard-killed on application exit."""
        if hasattr(self, 'active_karaoke_worker') and self.active_karaoke_worker:
            logger.info("Application closing: Terminating active background karaoke worker.")
            # Trigger the new teardown method defined in the markdown plan
            if hasattr(self.active_karaoke_worker, 'terminate_process'):
                self.active_karaoke_worker.terminate_process()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        # AI Diagnostic Dump Hook (Secured: Dev Mode Only)
        if IS_DEV_MODE and event.key() == Qt.Key.Key_D and event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            try:
                dump = self.player.dump_debug_state()
                with open("agent_debug.log", "w") as f:
                    f.write(dump)
                QMessageBox.information(self, "Diagnostics", "AI Diagnostic State dumped to agent_debug.log")
            except Exception as e:
                logger.error(f"Diagnostic dump failed: {e}")
            return
            
        # Allow pressing 'Escape' to cleanly exit fullscreen
        if event.key() == Qt.Key.Key_Escape and getattr(self, "is_fullscreen", False):
            self.toggle_karaoke_fullscreen()
        # Fire Layout Debug manually on F12
        elif event.key() == Qt.Key.Key_F12:
            self.dump_layout_debug()
        # Delete key hook to send selected track in all tracks tab to trash
        elif event.key() == Qt.Key.Key_Delete:
            if hasattr(self, 'library_tabs') and self.library_tabs.currentIndex() == 2:
                selected_ranges = self.table_songs.selectedRanges()
                if selected_ranges:
                    self.delete_selected_track()
                    return
        # OS Media Key hooks for laptop playback buttons
        # Windows keyboards send Key_MediaTogglePlayPause (not Key_MediaPlay/Key_MediaPause)
        elif event.key() in (Qt.Key.Key_MediaPlay, Qt.Key.Key_MediaPause, Qt.Key.Key_MediaTogglePlayPause):
            self.toggle_playback()
        elif event.key() == Qt.Key.Key_MediaNext:
            self.play_next_track()
        elif event.key() == Qt.Key.Key_MediaPrevious:
            self.play_previous_track()
        elif event.key() == Qt.Key.Key_MediaStop:
            if hasattr(self, 'audio_player') and self.audio_player:
                self.audio_player.stop()
        super().keyPressEvent(event)

    def changeEvent(self, event):
        if event.type() == event.Type.WindowStateChange:
            if self.isMinimized():
                # Trigger mini player safely on next event loop tick
                QTimer.singleShot(0, self.show_mini_player)
        super().changeEvent(event)

    # ==========================
    # PAGE 4: CONFIGURATION & SETTINGS VIEW
    # ==========================
    def setup_settings_page(self):
        # 1. Wrap the entire settings page in a Scroll Area to prevent vertical crushing
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setStyleSheet("background-color: transparent; border: none;")
        
        page = QWidget()
        page.setObjectName("SettingsInnerWidget")
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 20)
        layout.setSpacing(15)
        page.setLayout(layout)
        
        # Title
        title = QLabel("MozZzart Settings Panel")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: white; margin-bottom: 20px;")
        layout.addWidget(title)
        
        # Path Selector Box
        path_box = QFrame()
        path_box.setStyleSheet("background-color: #121212; border: 1px solid #1E1E1E; border-radius: 8px; padding: 15px; margin-bottom: 15px;")
        path_layout = QVBoxLayout()
        path_box.setLayout(path_layout)
        
        path_layout.addWidget(QLabel("MUSIC DIRECTORY ROOT"))
        
        path_row = QHBoxLayout()
        self.txt_music_path = QLineEdit(self.config["music_root_dir"])
        self.txt_music_path.setReadOnly(True)
        path_row.addWidget(self.txt_music_path, stretch=1)
        
        btn_browse = QPushButton("📁 Browse")
        btn_browse.setStyleSheet("background-color: #1A1A1A; color: white; padding: 8px 15px; border-radius: 4px;")
        btn_browse.clicked.connect(self.browse_music_directory)
        path_row.addWidget(btn_browse)
        
        path_layout.addLayout(path_row)
        layout.addWidget(path_box)
        
        # Karaoke engine parameters
        engine_box = QFrame()
        engine_box.setStyleSheet("background-color: #121212; border: 1px solid #1E1E1E; border-radius: 8px; padding: 15px; margin-bottom: 15px;")
        engine_layout = QVBoxLayout()
        engine_box.setLayout(engine_layout)
        
        engine_layout.addWidget(QLabel("KARAOKE GENERATOR PIPELINE"))
        
        # Red warning banner so the user never accidentally enables mock mode
        mock_warning = QLabel("⚠  DEV TESTING ONLY — Toggle below disables real AI transcription")
        mock_warning.setStyleSheet("""
            color: #FF5555;
            font-size: 11px;
            font-weight: bold;
            background-color: #2A0000;
            border: 1px solid #FF5555;
            border-radius: 4px;
            padding: 5px 8px;
            margin-bottom: 4px;
        """)
        mock_warning.setWordWrap(True)
        engine_layout.addWidget(mock_warning)
        
        self.toggle_mock_ml = QPushButton()
        self.update_mock_toggle_btn_text()
        self.toggle_mock_ml.clicked.connect(self.on_mock_toggle_clicked)
        engine_layout.addWidget(self.toggle_mock_ml)
        
        desc_ml = QLabel("When Mock Mode is OFF (default), MozZzart runs the real Demucs + Whisper AI pipeline to generate accurate word-level karaoke lyrics. Enabling Mock Mode replaces this with fast dummy lyrics for developer testing only — real transcription will NOT run.")
        desc_ml.setWordWrap(True)
        desc_ml.setStyleSheet("color: #888888; font-size: 11px; margin-top: 5px;")
        engine_layout.addWidget(desc_ml)
        
        # Language Override Selector
        lang_row = QHBoxLayout()
        lang_lbl = QLabel("Force Language (Override):")
        lang_lbl.setStyleSheet("font-weight: bold; color: #B3B3B3; font-size: 12px; margin-top: 10px;")
        lang_row.addWidget(lang_lbl)
        
        self.combo_whisper_lang = NoScrollComboBox()
        self.combo_whisper_lang.setObjectName("WhisperLangCombo")
        self._whisper_lang_map = [("Auto-Detect (Default)", None)]
        for lang in WHISPER_LANGUAGES:
            self._whisper_lang_map.append((lang, lang.lower()))
        for display_name, _code in self._whisper_lang_map:
            self.combo_whisper_lang.addItem(display_name)
        
        # Restore saved selection
        saved_lang = self.config.get("whisper_language", None)
        for i, (_name, code) in enumerate(self._whisper_lang_map):
            if code == saved_lang:
                self.combo_whisper_lang.setCurrentIndex(i)
                break
        
        self.combo_whisper_lang.setStyleSheet("""
            QComboBox {
                background-color: #1C1C1C;
                border: 1px solid #2C2C2C;
                border-radius: 6px;
                padding: 6px 12px;
                color: white;
                min-width: 180px;
                font-size: 12px;
                font-weight: bold;
            }
            QComboBox:hover {
                border: 1px solid #F0C419;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: #1C1C1C;
                color: white;
                selection-background-color: #2D7D46;
                selection-color: white;
                border: 1px solid #2C2C2C;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        self.combo_whisper_lang.currentIndexChanged.connect(self.on_whisper_lang_changed)
        lang_row.addWidget(self.combo_whisper_lang)
        lang_row.addStretch()
        engine_layout.addLayout(lang_row)
        
        lang_desc = QLabel("Override the Whisper large-v3 auto-detection to force a specific language. Use this if auto-detect hallucinates or misidentifies your music's language.")
        lang_desc.setWordWrap(True)
        lang_desc.setStyleSheet("color: #888888; font-size: 11px; margin-top: 2px;")
        engine_layout.addWidget(lang_desc)
        
        # Save Instrumental Tracks checkbox
        instr_row = QHBoxLayout()
        self.chk_download_instruments = QCheckBox("💾 Save Instrumental Tracks (True Karaoke Mode)")
        self.chk_download_instruments.setStyleSheet("""
            QCheckBox {
                color: #B3B3B3;
                font-size: 12px;
                font-weight: bold;
                spacing: 8px;
                margin-top: 10px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #2C2C2C;
                border-radius: 4px;
                background-color: #1C1C1C;
            }
            QCheckBox::indicator:checked {
                background-color: #2D7D46;
                border: 2px solid #2D7D46;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #F0C419;
            }
        """)
        self.chk_download_instruments.setChecked(self.config.get("download_instruments", True))
        self.chk_download_instruments.stateChanged.connect(self.on_download_instruments_changed)
        instr_row.addWidget(self.chk_download_instruments)
        instr_row.addStretch()
        engine_layout.addLayout(instr_row)
        
        instr_desc = QLabel("When enabled, Demucs will save the isolated instrumental (no_vocals.wav) alongside each song for True Karaoke Mode playback.")
        instr_desc.setWordWrap(True)
        instr_desc.setStyleSheet("color: #888888; font-size: 11px; margin-top: 2px;")
        engine_layout.addWidget(instr_desc)
        
        # Reverb Intensity Slider
        reverb_row = QHBoxLayout()
        reverb_lbl = QLabel("Mic Reverb Intensity:")
        reverb_lbl.setStyleSheet("font-weight: bold; color: #B3B3B3; font-size: 12px; margin-top: 10px;")
        reverb_row.addWidget(reverb_lbl)
        
        self.slider_reverb = QSlider(Qt.Orientation.Horizontal)
        self.slider_reverb.setRange(0, 100)
        self.slider_reverb.setValue(int(self.config.get("reverb_intensity", 0.35) * 100))
        self.slider_reverb.setFixedWidth(200)
        self.slider_reverb.setStyleSheet("""
            QSlider::groove:horizontal { height: 6px; background: #222222; border-radius: 3px; }
            QSlider::sub-page:horizontal { background: #2D7D46; border-radius: 3px; }
            QSlider::handle:horizontal { background: #F0C419; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px; }
        """)
        reverb_row.addWidget(self.slider_reverb)
        
        self.lbl_reverb_val = QLabel(f"{int(self.config.get('reverb_intensity', 0.35) * 100)}%")
        self.lbl_reverb_val.setStyleSheet("color: #F0C419; font-weight: bold; font-size: 12px; min-width: 40px;")
        reverb_row.addWidget(self.lbl_reverb_val)
        reverb_row.addStretch()
        engine_layout.addLayout(reverb_row)
        
        self.slider_reverb.valueChanged.connect(self.on_reverb_slider_changed)
        
        reverb_desc = QLabel("Controls the echo/reverb effect applied to the live microphone during Full Karaoke Mode. 0% = dry signal, 100% = maximum echo.")
        reverb_desc.setWordWrap(True)
        reverb_desc.setStyleSheet("color: #888888; font-size: 11px; margin-top: 2px;")
        engine_layout.addWidget(reverb_desc)
        
        layout.addWidget(engine_box)
        
        # yt-dlp binary updater
        update_box = QFrame()
        update_box.setStyleSheet("background-color: #121212; border: 1px solid #1E1E1E; border-radius: 8px; padding: 15px;")
        update_layout = QHBoxLayout()
        update_box.setLayout(update_layout)
        
        lbl_update = QLabel("Scraper Engine updates (yt-dlp):")
        lbl_update.setStyleSheet("font-weight: bold;")
        update_layout.addWidget(lbl_update)
        
        update_layout.addStretch()
        
        self.btn_update_ytdl = QPushButton("🔄 Check for Scraper Updates")
        self.btn_update_ytdl.setStyleSheet("background-color: #1A1A1A; color: #1DB954; font-weight: bold; padding: 8px 15px; border-radius: 4px;")
        self.btn_update_ytdl.clicked.connect(self.check_and_update_ytdlp_binary)
        update_layout.addWidget(self.btn_update_ytdl)
        
        layout.addWidget(update_box)
        
        # Web Remote / TV Streaming Toggle
        web_box = QFrame()
        web_box.setStyleSheet("background-color: #121212; border: 1px solid #1E1E1E; border-radius: 8px; padding: 15px; margin-top: 15px;")
        web_layout = QVBoxLayout()
        web_box.setLayout(web_layout)
        
        web_layout.addWidget(QLabel("WEB REMOTE / TV STREAMING"))
        
        web_row = QHBoxLayout()
        self.chk_web_remote = QCheckBox("📡 Enable Web Remote (TV/Phone Streaming on port 8080)")
        self.chk_web_remote.setStyleSheet("""
            QCheckBox {
                color: #B3B3B3;
                font-size: 12px;
                font-weight: bold;
                spacing: 8px;
                margin-top: 5px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #2C2C2C;
                border-radius: 4px;
                background-color: #1C1C1C;
            }
            QCheckBox::indicator:checked {
                background-color: #2D7D46;
                border: 2px solid #2D7D46;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #F0C419;
            }
        """)
        self.chk_web_remote.setChecked(self.config.get("web_remote_enabled", False))
        self.chk_web_remote.stateChanged.connect(self.manage_web_remote_server)
        web_row.addWidget(self.chk_web_remote)
        web_row.addStretch()
        web_layout.addLayout(web_row)
        
        self.lbl_web_remote_status = QLabel("")
        # FIX: Rely on config state, not thread .isRunning() due to boot race conditions
        if self.config.get("web_remote_enabled", False) and HAS_WEB_REMOTE:
            self.lbl_web_remote_status.setText(f"✅ Active — http://{get_local_ip() if HAS_WEB_REMOTE else '?'}:8080")
            self.lbl_web_remote_status.setStyleSheet("color: #1DB954; font-size: 11px; font-weight: bold; margin-top: 4px;")
        else:
            self.lbl_web_remote_status.setText("⏸ Disabled")
            self.lbl_web_remote_status.setStyleSheet("color: #888888; font-size: 11px; font-weight: bold; margin-top: 4px;")
        web_layout.addWidget(self.lbl_web_remote_status)
        
        web_desc = QLabel("Starts a local Flask server on your Wi-Fi network. Open the URL on your Smart TV or phone browser to stream audio and control playback remotely. Requires app restart to take effect.")
        web_desc.setWordWrap(True)
        web_desc.setStyleSheet("color: #888888; font-size: 11px; margin-top: 2px;")
        web_layout.addWidget(web_desc)
        
        layout.addWidget(web_box)
        
        # GIF Playlist Manager
        gif_box = QFrame()
        gif_box.setStyleSheet("background-color: rgba(18, 18, 18, 200); border: 1px solid #1E1E1E; border-radius: 8px; padding: 15px; margin-top: 15px;")
        gif_layout = QVBoxLayout()
        gif_box.setLayout(gif_layout)
        
        gif_layout.addWidget(QLabel("KARAOKE VISUALS (GIF PLAYLIST)"))
        
        self.gif_list_widget = DropListWidget()
        self.gif_list_widget.setFixedHeight(100)
        self.gif_list_widget.setStyleSheet("background-color: #1C1C1C; border-radius: 4px; padding: 5px; color: #B3B3B3;")
        self.gif_list_widget.addItems(self.config["gif_playlist"])
        self.gif_list_widget.files_dropped.connect(self.handle_dropped_gifs)
        gif_layout.addWidget(self.gif_list_widget)
        
        gif_btns = QHBoxLayout()
        btn_add_gif = QPushButton("➕ Add GIF (or Drag & Drop)")
        btn_add_gif.setStyleSheet("background-color: #2D7D46; color: white; padding: 8px; border-radius: 4px; font-weight: bold;")
        btn_add_gif.clicked.connect(self.add_gif_to_playlist)
        gif_btns.addWidget(btn_add_gif)
        
        btn_del_gif = QPushButton("🗑 Remove Selected")
        btn_del_gif.setStyleSheet("background-color: #1A1A1A; color: #FF5555; padding: 8px; border-radius: 4px; font-weight: bold;")
        btn_del_gif.clicked.connect(self.remove_selected_gif)
        gif_btns.addWidget(btn_del_gif)
        
        gif_layout.addLayout(gif_btns)
        
        gif_desc = QLabel("These GIFs will loop sequentially every time a new song loads in Karaoke mode.")
        gif_desc.setStyleSheet("color: #888888; font-size: 11px;")
        gif_layout.addWidget(gif_desc)
        
        layout.addWidget(gif_box)

        # AI Discovery & Playback Analytics Settings
        ai_box = QFrame()
        ai_box.setStyleSheet("background-color: #121212; border: 1px solid #1E1E1E; border-radius: 8px; padding: 15px; margin-top: 15px;")
        ai_layout = QVBoxLayout()
        ai_box.setLayout(ai_layout)
        
        ai_layout.addWidget(QLabel("🧠 AI DISCOVERY ENGINE (BYOK)"))
        
        # Gemini API Key Field Row
        key_row = QHBoxLayout()
        key_lbl = QLabel("Gemini API Key:")
        key_lbl.setStyleSheet("font-weight: bold; color: #B3B3B3; font-size: 12px;")
        key_row.addWidget(key_lbl)
        
        self.txt_gemini_key = QLineEdit(self.config.get("gemini_api_key", ""))
        self.txt_gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_gemini_key.setStyleSheet("background-color: #1C1C1C; border-radius: 6px; padding: 8px 12px; color: white;")
        self.txt_gemini_key.editingFinished.connect(self.on_gemini_key_changed)
        key_row.addWidget(self.txt_gemini_key, stretch=1)
        
        ai_layout.addLayout(key_row)
        
        ai_desc = QLabel("Enter your personal Google Gemini API Key. The 'Discover Weekly' recommender uses the free Gemini 3.5 Flash API to customize your feed. Your key is stored locally in config.json.")
        ai_desc.setWordWrap(True)
        ai_desc.setStyleSheet("color: #888888; font-size: 11px; margin-top: 2px; margin-bottom: 8px;")
        ai_layout.addWidget(ai_desc)
        
        # Reset AI Discovery History Button (Amendment 3)
        self.btn_reset_ai = QPushButton("Reset AI Discovery History")
        self.btn_reset_ai.setStyleSheet("""
            QPushButton {
                background-color: #1A1A1A;
                color: #FF5555;
                border: 1px solid #FF5555;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #3A0000;
                color: #FF8888;
            }
        """)
        self.btn_reset_ai.clicked.connect(self.reset_ai_discovery_history)
        
        reset_row = QHBoxLayout()
        reset_row.addWidget(self.btn_reset_ai)
        reset_row.addStretch()
        ai_layout.addLayout(reset_row)
        
        layout.addWidget(ai_box)
        layout.addStretch()
        
        # 2. Mount the page into the scroll area, then add the scroll area to the stack
        self.settings_scroll.setWidget(page)
        self.content_stack.addWidget(self.settings_scroll)

    def browse_music_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Music Root Folder", self.config["music_root_dir"])
        if dir_path:
            self.config["music_root_dir"] = dir_path
            self.txt_music_path.setText(dir_path)
            config.save_config(self.config)
            self.active_playlist = "Library"
            self.scan_music_library()
            logger.info(f"Music root directory relocated to: {dir_path}")

    def add_gif_to_playlist(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select GIFs", "", "GIF Images (*.gif)")
        if files:
            for f in files:
                if f not in self.config["gif_playlist"]:
                    self.config["gif_playlist"].append(f)
                    self.gif_list_widget.addItem(f)
            config.save_config(self.config)

    def handle_dropped_gifs(self, file_paths):
        for f in file_paths:
            if f not in self.config["gif_playlist"]:
                self.config["gif_playlist"].append(f)
                self.gif_list_widget.addItem(f)
        config.save_config(self.config)
        
    def remove_selected_gif(self):
        item = self.gif_list_widget.currentItem()
        if item:
            val = item.text()
            if val == "mozart dance.gif":
                QMessageBox.warning(self, "Action Denied", "The default Mozart GIF is protected and cannot be deleted.")
                return
            self.config["gif_playlist"].remove(val)
            self.gif_list_widget.takeItem(self.gif_list_widget.row(item))
            config.save_config(self.config)

    def _trigger_gif_cycle(self):
        """Decouples the GIF swap from the QMovie frameChanged signal to prevent crashes."""
        QTimer.singleShot(0, self.cycle_next_gif)

    def cycle_next_gif(self):
        """Advances to the next GIF in the playlist after the current animation loop finishes."""
        playlist = self.config.get("gif_playlist", ["mozart dance.gif"])
        if not playlist or len(playlist) <= 1:
            return # Do not cycle if there is only 1 GIF
            
        self.current_gif_index = (self.current_gif_index + 1) % len(playlist)
        current_gif_path = playlist[self.current_gif_index]
        
        if hasattr(self, 'mozart_left'):
            self.mozart_left.update_gif(current_gif_path)
            self.mozart_right.update_gif(current_gif_path)
            
        # Push the new GIF path to the Web Remote instantly so the TV updates mid-song
        self.broadcast_state_to_web()

    def update_mock_toggle_btn_text(self):
        active = self.config["use_mock_karaoke"]
        if active:
            text = "⚠  Mock Mode: ON — Real AI transcription DISABLED (dummy lyrics only)"
            style = "text-align: left; padding: 10px; font-weight: bold; border-radius: 4px; background-color: #3A0000; color: #FF5555; border: 1px solid #FF5555;"
        else:
            text = "✅ Mock Mode: OFF — Real Demucs + Whisper AI pipeline active"
            style = "text-align: left; padding: 10px; font-weight: bold; border-radius: 4px; background-color: #001A00; color: #2D7D46; border: 1px solid #2D7D46;"
        self.toggle_mock_ml.setText(text)
        self.toggle_mock_ml.setStyleSheet(style)
    def on_whisper_lang_changed(self, index):
        """Saves the selected Whisper language override to config."""
        _name, code = self._whisper_lang_map[index]
        self.config["whisper_language"] = code
        config.save_config(self.config)
        logger.info(f"Whisper language override set to: {_name} (code={code})")

    def on_download_instruments_changed(self, state):
        """Saves the instrumental download preference to config."""
        self.config["download_instruments"] = (state == 2)  # Qt.CheckState.Checked == 2
        config.save_config(self.config)
        logger.info(f"Download instruments set to: {self.config['download_instruments']}")

    def on_reverb_slider_changed(self, value):
        """Updates reverb intensity in config and live mic worker."""
        intensity = value / 100.0
        self.config["reverb_intensity"] = round(intensity, 2)
        config.save_config(self.config)
        self.lbl_reverb_val.setText(f"{value}%")
        # Update live mic worker if running
        if self.mic_worker and self.mic_worker.running:
            self.mic_worker.set_reverb_intensity(intensity)
        logger.info(f"Reverb intensity set to: {intensity:.2f}")

    def on_mock_toggle_clicked(self):
        self.config["use_mock_karaoke"] = not self.config["use_mock_karaoke"]
        config.save_config(self.config)
        self.update_mock_toggle_btn_text()
        logger.info(f"Mock mode toggled to: {self.config['use_mock_karaoke']}")

    def on_gemini_key_changed(self):
        """Saves the Gemini API key to config."""
        key = self.txt_gemini_key.text().strip()
        self.config["gemini_api_key"] = key
        config.save_config(self.config)
        logger.info("Gemini API Key updated in config.")

    def reset_ai_discovery_history(self):
        """Clears all logged recommendation history in the database."""
        try:
            import analytics
            success = analytics.clear_recommendation_history()
            if success:
                QMessageBox.information(
                    self,
                    "AI Reset Successful",
                    "Your AI Discovery History has been successfully cleared! The recommender will start completely fresh."
                )
            else:
                QMessageBox.warning(
                    self,
                    "AI Reset Failed",
                    "Could not clear recommendation history. Check app logs for details."
                )
        except Exception as e:
            logger.error(f"Error resetting AI discovery history: {e}")
            QMessageBox.critical(self, "Error", f"An error occurred while resetting history: {str(e)}")

    def check_and_update_ytdlp_binary(self):
        self.btn_update_ytdl.setEnabled(False)
        self.btn_update_ytdl.setText("Updating...")
        
        class UpdateWorker(QThread):
            done = pyqtSignal(bool)
            def run(self):
                success = utils.update_ytdlp()
                self.done.emit(success)
                
        self.update_worker = UpdateWorker()
        def on_done(success):
            self.btn_update_ytdl.setEnabled(True)
            self.btn_update_ytdl.setText("🔄 Check for Scraper Updates")
            if success:
                QMessageBox.information(self, "Success", "yt-dlp has been updated to the latest version successfully!")
            else:
                QMessageBox.warning(self, "Failed", "Failed to update yt-dlp. Please check your internet connection and try again.")
        self.update_worker.done.connect(on_done)
        self.update_worker.start()

    # ==========================
    # BACKGROUND AUDIO WORKERS & TIMERS
    # ==========================
    def update_playback_polling(self):
        """Invoked every 100ms. Refreshes timeline sliders and word highlights."""
        # Polling is also required if the player is active but paused during stream-rebuild transitions
        # to ensure that deferred seeks and pauses are applied.
        if not self.player.is_playing() and not getattr(self.player, '_pending_seek', None) and not getattr(self.player, '_pending_pause', False) and not getattr(self.player, '_vocal_pending_seek', None):
            return
        self.player.update_polling()

    def on_player_state_changed(self, state):
        """Toggles play buttons based on active mixer states."""
        if state == "playing":
            self.btn_play_pause.setIcon(qta.icon('fa5s.pause', color='#F0C419'))
            self.mini_player.update_play_state(True)
            if hasattr(self, 'btn_edit_lyrics'):
                self.btn_edit_lyrics.setEnabled(False)
            # Auto-save and exit if user hits play while editing
            if getattr(self, "is_editing_lyrics", False):
                self.toggle_lyrics_edit_mode() 
            # Resume Mozarts if in fullscreen
            if getattr(self, "is_fullscreen", False):
                if hasattr(self, 'mozart_left'): self.mozart_left.start()
                if hasattr(self, 'mozart_right'): self.mozart_right.start()
        else:
            self.btn_play_pause.setIcon(qta.icon('fa5s.play', color='#F0C419'))
            self.mini_player.update_play_state(False)
            if hasattr(self, 'btn_edit_lyrics'):
                self.btn_edit_lyrics.setEnabled(not getattr(self, 'karaoke_mode_active', False))
            # Freeze/pause Mozarts if in fullscreen
            if getattr(self, "is_fullscreen", False):
                if hasattr(self, 'mozart_left'): self.mozart_left.stop()
                if hasattr(self, 'mozart_right'): self.mozart_right.stop()
            if state == "stopped":
                self.pulse_currently_playing_row(0)

    def on_duration_resolved(self, duration):
        """Sets slider range limits."""
        self.timeline_slider.setRange(0, int(duration))
        self.lbl_time_max.setText(self.format_time_string(duration))
        
        try:
            self.player.position_updated.disconnect(self.on_position_updated)
        except TypeError:
            pass
        self.player.position_updated.connect(self.on_position_updated)

    def on_position_updated(self, position):
        """Updates slider values and triggers word timing calculations."""
        if not self.timeline_slider.isSliderDown():
            self.timeline_slider.setValue(int(position))
        self.lbl_time_curr.setText(self.format_time_string(position))
        
        # Refresh lyrics highlighted words
        self.update_karaoke_visuals(position)
        
        # Highlight and pulse the currently playing song in the library table
        self.pulse_currently_playing_row(position)
        
        # LIVE CLOCK SYNC: Send continuous time updates to the web server fast-path
        if hasattr(self, 'web_remote_worker') and self.web_remote_worker and self.web_remote_worker.isRunning():
            self.web_remote_worker.update_clock(position)

    def pulse_currently_playing_row(self, position):
        """Highlights the currently playing song row in table_songs with a subtle pulse effect synced to a simulated 120 BPM beat."""
        if not hasattr(self, 'table_songs'):
            return
            
        import math
        from PyQt6.QtWidgets import QLabel
        
        current_track = self.player.current_track
        
        # Calculate pulse intensity (0.0 to 1.0) synced to 120 BPM (2 beats/sec)
        bps = 120.0 / 60.0
        angle = 2.0 * math.pi * bps * position
        pulse = 0.5 + 0.5 * math.cos(angle)
        
        # Interpolate between pure white (255, 255, 255) and bright gold (240, 196, 25)
        r = int(255 - (255 - 240) * pulse)
        g = int(255 - (255 - 196) * pulse)
        b = int(255 - (255 - 25) * pulse)
        pulse_hex = f"#{r:02x}{g:02x}{b:02x}"
        
        for row in range(self.table_songs.rowCount()):
            fav_item = self.table_songs.item(row, 0)
            if not fav_item:
                continue
            path = fav_item.data(Qt.ItemDataRole.UserRole)
            title_label = self.table_songs.cellWidget(row, 1)
            if not isinstance(title_label, QLabel):
                continue
                
            if current_track and path == current_track:
                # Active playing track: apply pulse color and bold font
                title_label.setStyleSheet(f"color: {pulse_hex}; font-weight: bold; background-color: transparent;")
            else:
                # Inactive tracks: reset to parent inheritance (transparent background, no explicit color rule)
                title_label.setStyleSheet("background-color: transparent;")

    def on_timeline_seek(self, value):
        self.player.seek(float(value))

    def on_player_seeked(self, seek_value):
        """Seek Synchronization Guard: Instantly snaps highlights & centering on seek action."""
        logger.info(f"Seek guard caught reset timeline target: {seek_value:.2f}s")
        # 1. Update sliders instantly
        self.timeline_slider.setValue(int(seek_value))
        self.lbl_time_curr.setText(self.format_time_string(seek_value))
        # 2. Re-trigger lyric visual split updates instantly bypassing the QTimer tick!
        self.update_karaoke_visuals(seek_value)

    def on_volume_changed(self, value):
        self.player.set_volume(value)
        self.config["volume"] = value
        config.save_config(self.config)
        if value == 0:
            self.lbl_vol_icon.setText("🔇")
        elif value < 40:
            self.lbl_vol_icon.setText("🔈")
        else:
            self.lbl_vol_icon.setText("🔊")

    def update_volume_controls(self):
        self.player.set_volume(self.config["volume"])

    def format_time_string(self, time_seconds):
        mins, secs = divmod(int(time_seconds), 60)
        return f"{mins}:{secs:02d}"

    def load_and_play_track(self, song, auto_karaoke=False):
        """Loads selected file paths, mounts them into visual nodes, and starts audio."""
        logger.info(f"Loading track into player: {song['name']}")
        
        # Safety: deactivate Full Karaoke Mode before loading a new track
        # Keep fullscreen active if we are continuously chaining into another karaoke track
        keep_fs = auto_karaoke and song.get("has_karaoke", False)
        if getattr(self, 'karaoke_mode_active', False):
            self._deactivate_karaoke_mode(keep_fullscreen=keep_fs)
        else:
            self.player.clear_karaoke_channels()
        
        success = self.player.load_track(song["path"])
        if success:
            self.lbl_song_title.setText(song["name"])
            
            if hasattr(self, 'mini_player'):
                self.mini_player.update_track_info(song["name"], f"Local {song['type']} File")
            
            # Preload associated lyrics JSON
            self.load_karaoke_lyrics_data(song["path"])
            
            # Start Playback
            self.player.play()
            
            # Calculate Next Song for Preview UI
            next_song_name = "End of Playlist"
            if self.scanned_songs:
                try:
                    curr_idx = next(i for i, s in enumerate(self.scanned_songs) if s["path"] == song["path"])
                    if self.config.get("shuffle", False):
                        next_song_name = "Random Track (Shuffle ON)"
                    else:
                        next_idx = (curr_idx + 1) % len(self.scanned_songs)
                        next_song_name = self.scanned_songs[next_idx]["name"]
                except StopIteration:
                    pass
            
            if hasattr(self, 'lbl_next_up'):
                self.lbl_next_up.setText(f"Next Up: {next_song_name}")
            
            if song["has_karaoke"]:
                self.show_page(2)
                # AUTOMATIC CONTINUOUS KARAOKE TRIGGER
                if auto_karaoke:
                    QTimer.singleShot(100, self.toggle_full_karaoke_mode)
            else:
                # If the next song lacks karaoke, drop them back to the library view gracefully
                if auto_karaoke:
                    self.show_page(0)
        else:
            QMessageBox.warning(self, "Load Error", f"Could not load audio file: {song['filename']}")
        
        self.broadcast_state_to_web()

    def toggle_playback(self):
        """Toggles between play, pause, or starts first track if library is populated."""
        if self.player.current_track:
            if self.player.is_playing():
                self.player.pause()
                # Pause mic worker to prevent feedback loops
                if self.karaoke_mode_active and self.mic_worker:
                    self.mic_worker.pause()
            else:
                self.player.resume()
                # Resume mic worker
                if self.karaoke_mode_active and self.mic_worker:
                    self.mic_worker.resume()
        else:
            if self.scanned_songs:
                self.load_and_play_track(self.scanned_songs[0])
        
        self.broadcast_state_to_web()

    def play_next_track(self):
        """Plays next sequential song from library list."""
        if not getattr(self, 'scanned_songs', []):
            return
            
        # Capture the karaoke intent before we change tracks
        was_karaoke = getattr(self, 'karaoke_mode_active', False)
        
        next_idx = 0
        if self.player.current_track:
            # Fix: Resolve original track path if in karaoke mode to prevent index 0 resets
            curr_path = self.original_track_path if was_karaoke else self.player.current_track
            for idx, s in enumerate(self.scanned_songs):
                if s["path"] == curr_path:
                    if self.config.get("shuffle", False):
                        import random
                        next_idx = random.randint(0, len(self.scanned_songs) - 1)
                    else:
                        next_idx = (idx + 1) % len(self.scanned_songs)
                    break
                    
        self.load_and_play_track(self.scanned_songs[next_idx], auto_karaoke=was_karaoke)

    def play_previous_track(self):
        """Plays previous track."""
        if not getattr(self, 'scanned_songs', []):
            return
            
        was_karaoke = getattr(self, 'karaoke_mode_active', False)
        
        prev_idx = 0
        if self.player.current_track:
            # Fix: Resolve original track path if in karaoke mode to prevent index 0 resets
            curr_path = self.original_track_path if was_karaoke else self.player.current_track
            for idx, s in enumerate(self.scanned_songs):
                if s["path"] == curr_path:
                    prev_idx = (idx - 1) % len(self.scanned_songs)
                    break
                    
        self.load_and_play_track(self.scanned_songs[prev_idx], auto_karaoke=was_karaoke)

    def on_track_finished(self):
        """Fired naturally on song finish. Moves to next if repeat isn't toggled."""
        if self.config.get("repeat", False):
            was_karaoke = getattr(self, 'karaoke_mode_active', False)
            if was_karaoke:
                self._deactivate_karaoke_mode()
                self.player.play(0.0)
                QTimer.singleShot(100, self.toggle_full_karaoke_mode)
            else:
                self.player.play(0.0)
        else:
            self.play_next_track()

    def toggle_shuffle(self):
        self.config["shuffle"] = not self.config["shuffle"]
        config.save_config(self.config)
        self.btn_shuffle.setSlashed(not self.config["shuffle"])
        self.btn_shuffle.setProperty("active", "true" if self.config["shuffle"] else "false")
        self.btn_shuffle.style().unpolish(self.btn_shuffle)
        self.btn_shuffle.style().polish(self.btn_shuffle)

    def toggle_repeat(self):
        self.config["repeat"] = not self.config["repeat"]
        config.save_config(self.config)
        self.btn_repeat.setSlashed(not self.config["repeat"])
        self.btn_repeat.setProperty("active", "true" if self.config["repeat"] else "false")
        self.btn_repeat.style().unpolish(self.btn_repeat)
        self.btn_repeat.style().polish(self.btn_repeat)

    def set_run_on_startup(self, enable):
        """Registers/unregisters the application for auto-start on login (cross-platform)."""
        app_path = sys.executable if getattr(sys, 'frozen', False) else f'"{ sys.executable}" "{os.path.abspath(__file__)}"'
        
        if sys.platform == "win32":
            # Windows: Registry key
            try:
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                if enable:
                    winreg.SetValueEx(key, "MozZzartPlayer", 0, winreg.REG_SZ, app_path)
                else:
                    try:
                        winreg.DeleteValue(key, "MozZzartPlayer")
                    except FileNotFoundError:
                        pass
                winreg.CloseKey(key)
                logger.info(f"Startup {'enabled' if enable else 'disabled'} via Windows Registry.")
            except Exception as e:
                logger.error(f"Failed to set startup registry: {e}")
                
        elif sys.platform == "darwin":
            # macOS: LaunchAgents plist
            plist_path = os.path.expanduser("~/Library/LaunchAgents/com.mozzzart.player.plist")
            if enable:
                plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.mozzzart.player</string>
    <key>ProgramArguments</key><array><string>{app_path}</string></array>
    <key>RunAtLoad</key><true/>
</dict>
</plist>"""
                os.makedirs(os.path.dirname(plist_path), exist_ok=True)
                with open(plist_path, 'w') as f:
                    f.write(plist_content)
                logger.info("Startup enabled via macOS LaunchAgent plist.")
            else:
                if os.path.exists(plist_path):
                    os.remove(plist_path)
                logger.info("Startup disabled — macOS plist removed.")
                    
        elif sys.platform.startswith("linux"):
            # Linux: XDG autostart desktop entry
            desktop_path = os.path.expanduser("~/.config/autostart/mozzzart.desktop")
            if enable:
                desktop_content = f"""[Desktop Entry]
Type=Application
Name=MozZzart Player
Exec={app_path}
Hidden=false
X-GNOME-Autostart-enabled=true"""
                os.makedirs(os.path.dirname(desktop_path), exist_ok=True)
                with open(desktop_path, 'w') as f:
                    f.write(desktop_content)
                logger.info("Startup enabled via Linux .desktop autostart.")
            else:
                if os.path.exists(desktop_path):
                    os.remove(desktop_path)
                logger.info("Startup disabled — Linux .desktop removed.")

    # ==========================
    # BACKGROUND SEQUENTIAL KARAOKE PROCESSING
    # ==========================
    def show_mini_player(self):
        """Hides the main window and shows the floating mini player."""
        self.mini_player.sync_state()
        if self.isMinimized():
            self.showNormal()  # Invisible un-minimize so we can hide from taskbar cleanly
        self.hide()
        self.mini_player.show()
        self.mini_player.raise_()

    def restore_from_mini(self):
        """Restores the full main window from mini player mode."""
        self.mini_player.hide()
        self.show()
        self.raise_()

    def setup_sync_queue_page(self):
        """Stub - Sync Progress page removed. Badge states in library now reflect sync status."""
        pass

    def update_sync_queue_ui(self):
        """Refreshes the dynamic sync queue monitoring tab list."""
        if not hasattr(self, 'sync_queue_list'):
            return
            
        self.sync_queue_list.clear()
        
        # 1. Active Processing Item
        if self.active_karaoke_worker:
            name = self.active_karaoke_worker.song_name
            list_item = QListWidgetItem()
            self.sync_queue_list.addItem(list_item)
            
            row = QWidget()
            row_layout = QVBoxLayout()
            row_layout.setContentsMargins(10, 10, 10, 10)
            row_layout.setSpacing(0)
            row.setLayout(row_layout)
            
            bar = QProgressBar()
            bar.setObjectName("ActiveSyncProgressBar")
            bar.setStyleSheet("""
                QProgressBar {
                    background-color: #1A1A1A;
                    border: none;
                    border-radius: 6px;
                    text-align: center;
                    color: #FFFFFF;
                    font-weight: bold;
                    font-size: 11px;
                    height: 24px;
                }
                QProgressBar::chunk {
                    background-color: #F0C419;
                    border-radius: 6px;
                }
            """)
            bar.setFormat(f"Processing: {name} - 0%")
            bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bar.setValue(0)
            row_layout.addWidget(bar)
            
            list_item.setSizeHint(QSize(100, 44))
            self.sync_queue_list.setItemWidget(list_item, row)
            
        # 2. Queued Pending Items
        for song, silent, force, *_ in self.karaoke_queue:
            list_item = QListWidgetItem()
            self.sync_queue_list.addItem(list_item)
            
            row = QWidget()
            row_layout = QVBoxLayout()
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(6)
            row.setLayout(row_layout)
            
            title_lbl = QLabel(f"⏳ Queued: {song['name']}")
            title_lbl.setStyleSheet("font-weight: bold; color: #B3B3B3; font-size: 13px;")
            row_layout.addWidget(title_lbl)
            
            status_lbl = QLabel("Status: Pending in queue")
            status_lbl.setStyleSheet("color: #666666; font-size: 11px;")
            row_layout.addWidget(status_lbl)
            
            list_item.setSizeHint(QSize(100, 60))
            self.sync_queue_list.setItemWidget(list_item, row)
            
        # 3. Empty Queue Notice
        if not self.active_karaoke_worker and not self.karaoke_queue:
            list_item = QListWidgetItem()
            self.sync_queue_list.addItem(list_item)
            
            lbl = QLabel("☕ Sync Queue is Empty. All tracks are up to date!")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #888888; font-size: 13px; font-weight: bold; padding: 20px;")
            
            container = QWidget()
            c_lay = QVBoxLayout()
            c_lay.addWidget(lbl)
            container.setLayout(c_lay)
            list_item.setSizeHint(QSize(100, 60))
            self.sync_queue_list.setItemWidget(list_item, container)

    def update_sync_progress_ui(self, track_identifier, percentage):
        """Finds the correct row in the library table and updates the progress text."""
        target_column = 5
        
        for row in range(self.table_songs.rowCount()):
            title_widget = self.table_songs.cellWidget(row, 1)
            if isinstance(title_widget, QLabel):
                song_name = title_widget.text()
            else:
                item = self.table_songs.item(row, 1)
                song_name = item.text() if item else ""
                
            if song_name and song_name in track_identifier:
                widget = self.table_songs.cellWidget(row, target_column)
                if isinstance(widget, QPushButton):
                    widget.setText(f"Syncing... {percentage}%")
                break

    def toggle_full_karaoke_mode(self):
        """Toggles True Karaoke Mode: activates dual-channel mixer + microphone."""
        if not self.karaoke_mode_active:
            # --- Turning ON ---
            # FIX: Hot-reload JSON from disk to catch stems generated in the background
            if hasattr(self, 'player') and getattr(self.player, 'current_track', None):
                json_path = os.path.splitext(self.player.current_track)[0] + ".json"
                if os.path.isfile(json_path):
                    try:
                        with open(json_path, 'r', encoding='utf-8') as f:
                            self.lyrics_db = json.load(f)
                    except Exception:
                        pass
                        
            if not self.lyrics_db:
                QMessageBox.warning(self, "No Lyrics Loaded", "Cannot activate Full Karaoke Mode without a loaded karaoke track.")
                return
            
            instrumental_path = self.lyrics_db.get("instrumental_path")
            vocal_path = self.lyrics_db.get("vocal_path")
            
            if not instrumental_path or not os.path.isfile(instrumental_path):
                QMessageBox.warning(
                    self, "No Instrumental Track",
                    "This song does not have an instrumental track extracted yet.\n\n"
                    "Go to the Library and click the 🎸 button next to the song to extract it first."
                )
                return
            
            if not vocal_path or not os.path.isfile(vocal_path):
                QMessageBox.warning(
                    self, "No Vocal Guide Track",
                    "This song does not have a vocal guide stem extracted yet.\n\n"
                    "Go to the Library and click the 🎸 button to re-run extraction."
                )
                return
            
            # Save current position and original track for deactivation
            current_pos = self.player.get_current_position()
            self.original_track_path = self.player.current_track
            was_paused = getattr(self.player, 'is_paused', False) # Capture intent
            
            # Determine initial vocal guide volume from slider
            vocal_vol = self.slider_vocal_guide.value() / 100.0
            
            # Full device release before activating the channel-based engine.
            # This prevents the streaming music engine from holding the audio
            # device and conflicting with pygame.mixer.Channel playback.
            self.player.clear_karaoke_channels()
            
            # --- Visual Loading State ---
            self.btn_full_karaoke.setText("⏳ Syncing Streams...")
            self.btn_full_karaoke.setEnabled(False)
            QApplication.processEvents()
            
            # Start the dual-channel mixer using WAV fast-slicing
            logger.info(f"Full Karaoke Mode ON: dual-channel mixer at {current_pos:.2f}s")
            success = self.player.start_karaoke_mixer(
                instrumental_path=instrumental_path,
                vocal_path=vocal_path,
                start_time=current_pos,
                vocal_volume=vocal_vol,
                start_paused=was_paused
            )
            
            # Restore button text
            self.btn_full_karaoke.setText("🎤 Full Karaoke Mode")
            self.btn_full_karaoke.setEnabled(True)
            
            if not success:
                QMessageBox.warning(self, "Mixer Error", "Failed to start the dual-channel karaoke mixer.")
                return
            
            # Start microphone worker
            reverb_val = self.config.get("reverb_intensity", 0.35)
            self.mic_worker = MicrophoneWorker(reverb_intensity=reverb_val)
            self.mic_worker.error_signal.connect(self._on_mic_error)
            self.mic_worker.start()
            
            self.karaoke_mode_active = True
            if hasattr(self, 'btn_edit_lyrics'):
                self.btn_edit_lyrics.setEnabled(False)
            self.vocal_guide_widget.setVisible(True)
            self.btn_full_karaoke.setStyleSheet("background-color: #2D7D46; color: #F0C419; padding: 8px 16px; font-weight: bold; border-radius: 4px; border: 1px solid #F0C419;")
            logger.info("Full Karaoke Mode activated (dual-channel mixer + mic).")
            
            self.broadcast_state_to_web()
            # Safely flush layout engine without breaking OS maximized window states
            self.centralWidget().layout().invalidate()
            self.centralWidget().layout().activate()
            QApplication.processEvents()
        else:
            # --- Turning OFF ---
            self._deactivate_karaoke_mode()

    def _deactivate_karaoke_mode(self, keep_fullscreen=False):
        """
        Strictly ordered teardown sequence for Karaoke Mode → Regular Mode transition.

        Order matters:
          1. Capture timestamp FIRST (before any audio state changes).
          2. stop() — closes input_stream only, unblocking the read() loop in ~23ms.
          3. wait(2000) — block until run() finishes its finally block (pa.terminate).
          4. resume_regular_mode() — full Pygame streaming engine rebuild from timestamp.
          5. UI state cleanup.

        CRITICAL: Never call QThread.terminate() on the mic worker.
        terminate() hard-kills the thread mid-teardown, leaving PortAudio's C-library
        global state permanently corrupted. This causes a crash on the next toggle.
        """
        if not self.karaoke_mode_active:
            return

        # Step 1: Capture playback position BEFORE touching the audio device.
        resume_pos    = self.player.get_current_position()
        original_path = self.original_track_path
        was_paused    = getattr(self.player, 'is_paused', False) # Capture intent
        logger.info(f"Deactivating Karaoke Mode — resume position: {resume_pos:.3f}s")

        # Step 2: Signal the mic worker to stop.
        # stop() closes only input_stream (unblocks read() in one CHUNK ≈ 23ms).
        # pa.terminate() is handled exclusively by run()'s finally block.
        if self.mic_worker:
            self.mic_worker.stop()

            # Step 3: Wait for run() to finish its finally block.
            # One CHUNK = 23ms, so 2000ms is >> enough under any normal condition.
            # If it somehow times out, log it and proceed — but NEVER call terminate().
            finished = self.mic_worker.wait(2000)
            if not finished:
                logger.warning(
                    "MicrophoneWorker did not exit within 2s. "
                    "Proceeding without hard-kill to protect PortAudio state."
                )
            self.mic_worker = None

        # Step 4: Full Pygame streaming engine rebuild.
        # resume_regular_mode() clears karaoke channels then reloads the file from
        # disk and plays from the exact timestamp — no unpausing of stale state.
        if original_path and os.path.isfile(original_path):
            self.player.resume_regular_mode(original_path, resume_pos, start_paused=was_paused)
            # Re-apply the user's volume — the Hard Reboot resets pygame.mixer to 100%
            self.player.set_volume(self.volume_slider.value())
        else:
            self.player.clear_karaoke_channels()
            logger.warning("Karaoke deactivation: original track path missing.")

        # Step 5: Reset state and update UI
        self.original_track_path = None
        self.karaoke_mode_active = False
        if hasattr(self, 'btn_edit_lyrics') and hasattr(self, 'player'):
            self.btn_edit_lyrics.setEnabled(getattr(self.player, 'is_paused', False))
        self.vocal_guide_widget.setVisible(False)
        self.btn_full_karaoke.setStyleSheet(
            "background-color: #1A1A1A; color: #B3B3B3; padding: 8px 16px; font-weight: bold; border-radius: 4px;"
        )
        
        # Exit Fullscreen if active and we are not instructed to persist it
        if getattr(self, "is_fullscreen", False) and not keep_fullscreen:
            self.toggle_karaoke_fullscreen()
            
        logger.info("Full Karaoke Mode deactivated — streaming engine restored.")
        
        self.broadcast_state_to_web()
        # Safely flush layout engine without breaking OS maximized window states
        self.centralWidget().layout().invalidate()
        self.centralWidget().layout().activate()
        QApplication.processEvents()

    def on_guide_vocal_volume_changed(self, value):
        """Live-updates the vocal guide (Channel 1) volume during karaoke playback."""
        pct = f"{value}%"
        self.lbl_vocal_guide_pct.setText(pct)
        if self.karaoke_mode_active:
            self.player.set_vocal_guide_volume(value / 100.0)
        logger.debug(f"Guide vocal volume: {pct}")

    def _on_mic_error(self, error_msg):
        """Handles microphone worker errors."""
        logger.error(f"Microphone error: {error_msg}")
        QMessageBox.warning(self, "Microphone Error", f"Microphone could not be activated:\n{error_msg}")
        self._deactivate_karaoke_mode()

    def broadcast_state_to_web(self):
        """Pushes current playback state and Master Clock to the Flask web server securely."""
        if not (hasattr(self, 'web_remote_worker') and self.web_remote_worker and self.web_remote_worker.isRunning()):
            return
        
        try:
            is_playing = False
            current_time = 0.0
            if hasattr(self, 'player') and self.player is not None:
                is_playing = getattr(self.player, 'is_playing', lambda: False)()
                # Capture the Master Clock timestamp
                current_time = getattr(self.player, 'get_current_position', lambda: 0.0)()
            
            is_karaoke = getattr(self, 'karaoke_mode_active', False)
            title = self.lbl_song_title.text() if hasattr(self, 'lbl_song_title') else "MozZzart Player"
            
            # Defensively capture stream paths
            stream_path = None
            vocal_path = None
            if hasattr(self, 'player') and self.player is not None:
                stream_path = getattr(self.player, 'current_track', None)
                if is_karaoke:
                    vocal_path = getattr(self.player, '_last_vocal_path', None)
            
            # Package library safely
            library_data = []
            if hasattr(self, 'scanned_songs') and self.scanned_songs is not None:
                for i, s in enumerate(self.scanned_songs):
                    library_data.append({
                        "idx": i,
                        "name": s.get("name", "Unknown Track"),
                        "has_karaoke": s.get("has_karaoke", False)
                    })
            
            # Dynamic download progress collection
            dl_status = []
            if hasattr(self, 'download_progress_widgets') and self.download_progress_widgets:
                for idx, w in list(self.download_progress_widgets.items()):
                    try:
                        dl_status.append({
                            "title": w["title_label"].text(),
                            "status": w["status_label"].text(),
                            "progress": w["progress_bar"].value()
                        })
                    except RuntimeError:
                        # Catch widget cleanup deletion races gracefully
                        continue
            
            lyrics_data = getattr(self, 'lyrics_db', None)
            
            # Capture active GIF path
            playlist = self.config.get("gif_playlist", ["mozart dance.gif"])
            current_gif_path = playlist[self.current_gif_index] if playlist else "mozart dance.gif"
            
            # Pass current_time and current_gif_path into the worker
            self.web_remote_worker.update_state(
                stream_path, vocal_path, title, is_playing, is_karaoke, 
                library_data, lyrics_data, dl_status, current_time, current_gif_path
            )
        except Exception as e:
            logger.error(f"Race condition caught in broadcast_state_to_web: {e}")

    def _start_web_remote(self):
        """Initializes and starts the Flask Web Remote server."""
        if not HAS_WEB_REMOTE:
            return
        self.web_remote_worker = WebRemoteWorker(port=8080)
        self.web_remote_worker.command_received.connect(self._handle_web_command)
        self.web_remote_worker.start()
        ip = get_local_ip()
        logger.info(f"Web Remote / TV Streaming available at http://{ip}:8080")
        # Push initial state after event loop settles (worker needs time to spin up)
        QTimer.singleShot(500, self.broadcast_state_to_web)

    def manage_web_remote_server(self, state):
        """Handles the Enable Web Remote checkbox toggle in Settings."""
        enabled = bool(state)
        self.config["web_remote_enabled"] = enabled
        config.save_config(self.config)
        
        if enabled and HAS_WEB_REMOTE:
            if not (self.web_remote_worker and self.web_remote_worker.isRunning()):
                self._start_web_remote()
            ip = get_local_ip()
            self.lbl_web_remote_status.setText(f"✅ Active — http://{ip}:8080")
            self.lbl_web_remote_status.setStyleSheet("color: #1DB954; font-size: 11px; font-weight: bold; margin-top: 4px;")
        else:
            self.lbl_web_remote_status.setText("⏸ Disabled (restart to fully stop server)")
            self.lbl_web_remote_status.setStyleSheet("color: #888888; font-size: 11px; font-weight: bold; margin-top: 4px;")
        
        logger.info(f"Web Remote toggled: {'ENABLED' if enabled else 'DISABLED'}")

    def _handle_web_command(self, command):
        """Routes commands received from the Flask TV remote to the appropriate handler."""
        self.handle_web_remote_command(command)

    def handle_web_remote_command(self, cmd):
        """Routes commands received from the local network HTTP server."""
        logger.info(f"Received Web Remote Command: {cmd}")
        if cmd == 'play':
            self.toggle_playback()
        elif cmd == 'next':
            self.play_next_track()
        elif cmd == 'prev':
            self.play_previous_track()
        elif cmd == 'karaoke':
            if not getattr(self, 'karaoke_mode_active', False):
                self.show_page(2)
            self.toggle_full_karaoke_mode()
        elif cmd.startswith('play_idx:'):
            try:
                idx = int(cmd.split(':')[1])
                if hasattr(self, 'scanned_songs') and 0 <= idx < len(self.scanned_songs):
                    self.load_and_play_track(self.scanned_songs[idx])
            except Exception as e:
                logger.error(f"Failed to play web index: {e}")
        elif cmd.startswith('download:'):
            from urllib.parse import unquote
            query = unquote(cmd.split(':', 1)[1])
            if query:
                logger.info(f"Web Remote requested download for: {query}")
                # Inject query into the downloader form and trigger the worker natively
                self.txt_yt_urls.setText(query)
                self.trigger_youtube_download()

    def trigger_track_karaoke_generation(self, song, silent=False, force=False, instrumental_only=False):
        """Queues background stem vocal splitting and Whisper alignments."""
        song_path = song["path"]
        
        # Check if already in queue or running
        if any(item[0]["path"] == song_path for item in self.karaoke_queue):
            logger.info(f"Vocal separation is already queued for {song['name']}.")
            return
            
        if self.active_karaoke_worker and self.active_karaoke_worker.song_path == song_path:
            logger.info(f"Vocal separation is already actively running for {song['name']}.")
            return
            
        logger.info(f"Queueing karaoke generation for: {song_path} (Silent: {silent}, Force: {force})")
        self.karaoke_queue.append((song, silent, force, instrumental_only))
        self.update_sync_queue_ui()
        
        # If no worker is active, trigger processing for the next item!
        if not self.active_karaoke_worker:
            self.process_next_karaoke_item()

    def process_next_karaoke_item(self):
        """Processes the next track in the karaoke queue sequentially."""
        if not self.karaoke_queue:
            logger.info("Karaoke processing queue is completely empty.")
            self.active_karaoke_worker = None
            self.update_sync_queue_ui()
            return
            
        queue_item = self.karaoke_queue.pop(0)
        song = queue_item[0]
        silent = queue_item[1]
        force = queue_item[2]
        instrumental_only = queue_item[3] if len(queue_item) > 3 else False
        song_path = song["path"]
        
        logger.info(f"Starting sequential karaoke generation for: {song_path} (Silent: {silent}, Force Overwrite: {force})")
        
        if force:
            json_path = os.path.splitext(song_path)[0] + ".json"
            if os.path.isfile(json_path):
                logger.info(f"Manual re-sync (force overwrite) requested. Deleting existing karaoke file: {json_path}")
                try:
                    os.remove(json_path)
                except Exception as e:
                    logger.warning(f"Could not remove existing JSON file before manual re-sync: {e}")
        
        logger.info(f"Background processing initiated silently for {song['name']}.")
            
        import analytics
        whisper_lang = analytics.get_track_language(song_path)
        if not whisper_lang:
            whisper_lang = self.config.get("whisper_language", None)
        worker = KaraokeProcessorWorker(
            song_path,
            use_mock=self.config["use_mock_karaoke"],
            language=whisper_lang,
            download_instruments=self.config.get("download_instruments", True),
            instrumental_only=instrumental_only,
            music_root_dir=self.config.get("music_root_dir", None)
        )
        
        # Log progress to the app logger; badge states in library update on scan
        def on_progress(msg, percentage):
            logger.info(f"Karaoke [{song['name']}] {msg} ({int(percentage)}%)")
            self.update_sync_progress_ui(song_path, int(percentage))
                
        worker.progress_signal.connect(on_progress)
        
        def on_finished(s_path, json_path):
            logger.info(f"Karaoke generation finished: {s_path} -> {json_path}")
            
            def complete_transition():
                self.scan_music_library()
                if hasattr(self, 'player') and self.player.current_track == s_path:
                    self.load_karaoke_lyrics_data(s_path)
                
                # Start next queue item sequentially
                # If queue is empty, this function safely sets active_karaoke_worker = None after the thread has naturally died
                self.process_next_karaoke_item()
                
            # Let the user see "100%" for a moment before refreshing the UI
            QTimer.singleShot(1500, complete_transition)
            
        def on_error(s_path, error_msg):
            logger.error(f"Karaoke thread failure for {s_path}: {error_msg}")
            
            # Start next queue item sequentially
            self.process_next_karaoke_item()
            
        worker.finished_signal.connect(on_finished)
        worker.error_signal.connect(on_error)
        worker.finished.connect(worker.deleteLater)
        
        self.active_karaoke_worker = worker
        self.update_sync_queue_ui()
        
        # Force UI badge update from 'Queue' to 'Syncing' instantly
        if getattr(self, "scanned_songs", []):
            self.populate_library_table(self.scanned_songs)
            
        worker.start()

    def trigger_manual_re_sync(self):
        """Forces manual re-sync and overwrite of karaoke files for the currently loaded/playing song."""
        if not self.player.current_track:
            QMessageBox.warning(self, "No Track Loaded", "Please load or play a track first before triggering manual sync!")
            return
            
        current_path = self.player.current_track
        song = None
        for s in self.scanned_songs:
            if s["path"] == current_path:
                song = s
                break
                
        if not song:
            song = {
                "name": os.path.splitext(os.path.basename(current_path))[0],
                "filename": os.path.basename(current_path),
                "path": current_path,
                "type": "MP3",
                "has_karaoke": True
            }
            
        self.trigger_track_karaoke_generation(song, force=True)

    def on_bulk_toggle_changed(self, checked):
        if checked:
            self.btn_bulk_toggle.setText("Everything")
        else:
            self.btn_bulk_toggle.setText("Missing")

    def run_bulk_karaoke_processing(self):
        """Processes missing or all tracks based on the toggle."""
        process_all = getattr(self, 'btn_bulk_toggle', None) and self.btn_bulk_toggle.isChecked()
        
        if process_all:
            unprocessed = self.scanned_songs
        else:
            unprocessed = [s for s in self.scanned_songs if not s["has_karaoke"]]
            
        if not unprocessed:
            QMessageBox.information(self, "Up to Date", "All tracks in this folder already have word-synchronized karaoke files!")
            return
            
        logger.info(f"Bulk processing started for {len(unprocessed)} tracks. (Force: {process_all})")
        for song in unprocessed:
            self.trigger_track_karaoke_generation(song, silent=True, force=process_all)

    # ── AI Music Discovery Feed & Playback Analytics slots (v5.8.0) ──

    def on_library_tab_changed(self, index):
        """Called when switching tabs within the Full Library view."""
        if index == 1:  # Tab 2: Most Listened
            self.refresh_most_listened_table()

    def refresh_most_listened_table(self):
        """Queries the analytics layer to refresh the user's top played tracks."""
        try:
            import analytics
            top_tracks = analytics.get_top_played_tracks(limit=50, playlist_name="Global")
            
            self.table_most_listened.setRowCount(0)
            self.table_most_listened.setRowCount(len(top_tracks))
            
            for row_idx, track in enumerate(top_tracks):
                title = track.get("title", "Unknown Title")
                artist = track.get("artist", "Unknown Artist")
                play_count = track.get("play_count", 0)
                last_played = track.get("last_played_timestamp", "")
                
                if last_played:
                    try:
                        last_played = last_played.split(".")[0].replace("T", " ")
                    except Exception:
                        pass
                
                item_title = QTableWidgetItem(title)
                item_artist = QTableWidgetItem(artist)
                item_count = QTableWidgetItem(str(play_count))
                item_time = QTableWidgetItem(last_played)
                
                # Make items read-only
                for item in (item_title, item_artist, item_count, item_time):
                    item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                    
                self.table_most_listened.setItem(row_idx, 0, item_title)
                self.table_most_listened.setItem(row_idx, 1, item_artist)
                self.table_most_listened.setItem(row_idx, 2, item_count)
                self.table_most_listened.setItem(row_idx, 3, item_time)
        except Exception as e:
            logger.error(f"Failed to refresh most listened table: {e}")

    def reroll_discovery_feed(self):
        """Triggers manual re-rolling of the discovery feed, with session token checks and rate-limiting."""
        if getattr(self, "reroll_count", 10) <= 0:
            self.btn_reroll_feed.setEnabled(False)
            QMessageBox.warning(self, "No Re-rolls Left", "You have exhausted your 10 session re-rolls.")
            return
            
        # Extract and exclude currently displayed recommendations from future rolls (manual re-roll exclusion)
        try:
            import analytics
            for row in range(self.table_discovery.rowCount()):
                title_item = self.table_discovery.item(row, 1)
                artist_item = self.table_discovery.item(row, 2)
                if title_item and artist_item:
                    title = title_item.text().strip()
                    artist = artist_item.text().strip()
                    analytics.add_to_recommendation_history(title, artist)
        except Exception as e:
            logger.error(f"Failed to save current recommendation list to exclusion history: {e}")
            
        # UI Rate-limiting: Instantly disable button, update text (Rate-limiting directive)
        self.btn_reroll_feed.setEnabled(False)
        self.btn_reroll_feed.setText("🧠 Analyzing...")
        
        # Decrement counter
        self.reroll_count -= 1
        
        # Launch Discovery
        self.run_gemini_discovery()
        
        # Start a 10-second QTimer to re-enable button after cooldown
        QTimer.singleShot(10000, self.enable_reroll_button_after_cooldown)

    def enable_reroll_button_after_cooldown(self):
        """Re-enables the re-roll button and restores text showing remaining tokens."""
        if getattr(self, "reroll_count", 10) > 0:
            self.btn_reroll_feed.setEnabled(True)
            self.btn_reroll_feed.setText(f"Re-roll Feed ({self.reroll_count} Left)")
        else:
            self.btn_reroll_feed.setEnabled(False)
            self.btn_reroll_feed.setText("Re-roll Feed (0 Left)")

    def run_gemini_discovery(self):
        """Compiles contexts and spawns background thread to fetch recommendations."""
        api_key = self.config.get("gemini_api_key", "").strip()
        if not api_key:
            self.table_discovery.setRowCount(0)
            item_msg = QTableWidgetItem("Please enter a valid Gemini API Key in the Settings page to enable AI music discovery.")
            item_msg.setFlags(Qt.ItemFlag.NoItemFlags)
            self.table_discovery.setRowCount(1)
            self.table_discovery.setItem(0, 1, item_msg)
            # Re-enable button in case it was a re-roll click without a key
            self.enable_reroll_button_after_cooldown()
            return
            
        # Disable feed table during loading
        self.table_discovery.setRowCount(0)
        self.table_discovery.setRowCount(1)
        loading_item = QTableWidgetItem("Fetching recommendations from Google Gemini 3.5 Flash...")
        loading_item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.table_discovery.setItem(0, 1, loading_item)
        
        # Build prompt lists
        try:
            import analytics
            # 1. Top 10 played tracks
            top_10 = analytics.get_top_played_tracks(limit=10, playlist_name="Global")
            
            # Fetch explicitly favorited tracks
            favorites = analytics.get_all_favorites()
            
            # Merge and deduplicate case-insensitively to create the user's core profile
            seen_tracks = set()
            hybrid_music_profile = []
            
            for s in top_10:
                artist = s.get("artist", "Unknown Artist").strip()
                title = s.get("title", "Unknown Title").strip()
                key = (artist.lower(), title.lower())
                if key not in seen_tracks:
                    seen_tracks.add(key)
                    hybrid_music_profile.append({"artist": artist, "title": title})
                    
            for s in favorites:
                artist = s.get("artist", "Unknown Artist").strip()
                title = s.get("title", "Unknown Title").strip()
                key = (artist.lower(), title.lower())
                if key not in seen_tracks:
                    seen_tracks.add(key)
                    hybrid_music_profile.append({"artist": artist, "title": title})
            
            # 2. Excluded Filter List
            rec_history = analytics.get_recommendation_history()
            
            top_50 = analytics.get_top_played_tracks(limit=50, playlist_name="Global")
            top_50_paths = {t["track_path"] for t in top_50 if "track_path" in t}
            
            excluded_library = []
            root_dir = self.config.get("music_root_dir", "")
            
            # Recursively scan root_dir for all owned audio tracks across playlists/subfolders
            all_owned_paths = []
            if os.path.isdir(root_dir):
                for walk_root, walk_dirs, walk_files in os.walk(root_dir):
                    # Firewall: Skip raw Demucs wav stems
                    if "instrumentals" in walk_root.replace("\\", "/").lower():
                        continue
                    for file in walk_files:
                        if "instrumentals" in file.lower():
                            continue
                        if file.lower().endswith((".mp3", ".wav")):
                            all_owned_paths.append(os.path.join(walk_root, file))
                            
            for path in all_owned_paths:
                if path not in top_50_paths:
                    artist, title = analytics.parse_track_meta(path)
                    excluded_library.append({"title": title, "artist": artist})
                    
            excluded_filter_list = rec_history + excluded_library
            
        except Exception as e:
            logger.error(f"Error compiling analytics lists for discovery: {e}")
            hybrid_music_profile = []
            excluded_filter_list = []
            
        # Format lists into prompt
        profile_songs_str = "\n".join([f"- {s['artist']} - {s['title']}" for s in hybrid_music_profile])
        excluded_truncated = excluded_filter_list[:500]
        excluded_str = "\n".join([f"- {s.get('artist', 'Unknown')} - {s.get('title', 'Unknown')}" for s in excluded_truncated])
        
        genre = self.txt_discovery_genre.text().strip()
        
        prompt = "Based on the user's top 10 tracks and favorite tracks:\n"
        if profile_songs_str:
            prompt += f"{profile_songs_str}\n"
        else:
            prompt += "- (No playback history or favorites yet. Recommend a highly rated diverse playlist.)\n"
            
        prompt += f"\nPlease recommend 10 new, real-world tracks.\n"
        
        if genre:
            prompt += f"\nFilter by Genre/Style: {genre}\n"
            
        if excluded_str:
            prompt += f"\nExcluded Filter List (DO NOT recommend any of these):\n{excluded_str}\n"
            
        system_instruction = (
            "You are a precise music database recommendation agent. Your task is to analyze a user's passive "
            "listening habits alongside their active favorites to recommend 10 new, real-world tracks they "
            "do not currently have in heavy rotation.\n\n"
            "CRITICAL RULES:\n"
            "1. Every song and artist combination MUST exist in reality. Do not hallucinate or invent titles.\n"
            "2. You are FORBIDDEN from recommending any track listed in the Excluded Filter List.\n"
            "3. Adhere strictly to the requested optional Genre if provided.\n"
            "4. Return output strictly as a JSON array of objects: [{'title': '...', 'artist': '...'}]"
        )
        
        # Spawn background worker thread
        self.discovery_worker = GeminiDiscoveryWorker(api_key, prompt, system_instruction)
        self.discovery_worker.finished.connect(self.on_discovery_finished)
        self.discovery_worker.error.connect(self.on_discovery_error)
        self.discovery_worker.start()

    def populate_discovery_table_view(self, recommendations):
        """Populates the Discovery Feed table with AI recommendations."""
        self.table_discovery.setRowCount(0)
        self.table_discovery.setRowCount(len(recommendations))
        
        for row_idx, track in enumerate(recommendations):
            title = track.get("title", "Unknown Title")
            artist = track.get("artist", "Unknown Artist")
            
            # Checkbox column
            chk = QCheckBox()
            chk.setChecked(False)
            chk.setCursor(Qt.CursorShape.PointingHandCursor)
            chk.setStyleSheet("""
                QCheckBox {
                    spacing: 0px;
                }
                QCheckBox::indicator {
                    width: 24px;
                    height: 24px;
                    background-color: #242424;
                    border: 2px solid #555555;
                    border-radius: 4px;
                    image: none;
                }
                QCheckBox::indicator:checked {
                    background-color: #1DB954;
                    border: 2px solid #1DB954;
                    image: none;
                }
                QCheckBox::indicator:hover {
                    border: 2px solid #1DB954;
                }
            """)
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            
            item_title = QTableWidgetItem(title)
            item_artist = QTableWidgetItem(artist)
            
            item_title.setFlags(item_title.flags() ^ Qt.ItemFlag.ItemIsEditable)
            item_artist.setFlags(item_artist.flags() ^ Qt.ItemFlag.ItemIsEditable)
            
            self.table_discovery.setCellWidget(row_idx, 0, chk_widget)
            self.table_discovery.setItem(row_idx, 1, item_title)
            self.table_discovery.setItem(row_idx, 2, item_artist)
            
        logger.info(f"Loaded {len(recommendations)} AI recommendations into the Discovery Feed.")

    def on_discovery_finished(self, recommendations):
        """Populates the Discovery Feed table with AI recommendations."""
        self.populate_discovery_table_view(recommendations)

    def on_discovery_error(self, error_msg):
        """Displays error details to the user and logs them safely."""
        logger.error(f"Gemini Discovery failed: {error_msg}")
        self.table_discovery.setRowCount(0)
        self.table_discovery.setRowCount(1)
        err_item = QTableWidgetItem(f"Discovery Error: {error_msg}")
        err_item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.table_discovery.setItem(0, 1, err_item)

    def download_selected_tracks(self):
        """Wires checked recommendations into background grabber, updates feed list and switches view."""
        checked_tracks = []
        remaining_tracks = []
        
        for row in range(self.table_discovery.rowCount()):
            chk_widget = self.table_discovery.cellWidget(row, 0)
            if chk_widget:
                chk = chk_widget.findChild(QCheckBox)
                title_item = self.table_discovery.item(row, 1)
                artist_item = self.table_discovery.item(row, 2)
                if title_item and artist_item:
                    track_info = {
                        "title": title_item.text(),
                        "artist": artist_item.text()
                    }
                    if chk and chk.isChecked():
                        checked_tracks.append(track_info)
                    else:
                        remaining_tracks.append(track_info)
                        
        if not checked_tracks:
            QMessageBox.information(self, "No Selection", "Please check at least one track to download.")
            return
            
        # 1. Append selected tracks to recommendation_history
        try:
            import analytics
            for track in checked_tracks:
                analytics.add_to_recommendation_history(track["title"], track["artist"])
        except Exception as e:
            logger.error(f"Failed to log download to recommendation history: {e}")
            
        # 2. Erase selected songs from the Discovery Feed list table and readjust
        self.populate_discovery_table_view(remaining_tracks)
            
        # 3. Convert to formatted search query list without "audio" keyword (Amendment 1)
        queries = []
        for track in checked_tracks:
            queries.append(f"ytsearch1:{track['artist']} - {track['title']}")
            
        # Paste queries into the text field on Grab/Queue tab
        self.txt_yt_urls.setPlainText("\n".join(queries))
        
        # 4. View Handshake: programmatically switch selection to Grab/Queue tab
        self.show_page(1)
        
        # 5. Trigger bulk download
        self.trigger_youtube_download()


class GeminiDiscoveryWorker(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def __init__(self, api_key, prompt, system_instruction):
        super().__init__()
        self.api_key = api_key
        self.prompt = prompt
        self.system_instruction = system_instruction
        
    def run(self):
        import urllib.request
        import json
        import urllib.error
        import logging

        logger = logging.getLogger("MozZzartDiscoveryWorker")

        fallback_models = [
            "gemini-3.5-flash",
            "gemini-3-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash"
        ]
        
        headers = {
            "Content-Type": "application/json"
        }
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": self.prompt
                        }
                    ]
                }
            ],
            "systemInstruction": {
                "parts": [
                    {
                        "text": self.system_instruction
                    }
                ]
            },
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }

        last_error_msg = "Unknown error"
        
        for model in fallback_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            logger.info(f"Attempting discovery with model: {model}")
            try:
                req = urllib.request.Request(
                    url, 
                    data=json.dumps(payload).encode("utf-8"), 
                    headers=headers, 
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    res_data = response.read().decode("utf-8")
                    res_json = json.loads(res_data)
                    
                    candidates = res_json.get("candidates", [])
                    if not candidates:
                        raise ValueError("Gemini returned an empty response.")
                        
                    text_content = candidates[0]["content"]["parts"][0]["text"]
                    recommendations = json.loads(text_content.strip())
                    
                    if isinstance(recommendations, dict) and "recommendations" in recommendations:
                        recommendations = recommendations["recommendations"]
                        
                    if not isinstance(recommendations, list):
                        raise ValueError("Gemini response is not a valid list.")
                        
                    self.finished.emit(recommendations)
                    return
                    
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    last_error_msg = f"Rate Limit Exceeded (HTTP 429): Gemini API rate limit reached."
                else:
                    try:
                        err_body = e.read().decode("utf-8")
                        err_json = json.loads(err_body)
                        msg = err_json.get("error", {}).get("message", str(e))
                        last_error_msg = f"Gemini API Error (HTTP {e.code}): {msg}"
                    except Exception:
                        last_error_msg = f"Gemini API Error (HTTP {e.code}): {e.reason}"
                logger.warning(f"Model {model} failed: {last_error_msg}")
            except Exception as e:
                last_error_msg = str(e)
                logger.warning(f"Model {model} failed: {last_error_msg}")
                
        # If loop finished, all models failed
        logger.error(f"All fallback models failed. Final error: {last_error_msg}")
        self.error.emit(f"Failed to generate recommendations: {last_error_msg}")


class GeminiLyricsCorrectionWorker(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def __init__(self, api_key, prompt, system_instruction):
        super().__init__()
        self.api_key = api_key
        self.prompt = prompt
        self.system_instruction = system_instruction
        
    def run(self):
        import urllib.request
        import json
        import urllib.error
        import logging

        logger = logging.getLogger("MozZzartCorrectionWorker")

        fallback_models = [
            "gemini-3.5-flash",
            "gemini-3-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash"
        ]
        
        headers = {
            "Content-Type": "application/json"
        }
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": self.prompt
                        }
                    ]
                }
            ],
            "systemInstruction": {
                "parts": [
                    {
                        "text": self.system_instruction
                    }
                ]
            },
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }

        last_error_msg = "Unknown error"
        
        for model in fallback_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            logger.info(f"Attempting correction with model: {model}")
            try:
                req = urllib.request.Request(
                    url, 
                    data=json.dumps(payload).encode("utf-8"), 
                    headers=headers, 
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    res_data = response.read().decode("utf-8")
                    res_json = json.loads(res_data)
                    
                    candidates = res_json.get("candidates", [])
                    if not candidates:
                        raise ValueError("Gemini returned an empty response.")
                        
                    text_content = candidates[0]["content"]["parts"][0]["text"]
                    data = json.loads(text_content.strip())
                    
                    if isinstance(data, dict):
                        for key in ["corrected_lyrics", "lyrics", "lines", "corrections"]:
                            if key in data and isinstance(data[key], list):
                                data = data[key]
                                break
                                
                    if not isinstance(data, list):
                        raise ValueError("Gemini response is not a valid list.")
                        
                    # Ensure all items are strings
                    data = [str(x) for x in data]
                    
                    self.finished.emit(data)
                    return
                    
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    last_error_msg = f"Rate Limit Exceeded (HTTP 429): Gemini API rate limit reached."
                else:
                    try:
                        err_body = e.read().decode("utf-8")
                        err_json = json.loads(err_body)
                        msg = err_json.get("error", {}).get("message", str(e))
                        last_error_msg = f"Gemini API Error (HTTP {e.code}): {msg}"
                    except Exception:
                        last_error_msg = f"Gemini API Error (HTTP {e.code}): {e.reason}"
                logger.warning(f"Model {model} failed: {last_error_msg}")
            except Exception as e:
                last_error_msg = str(e)
                logger.warning(f"Model {model} failed: {last_error_msg}")
                
        logger.error(f"All fallback models failed. Final error: {last_error_msg}")
        self.error.emit(f"Failed to correct lyrics: {last_error_msg}")


def main():
    # Linux Wayland Transparency Fix: force X11 rendering to prevent black window artifacts
    if sys.platform.startswith("linux"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    
    # Bind portable bin/ containing FFmpeg to system PATH at runtime
    # This guarantees Whisper and Demucs find FFmpeg seamlessly without system-wide modifications
    utils.bind_ffmpeg_to_path()
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # ── Single Instance Guard ──────────────────────────────────────────
    # Prevents multiple copies of the app from running simultaneously.
    from PyQt6.QtCore import QSharedMemory
    shared_memory_key = "MozZzartPlayer_SingleInstance_Lock_Token"
    shared_mem = QSharedMemory(shared_memory_key)
    
    # HOTFIX: Check if this process was launched with command-line arguments.
    # Regular users double-clicking the app pass 0 extra args (len == 1).
    # Background worker subprocesses (like Demucs/PyInstaller forks) pass extra arguments.
    is_background_worker = len(sys.argv) > 1
    
    # Only enforce the single-instance window block for primary GUI launches
    if not is_background_worker:
        if shared_mem.attach():
            print("[!] MozZzart Player is already running. Exiting secondary instance safely.")
            sys.exit(0)
            
        if not shared_mem.create(1):
            print("[!] Critical Error checking single instance state. Exiting.")
            sys.exit(1)
    
    if not utils.has_dependencies():
        setup_dialog = DependencySetupDialog()
        if setup_dialog.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
            
    window = MozZzartPlayerApp()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    import sys
    import multiprocessing
    multiprocessing.freeze_support()
    
    # 2. PYINSTALLER SUBPROCESS MULTIPLEXER (THE HOTFIX)
    # When compiled, sys.executable is MozZzartPlayer.exe. If a background worker 
    # calls `subprocess.Popen([sys.executable, "-m", "demucs", ...])`, 
    # it launches the .exe again. We must intercept this and run the module natively, 
    # otherwise it will load a duplicate GUI in the background!
    if getattr(sys, 'frozen', False) and len(sys.argv) > 2 and sys.argv[1] == "-m":
        import runpy
        
        # Reconstruct sys.argv so the target module parses its arguments correctly.
        # Old: ['MozZzartPlayer.exe', '-m', 'demucs', ...]
        # New: ['demucs', ...]
        module_name = sys.argv[2]
        
        # PyInstaller does not package demucs.__main__ by default.
        # Route 'demucs' directly to 'demucs.separate' where the CLI logic resides.
        if module_name == "demucs":
            module_name = "demucs.separate"
            
        sys.argv = sys.argv[2:] 
        
        # Execute the module natively and terminate this process immediately
        try:
            runpy.run_module(module_name, run_name="__main__", alter_sys=True)
        except SystemExit as e:
            sys.exit(e.code)
        sys.exit(0)

    main()

# ==============================================================================
# DEV DIARY — VERSION CONTROL & ARCHITECTURE NOTES
# ==============================================================================
#
# --- v2.0: True Karaoke Mode (2026-05-29) ---
#
# NEW DEPENDENCY: pyaudio (v0.2.14)
#   - Required for live microphone capture and speaker output routing.
#   - Uses PortAudio backend. Install via: pip install pyaudio
#   - If installation fails on Windows, try: pipwin install pyaudio
#
# NEW FILE: mic_worker.py
#   - MicrophoneWorker(QThread) — captures mic input via PyAudio, applies a
#     delay-line circular buffer DSP echo/reverb effect, and writes processed
#     audio to the default speaker output in real-time.
#   - Configurable reverb_intensity (0.0 - 1.0) via settings slider.
#   - Thread-safe pause/resume/stop controls integrated with playback state.
#   - Delay buffer: 8 chunks × 1024 frames @ 44100 Hz ≈ 0.19s echo delay.
#   - Known consideration: mic latency depends on system audio buffer size.
#     If users report echo-on-echo feedback, reduce DELAY_CHUNKS or increase
#     CHUNK size in mic_worker.py. PortAudio's default latency on Windows is
#     typically ~30-50ms which is acceptable for karaoke.
#
# MODIFIED: karaoke_engine.py
#   - KaraokeProcessorWorker now accepts download_instruments and
#     instrumental_only parameters.
#   - Demucs output: now locates BOTH vocals.wav and no_vocals.wav.
#   - Instrumental stem (no_vocals.wav) is copied to the music folder as
#     "{SongName} (Instrumental).wav" when download_instruments=True.
#   - New instrumental_only mode: runs Demucs but skips Whisper transcription
#     entirely, only extracting the instrumental stem. Used when a song
#     already has lyrics but needs the instrumental extracted.
#   - JSON output now includes "instrumental_path" key for hot-swap lookup.
#   - Model upgraded from Whisper 'tiny' to 'large-v3' for maximum accuracy.
#
# MODIFIED: config.py
#   - Added "download_instruments" (default: True) — controls instrumental saving.
#   - Added "reverb_intensity" (default: 0.35) — mic echo DSP intensity.
#   - Added "whisper_language" (default: None) — Whisper language override.
#
# --- v2.1: Architecture Refinement — Mixer & Firewall (2026-05-29) ---
#
# LIBRARY FIREWALL (scan_music_library)
#   - Added explicit bypass rule: any path containing "instrumentals" is skipped
#     entirely during library scanning. This prevents Demucs WAV stems from
#     appearing as regular songs in the UI.
#   - The instrumentals/ subfolder is created inside music_root_dir, not
#     inside the individual playlist/subfolder. This keeps the firewall
#     architecture clean regardless of which playlist is active.
#
# FIXED OUTPUT DIRECTORY (karaoke_engine.py)
#   - Stems are now saved to {music_root_dir}/instrumentals/ (not song_dir).
#   - Standardized filenames: {SongName}_instrumental.wav / {SongName}_vocal.wav.
#     (Previously: "{SongName} (Instrumental).wav" in the song's own folder.)
#   - Both absolute paths are written into the JSON:
#       "instrumental_path": "...\instrumentals\{name}_instrumental.wav"
#       "vocal_path": "...\instrumentals\{name}_vocal.wav"
#   - KaraokeProcessorWorker now accepts music_root_dir to locate the output folder.
#
# DUAL-CHANNEL MIXER (player_engine.py)
#   - pygame.mixer.Channel(0) = instrumental at 1.0 volume (always).
#   - pygame.mixer.Channel(1) = vocal guide at adjustable volume (default 0.10).
#   - Both channels launched simultaneously for sample-perfect sync.
#   - A silent music stream is loaded in the background as a reference clock for
#     get_current_position() polling (pygame Sound channels have no get_pos()).
#   - set_vocal_guide_volume(float) adjusts Channel 1 live with no interruption.
#   - Latency debugging: if channels drift, check pygame.mixer.pre_init() buffer size.
#     Reducing the CHUNK size (1024 → 512) will reduce latency at the cost of more
#     CPU overhead. On high-latency systems, increase to 2048.
#
# VOCAL GUIDE SLIDER (setup_karaoke_page in main.py)
#   - QSlider (0-100%) added to the karaoke header as "🎤 Guide Vol:".
#   - Widget is hidden by default and shown only when Karaoke Mode is ON.
#   - on_guide_vocal_volume_changed() calls player.set_vocal_guide_volume() live.
#   - Percentage display label updates in real-time alongside the slider.
#
# --- v2.2: State Management & WAV Fast-Slicing (2026-05-29) ---
#
# BUG FIX: Lingering Channels Corrupting Standard Playback
#   Root cause: pygame.mixer.Channel Sound buffers are RAM-resident and persist
#   even after the Channel object goes out of scope. When the streaming music
#   engine (pygame.mixer.music) attempts to claim the audio device after Karaoke
#   Mode ends, it conflicts with still-active channel buffers, producing silence
#   or corrupted output.
#   Fix: AudioPlayer.clear_karaoke_channels() calls pygame.mixer.stop() (which
#   halts ALL channels at once) followed by pygame.mixer.music.stop(). This is
#   the nuclear option — it guarantees a clean audio device before any transition.
#   Integration points in main.py:
#     1. load_and_play_track() — always called before player.load_track().
#     2. toggle_full_karaoke_mode() ON path — called before start_karaoke_mixer().
#     3. _deactivate_karaoke_mode() — called before restoring the original track.
#
# BUG FIX: Mid-Song Desync (Channel.play() ignores start offset)
#   Root cause: pygame.mixer.Channel.play(sound) always begins at frame 0 of the
#   Sound buffer. Passing a Sound loaded from the full WAV when the song is 90s
#   in causes an immediate 90-second desync with the lyrics display.
#   Fix: load_sliced_sound(filepath, start_time_sec) in player_engine.py:
#     1. Opens the WAV with Python's built-in wave module (no disk copy).
#     2. Calculates the exact byte-frame offset: start_frame = int(t * frame_rate).
#     3. Calls wav.setpos(start_frame) then wav.readframes(remaining).
#     4. Rebuilds a complete RIFF/WAV header (44 bytes, struct.pack) prepended to
#        the trimmed audio bytes.
#     5. Returns pygame.mixer.Sound(buffer=header + raw_data) — the Sound now
#        appears to start at t=0 but contains only audio from start_time onwards.
#   This technique works for any PCM WAV file (which Demucs always outputs).
#   It is used in both start_karaoke_mixer() and _seek_karaoke_channels().
#
# SEEK WHILE KARAOKE MODE IS ACTIVE
#   player_engine.seek() detects self._karaoke_mode and routes to
#   _seek_karaoke_channels(position_seconds, was_playing) which:
#     1. Stops both channels.
#     2. Re-slices both WAV stems at the new position via load_sliced_sound().
#     3. Restarts the silent reference clock stream at the new offset.
#     4. Replays both channels from their fresh sliced buffers simultaneously.
#   The seek is fully integrated with the existing timeline slider signal
#   (on_timeline_seek → player.seek()) with no additional changes required.
#
# MODIFIED: main.py (this file)
#   - Settings page: added QCheckBox for instrumental saving, QSlider for
#     reverb intensity, QComboBox for Whisper language override.
#   - Library table: removed 🗑 trash/delete button. Replaced with 🎸
#     Instruments button that triggers instrumental extraction (Option B if
#     song has lyrics, Option A full pipeline if no lyrics yet).
#   - Karaoke screen: added "🎤 Full Karaoke Mode" toggle button.
#   - Hot-swap playback logic: reads current position, loads instrumental
#     track via pygame.mixer, and resumes at the exact timestamp.
#   - MicrophoneWorker integration: starts on karaoke mode activation,
#     pauses on playback pause, stops on mode deactivation or track change.
#   - Safety: _deactivate_karaoke_mode() called automatically on track change
#     to prevent orphaned mic streams and audio feedback loops.
#
# --- v2.3: Hardware Lock Fix & Clean Resume (2026-05-29) ---
#
# BUG: PyAudio Holding the Audio Device After Karaoke Mode Ends
#   Root cause: PyAudio opens the audio device (WASAPI/WDM on Windows) for
#   exclusive or shared access. Even after self.running = False, the run()
#   thread may still be processing a final audio chunk when pygame.mixer.music
#   attempts to reclaim the device, causing a lock conflict and broken playback.
#   Fix in mic_worker.py:
#     - Streams stored as instance attributes (self.input_stream, self.output_stream,
#       self.pyaudio_instance) so stop() can close them from the CALLING thread,
#       not just from inside run().
#     - MicrophoneWorker.stop() now force-closes streams immediately, then
#       run() finally block is a safety net only.
#     - Loop checks if streams are None (set by stop()) and breaks cleanly.
#   Fix in main.py:
#     - _deactivate_karaoke_mode() calls mic_worker.stop() then mic_worker.wait(3000)
#       before ANY pygame operation. wait() blocks until the thread is confirmed dead.
#
# BUG: Broken Player After Karaoke → Regular Mode Transition
#   Root cause: After pygame.mixer.stop() and channel teardown, the
#   pygame.mixer.music streaming engine is in an undefined internal state.
#   Calling music.unpause() or music.play() on a stale/broken stream produces
#   silence or a freeze rather than resuming cleanly.
#   Fix — AudioPlayer.resume_regular_mode(filepath, start_time) in player_engine.py:
#     1. clear_karaoke_channels() — nuclear device release.
#     2. pygame.mixer.music.load(filepath) — full stream remount from disk.
#        This resets ALL internal streaming state, not just the position pointer.
#     3. pygame.mixer.music.play(start=t) — seeks to exact timestamp atomically.
#     4. Updates _is_active=True, is_paused=False, elapsed_accumulator=t.
#   Called from _deactivate_karaoke_mode() AFTER mic_worker.wait() completes.
#
# TRANSITION ORDER (guaranteed sequence):
#   1. resume_pos = player.get_current_position()   # Capture timestamp first
#   2. mic_worker.stop()                             # Set flags only — no stream touching
#   3. mic_worker.wait(2000)                         # Block until run() finally block done
#   4. player.resume_regular_mode(path, resume_pos) # Rebuild streaming engine
#   5. UI state reset                                # Hide guide slider, reset button
#
# --- v2.4: Segfault Root Cause Eliminated (2026-05-29) ---
#
# CRASH: C-level Segmentation Fault on Karaoke → Regular Mode
#   Root cause: stop() was calling input_stream.stop_stream() and
#   input_stream.close() from the MAIN GUI thread while the run() thread was
#   actively blocked inside input_stream.read(). PortAudio's C internals have
#   no mutex protecting concurrent read/close on the same stream object.
#   The result is a memory access violation (SIGSEGV) that crashes the entire
#   Python process instantly — no exception, no log, just a hard exit.
#
# FIX: mic_worker.py — stop() now sets flags ONLY
#   stop() sets self.running = False and self._paused = False.
#   It does NOT touch input_stream, output_stream, or pyaudio_instance.
#   The CHUNK read (1024 frames @ 44100 Hz) blocks for at most ~23ms.
#   Once read() returns naturally on the next chunk boundary, the while loop
#   checks self.running == False and exits. The finally block then safely
#   closes all streams and calls pa.terminate() from the owning thread.
#   wait(2000) in _deactivate_karaoke_mode() is >> sufficient to cover this.
#
# FIX: player_engine.py — music.unload() before music.load()
#   resume_regular_mode() now calls pygame.mixer.music.unload() inside a
#   try/except before music.load(). This explicitly releases the OS file
#   handle from the previous streaming session, preventing "file in use"
#   errors on Windows NTFS that can occur when PyAudio and Pygame both
#   recently held the audio device.
#   (Superseded by the Hard Reboot in v2.5 — unload() no longer needed but harmless.)
#
# --- v2.5: Mixer Hard Reboot — Zombie Audio Device Fix (2026-05-29) ---
#
# BUG: Silence After Karaoke → Regular Mode (Zombie Audio Device)
#   Root cause: When PyAudio calls pa.terminate(), PortAudio sends a shutdown
#   signal to the OS audio session (WASAPI endpoint on Windows). This invalidates
#   the shared device handle that SDL_mixer was also holding. After this point,
#   pygame.mixer.music.load() and play() appear to succeed (no exception thrown)
#   but write audio data to a dead endpoint — producing complete silence.
#
# FIX: player_engine.py — Mixer Hard Reboot in resume_regular_mode()
#   The try block now calls:
#     1. pygame.mixer.quit()                   — destroys the stale SDL device handle
#     2. pygame.mixer.pre_init(44100, -16, 2, 1024) — configures the new session
#     3. pygame.mixer.init()                   — forces SDL to negotiate a FRESH OS
#                                                audio endpoint with WASAPI/DirectSound
#     4. pygame.mixer.set_num_channels(8)      — restore channel pool
#   After the reboot, music.load() + music.play() connect to the new live endpoint.
#
# FIX: main.py — Volume Re-Sync after Hard Reboot
#   pygame.mixer.quit() + init() resets SDL's internal volume table to 1.0 (100%).
#   Immediately after resume_regular_mode() returns, _deactivate_karaoke_mode()
#   calls self.player.set_volume(self.volume_slider.value()) to restore the
#   user's actual volume setting — preventing a speaker-blast jumpscare.
#
# --- v2.6: Live Edit Mode & Responsiveness (2026-05-29) ---
#
# NEW FEATURE: Live Lyrics Edit on Karaoke Screen
#   - Pausing the music enables the "✏️ Edit Lyrics" button in the Karaoke Header.
#   - Hitting play while editing automatically saves changes and resumes.
#   - Hot-swaps dynamic QLabels inside the lyric scroll layout for QLineEdits.
#   - On save, converts QLineEdits back to HTML QLabels and reloads visuals.
#   - Bypasses diff-match logic via Proportional Timestamp Splitting:
#     Splits parent line's elapsed duration equally across new word tokens.
#
# BUG FIX / REFINEMENT: Library Table Instrument Button Double-Click Lock
#   - Clicking the "🎸" instrument button now immediately disables it, turns its text
#     color to dim gray (#888888), and changes its tooltip to "Extracting instrumental..."
#     to block concurrent extractions.
#   - Clicking "🎸" also immediately updates the adjacent "Lyrics Synced" column badge
#     to "⚡ Syncing..." or "⏳ Queue" and disables it inline to keep UI perfectly in sync
#     without waiting for asynchronous separation loops or manual rescans.
#   - Tracks already separation/syncing in the background are automatically initialized
#     in the disabled state on table load.
#
# --- v2.7: Fullscreen Karaoke Mode & QMovie GIF Playback (2026-05-29) ---
#
# REMOVED DEPENDENCIES: opencv-python, numpy
#   - Pivoted away from heavy real-time OpenCV chroma-keying to native PyQt6 QMovie 
#     rendering of pre-keyed transparent GIF. This eliminates heavy CPU cycles and
#     external libraries.
#
# LIGHTWEIGHT NATIVE WIDGET (MozartPlayer class)
#   - Renders "mozart dance.gif" (Tall portrait layout: 250x450).
#   - Uses QMovie with CacheMode.CacheAll to guarantee smooth, low-overhead animation loops.
#   - Symmetrically placed on both sides of QScrollArea inside setup_karaoke_page.
#   - Automatically jumps to frame 0 on stop() so he is never frozen in a mid-dance posture.
#
# FULLSCREEN TRANSITION & EXTRA CONTROLS (MozZzartPlayerApp)
#   - self.sidebar and self.bottom_bar converted to class properties to allow hiding/showing.
#   - toggle_karaoke_fullscreen() toggles between showFullScreen() and showNormal().
#   - Esc key event connects to keyPressEvent() to cleanly exit fullscreen.
#   - Performance: GIF start() and stop() bound directly to play/pause transitions to
#     freeze/resume animations inline alongside media playback.
#   - Page Switch Safety: Navigating away from Karaoke page index 2 triggers automatic
#     clean up: stops GIF playback, resets to frame 0, and exits fullscreen mode.
#
# --- v2.8: Autoplay Karaoke Mode State Reset (2026-05-29) ---
#
# BUG: Autoplay Desync loops or breaks on naturally finishing a Karaoke track.
#   Root cause: When a song finishes naturally inside Karaoke Mode, self._karaoke_mode
#   remained flagged as True inside player_engine.py. When the main thread's
#   autoplay advanced to play the next song, player_engine.py attempted to load
#   and seek inside the dual-channel mixer using stale/missing stem files, resulting
#   in undefined loops and loader errors.
#
# FIX: player_engine.py — update_polling() reset
#   Inside the track finished logic block:
#     - Explicitly resets self._karaoke_mode to False if it was True.
#     - Invokes self.clear_karaoke_channels() to release all Pygame sound resources.
#
# FIX: main.py — play_next_track() reset
#   At the very top of play_next_track():
#     - Checks self.karaoke_mode_active.
#     - Automatically calls self._deactivate_karaoke_mode() to reset all UI controls,
#       hide guide volume sliders, restore regular playback buttons, and cleanly transition
#       the player back to regular streaming engine mode BEFORE loading the next song.
#
# --- v2.9: Continuous Karaoke Autoplay Intent-Passing (2026-05-29) ---
#
# NEW FEATURE: Continuous Karaoke Autoplay
#   - Keeps user in Full Karaoke Mode when tracks advance naturally or via Next/Prev clicks,
#     provided the subsequent track contains synchronized lyrics.
#   - Intent-Passing Architecture: play_next_track() and play_previous_track() capture the
#     pre-transition karaoke mode state ('was_karaoke') and pass it forward to load_and_play_track().
#   - load_and_play_track() takes an optional auto_karaoke parameter:
#       - If True and the new track contains lyrics, it swaps layout to the Karaoke page and
#         uses a QTimer singleShot (100ms delay) to automatically activate the dual-channel mixer and mic.
#       - If True but the track lacks lyrics, it falls back to regular mode and drops the user
#         back to the library stack index 0 cleanly and gracefully.
#   - Repeat Mode Support: on_track_finished() similarly intercepts loop intents. Re-runs deactivation,
#     re-seeks the stream naturally, and triggers the hotswap mixer with a 100ms singleShot delay.
#
# --- v3.0: Autoplay Path Resolution, Fullscreen Persistence & Next Up UI (2026-05-29) ---
#
# BUG FIX: Autoplay Pointer Overwrite — Index 0 Jump During Karaoke Mode
#   Root cause: play_next_track() and play_previous_track() both resolved the
#   current track path from self.player.current_track. During Karaoke Mode, that
#   property points to the *instrumental WAV* path inside the instrumentals/ folder,
#   NOT the original MP3 in the library. Since no scanned_songs entry matches a
#   WAV path, the enumeration loop falls through without finding a match, leaving
#   next_idx/prev_idx at its initialized value of 0 — forcing the playlist to
#   always jump back to the very first song.
#   Fix: Both methods now conditionally resolve curr_path from self.original_track_path
#   when was_karaoke is True. This guarantees the library index search matches the
#   original MP3, advancing correctly to song N+1 (or N-1).
#
# NEW FEATURE: Fullscreen State Persistence Across Continuous Karaoke Tracks
#   Problem: During continuous karaoke autoplay, each track transition called
#   _deactivate_karaoke_mode() which unconditionally exited fullscreen. This caused
#   an awkward visual flash (fullscreen → windowed → fullscreen) between every song.
#   Fix: _deactivate_karaoke_mode() now accepts a keep_fullscreen=False parameter.
#   load_and_play_track() calculates keep_fs = auto_karaoke AND song.has_karaoke.
#   When both conditions are true (continuous karaoke chaining), the fullscreen
#   toggle is bypassed entirely — producing a seamless, uninterrupted immersive
#   experience across track boundaries.
#
# NEW FEATURE: Next Up Preview UI on Karaoke Screen
#   - QLabel self.lbl_next_up added at the bottom of setup_karaoke_page().
#   - Styled with dark background (#0A0A0A), subtle border, and dim text (#888888).
#   - Updated dynamically inside load_and_play_track() after playback starts:
#       - If shuffle is ON: displays "Random Track (Shuffle ON)".
#       - If shuffle is OFF: resolves (curr_idx + 1) % len(scanned_songs) and
#         displays the next song's name.
#       - If the current song can't be found in the library: falls back to
#         "End of Playlist".
#   - Provides clear visual feedback so karaoke users always know what's coming next.
#
# --- v3.1: Mic Latency Optimization & Whisper Model RAM Caching (2026-05-29) ---
#
# OPTIMIZATION: mic_worker.py — Low-Latency 512-Frame Buffer
#   Changed CHUNK from 1024 to 512 frames, cutting the blocking read() time
#   from ~23ms to ~11ms. This tightens the round-trip voice-to-speaker latency
#   significantly, making the karaoke singing experience feel more immediate.
#   DELAY_CHUNKS was compensated from 8 to 16 to preserve the original ~0.19s
#   echo delay (16 * 512 / 44100 ≈ 0.186s ≈ 8 * 1024 / 44100 ≈ 0.186s).
#   All thread ownership contracts and C-level segfault protections are preserved.
#   stop() log message updated to reflect the new ~11ms exit window.
#
# OPTIMIZATION: karaoke_engine.py — Global Whisper Model Cache
#   Root problem: The large-v3 Whisper model (~3GB) was instantiated locally
#   inside KaraokeProcessorWorker.run_ml_pipeline() on every single invocation.
#   In a bulk queue of N songs, this caused N redundant disk-to-RAM reloads —
#   each taking 30-60 seconds depending on storage speed.
#   Fix: Added module-level _WHISPER_MODEL_CACHE = None. On first call,
#   stable_whisper.load_model() populates the cache. All subsequent calls in
#   the same session reuse the cached model with zero load overhead.
#   The progress bar message differentiates first-load ("first time only...")
#   from cache hits ("Using cached...") for clear user feedback.
#   Memory note: The model persists in RAM for the lifetime of the app process.
#   This is intentional — users processing karaoke playlists benefit from the
#   persistent cache, and 3GB is acceptable on modern systems with 16GB+ RAM.
#
# --- v3.2: UI Polish — Sync Badges, Text DL Search, Native Minimize Hook & Marquee (2026-05-29) ---
#
# FIX: Sync Badge Instant Refresh
#   process_next_karaoke_item() now calls populate_library_table() immediately
#   after assigning the active worker. This forces the library table to re-render
#   badges in real-time, snapping the active song row from "⏳ Queue" to
#   "⚡ Syncing" the instant the worker thread starts — not when it finishes.
#
# NEW FEATURE: Text-Based Search in Downloader
#   The URL input field (txt_yt_urls) now accepts plain-text song names alongside
#   URLs. Any non-http, non-ytsearch line is auto-prefixed with "ytsearch1:" and
#   fed directly to yt-dlp as a search query. Users can now paste lists like:
#     Bruno Mars - Uptown Funk
#     Adele - Hello
#   and yt-dlp acts as a search engine, auto-downloading the top result for each.
#   Placeholder text updated to inform users of this new capability.
#
# CLEANUP: Next Up Label
#   Removed the ⏭ emoji from the karaoke screen's "Next Up" preview label for
#   a cleaner, more readable appearance.
#
# NEW FEATURE: Native OS Minimize Hook → Mini Player
#   Added changeEvent() override to MozZzartPlayerApp. When the user clicks the
#   native Windows minimize button (or Win+D), the app intercepts the
#   WindowStateChange event, detects isMinimized(), and triggers show_mini_player()
#   on the next event loop tick via QTimer.singleShot(0). show_mini_player() now
#   calls showNormal() before hide() when minimized, ensuring the taskbar entry
#   is cleanly removed without visual artifacts.
#
# NEW FEATURE: Marquee Scrolling Title in Mini Player
#   MiniPlayerWindow now has a QTimer-driven marquee effect for long song titles
#   (>20 characters). When playing, the padded title string rotates rightward
#   every 250ms, displaying a sliding 25-character window. The marquee pauses
#   when playback pauses and resumes when playback resumes. Short titles are
#   displayed statically (truncated with "..." if >25 chars).
#   sync_state() now routes through update_track_info() and update_play_state()
#   instead of directly setting labels, ensuring consistent marquee behavior.
#
# --- v3.3: Flask Client-Server Media Streaming Architecture (2026-05-29) ---
#
# ARCHITECTURAL PIVOT: Replaced OS-level screen mirroring concept with a true
#   Client-Server media streaming architecture using Flask.
#
# NEW FILE: web_remote.py
#   - Flask app serving a dark-themed HTML5 TV/Mobile remote interface on port 8080.
#   - /            — Renders the TV UI with play/pause/prev/next/karaoke buttons.
#   - /api/state   — Returns JSON with current track_path, title, is_playing, karaoke_mode.
#   - /api/cmd/<c> — Receives commands from the TV buttons and emits pyqtSignal back to GUI.
#   - /stream      — Serves the current audio file with Flask's native byte-range (206)
#                    support, allowing TV browsers to natively buffer and play the track
#                    via the HTML5 <audio> tag.
#   - WebRemoteWorker(QThread) wraps the Flask server in a daemon thread.
#   - Global APP_STATE dict bridges PyQt state to Flask routes without thread locks
#     (Python GIL provides sufficient safety for simple dict writes).
#   - get_local_ip() resolves the machine's LAN IP for display in the UI.
#
# NEW DEPENDENCY: flask
#   - pip install flask
#
# INTEGRATION POINTS (main.py):
#   - WebRemoteWorker initialized in MozZzartPlayerApp.__init__() and started immediately.
#   - command_received signal wired to _handle_web_command() which routes play/next/prev/karaoke.
#   - broadcast_state_to_web() helper pushes current playback state to APP_STATE.
#     Intelligently streams the instrumental WAV during Karaoke Mode (from lyrics_db)
#     or the original MP3 during regular playback.
#   - Broadcast hooks added to: load_and_play_track(), toggle_playback(),
#     toggle_full_karaoke_mode(), and _deactivate_karaoke_mode().
#
# PARTY MODE USAGE:
#   1. Launch MozZzart on the PC.
#   2. Open http://<PC_IP>:8080 on your Smart TV browser.
#   3. Set PC volume to 0% — TV plays the backing track over Wi-Fi.
#   4. Hardware amp handles live mics as usual.
#   5. TV remote buttons control playback; state syncs every 1 second.
#
# --- v3.4: Headless SPA Frontend — Zero-Latency Lyrics & Remote Library (2026-05-29) ---
#
# REWRITE: web_remote.py — Full Single Page Application
#   Replaced the basic TV remote with a tabbed SPA featuring two views:
#
#   Screen Tab (🎤):
#   - Displays the current track title in gold.
#   - Renders the full synchronized lyrics DOM from the lyrics_db JSON.
#   - Word-level highlighting driven directly by audio.ontimeupdate (HTML5 native).
#     This bypasses all server polling for sync — the browser's own audio clock
#     fires 4x/sec, giving sub-250ms highlight latency with zero network overhead.
#   - Smart scroll: scrollIntoView() only fires when the active LINE changes,
#     not on every timeupdate tick, preventing jitter.
#   - Lyrics DOM is rebuilt only when lyrics JSON changes (Live Edit support).
#
#   Library Tab (📚):
#   - Lists all scanned_songs with name and Karaoke badge.
#   - Tapping a song emits play_idx:<n> command to load it directly on the PC.
#   - Library HTML is diffed against a cached JSON string — DOM is only rewritten
#     when the library contents actually change, preventing flicker.
#
# UPDATED: broadcast_state_to_web() in main.py
#   - Now packages library_data (list of {idx, name, has_karaoke}) and
#     lyrics_data (raw lyrics_db dict) into the state broadcast.
#   - update_state() signature in WebRemoteWorker extended to accept both.
#   - Broadcast hook added to scan_music_library() so the web Library tab
#     refreshes automatically whenever the user switches playlists.
#
# UPDATED: handle_web_remote_command() in main.py
#   - Renamed from _handle_web_command (kept as thin shim for signal wiring).
#   - Added play_idx:<n> handler: parses the index, validates bounds,
#     and calls load_and_play_track(scanned_songs[idx]) directly.
#   - Karaoke toggle now navigates to page 2 first if not already there.
#
# --- v3.5: Dual-Channel Streaming, Find-a-Song, TV Dashboard (2026-05-29) ---
#
# REWRITE: web_remote.py — Full TV Dashboard SPA
#   Major architectural upgrade to the Flask Web Remote:
#
#   DUAL-CHANNEL AUDIO STREAMING:
#   - Two HTML5 <audio> tags: audInst (instrumental) and audVoc (vocal guide at 10%).
#   - /stream serves the main track (instrumental in karaoke mode, MP3 otherwise).
#   - /stream_vocal serves the vocal guide WAV when karaoke is active.
#   - 0.3-second drift correction: if audVoc drifts >300ms from audInst, it's snapped back.
#   - Mid-song toggle safety: disabling karaoke pauses/flushes audVoc immediately;
#     enabling karaoke mid-song hot-swaps audVoc with currentTime sync.
#
#   BOTTOM-TAB NAVIGATION:
#   - Controls (play/prev/next/karaoke) pinned at bottom with tab bar below.
#   - Three tabs: 🎤 Screen (karaoke), 📚 Library, 🔍 Find a Song.
#
#   DANCING MOZART GIF:
#   - /asset/mozart route serves 'mozart dance.gif' from project root.
#   - Two CSS-positioned divs (left + mirrored right) appear only during karaoke mode
#     on the Screen tab. Hidden on Library/Find tabs.
#
#   FIND A SONG TAB:
#   - Text input with real-time library filter (client-side search).
#   - "⬇ Download" button sends download:<query> command to the Python backend,
#     which injects it into txt_yt_urls and triggers trigger_youtube_download().
#   - Live download progress cards rendered from dl_status array.
#
# UPDATED: broadcast_state_to_web() in main.py
#   - Now race-condition safe: entire body wrapped in try/except.
#   - Pushes vocal_path (from player._last_vocal_path) when karaoke is active.
#   - Collects live download progress from download_progress_widgets safely
#     (catches RuntimeError from widget cleanup deletion races).
#   - update_state() signature extended: +vocal_path, +dl_status.
#
# UPDATED: handle_web_remote_command() in main.py
#   - Added download:<query> handler: URL-decodes the query, injects it into
#     the downloader text field, and triggers the download pipeline.
#
# --- v3.7: Master Clock Synchronization & Drift Correction (2026-05-29) ---
#
# MASTER CLOCK PROTOCOL:
# - TV browser now perfectly seeks and locks to the host PC timestamp during mode transitions.
# - Captures the player's exact floating-point timestamp and passes it to the web remote worker.
# - Implements 1.5s drift correction: if the TV drifts more than 1.5 seconds from the PC, it snaps back.
#
# --- v3.9: Layout Bursting & Repaint Fix (2026-05-29) ---
#
# LAYOUT & REPAINT FIXES:
# - Removed restrictive SetMinAndMaxSize constraint from lyrics layout.
# - Enforced strict boundaries on the lyric scroll area so it absorbs dynamic font resizing.
# - Added forced repaints and layout activations (QApplication.processEvents, centralWidget().layout().activate())
#   during fullscreen and karaoke mode toggles to keep the bottom media bar locked to the screen.
#
# --- v3.11: Maximized Window Layout Fix (2026-05-29) ---
#
# MAXIMIZED WINDOW LAYOUT SYNC:
# - Replaced the window-breaking resize hack with internal layout invalidations (invalidate()) and activate().
# - Applied SetNoConstraint to the lyrics layout to prevent massive minimumSizeHint explosions (e.g., 1636px height)
#   from pushing controls off-screen.
#
# --- v3.13: The Layout Firewall (2026-05-29) ---
#
# THE LAYOUT FIREWALL:
# - Discovered that deeply nested QScrollArea SizeHints were forcing the QMainWindow minimum height to 1636px,
#   causing OS-level window clipping and off-screen bottom player controls.
# - Applied SetNoConstraint to the absolute root main_layout and set a manual setMinimumSize(1024, 720) to
#   permanently sever layout size bubbling.
#
# --- v3.14: Settings Layout Squish Fix (2026-05-29) ---
#
# SETTINGS SCROLL WRAPPER:
# - Wrapped setup_settings_page in a QScrollArea to immunize it from the Ignored vertical size constraints
#   of the parent QStackedWidget, preventing buttons and comboboxes from being crushed.
# - Added F11 diagnostic settings debug probe.
#
# --- v3.15: Custom Title Bar & Global GIF Playlist (2026-05-29) ---
#
# CUSTOM TITLE BAR & VISUAL OVERHAUL:
# - Translucent frameless QMainWindow with CustomTitleBar and bottom-right QSizeGrip.
# - Replaced artist label with static QPixmap logo.
# - Added dynamic settings-based GIF playlist manager and global sequential GIF rotation synchronized with the Flask Web Remote.
#
# --- v4.9: Explicit Hardware Acceleration (2026-05-30) ---
#
# EXPLICIT HARDWARE ACCELERATION:
# - Hardened the AI processing pipelines against silent CPU fallbacks.
# - Modified the Demucs subprocess invocation block to inject the -d cuda argument.
# - Forced device="cuda" inside the stable_whisper.load_model cache factory to guarantee NVIDIA GPU processing blocks execute natively.
#
# --- v4.10: Smart Hardware Fallback (2026-05-30) ---
#
# SMART HARDWARE FALLBACK:
# - Upgraded karaoke_engine.py to intelligently detect environment hardware using torch.cuda.is_available().
# - The pipeline now dynamically assigns processing_device to either "cuda" or "cpu", guaranteeing maximum GPU performance for NVIDIA users while preventing fatal crashes for users sharing the app on unsupported hardware.
#
# ==============================================================================
#
# --- v4.11-4.12: Universal Cross-Platform Architecture & UI Overhaul (2026-05-30) ---
#
# CROSS-PLATFORM ARCHITECTURE:
# - Patched AI hardware routing to support Apple Silicon (MPS) via torch.backends.mps.
# - Demucs subprocess guards MPS→CPU since Demucs CLI does not support Metal natively.
# - Added set_run_on_startup() for macOS .plist (LaunchAgents) and Linux .desktop (XDG autostart).
# - Hardened utils.py downloader to detect sys.platform for yt-dlp and FFmpeg URLs.
# - Added os.chmod(0o755) for Unix binary executability.
# - Added cross-OS config sanitizer in ensure_music_dir_exists() to prevent fatal crashes
#   when a Windows config.json is loaded on macOS/Linux (detects drive letter paths).
# - Added Linux Wayland transparency fix (QT_QPA_PLATFORM="xcb") before QApplication init.
# - Added native OS media key support (Key_MediaPlay/Pause/Next/Previous) in keyPressEvent.
#
# UI OVERHAUL:
# - Replaced all 18 Windows-exclusive Segoe MDL2 Assets Unicode glyphs with universal
#   qtawesome (FontAwesome 5 Solid) vector icons across main bar and mini player.
# - Purged font-family: 'Segoe MDL2 Assets' from 7 stylesheet locations (styles.py + main.py inline).
# - All setText() glyph calls converted to setIcon(qta.icon()) for cross-platform rendering.
#
# libVLC MIGRATION BLUEPRINT:
# - Created player_engine_vlc.py with robust C-thread safety (air-gap pattern),
#   parsing race conditions (MediaPlayerPlaying event instead of 50ms QTimer hack),
#   macOS dylib routing (VLC_PLUGIN_PATH), and future video handle routing.
#
# --- v5.1: libVLC State Race Condition Fixes (2026-05-30) ---
#
# v5.1: libVLC State Race Condition Fixes. Resolved a bug where toggling karaoke mode while paused trapped the deferred seek logic by switching the check from .is_playing() to vlc.State.Playing/Paused. Fixed the "Vocal volume bleeding into Normal mode" bug by introducing a deferred volume caching system (_pending_main_volume), guaranteeing VLC accepts audio_set_volume commands after the Opening phase concludes.
#
# --- v5.6 - 5.7: Multi-Platform Portable libVLC & OTA Updates (2026-05-30) ---
#
# v5.6 - 5.7: Multi-Platform Portable libVLC & OTA Updates. Implemented unified local bin/vlc/
# discovery logic across win32, darwin, and linux. Delivered bundle_vlc.py for automated binary
# extraction. Built asynchronous GitHub release checker and external updater.py featuring strict
# exclusion zones (config.json, bin/) to safely bypass OS file-locks during live patches. Fixed
# VLC async duration parsing bug (switched to synchronous mutagen) and volume persistence bug
# in resume_regular_mode() (master volume now cached and restored across karaoke toggles).
#
# ==============================================================================


