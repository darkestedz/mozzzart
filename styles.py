# Spotify-like premium dark theme QSS stylesheet for MozZzart Player & Karaoke
# Rebranded with Yellow (MozZzart Gold #F0C419), Green (MozZzart Green #2D7D46) and deep Black.

SPOTIFY_STYLE = """
/* Global Styles */
QWidget {
    background-color: #080808;
    color: #FFFFFF;
    font-family: 'Outfit', 'Inter', 'Segoe UI', sans-serif;
    font-size: 13px;
}

QMainWindow {
    background-color: #050505;
}

/* Sidebar Styling */
QFrame#SidebarFrame {
    background-color: #000000;
    border-right: 1px solid #1A1A1A;
}

QLabel#SidebarTitle {
    color: #F0C419;
    font-size: 22px;
    font-weight: bold;
    padding: 15px;
    margin-bottom: 15px;
}

/* Scroll Area Styling */
QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollArea QWidget {
    background-color: transparent;
}

/* Base Buttons */
QPushButton {
    background-color: transparent;
    color: #B3B3B3;
    border: none;
    border-radius: 6px;
    font-weight: bold;
    padding: 10px 18px;
    text-align: left;
}

QPushButton:hover {
    color: #FFFFFF;
    background-color: #222222;
}

QPushButton:pressed {
    background-color: #151515;
}

/* Premium Highlighted Buttons */
QPushButton#PrimaryButton {
    background-color: #2D7D46;
    color: #FFFFFF;
    border-radius: 20px;
    padding: 2px 26px;
    font-size: 14px;
    font-weight: bold;
    text-align: center;
}

QPushButton#PrimaryButton:hover {
    background-color: #F0C419;
    color: #000000;
}

QPushButton#PrimaryButton:pressed {
    background-color: #E0B510;
    color: #000000;
}

/* Bottom Bar Media Controls */
QPushButton#PlayButton {
    background-color: #121212;
    color: #F0C419;
    border-radius: 28px;
    min-width: 56px;
    max-width: 56px;
    min-height: 56px;
    max-height: 56px;
    padding: 0px;
    font-size: 18px;
    text-align: center;
    border: 3px solid #2D7D46;
}

QPushButton#PlayButton:hover {
    background-color: #1A1A1A;
    border-color: #F0C419;
    color: #FFFFFF;
}

QPushButton#PlayButton:pressed {
    background-color: #0A0A0A;
    border-color: #E0B510;
    color: #E0B510;
}

QPushButton#NavButton {
    color: #B3B3B3;
    font-size: 16px;
    min-width: 44px;
    max-width: 44px;
    min-height: 44px;
    max-height: 44px;
    padding: 0px;
    text-align: center;
    border-radius: 22px;
}

QPushButton#NavButton:hover {
    color: #FFFFFF;
    background-color: #222222;
}

QPushButton#NavButton:pressed {
    background-color: #333333;
    color: #F0C419;
}

/* Dynamic active state for toggled controls (shuffle, repeat) */
QPushButton#NavButton[active="true"] {
    color: #F0C419;
}

QPushButton#NavButton[active="true"]:hover {
    color: #FFFFFF;
    background-color: #2D7D46;
}

QPushButton#NavButton[active="true"]:pressed {
    background-color: #333333;
    color: #FFFFFF;
}

/* List Views */
QListWidget {
    border: none;
    background-color: transparent;
    padding: 5px;
}

QListWidget::item {
    color: #B3B3B3;
    padding: 11px 14px;
    border-radius: 6px;
    margin-bottom: 4px;
    background-color: transparent;
}

QListWidget::item:hover {
    background-color: #1A1A1A;
    color: #FFFFFF;
}

QListWidget::item:selected {
    background-color: #2D7D46;
    color: #FFFFFF;
    font-weight: bold;
}

/* Input Fields (Single Line and Multi-line Text Area) */
QLineEdit, QTextEdit {
    background-color: #151515;
    border: 1px solid #222222;
    border-radius: 16px;
    padding: 10px 18px;
    color: #FFFFFF;
    font-size: 13px;
    selection-background-color: #F0C419;
    selection-color: #000000;
}

QLineEdit:focus, QTextEdit:focus {
    border: 1px solid #F0C419;
    background-color: #1C1C1C;
}

/* Multi-line Text Area styling specifically */
QTextEdit {
    border-radius: 8px;
    padding: 12px;
    font-family: Consolas, 'Courier New', monospace;
    font-size: 12px;
}

/* Sleek Progress Bar */
QProgressBar {
    background-color: #1A1A1A;
    border: none;
    border-radius: 5px;
    text-align: center;
    color: #FFFFFF;
    font-weight: bold;
    font-size: 10px;
    height: 10px;
}

QProgressBar::chunk {
    background-color: #F0C419;
    border-radius: 5px;
}

/* Horizontal Sliders (Volume, Timeline) */
QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background: #222222;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: #F0C419;
    border-radius: 3px;
}

QSlider::sub-page:horizontal:hover {
    background: #E0B510;
}

QSlider::handle:horizontal {
    background: #FFFFFF;
    border: none;
    width: 14px;
    height: 14px;
    margin: -4px 0;
    border-radius: 7px;
}

QSlider::handle:horizontal:hover {
    background: #F0C419;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

/* Bottom Player Panel */
QFrame#BottomPlayerBar {
    background-color: #0A0A0A;
    border-top: 1px solid #151515;
    min-height: 115px;
    max-height: 115px;
}

QLabel#SongTitleLabel {
    color: #F0C419;
    font-size: 15px;
    font-weight: bold;
}

QLabel#ArtistLabel {
    color: #B3B3B3;
    font-size: 12px;
}

QLabel#TimeLabel {
    color: #B3B3B3;
    font-size: 11px;
    font-weight: bold;
}

/* Library Songs Table */
QTableWidget {
    border: none;
    gridline-color: transparent;
    background-color: transparent;
}

QTableWidget::item {
    padding: 12px;
    border-bottom: 1px solid #141414;
    color: #B3B3B3;
}

QTableWidget::item:selected {
    background-color: #1A1A1A;
    color: #F0C419;
}

QHeaderView::section {
    background-color: transparent;
    color: #888888;
    padding: 10px;
    border: none;
    font-weight: bold;
    text-align: left;
    border-bottom: 1px solid #1E1E1E;
}

/* Custom Scrollbars */
QScrollBar:vertical {
    border: none;
    background: #050505;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #222222;
    min-height: 25px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #2D7D46;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    border: none;
    background: none;
    height: 0px;
}

QScrollBar:horizontal {
    border: none;
    background: #050505;
    height: 10px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background: #222222;
    min-width: 25px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background: #2D7D46;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    border: none;
    background: none;
    width: 0px;
}

/* Karaoke Lyric View Text Lines */
QLabel#LyricLineLabel {
    font-size: 24px;
    font-weight: bold;
    color: #444444;
    padding: 12px;
    background-color: transparent;
}

QLabel#ActiveLyricLineLabel {
    font-size: 32px;
    font-weight: bold;
    color: #F0C419;
    padding: 12px;
    background-color: transparent;
}

QFrame#LyricScrollWidget {
    background-color: #030303;
    border-radius: 12px;
}
"""
