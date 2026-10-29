"""
    New display for Practice Monitor
    Version 2: Two practice times and a message area.

    For 1.44" 128x128 TFT - https://learn.adafruit.com/adafruit-1-44-color-tft-with-micro-sd-socket
    https://www.adafruit.com/product/2088

    Feather     EYESPI
    -------     ------
    Hardwired
    SCK         SCK
    MO          MOSI
    MI          MISO

    Passed in as params
    D5          TCS
    D6          DC
    D9          RST
    D10         BL

"""

import random
import time

import board
import digitalio
import displayio
import gc
import pwmio

import adafruit_imageload
from adafruit_bitmap_font import bitmap_font
from adafruit_display_text import label
from adafruit_display_shapes.rect import Rect
from adafruit_st7735r import ST7735R
from fourwire import FourWire
import terminalio

# TODO: Input these at constructor? setters? meh.
BACKGROUND_COLOR = 0xFF_FF_D0   # no longer used, since we use a .bmp for background?
MIDI_COLOR_A = 0xFF_00_00   # For MIDI activity indicator
MIDI_COLOR_B = 0x00_FF_00

BLACK = 0x00_00_00

HEIGHT = 128
WIDTH  = 128

MAX_STATUS_CHARS = 20

class TFT144Display():
    """Display based on Adafruit 1.44" TFT.
    
    Will expose 2 updateable fields, one two-line status area, and one blinky MIDI indicator.
    
        +----------------------------------+
        |  _label_1                        |
        |  _text_1                         |
        |                                  |
        |  _label_2                        |
        |  _text_2                         |
        |                                  |
        |  _status_1                       |
        |  _status_2       _midi_indicator |
        +----------------------------------+

    with methods
        .set_label_1(t) .set_label_1_color(c)
        .set_text_1(t)  .set_text_1_color(c)
        ...

    """

    def __init__(self, pin_cs, pin_dc, pin_reset, pin_backlight, use_pwm, bg_file_path, rotation):
        """
        Construct a display object; indicate the 4 pins - in addition to SCK, MI, and MO - that are used.
        rotation: 90 is EYESPI cable at top.
        """

        # Important!
        displayio.release_displays()

        # This uses the standard SCK, MI, and MO pins.
        spi = board.SPI()

        display_bus = FourWire(spi, command=pin_dc, chip_select=pin_cs, reset=pin_reset)
        display = ST7735R(display_bus, width=WIDTH, height=HEIGHT, colstart=2, rowstart=3)
        display.rotation = rotation

        self._use_pwm = use_pwm

        if use_pwm:
            self._bl_pwm = pwmio.PWMOut(pin_backlight, frequency=5000, duty_cycle=0)
        else:
            self._backlight = digitalio.DigitalInOut(pin_backlight)
            self._backlight.switch_to_output()
            self._backlight.value = True


        # Load a background image to the group.
        # if bg_file_path is not None:

        print(f"Loading image from {bg_file_path}")
        bitmap, palette = adafruit_imageload.load(  bg_file_path,
                                                    bitmap=displayio.Bitmap,
                                                    palette=displayio.Palette)
        # print(f"Loaded pallette size {palette.__len__()}")

        # else:
        #     print("No background?")
        #     bitmap = displayio.Bitmap(WIDTH, HEIGHT, 4)
        #     palette = displayio.Palette(4)
        #     palette[0] = BACKGROUND_COLOR # don't know if this is used
        #     palette[1] = BLACK
        #     palette[2] = MIDI_COLOR_A
        #     palette[3] = MIDI_COLOR_B

        # So we can dispose it when switching?
        self._bitmap = bitmap

        self._midi_indicator_index = 2

        group = displayio.Group()
        display.root_group = group
        bg_sprite = displayio.TileGrid(bitmap, pixel_shader=palette, x=0, y=0)
        group.append(bg_sprite)

        # Hang onto this so we can change the background image.
        self._group = group

        print("Loading fonts....")
        little_font = terminalio.FONT
        big_font = bitmap_font.load_font("fonts/cmuntb22.bdf")
        print("Fonts loaded.")

        # Create the text labels; hang onto them as instance vars
        tx =  0
        ty = 10
        big_inc = 26

        lab = label.Label(big_font, color=BLACK, x=tx, y=ty)
        group.append(lab)
        self._label_1 = lab

        ty += big_inc
        text = label.Label(big_font, scale=1, color=BLACK, x=tx, y=ty)
        group.append(text)
        self._text_1 = text

        ty += big_inc
        lab = label.Label(big_font, color=BLACK, x=tx, y=ty)
        group.append(lab)
        self._label_2 = lab

        ty += big_inc
        text = label.Label(big_font, scale=1, color=BLACK, x=tx, y=ty)
        group.append(text)
        self._text_2 = text

        # Two little labels at the bottom for status.
        tx = 4
        ty = 128 - 18
        text = label.Label(little_font, color=BLACK, x=tx, y=ty)
        group.append(text)
        self._status_1 = text

        ty += 10
        text_area = label.Label(little_font, color=BLACK, x=tx, y=ty)
        group.append(text_area)
        self._status_2 = text_area
    

        # The MIDI activity indicator
        self._indicator = Rect(114, 114, 12, 12, fill=MIDI_COLOR_A)
        group.append(self._indicator)
        display.root_group = group

        print(f"{__name__} OK!")

    # FIXME: could have just exposed the labels themselves and then set .text and .color on them. ?
    # whatev

    def set_background(self, bg_file_path):

        gc.collect()
        print(f"1 {gc.mem_free()=}")
        self._bitmap = None

        print(f"Loading new bitmap {bg_file_path}...")
        bitmap, palette = adafruit_imageload.load(  bg_file_path,
                                                    bitmap=displayio.Bitmap,
                                                    palette=displayio.Palette)
        gc.collect()
        print(f"2 {gc.mem_free()=}")
        self._group[0] = displayio.TileGrid(bitmap, pixel_shader=palette, x=0, y=0)
        gc.collect()
        print(f"3 {gc.mem_free()=}")

    def set_label_1(self, text):
        self._label_1.text = text

    def set_label_1_color(self, color):
        self._label_1.color = color

    def set_text_1(self, text):
        self._text_1.text = text

    def set_text_1_color(self, color):
        self._text_1.color = color

    def set_label_2(self, text):
        self._label_2.text = text

    def set_label_2_color(self, color):
        self._label_2.color = color

    def set_text_2(self, text):
        self._text_2.text = text

    def set_text_2_color(self, color):
        self._text_2.color = color


    def set_text_status(self, text):
        """Displays in status fields: text 3 with overflow to area 4 if needed. 
        Max MAX_STATUS_CHARS chars each."""

        t1 = text.strip()
        t2 = ""
        if len(t1) > MAX_STATUS_CHARS:
            t1 = text[:MAX_STATUS_CHARS]
            t2 = text[MAX_STATUS_CHARS:]

        if len(t2) > MAX_STATUS_CHARS:
            t2 = t2[0:MAX_STATUS_CHARS]
    
        t1 = t1.strip()
        t2 = t2.strip()

        self._status_1.text = t1
        self._status_2.text = t2


    def set_midi_indicator(self, color):
        self._indicator.fill = color


    def blank_screen(self, blank):
        """If 'blank' is true, blank the screen."""

        # TODO: this doesn't really blank it, just turns the backlight off. good enough?
        
        # print(f"Blanking screen? {blank=} ({USE_PWM=})")

        if self._use_pwm:
            # self._bl_pwm.duty_cycle = 0 if blank else 100
            level = 0 if blank else 100
            self.set_bl_percent(level)
        else:
            self._backlight.value = not blank


    def set_bl_percent(self, percent):
        if not self._use_pwm:
            return
        frac = percent / 100
        print(f"Setting backlight to {percent}% = {frac}")
        self._bl_pwm.duty_cycle = int(65535 * frac)


def test():
    """Example code. 
    """

    print("Creating TFT144Display for test...")

    # disp = TFT144Display(board.D5, board.D6, board.D9, board.D10, "bmps/aqua.bmp")
    disp = TFT144Display(board.D5, board.D6, board.D9, board.D10, False, None, 90)

    disp.set_bl_percent(100)

    # disp.set_text_1("1:23:45")

    def increment_time(h, m, s):
        """Return (h,m,s)"""
        s += 1
        if s == 60:
            m += 1
            s = 0
        if m == 60:
            h += 1
            m = 0
        return h, m, s

    h_prac = 0
    m_prac = 0
    s_prac = 0

    h_play = 0
    m_play = 0
    s_play = 0

    practice = True
    count = 0
    while count < 5:

        count += 1
    
        disp.set_display_practice_mode(practice)

        r = random.randint(15, 30)
        for i in range(r):
            if practice:
                h_prac, m_prac, s_prac = increment_time(h_prac, m_prac, s_prac)
                disp.set_text_1(f" {h_prac:01}:{m_prac:02}:{s_prac:02}")
            else:
                h_play, m_play, s_play = increment_time(h_play, m_play, s_play)
                disp.set_text_2(f" {h_play:01}:{m_play:02}:{s_play:02}")
            time.sleep(.1)

        practice = not practice

        if False:
            print("Testing screen blanking....")
            if USE_PWM:
                for p in [100, 80, 60, 40, 20, 10, 5]:
                    disp.set_bl_percent(p)
                    time.sleep(.5)
            else:
                disp.blank_screen(True)
                time.sleep(2)
                disp.blank_screen(False)
