#!/usr/bin/env python3
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# Waveshare library path (from their repo)
import sys
sys.path.append("/home/eric/projects/e-Paper/RaspberryPi_JetsonNano/python/lib")

from waveshare_epd import epd7in5_V2

def main():
    epd = epd7in5_V2.EPD()
    epd.init()
    epd.Clear()

    W, H = epd.width, epd.height  # should be 800x480

    img = Image.new("1", (W, H), 255)  # 1-bit image, 255=white
    draw = ImageDraw.Draw(img)

    # Font: use a basic system font if available
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except Exception:
        font = ImageFont.load_default()

    draw.rectangle((10, 10, W - 10, H - 10), outline=0, width=3)
    draw.text((30, 40), "eink-todoist", font=font, fill=0)
    draw.text((30, 90), f"Pi: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", font=font, fill=0)
    draw.text((30, 140), "Display OK", font=font, fill=0)

    epd.display(epd.getbuffer(img))
    epd.sleep()

if __name__ == "__main__":
    main()
