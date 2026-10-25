"""Render the verified-label Synchro wiring drawing to PNG and editable SVG."""
from pathlib import Path
from html import escape
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "hardware"
OUT.mkdir(exist_ok=True)
W, H = 2100, 1690
BG, INK, MUTED = "#F7F9FC", "#17283B", "#506278"
RED, ORANGE, BLUE, PURPLE = "#C33538", "#AD5A00", "#176FA1", "#7954A8"
im = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(im)
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
       f'<rect width="{W}" height="{H}" fill="{BG}"/>']

def font(size, bold=False):
    return ImageFont.truetype("C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf", size)

def txt(x, y, value, size=21, color=INK, bold=False, anchor="start"):
    # The same text and geometry drive both file formats.
    for i, line in enumerate(value.split("\n")):
        yy = y + i * (size + 9)
        f = font(size, bold)
        width = d.textlength(line, font=f)
        xx = x - (width / 2 if anchor == "middle" else width if anchor == "end" else 0)
        if not (0 <= xx and xx + width <= W and 0 <= yy < H - size):
            raise ValueError(f"Text outside canvas: {line}")
        d.text((xx, yy), line, font=f, fill=color, anchor="lt")
        svg.append(f'<text x="{x}" y="{yy}" dominant-baseline="text-before-edge" text-anchor="{anchor}" '
                   f'font-family="Segoe UI, sans-serif" font-size="{size}" font-weight="{600 if bold else 400}" '
                   f'fill="{color}">{escape(line)}</text>')

def line(points, color=INK, width=3):
    d.line(points, fill=color, width=width, joint="curve")
    coords = " ".join(f"{x},{y}" for x, y in points)
    svg.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"/>')

def rect(x, y, w, h, fill="white", stroke="#C7D1DC", radius=14):
    d.rounded_rectangle((x, y, x+w, y+h), radius=radius, fill=fill, outline=stroke, width=2)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')

def dot(x, y, color=INK, radius=6):
    d.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
    svg.append(f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{color}"/>')

def block(x, y, w, h, name, subtitle=""):
    rect(x, y, w, h)
    txt(x+24, y+20, name, 27, bold=True)
    if subtitle:
        txt(x+24, y+59, subtitle, 18, MUTED)

def pin(x, y, label, side="left", color=INK):
    dot(x, y, color, 5)
    txt(x+18 if side == "left" else x-18, y-13, label, 21, color,
        anchor="start" if side == "left" else "end")

def tag(x, y, label):
    rect(x-26, y-16, 52, 32, "#E9EEF4", INK, 5)
    txt(x, y-14, label, 20, INK, True, "middle")

txt(65, 35, "SYNCHRO  /  COMPLETE WIRING", 40, bold=True)
txt(65, 91, "One MPU on the back of the hand + conductive-tape clicks + Bluetooth camera  |  No breadboard", 23, MUTED)

# Upper power chain. USB power goes to the Nano's connector, never VIN.
block(65, 165, 405, 170, "PKCELL LP803860", "3.7 V nominal  /  2000 mAh LiPo")
txt(90, 262, "Use the existing JST plug.", 22)
txt(90, 296, "Check red + and black - polarity.", 18, MUTED)
block(620, 165, 550, 325, "Adafruit PowerBoost 1000C", "5V output pin supplies approximately 5.2 V")
pin(620, 275, "BATTERY JST")
line([(470, 275), (620, 275)], RED, 5)
txt(545, 237, "2-wire JST", 18, RED, anchor="middle")
pin(1170, 275, "5V OUT", "right", RED)
pin(1170, 310, "GND", "right")
pin(620, 415, "micro-USB IN")
txt(645, 350, "EN open = ON; USB / BAT / VS / LBO", 18, MUTED)
txt(645, 379, "header pins are unused in this circuit.", 18, MUTED)
pin(1000, 490, "", "right", PURPLE)
txt(1000, 452, "USB-A OUTPUT SOCKET", 20, PURPLE, True, "middle")

block(65, 380, 405, 115, "5 V USB charger", "Only plug in when charging; charge off-body.")
line([(470, 415), (620, 415)], MUTED, 3)
txt(545, 455, "micro-USB cable", 17, MUTED, anchor="middle")

# Camera connections are explicit; GND/R is not ground in this design.
block(1500, 165, 535, 355, "Inland ESP32-CAM", "Existing 640 x 480 Bluetooth firmware")
pin(1500, 275, "5V", color=RED)
pin(1500, 310, "GND  (plain GND only)")
pin(1500, 380, "U0T / TX", color=BLUE)
pin(1500, 440, "U0R / RX", color=BLUE)
txt(1525, 480, "IO0 and GND/R: leave disconnected.", 19, MUTED)
line([(1170, 275), (1500, 275)], RED, 5)
line([(1170, 310), (1500, 310)], INK, 4)
dot(1340, 310)
line([(1340, 310), (1340, 340)])
tag(1340, 350, "G1")

# Nano: the names correspond to printed board labels, not raw ESP32 GPIO.
block(760, 600, 460, 725, "Arduino Nano ESP32", "Use the printed Arduino pin labels.")
pin(1000, 600, "", color=PURPLE)
txt(1000, 685, "USB-C power input", 19, PURPLE, True, "middle")
line([(1000, 490), (1000, 600)], PURPLE, 8)
txt(1020, 536, "USB-A to USB-C cable", 20, PURPLE)
pin(760, 750, "GND near D2")
line([(698, 750), (760, 750)])
tag(673, 750, "G1")
pin(760, 840, "GND near VIN")
line([(698, 840), (760, 840)])
tag(673, 840, "G2")
for y, label, color in [(720, "D2", BLUE), (775, "D3", BLUE), (865, "3V3", ORANGE),
                        (925, "A4 / SDA", BLUE), (985, "A5 / SCL", BLUE),
                        (1125, "D4", BLUE), (1205, "D5", BLUE)]:
    pin(1220, y, label, "right", color)
txt(785, 1270, "VIN and VUSB header pins: unused.", 19, MUTED)
line([(1220, 720), (1275, 720), (1275, 380), (1500, 380)], BLUE)
line([(1220, 775), (1325, 775), (1325, 440), (1500, 440)], BLUE)
txt(1355, 550, "UART wires", 17, BLUE)
txt(1355, 576, "for camera flashing", 17, BLUE)

# One MPU only. Ground net tags reference the actual four-wire G2 splice.
block(1500, 620, 535, 380, "MPU-6050 / GY-521", "Mount firmly on the back of the hand.")
pin(1500, 725, "VCC", color=ORANGE)
pin(1500, 785, "SDA", color=BLUE)
pin(1500, 845, "SCL", color=BLUE)
line([(1220, 865), (1360, 865), (1360, 725), (1500, 725)], ORANGE, 4)
line([(1220, 925), (1405, 925), (1405, 785), (1500, 785)], BLUE)
line([(1220, 985), (1445, 985), (1445, 845), (1500, 845)], BLUE)
txt(1530, 900, "XDA / XCL / INT: leave disconnected.", 19, MUTED)
for x, label in ((1650, "GND"), (1900, "AD0 (0x68)")):
    txt(x, 961, label, 21, anchor="middle")
    dot(x, 1000, radius=5)
    line([(x, 1000), (x, 1025)])
    tag(x, 1040, "G2")

# Conductive tape switches: an electrically grounded thumb closes either input.
block(1500, 1060, 535, 290, "Conductive-tape pads", "Tape surfaces touch during each pinch.")
pin(1500, 1170, "INDEX: left-click input", color=BLUE)
pin(1500, 1250, "MIDDLE: right-click input", color=BLUE)
pin(1500, 1320, "THUMB: common ground")
line([(1220, 1125), (1360, 1125), (1360, 1170), (1500, 1170)], BLUE)
line([(1220, 1205), (1405, 1205), (1405, 1250), (1500, 1250)], BLUE)
line([(1460, 1320), (1500, 1320)])
tag(1434, 1320, "G2")

# Physical solder splices, not additional components or extra board pins.
block(65, 610, 520, 240, "G1: POWER GROUND SPLICE", "Solder these 3 wire ends together; insulate.")
txt(92, 710, "1  PowerBoost GND\n2  Camera plain GND\n3  Nano GND near D2", 23)
block(65, 905, 520, 285, "G2: SENSOR GROUND SPLICE", "Solder these 4 wire ends together; insulate.")
txt(92, 1005, "1  Nano GND near VIN\n2  MPU GND\n3  MPU AD0\n4  Thumb tape", 23)
txt(80, 1220, "G1 and G2 are labels for wire joints.", 21, bold=True)
txt(80, 1255, "The Nano's two GND pins are connected\ninternally. The USB cable also carries GND.", 20, MUTED)

# Clear mode change and electrical limits belong on the drawing itself.
rect(65, 1400, 1970, 125, "#FFF2DF", "#D7A75A")
txt(90, 1420, "REMOVE THE OLD NANO VUSB -> CAMERA 5V WIRE before using this battery circuit.", 24, "#7B3B00", True)
txt(90, 1461, "To program/test the Nano: unplug its PowerBoost USB cable and connect the laptop's USB data cable instead.", 22)
txt(90, 1494, "Keep the camera powered by the PowerBoost. Never join the laptop USB 5V supply to the PowerBoost output.", 20)
txt(65, 1555, "Pin labels are schematic labels, not physical pin positions. Build with battery and USB disconnected; plug the battery in last.", 20, MUTED)
txt(65, 1588, "Circuit checked against manufacturer documentation. Combined battery operation and motion/click hardware are not yet bench-tested.", 20, MUTED)
txt(65, 1621, "Sources and full numbered connection list: firmware/README.md  |  24 October 2026", 18, MUTED)

svg.append("</svg>")
im.save(OUT / "synchro-complete-wiring.png")
(OUT / "synchro-complete-wiring.svg").write_text("\n".join(svg), encoding="utf-8")
print(OUT / "synchro-complete-wiring.png")
print(OUT / "synchro-complete-wiring.svg")
