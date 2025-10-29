# camswitcher

Simple Video Switcher (Debian 12 / Ubuntu 24 compatible)
- Two physical webcams as inputs
- One virtual webcam (v4l2loopback) as output
- GTK4 UI with live preview and one-click switching
- save settings and reload on startup

Tested on: Debian 12 (Bookworm) and Ubuntu 24.04

## Dependencies (Debian 12 / ubuntu 24):
### Debian 12:
 sudo apt update && sudo apt install -y \
    python3-gi python3-gst-1.0 gir1.2-gtk-4.0 gir1.2-gstreamer-1.0 \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-gl \
    gstreamer1.0-gtk3 gstreamer1.0-gl v4l2loopback-dkms v4l2loopback-utils
   

### Ubuntu 24:
sudo apt update && sudo apt install -y \
    python3-gi python3-gst-1.0 gir1.2-gtk-4.0 gir1.2-gstreamer-1.0 \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-gl \
    gstreamer1.0-gtk3 gstreamer1.0-gtk4 gstreamer1.0-gl v4l2loopback-dkms v4l2loopback-utils


## Setup
(Recommended) give your user webcam access and re-login:
  sudo usermod -aG video "$USER"

Load v4l2loopback (once per boot or persist via modprobe.d):
  sudo modprobe v4l2loopback video_nr=10 card_label="VirtualCam" exclusive_caps=1
  Your virtual camera will be /dev/video10 (change video_nr if you prefer)

## Usage
Run:
  python3 video_switcher.py
run you videoconferencing software, and choose /dev/video10 or "Virtual Cam" 


## AI disclaimer
This application is mainly writen by OpenAI`s ChatGPT5, and checked and modified by a human

