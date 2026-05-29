import os
import json
import logging
from utils import get_app_dir

logger = logging.getLogger("PlayerConfig")

DEFAULT_CONFIG = {
    "music_root_dir": "",
    "volume": 70,
    "use_mock_karaoke": False, # Exclusively run true ML pipeline (Demucs + Whisper stable-ts)
    "whisper_language": None,  # Language override for Whisper (None = auto-detect)
    "download_instruments": True,  # Save instrumental stems for True Karaoke Mode
    "reverb_intensity": 0.35,  # Mic echo/reverb DSP intensity (0.0 - 1.0)
    "last_playlist": "",
    "shuffle": False,
    "repeat": False,
    "spotify_client_id": "",
    "spotify_client_secret": "",
    "web_remote_enabled": True
}

def get_config_path():
    """Gets the path to the portable config.json."""
    return os.path.join(get_app_dir(), "config.json")

def load_config():
    """Loads config.json from disk. Creates it with defaults if missing."""
    config_path = get_config_path()
    if not os.path.exists(config_path):
        logger.info(f"config.json not found. Initializing with default config.")
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
        
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            # Ensure all default keys exist
            for key, val in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = val
            return config
    except Exception as e:
        logger.error(f"Error loading config.json: {e}. Resetting to defaults.")
        return DEFAULT_CONFIG.copy()

def save_config(config_data):
    """Saves the config dictionary to config.json."""
    config_path = get_config_path()
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        logger.debug(f"Saved config: {config_data}")
        return True
    except Exception as e:
        logger.error(f"Error saving config.json: {e}")
        return False
