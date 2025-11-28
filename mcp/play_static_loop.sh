#!/usr/bin/bash
# Play static noise video in an infinite loop
# This keeps the display active when the system is idle

STATIC_VIDEO="/home/twistedtv/videos/static.mp4"

# Wake up the display system first
sudo chvt 1
sleep 0.1
sudo bash -c 'echo 0 > /sys/class/graphics/fb0/blank'
sleep 0.3

# Loop forever, playing the static video
while true; do
    mpv --drm-device=/dev/dri/card1 \
        --audio-device=alsa/hdmi:CARD=vc4hdmi0,DEV=0 \
        --no-osc \
        --no-osd-bar \
        --loop=inf \
        --fullscreen \
        "$STATIC_VIDEO"

    # If MPV exits for any reason, wait a moment and restart
    sleep 1
done
