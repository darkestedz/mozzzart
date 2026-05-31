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
    """Returns the absolute path to the local ffmpeg binary."""
    ext = ".exe" if sys.platform == "win32" else ""
    return os.path.join(get_bin_dir(), f"ffmpeg{ext}")

def get_ytdlp_path():
    """Returns the absolute path to the local yt-dlp binary."""
    ext = ".exe" if sys.platform == "win32" else ""
    return os.path.join(get_bin_dir(), f"yt-dlp{ext}")

def has_dependencies():
    """Checks if local ffmpeg and yt-dlp binaries exist."""
    ffmpeg_exists = os.path.isfile(get_ffmpeg_path())
    ytdlp_exists = os.path.isfile(get_ytdlp_path())
    return ffmpeg_exists and ytdlp_exists

def download_file_with_progress(url, dest_path, progress_callback=None):
    """Downloads a file from a URL with optional progress callback (receives float 0.0 - 1.0)."""
    logger.info(f"Starting download of {url} to {dest_path}")
    
    last_exception = None
    
    # Method 1: Standard urllib secure request
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
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
        logger.info(f"Download complete via standard urllib: {dest_path}")
        return True
    except Exception as e:
        last_exception = e
        logger.warning(f"Standard urllib download failed for {url} ({e}). Retrying with unverified SSL context fallback...")
        
    # Method 2: Unverified SSL context urllib request (fixes Windows root CA certificate issue)
    try:
        import ssl
        context = ssl._create_unverified_context()
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, context=context, timeout=30) as response:
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
        logger.info(f"Download complete via unverified urllib SSL context: {dest_path}")
        return True
    except Exception as e:
        last_exception = e
        logger.warning(f"Unverified SSL context urllib download failed for {url} ({e}). Trying system curl fallback...")

    # Method 3: System curl tool (allows -k for insecure, follows redirects with -L)
    try:
        import subprocess
        import shutil
        if shutil.which("curl"):
            logger.info("curl executable found. Initiating curl subprocess download...")
            cmd = ["curl", "-k", "-L", "-o", dest_path, url]
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            res = subprocess.run(
                cmd, 
                startupinfo=startupinfo,
                capture_output=True, 
                timeout=120
            )
            if res.returncode == 0 and os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                logger.info(f"Download complete via system curl: {dest_path}")
                if progress_callback:
                    progress_callback(1.0)
                return True
            else:
                err_msg = res.stderr.decode("utf-8", errors="ignore").strip()
                logger.warning(f"curl download exited with code {res.returncode}: {err_msg}")
                last_exception = Exception(f"curl exited with code {res.returncode}: {err_msg}")
        else:
            logger.warning("curl is not available in the system PATH.")
    except Exception as e:
        logger.warning(f"curl download failed with exception: {e}")
        last_exception = e

    # Method 4: PowerShell Invoke-WebRequest (Windows specific)
    if sys.platform == "win32":
        try:
            logger.info("Attempting PowerShell WebClient download fallback...")
            import subprocess
            ps_script = (
                "[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}; "
                f"Invoke-WebRequest -Uri '{url}' -OutFile '{dest_path}' -UseBasicParsing"
            )
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            res = subprocess.run(
                cmd, 
                startupinfo=startupinfo,
                capture_output=True, 
                timeout=120
            )
            if res.returncode == 0 and os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                logger.info(f"Download complete via PowerShell: {dest_path}")
                if progress_callback:
                    progress_callback(1.0)
                return True
            else:
                err_msg = res.stderr.decode("utf-8", errors="ignore").strip()
                logger.warning(f"PowerShell download exited with code {res.returncode}: {err_msg}")
                last_exception = Exception(f"PowerShell exited with code {res.returncode}: {err_msg}")
        except Exception as e:
            logger.warning(f"PowerShell download failed with exception: {e}")
            last_exception = e

    # Raise the final consolidated exception if all methods failed
    raise last_exception

def setup_dependencies(progress_callback=None, status_callback=None):
    """
    Downloads and installs ffmpeg.exe and yt-dlp.exe locally if missing.
    progress_callback receives a float (0.0 to 1.0)
    status_callback receives a status string
    """
    bin_dir = get_bin_dir()
    ffmpeg_path = get_ffmpeg_path()
    ytdlp_path = get_ytdlp_path()
    
    # 1. Setup yt-dlp (cross-platform)
    if not os.path.isfile(ytdlp_path):
        if status_callback:
            status_callback("Downloading yt-dlp...")
        if sys.platform == "win32":
            ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        elif sys.platform == "darwin":
            ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
        else:
            ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux"
        
        # We will split progress between yt-dlp (20%) and ffmpeg (80%)
        def ytdlp_progress(p):
            if progress_callback:
                progress_callback(p * 0.2)
                
        try:
            download_file_with_progress(ytdlp_url, ytdlp_path, ytdlp_progress)
        except Exception as e:
            raise Exception(
                f"Failed to download yt-dlp: {e}\n\n"
                "Suggestions to fix:\n"
                "1. Check your internet connection.\n"
                "2. If this machine lacks internet access or blocks GitHub downloads, please manually download 'yt-dlp.exe' from:\n"
                "   https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe\n"
                "   and place it inside the 'bin/' folder next to MozZzartPlayer.exe.\n"
                "3. Verify that the 'bin/' folder has write permissions."
            )
        # Ensure Unix binaries are executable
        if sys.platform != "win32":
            os.chmod(ytdlp_path, 0o755)
    else:
        logger.info("yt-dlp binary already exists.")
        if progress_callback:
            progress_callback(0.2)

    # 2. Setup ffmpeg (cross-platform)
    if not os.path.isfile(ffmpeg_path):
        if status_callback:
            status_callback("Downloading FFmpeg...")
        
        # Platform-specific FFmpeg builds
        if sys.platform == "win32":
            ffmpeg_url = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        elif sys.platform == "darwin":
            ffmpeg_url = "https://evermeet.cx/ffmpeg/getrelease/zip"
        else:
            ffmpeg_url = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
        
        temp_archive = os.path.join(tempfile.gettempdir(), "ffmpeg_temp_archive")
        
        def ffmpeg_progress(p):
            if progress_callback:
                progress_callback(0.2 + (p * 0.7)) # ffmpeg download is 70% of total
                
        try:
            download_file_with_progress(ffmpeg_url, temp_archive, ffmpeg_progress)
        except Exception as e:
            raise Exception(
                f"Failed to download FFmpeg: {e}\n\n"
                "Suggestions to fix:\n"
                "1. Check your internet connection.\n"
                "2. If this machine lacks internet access or blocks GitHub downloads, please manually download the FFmpeg zip from:\n"
                f"   {ffmpeg_url}\n"
                "   extract 'ffmpeg.exe' and 'ffprobe.exe', and place them inside the 'bin/' folder next to MozZzartPlayer.exe.\n"
                "3. Verify that the 'bin/' folder has write permissions."
            )
            
        if status_callback:
            status_callback("Extracting FFmpeg...")
            
        try:
            if ffmpeg_url.endswith(".tar.xz"):
                import tarfile
                with tarfile.open(temp_archive, 'r:xz') as tar:
                    for member in tar.getmembers():
                        basename = os.path.basename(member.name)
                        if basename == "ffmpeg":
                            member.name = basename
                            tar.extract(member, bin_dir)
                            logger.info("Successfully extracted ffmpeg")
                        elif basename == "ffprobe":
                            member.name = basename
                            tar.extract(member, bin_dir)
                            logger.info("Successfully extracted ffprobe")
            else:
                with zipfile.ZipFile(temp_archive, 'r') as zip_ref:
                    ffmpeg_member = None
                    ffprobe_member = None
                    ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
                    ffprobe_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
                    for member in zip_ref.namelist():
                        if member.endswith(ffmpeg_name):
                            ffmpeg_member = member
                        elif member.endswith(ffprobe_name):
                            ffprobe_member = member
                    
                    if ffmpeg_member:
                        with zip_ref.open(ffmpeg_member) as source, open(ffmpeg_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
                        logger.info("Successfully extracted ffmpeg")
                    else:
                        raise Exception("ffmpeg not found in downloaded archive.")
                        
                    if ffprobe_member:
                        ffprobe_path = os.path.join(bin_dir, ffprobe_name)
                        with zip_ref.open(ffprobe_member) as source, open(ffprobe_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
                        logger.info("Successfully extracted ffprobe")
            
            # Ensure Unix binaries are executable
            if sys.platform != "win32":
                os.chmod(ffmpeg_path, 0o755)
                ffprobe_unix = os.path.join(bin_dir, "ffprobe")
                if os.path.exists(ffprobe_unix):
                    os.chmod(ffprobe_unix, 0o755)
        finally:
            if os.path.exists(temp_archive):
                try:
                    os.remove(temp_archive)
                except Exception:
                    pass
                    
        if progress_callback:
            progress_callback(1.0)
        if status_callback:
            status_callback("FFmpeg extraction completed successfully!")
    else:
        logger.info("ffmpeg binary already exists.")
        if progress_callback:
            progress_callback(1.0)
            
    return True

def update_ytdlp():
    """Updates yt-dlp to the latest version (cross-platform)."""
    ytdlp_path = get_ytdlp_path()
    temp_ytdlp = ytdlp_path + ".new"
    if sys.platform == "win32":
        ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    elif sys.platform == "darwin":
        ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
    else:
        ytdlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux"
    
    logger.info("Checking/Updating yt-dlp to the latest release...")
    try:
        success = download_file_with_progress(ytdlp_url, temp_ytdlp)
        if success:
            if os.path.exists(ytdlp_path):
                os.remove(ytdlp_path)
            os.rename(temp_ytdlp, ytdlp_path)
            # Ensure Unix binaries are executable
            if sys.platform != "win32":
                os.chmod(ytdlp_path, 0o755)
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
