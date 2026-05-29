import socket
import logging
import threading
import os
import json
from urllib.parse import unquote
from flask import Flask, jsonify, send_file, render_template_string
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger("WebRemote")

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

app = Flask(__name__)

APP_STATE = {
    'track_path': None,
    'vocal_path': None,
    'title': 'MozZzart Player',
    'is_playing': False,
    'karaoke_mode': False,
    'library': [],
    'lyrics': None,
    'downloads': [],
    'current_time': 0.0,
    'gif_path': 'mozart dance.gif'
}
qt_worker_ref = None

@app.route('/')
def index():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>MozZzart TV</title>
        <style>
            :root { --bg: #050505; --surface: #121212; --primary: #1DB954; --gold: #F0C419; --text: #FFFFFF; --text-dim: #888888; }
            body { background-color: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; overflow: hidden; display: flex; flex-direction: column; height: 100vh; }

            /* Content Areas */
            .view { display: none; flex: 1; overflow-y: auto; padding: 20px; width: 100%; max-width: 900px; margin: 0 auto; padding-bottom: 180px; box-sizing: border-box; }
            .view.active { display: block; }

            /* Bottom Navigation & Controls */
            .bottom-panel { position: fixed; bottom: 0; left: 0; right: 0; background-color: var(--surface); border-top: 1px solid #222; z-index: 200; display: flex; flex-direction: column; }
            .controls { display: flex; gap: 10px; padding: 15px; justify-content: center; }
            .nav { display: flex; gap: 5px; padding: 0 15px 15px 15px; justify-content: center; }

            .btn { background: #1A1A1A; border: 1px solid #333; color: white; padding: 15px; font-size: 16px; font-weight: bold; border-radius: 8px; cursor: pointer; flex: 1; max-width: 140px; }
            .btn:active { background: #333; }
            .btn-gold { border-color: var(--gold); color: var(--gold); }
            .nav-btn { background: transparent; border: none; color: var(--text-dim); font-size: 16px; font-weight: bold; cursor: pointer; padding: 10px; flex: 1; max-width: 150px; transition: 0.2s; }
            .nav-btn.active { color: var(--gold); border-bottom: 2px solid var(--gold); }

            /* Library & Search Lists */
            .song-item { display: flex; justify-content: space-between; align-items: center; padding: 15px; border-bottom: 1px solid #1E1E1E; cursor: pointer; }
            .song-item:hover { background-color: #1A1A1A; }
            .song-title { font-size: 16px; font-weight: bold; }
            .badge-k { background: var(--gold); color: #000; padding: 4px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; }

            .search-box { display: flex; gap: 10px; margin-bottom: 20px; }
            .search-input { flex: 1; padding: 15px; border-radius: 8px; border: 1px solid #333; background: #1A1A1A; color: white; font-size: 16px; }

            /* Karaoke View */
            #tv_title { color: var(--gold); font-size: 26px; text-align: center; margin-bottom: 10px; }
            .lyrics-container { text-align: center; padding-top: 40px; }
            .lyric-line { font-size: 26px; font-weight: bold; color: #444; padding: 15px 10px; transition: 0.3s; }
            .lyric-line.active { font-size: 34px; color: var(--text); }
            .word { transition: color 0.1s; }
            .word.active-word { color: var(--primary); }

            /* Dancing Mozarts */
            .mozart { position: fixed; bottom: 160px; width: 250px; height: 400px; background-image: url('/asset/mozart'); background-size: contain; background-repeat: no-repeat; background-position: bottom; z-index: -1; display: none; }
            .mozart.left { left: 10px; }
            .mozart.right { right: 10px; transform: scaleX(-1); }

            ::-webkit-scrollbar { display: none; }
        </style>
    </head>
    <body>
        <audio id="tv_audio_inst" preload="auto"></audio>
        <audio id="tv_audio_voc" preload="auto"></audio>

        <div id="view_karaoke" class="view active">
            <h2 id="tv_title">MozZzart Player</h2>
            <div id="mozart_left" class="mozart left"></div>
            <div id="mozart_right" class="mozart right"></div>
            <div id="lyrics_container" class="lyrics-container"></div>
        </div>

        <div id="view_library" class="view">
            <div id="library_list"></div>
        </div>

        <div id="view_find" class="view">
            <div class="search-box">
                <input type="text" id="search_input" class="search-input" placeholder="Search library or type song to download..." oninput="filterLibrary()">
                <button class="btn btn-gold" onclick="downloadSong()">⬇ Download</button>
            </div>
            <div id="download_list"></div>
            <div id="filtered_library_list"></div>
        </div>

        <div class="bottom-panel">
            <div class="controls">
                <button class="btn btn-gold" onclick="sendCmd('karaoke')">🎤 Mode</button>
                <button class="btn" onclick="sendCmd('prev')">⏮ Prev</button>
                <button class="btn" onclick="sendCmd('play')">⏯ Play/Pause</button>
                <button class="btn" onclick="sendCmd('next')">⏭ Next</button>
            </div>
            <div class="nav">
                <button class="nav-btn active" onclick="switchTab('karaoke', this)">🎤 Screen</button>
                <button class="nav-btn" onclick="switchTab('library', this)">📚 Library</button>
                <button class="nav-btn" onclick="switchTab('find', this)">🔍 Find a Song</button>
            </div>
        </div>

        <script>
            const audInst = document.getElementById('tv_audio_inst');
            const audVoc = document.getElementById('tv_audio_voc');
            audVoc.volume = 0.10; // 10% Vocal Guide Volume

            const lyricsDiv = document.getElementById('lyrics_container');
            let currentPath = null;
            let currentLyrics = null;
            let stateData = null;
            let activeLineId = null;
            let libraryJson = "[]";
            let APP_STATE_GIF = null;

            function switchTab(tab, btn) {
                document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
                document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
                document.getElementById('view_' + tab).classList.add('active');
                if (btn) btn.classList.add('active');
                updateMozarts();
            }

            function updateMozarts() {
                const isKaraokeTab = document.getElementById('view_karaoke').classList.contains('active');
                if (stateData && stateData.karaoke_mode && isKaraokeTab) {
                    document.getElementById('mozart_left').style.display = 'block';
                    document.getElementById('mozart_right').style.display = 'block';
                } else {
                    document.getElementById('mozart_left').style.display = 'none';
                    document.getElementById('mozart_right').style.display = 'none';
                }
            }

            setInterval(async () => {
                try {
                    const res = await fetch('/api/state');
                    stateData = await res.json();

                    document.getElementById('tv_title').innerText = stateData.title;
                    updateMozarts();

                    if (stateData.gif_path !== APP_STATE_GIF) {
                        APP_STATE_GIF = stateData.gif_path;
                        // Cache-bust the URL to force the TV to load the new GIF
                        const newUrl = "url('/asset/mozart?t=" + Date.now() + "')";
                        document.getElementById('mozart_left').style.backgroundImage = newUrl;
                        document.getElementById('mozart_right').style.backgroundImage = newUrl;
                    }

                    // Update Library UI only when data changes
                    const newLibJson = JSON.stringify(stateData.library);
                    if (newLibJson !== libraryJson) {
                        libraryJson = newLibJson;
                        let libHtml = "";
                        stateData.library.forEach(song => {
                            let badge = song.has_karaoke ? `<span class="badge-k">Karaoke</span>` : ``;
                            libHtml += `<div class="song-item" onclick="sendCmd('play_idx:${song.idx}')">
                                          <span class="song-title">${song.name}</span>${badge}
                                        </div>`;
                        });
                        document.getElementById('library_list').innerHTML = libHtml;
                    }

                    // Update Downloads UI
                    let dlHtml = "";
                    stateData.downloads.forEach(d => {
                        dlHtml += `<div class="song-item" style="cursor:default;">
                                     <div><b style="color:#1DB954;">${d.title}</b><br><small>${d.status} (${d.progress}%)</small></div>
                                   </div>`;
                    });
                    document.getElementById('download_list').innerHTML = dlHtml;

                    // Re-run filter if on Find tab
                    if(document.getElementById('search_input').value) filterLibrary();

                    // Dual-Channel Audio Sync Handling (Master Clock Protocol)
                    const HOST_TIME = stateData.current_time || 0;
                    
                    if (stateData.track_path !== currentPath) {
                        currentPath = stateData.track_path;
                        currentLyrics = stateData.lyrics;
                        buildLyricsDOM();
                        
                        if (currentPath) {
                            audInst.src = '/stream?t=' + Date.now();
                            if (stateData.vocal_path) {
                                audVoc.src = '/stream_vocal?t=' + Date.now();
                            } else {
                                audVoc.removeAttribute('src');
                                audVoc.load();
                            }
                            
                            // Seamless Transition Fix: Wait for audio buffer, then snap to Master Clock
                            audInst.oncanplay = function() {
                                audInst.currentTime = stateData.current_time;
                                if (stateData.vocal_path) audVoc.currentTime = stateData.current_time;
                                audInst.oncanplay = null; // Unbind to prevent loops
                                
                                if (stateData.is_playing) {
                                    audInst.play().catch(e => console.log("Play blocked:", e));
                                    if(stateData.vocal_path) audVoc.play().catch(e => console.log("Voc blocked:", e));
                                }
                            };
                        } else {
                            audInst.pause(); audInst.removeAttribute('src');
                            audVoc.pause(); audVoc.removeAttribute('src');
                        }
                    } else {
                        // Path matches. Check for Master Clock Drift.
                        if (stateData.is_playing) {
                            // If the TV drifts more than 2.5 seconds from the PC, snap it back!
                            if (Math.abs(audInst.currentTime - HOST_TIME) > 2.5) {
                                console.log("Drift detected. Resyncing to Master Clock...", audInst.currentTime, HOST_TIME);
                                audInst.currentTime = HOST_TIME;
                                if (stateData.vocal_path && !audVoc.paused) audVoc.currentTime = HOST_TIME;
                            }
                            
                            // Mid-song Vocal Guide toggle safety
                            if (!stateData.vocal_path && audVoc.src && !audVoc.paused) {
                                audVoc.pause(); audVoc.removeAttribute('src'); audVoc.load();
                            } else if (stateData.vocal_path && !audVoc.src) {
                                audVoc.src = '/stream_vocal?t=' + Date.now();
                                audVoc.currentTime = HOST_TIME;
                                audVoc.play().catch(e=>console.log(e));
                            }

                            if (audInst.paused) audInst.play().catch(e=>console.log(e));
                            if (stateData.vocal_path && audVoc.paused) audVoc.play().catch(e=>console.log(e));
                        } else {
                            if (!audInst.paused) audInst.pause();
                            if (!audVoc.paused) audVoc.pause();
                        }
                        
                        if (JSON.stringify(stateData.lyrics) !== JSON.stringify(currentLyrics)) {
                            currentLyrics = stateData.lyrics;
                            buildLyricsDOM();
                        }
                    }
                } catch (e) { console.log("Waiting for server..."); }
            }, 1000);

            function sendCmd(cmd) { fetch('/api/cmd/' + cmd); }

            function downloadSong() {
                const q = document.getElementById('search_input').value;
                if(q.trim() !== '') {
                    fetch('/api/cmd/download:' + encodeURIComponent(q));
                    document.getElementById('search_input').value = '';
                }
            }

            function filterLibrary() {
                const q = document.getElementById('search_input').value.toLowerCase();
                if (!q || !stateData) { document.getElementById('filtered_library_list').innerHTML = ""; return; }
                let html = "";
                stateData.library.forEach(song => {
                    if(song.name.toLowerCase().includes(q)) {
                        let badge = song.has_karaoke ? `<span class="badge-k">Karaoke</span>` : ``;
                        html += `<div class="song-item" onclick="sendCmd('play_idx:${song.idx}')">
                                    <span class="song-title">${song.name}</span>${badge}
                                </div>`;
                    }
                });
                document.getElementById('filtered_library_list').innerHTML = html;
            }

            function buildLyricsDOM() {
                lyricsDiv.innerHTML = '';
                activeLineId = null;
                if (!currentLyrics || !currentLyrics.lyrics) return;

                currentLyrics.lyrics.forEach((line, lIdx) => {
                    const div = document.createElement('div');
                    div.className = 'lyric-line';
                    div.id = 'line_' + lIdx;
                    div.dataset.start = line.start;
                    div.dataset.end = line.end;
                    if (line.words) {
                        line.words.forEach(w => {
                            const span = document.createElement('span');
                            span.className = 'word';
                            span.dataset.start = w.start;
                            span.innerText = w.word + ' ';
                            div.appendChild(span);
                        });
                    } else { div.innerText = line.text; }
                    lyricsDiv.appendChild(div);
                });
            }

            // Zero-Latency Lyric and Dual-Audio Sync
            audInst.ontimeupdate = () => {
                // Ensure vocal track stays perfectly aligned with instrumental
                if (stateData && stateData.vocal_path && !audVoc.paused) {
                    if (Math.abs(audInst.currentTime - audVoc.currentTime) > 0.3) {
                        audVoc.currentTime = audInst.currentTime;
                    }
                }

                if (!currentLyrics) return;
                const t = audInst.currentTime;
                let currentLineFound = null;

                document.querySelectorAll('.lyric-line').forEach(line => {
                    if (t >= parseFloat(line.dataset.start) && t <= parseFloat(line.dataset.end)) {
                        line.classList.add('active');
                        currentLineFound = line.id;
                    } else {
                        line.classList.remove('active');
                    }
                });

                if (currentLineFound && currentLineFound !== activeLineId) {
                    activeLineId = currentLineFound;
                    document.getElementById(activeLineId).scrollIntoView({behavior: "smooth", block: "center"});
                }
                document.querySelectorAll('.word').forEach(word => {
                    if (t >= parseFloat(word.dataset.start)) word.classList.add('active-word');
                    else word.classList.remove('active-word');
                });
            };
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/api/state')
def get_state():
    return jsonify(APP_STATE)

@app.route('/api/cmd/<command>')
def handle_cmd(command):
    if qt_worker_ref:
        qt_worker_ref.command_received.emit(command)
    return jsonify({"status": "ok"})

@app.route('/stream')
def stream_audio():
    if not APP_STATE['track_path']: return "No track", 404
    return send_file(APP_STATE['track_path'], conditional=True)

@app.route('/stream_vocal')
def stream_vocal():
    if not APP_STATE['vocal_path']: return "No vocal track", 404
    return send_file(APP_STATE['vocal_path'], conditional=True)

@app.route('/asset/mozart')
def asset_mozart():
    path = APP_STATE.get('gif_path', 'mozart dance.gif')
    if os.path.exists(path):
        return send_file(path, mimetype='image/gif')
    return "No image", 404

def run_flask(port):
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

class WebRemoteWorker(QThread):
    command_received = pyqtSignal(str)

    def __init__(self, port=8080):
        super().__init__()
        self.port = port

    def run(self):
        global qt_worker_ref
        qt_worker_ref = self
        logger.info(f"Flask Media Server starting on {get_local_ip()}:{self.port}")
        self.server_thread = threading.Thread(target=run_flask, args=(self.port,), daemon=True)
        self.server_thread.start()
        # Keep the QThread alive so isRunning() returns True for broadcast guards
        self.exec()

    def update_state(self, track_path, vocal_path, title, is_playing, karaoke_mode, library_data, lyrics_data, dl_status, current_time, gif_path):
        APP_STATE['track_path'] = track_path
        APP_STATE['vocal_path'] = vocal_path
        APP_STATE['title'] = title
        APP_STATE['is_playing'] = is_playing
        APP_STATE['karaoke_mode'] = karaoke_mode
        APP_STATE['library'] = library_data
        APP_STATE['lyrics'] = lyrics_data
        APP_STATE['downloads'] = dl_status
        APP_STATE['current_time'] = current_time
        APP_STATE['gif_path'] = gif_path

    def update_clock(self, current_time):
        """Fast-path update for the Master Clock to avoid heavy JSON rebuilds."""
        APP_STATE['current_time'] = current_time
