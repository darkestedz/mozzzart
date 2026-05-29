import os
import sys
import logging
import urllib.request
import zipfile
import tempfile
import shutil

# Setup Logging
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("PlayerUtils")

def get_app_dir():
    """Gets the folder where the application or executable is running."""
    if getattr(sys, 'frozen', False):
        # Running as compiled PyInstaller executable
        return os.path.dirname(sys.executable)
    else:
        # Running as standard Python script
        return os.path.dirname(os.path.abspath(__file__))

def get_bin_dir():
    """Get path to the local bin/ folder."""
    bin_dir = os.path.join(get_app_dir(), "bin")
    os.makedirs(bin_dir, exist_ok=True)
    return bin_dir

def get_models_dir():
    """Get path to the local models/ folder."""
    models_dir = os.path.join(get_app_dir(), "models")
    os.makedirs(models_dir, exist_ok=True)
    return models_dir

def get_ffmpeg_path():
    """Returns the absolute path to local ffmpeg.exe."""
    return os.path.join(get_bin_dir(), "ffmpeg.exe")

def get_ytdlp_path():
    """Returns the absolute path to local yt-dlp.exe."""
    return os.path.join(get_bin_dir(), "yt-dlp.exe")

def has_dependencies():
    """Checks if local ffmpeg.exe and yt-dlp.exe exist."""
    ffmpeg_exists = os.path.isfile(get_ffmpeg_path())
    ytdlp_exists = os.path.isfile(get_ytdlp_path())
    return ffmpeg_exists and ytdlp_exists

def download_file_with_progress(url, dest_path, progress_callback=None):
    """Downloads a file from a URL with optional progress callback (receives float 0.0 - 1.0)."""
    logger.info(f"Starting download of {url} to {dest_path}")
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response:
            total_size = int(response.info().get('Content-Length', 0))
            bytes_downloaded = 0
            block_size = 8192
            
            with open(dest_path, 'wb') as f:
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    f.write(buffer)
                    bytes_downloaded += len(buffer)
                    if total_size > 0 and progress_callback:
                        progress = bytes_downloaded / total_size
                        progress_callback(progress)
        logger.info(f"Download complete: {dest_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        return False

def setup_dependencies(progress_callback=None, status_callback=None):
    """
    Downloads and installs ffmpeg.exe and yt-dlp.exe locally if missing.
    progress_callback receives a float (0.0 to 1.0)
    status_callback receives a status string
    """
    bin_dir = get_bin_dir()
    ffmpeg_path = get_ffmpeg_path()
    ytdlp_path = get_ytdlp_path()
    
    # 1. Setup yt-dlp
    if not os.path.isfile(ytdlp_path):
        if status_callback:
            status_callback("Downloading yt-dlp.exe...")
        ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        
        # We will split progress between yt-dlp (20%) and ffmpeg (80%)
        def ytdlp_progress(p):
            if progress_callback:
                progress_callback(p * 0.2)
                
        success = download_file_with_progress(ytdlp_url, ytdlp_path, ytdlp_progress)
        if not success:
            raise Exception("Failed to download yt-dlp.exe")
    else:
        logger.info("yt-dlp.exe already exists.")
        if progress_callback:
            progress_callback(0.2)

    # 2. Setup ffmpeg
    if not os.path.isfile(ffmpeg_path):
        if status_callback:
            status_callback("Downloading FFmpeg zip package...")
        
        # yt-dlp hosted ffmpeg builds are highly compatible and standard
        ffmpeg_url = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        
        temp_zip = os.path.join(tempfile.gettempdir(), "ffmpeg_temp.zip")
        
        def ffmpeg_progress(p):
            if progress_callback:
                progress_callback(0.2 + (p * 0.7)) # ffmpeg download is 70% of total
                
        success = download_file_with_progress(ffmpeg_url, temp_zip, ffmpeg_progress)
        if not success:
            raise Exception("Failed to download FFmpeg zip archive")
            
        if status_callback:
            status_callback("Extracting FFmpeg...")
            
        try:
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                # Find ffmpeg.exe inside the zip file
                # The zip structure is usually: ffmpeg-master-latest-win64-gpl/bin/ffmpeg.exe
                ffmpeg_member = None
                ffprobe_member = None
                for member in zip_ref.namelist():
                    if member.endswith("ffmpeg.exe"):
                        ffmpeg_member = member
                    elif member.endswith("ffprobe.exe"):
                        ffprobe_member = member
                
                if ffmpeg_member:
                    # Extract ffmpeg.exe
                    with zip_ref.open(ffmpeg_member) as source, open(ffmpeg_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
                    logger.info("Successfully extracted ffmpeg.exe")
                else:
                    raise Exception("ffmpeg.exe not found in downloaded zip archive.")
                    
                if ffprobe_member:
                    ffprobe_path = os.path.join(bin_dir, "ffprobe.exe")
                    with zip_ref.open(ffprobe_member) as source, open(ffprobe_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
                    logger.info("Successfully extracted ffprobe.exe")
        finally:
            if os.path.exists(temp_zip):
                try:
                    os.remove(temp_zip)
                except Exception:
                    pass
                    
        if progress_callback:
            progress_callback(1.0)
        if status_callback:
            status_callback("FFmpeg extraction completed successfully!")
    else:
        logger.info("ffmpeg.exe already exists.")
        if progress_callback:
            progress_callback(1.0)
            
    return True

def update_ytdlp():
    """Updates yt-dlp to the latest version."""
    ytdlp_path = get_ytdlp_path()
    temp_ytdlp = ytdlp_path + ".new"
    ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    
    logger.info("Checking/Updating yt-dlp to the latest release...")
    try:
        success = download_file_with_progress(ytdlp_url, temp_ytdlp)
        if success:
            if os.path.exists(ytdlp_path):
                os.remove(ytdlp_path)
            os.rename(temp_ytdlp, ytdlp_path)
            logger.info("yt-dlp updated successfully!")
            return True
    except Exception as e:
        logger.error(f"Failed to update yt-dlp: {e}")
        if os.path.exists(temp_ytdlp):
            try:
                os.remove(temp_ytdlp)
            except Exception:
                pass
    return False

def configure_logger_to_file():
    """Adds a file handler to log directly to portable app.log file."""
    log_file = os.path.join(get_app_dir(), "app.log")
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(file_handler)
    logger.info(f"File logging configured. Logs saved to: {log_file}")

def bind_ffmpeg_to_path():
    """Prepends the local bin/ directory containing FFmpeg to the system environment PATH."""
    bin_dir = get_bin_dir()
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    logger.info(f"Dynamically bound local bin/ to system PATH: {bin_dir}")
