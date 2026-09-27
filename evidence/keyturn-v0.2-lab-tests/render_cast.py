#!/usr/bin/env python3
"""Render an asciinema v2 cast faithfully to MP4 (1920x1080). Real terminal output only; timing preserved
except that idle gaps longer than --max-idle are shortened (and the cut is logged, for the edit list).
Usage: render_cast.py in.cast out.mp4 [--fps 10] [--max-idle 2.0]"""
import argparse
import json
import re
import subprocess

import pyte
from PIL import Image, ImageDraw, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument("cast")
ap.add_argument("out")
ap.add_argument("--fps", type=int, default=10)
ap.add_argument("--max-idle", type=float, default=2.0)
ap.add_argument("--font", default="/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
ap.add_argument("--bold", default="/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf")
ap.add_argument("--size", type=int, default=26)
a = ap.parse_args()

lines = open(a.cast).read().splitlines()
hdr = json.loads(lines[0])
cols, rows = hdr["width"], hdr["height"]
events = [json.loads(l) for l in lines[1:] if l.strip()]
events = [e for e in events if e[1] == "o"]

W, H = 1920, 1080
font = ImageFont.truetype(a.font, a.size)
bold = ImageFont.truetype(a.bold, a.size)
cw = font.getbbox("M")[2]
lh = int(a.size * 1.3)
x0 = max(20, (W - cw * cols) // 2)
y0 = max(20, (H - lh * rows) // 2)
BG = (22, 24, 28)
COL = {"default": (220, 220, 220), "red": (255, 110, 110), "green": (120, 220, 120), "yellow": (240, 200, 90),
       "blue": (120, 170, 255), "magenta": (220, 140, 220), "cyan": (120, 210, 220), "white": (240, 240, 240), "black": (60, 60, 60)}

screen = pyte.Screen(cols, rows)
stream = pyte.Stream(screen)


def frame():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for y in range(rows):
        row = screen.buffer[y]
        for x in range(cols):
            ch = row[x]
            if ch.data.strip():
                d.text((x0 + x * cw, y0 + y * lh), ch.data, font=bold if ch.bold else font, fill=COL.get(ch.fg, COL["default"]))
    return img.tobytes()


ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H),
                       "-r", str(a.fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", a.out], stdin=subprocess.PIPE)
t_video, t_prev, cuts, markers = 0.0, 0.0, [], {}
step = 1.0 / a.fps
cur = frame()
for t, _, data in events:
    gap = t - t_prev
    if gap > a.max_idle:
        cuts.append({"at_source_s": round(t_prev, 1), "idle_s": round(gap, 1), "shown_s": a.max_idle})
        gap = a.max_idle
    n = int(round(gap / step))
    for _ in range(n):
        ff.stdin.write(cur)
    t_video += n * step
    stream.feed(data)
    cur = frame()
    t_prev = t
    for m in re.findall(r"\u25b6 (\d+)\.", re.sub(r"\x1b\[[0-9;]*m", "", data)):
        markers.setdefault("step" + m, round(t_video, 2))
for _ in range(a.fps * 3):
    ff.stdin.write(cur)
ff.stdin.close()
ff.wait()
json.dump({"source_cast": a.cast, "source_duration_s": round(events[-1][0], 1), "video_duration_s": round(t_video + 3, 1),
           "idle_cuts": cuts, "step_markers_video_s": markers}, open(a.out + ".edit-log.json", "w"), indent=1)
print("video %.1fs from %.1fs of source; %d idle gaps shortened" % (t_video + 3, events[-1][0], len(cuts)))
