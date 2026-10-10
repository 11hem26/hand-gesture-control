# ✋ Hand Gesture PC Control

<p align="center">
  <img src="banner.svg" alt="Hand Gesture PC Control Banner" width="100%">
</p>

<p align="center">
  Control your computer mouse using hand gestures and a webcam!
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9--3.12-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/OpenCV-Computer%20Vision-green?logo=opencv" alt="OpenCV">
  <img src="https://img.shields.io/badge/MediaPipe-Hand%20Tracking-orange" alt="MediaPipe">
</p>

## 📌 Project Overview

**Hand Gesture PC Control** is a Python-based project that allows you to control your computer mouse using hand gestures captured through a webcam.

It uses **OpenCV** to process camera frames, **MediaPipe** to track hand landmarks, and **PyAutoGUI** to control mouse movements and actions.

You can move the cursor, open files, right-click, drag and drop files, and scroll without using a physical mouse.

### 🎯 Objective

To develop a touch-free computer control system using real-time hand tracking and computer vision.

### 💡 Applications

- Hands-free computer interaction
- Touch-free navigation
- Computer vision learning
- Human-computer interaction

## 🚀 Features

- 🖐️ Move the mouse cursor using your hand.
- 👌 Pinch thumb and index finger to open files or folders.
- 🤏 Pinch thumb and ring finger to right-click.
- ✊ Use a fist to drag and drop files.
- ✌️ Use a peace sign to scroll.
- ⏯️ Pause and resume mouse control.
- 🎥 Real-time webcam hand tracking.
- 🛡️ PyAutoGUI failsafe for emergency stopping.

## 🛠️ Technologies Used

- **Python** — Main programming language
- **OpenCV** — Webcam and image processing
- **MediaPipe** — Hand landmark detection
- **PyAutoGUI** — Mouse control

## 📋 Requirements

- Python 3.9–3.12
- A working webcam
- Windows, macOS, or a compatible Linux desktop
- Required Python packages listed in `requirements.txt`

## 📥 Installation

### 1. Clone the repository

```bash
git clone https://github.com/11hem26/hand-gesture-control.git
cd hand-gesture-control
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

### 3. Activate the virtual environment

**Windows:**

```bash
venv\Scripts\activate
```

**Linux / macOS:**

```bash
source venv/bin/activate
```

### 4. Install dependencies

Install all required packages using your `requirements.txt` file:

```bash
python -m pip install -r requirements.txt
```

### 5. Run the project

```bash
python hand_control.py
```

## ✋ Hand Gestures

| Symbol | Gesture | Action |
|---|---|---|
| 🖐️ | Open Hand | 🖱️ Move Cursor |
| 👌 | Thumb + Index Pinch | 📂 Open File / Folder |
| 🤏 | Thumb + Ring Pinch | 🖱️ Right Click |
| ✊ | Fist | 📦 Drag & Drop Files |
| ✌️ | Peace Sign | 📜 Scroll Up / Down |


## ⌨️ Keyboard Controls

| Key | Action |
|---|---|
| `p` | Pause or resume control |
| `q` | Quit the application |

## ⚙️ Troubleshooting

- **Webcam not opening:** Close other applications using the camera or check the camera index in the Python script.
- **MediaPipe error:** Check your Python version and install compatible dependencies.
- **Cursor not moving:** Check camera permissions and ensure your hand is visible.
- **Gestures not working properly:** Use good lighting and keep your hand inside the camera frame.
- **Package installation failed:** Update pip using `python -m pip install --upgrade pip` and try installing the requirements again.

## 👨‍💻 Author

GitHub: [@11hem26](https://github.com/11hem26)

## ⭐ Support

If you find this project useful, please give the repository a star ⭐

**Learn • Build • Improve 🚀**
