import sys
import os
import time
import traceback
import subprocess
from PyQt6.QtCore import QCoreApplication, QTimer
from player_engine_vlc import AudioPlayer

class TestRunner:
    def __init__(self, track_path):
        self.app = QCoreApplication(sys.argv)
        self.player = AudioPlayer()
        self.track_path = track_path
        self.timer = QTimer()
        self.timer.timeout.connect(self.player.update_polling)
        self.timer.start(100)
        
        self.test_idx = 0
        self.tests = [
            self.test_3_2_volume_persistence,
            self.test_4_1_path_sanitization,
            self.test_4_2_headless_boot
        ]
        
        self.player.state_changed.connect(self.on_state_changed)
        self.player.track_finished.connect(self.on_track_finished)
        
        self.current_state = "stopped"
        self.finished_flag = False

    def on_state_changed(self, state):
        self.current_state = state

    def on_track_finished(self):
        self.finished_flag = True

    def log(self, msg):
        print(f"[TEST] {msg}")

    def wait_seconds(self, secs):
        start = time.time()
        while time.time() - start < secs:
            self.app.processEvents()
            time.sleep(0.01)

    def start(self):
        self.log("Starting Extended Automated Tests (3.2, 4.1, 4.2)...")
        self.run_next_test()
        self.app.exec()

    def run_next_test(self):
        if self.test_idx < len(self.tests):
            try:
                self.tests[self.test_idx]()
            except Exception as e:
                self.log(f"Test {self.test_idx} failed with exception: {e}")
                traceback.print_exc()
                self.next_test()
        else:
            self.log("All tests finished.")
            self.app.quit()

    def next_test(self):
        self.test_idx += 1
        QTimer.singleShot(1000, self.run_next_test)

    # --- Test 3.2 ---
    def test_3_2_volume_persistence(self):
        self.log("--- Running Test 3.2: Volume Persistence Across Karaoke Toggles ---")
        
        # Start regular play
        self.player.load_track(self.track_path)
        self.player.play()
        self.wait_seconds(0.5)
        
        self.player.set_volume(50)
        self.wait_seconds(0.5)
        main_vol = self.player._player_main.audio_get_volume()
        assert main_vol == 50, f"Main volume is {main_vol}, expected 50"
        
        # Start Karaoke
        self.log("Starting Karaoke Mode...")
        self.player.start_karaoke_mixer(self.track_path, self.track_path, start_time=1.0, vocal_volume=0.25)
        self.wait_seconds(1.0)
        
        main_vol = self.player._player_main.audio_get_volume()
        vocal_vol = self.player._player_vocal.audio_get_volume()
        
        assert main_vol == 50, f"Karaoke Main volume is {main_vol}, expected 50"
        assert vocal_vol == 25, f"Karaoke Vocal volume is {vocal_vol}, expected 25"
        
        # Switch back to regular mode
        self.log("Switching back to regular mode...")
        self.player.resume_regular_mode(self.track_path, start_time_sec=2.0)
        self.wait_seconds(1.0)
        
        # NOTE: resume_regular_mode in player_engine_vlc.py currently does NOT re-apply _master_volume!
        # Wait, let's see if it does. If it fails, we found a bug!
        main_vol = self.player._player_main.audio_get_volume()
        if main_vol != 50:
            self.log(f"BUG DETECTED! Regular mode volume reset to {main_vol} instead of 50.")
            assert False, f"Volume lost after karaoke toggle! Expected 50, got {main_vol}"
            
        self.log("Test 3.2 Passed!")
        self.player.stop()
        self.next_test()

    # --- Test 4.1 ---
    def test_4_1_path_sanitization(self):
        self.log("--- Running Test 4.1: Cross-Platform Path Sanitization ---")
        import main
        import config
        class MockWindow:
            def __init__(self):
                # Fake a macOS path if on Windows, or vice versa
                if sys.platform == "win32":
                    fake_path = "/Users/Steve/Music"
                else:
                    fake_path = "C:\\Users\\Steve\\Music"
                    
                self.config = {"music_root_dir": fake_path}
                
            ensure_music_dir_exists = main.MozZzartPlayerApp.ensure_music_dir_exists
            
        mock = MockWindow()
        mock.ensure_music_dir_exists()
        
        # Check if the path was sanitized
        final_path = mock.config["music_root_dir"]
        self.log(f"Sanitized Path: {final_path}")
        assert "Steve" not in final_path, "Path was not sanitized!"
        assert os.path.exists(final_path), "Fallback directory was not created!"
        
        self.log("Test 4.1 Passed!")
        self.next_test()

    # --- Test 4.2 ---
    def test_4_2_headless_boot(self):
        self.log("--- Running Test 4.2: Auto-Boot (Headless Init) ---")
        self.log("Spawning main.py as a subprocess for 8 seconds...")
        
        try:
            # Run main.py as a subprocess
            process = subprocess.Popen(
                [sys.executable, "main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait for 8 seconds, then kill it
            time.sleep(8)
            process.terminate()
            stdout, stderr = process.communicate(timeout=5)
            
            # Analyze logs
            logs = stdout + stderr
            if "Traceback" in logs or "Exception" in logs:
                self.log(f"Subprocess threw an exception:\n{logs}")
                assert False, "Exceptions thrown during auto-boot"
            
            if "Aura Player MainWindow initialized successfully" in logs:
                self.log("Test 4.2 Passed! App booted gracefully without exceptions.")
            else:
                self.log(f"Did not find initialization string. Logs:\n{logs}")
                assert False, "App did not initialize successfully"
                
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            self.log("Subprocess timeout handling.")
            assert False, "Subprocess hung"
            
        self.next_test()

if __name__ == "__main__":
    track_path = r"C:\\Users\\Smash-Edit\\Desktop\\Webscraping player\\Music\\Avicii - Feeling Good (Lyrics).mp3"
    runner = TestRunner(track_path)
    runner.start()
