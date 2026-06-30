"""MIDI Practice Monitor

a.k.a. MIDI-bit - A fitbit for your MIDI keyboard

(c)2026 Rob Cranfill

See https://github.com/RobCranfill/MIDIbit2

Version 2: Two accumulated times - "practice" and "play".

For CircuitPython, on the device known as 
"Adafruit Feather RP2040 with USB Type A Host" (whew!)
(Adafruit Product ID: 5723)

To force startup mode (see README file)
    import microcontroller; microcontroller.nvm[0] = 0x12 # (18 decimal) for run mode
    import microcontroller; microcontroller.nvm[0] = 0x34 # (52) # for dev mode
  then
    microcontroller.reset()
  

    TODO:

    Not done:
     - after switching dev/run mode, reboot mcu?
     - show more info at startup? dev mode, uh?
     - save prac/play mode?

    Things done, I think:
     - show message when changing backlight level?
     - show something when scanning for MIDI
     - if looking for MIDI, don't timeout and blank the screen? 
     - if looking for MIDI and a device gets plugged in, un-blank.
     - erase "Found midi device" message at start.

    Can't reproduce?
     - something wrong with "Found Roland Digital Piano" message at start - wraps wrong.
     - WEIRD BEHAVIOR - LOW MEMORY???
        - working ok now? (the initial text painting is kinda slow but ok, kinda cool)

"""

# stdlibs
import board
import digitalio
import gc
import microcontroller
import supervisor
import time
import usb.core

# adafruit libs
import adafruit_datetime as datetime
import adafruit_midi
import adafruit_midi.midi_message
import neopixel

# FIXME: this seems clunky. can't we do this more succinctly?
from adafruit_midi.control_change import ControlChange
from adafruit_midi.note_off import NoteOff
from adafruit_midi.note_on import NoteOn
from adafruit_midi.pitch_bend import PitchBend

import adafruit_usb_host_midi

# Our libs
import tft_144_display as display_144
import midi_state_machine
import midibit_defines as DEF

MIDIBIT_VERSION_STRING = "2.a1"

# TODO: how does this affect responsiveness? buffering? what-all??
MIDI_TIMEOUT = .1

# Timeouts, in seconds.
# Defaults will be changed if dev mode
SESSION_TIMEOUT = 15
DISPLAY_IDLE_TIMEOUT = 60 # for display blanking

SETTINGS_NAME = "midibit_settings.text"
BG_FILE_NAME = "background.bmp"

# Keyboard "attention" sequence MIDI notes: G G G Eb F F F D
MIDI_TRIGGER_SEQ_PREFIX = (67, 67, 67, 63, 65, 65, 65, 62)

# Post-trigger 'command' note
MIDI_TRIGGER_SEQ_RESET = MIDI_TRIGGER_SEQ_PREFIX + (60,) # middle C
MIDI_TRIGGER_SEQ_TOGGLE_BOOT = MIDI_TRIGGER_SEQ_PREFIX + (62,) # D above middle C
MIDI_TRIGGER_SEQ_BACKLIGHT = MIDI_TRIGGER_SEQ_PREFIX + (64,) # E
MIDI_TRIGGER_SEQ_TOGGLE_PRACTICE = MIDI_TRIGGER_SEQ_PREFIX + (65,) # F

# Indicator colors when looking for MIDI
NO_MIDI_BLINK_COLORS = [0x20_20_20, 0x80_80_80]
ACTIVE_MODE_COLOR = 0x00_00_00
INACTIVE_MODE_COLOR = 0x80_80_80


BACKLIGHT_LEVELS = [10, 25, 50, 75, 100]
backlight_level_index = 3


neopixel_ = neopixel.NeoPixel(board.NEOPIXEL, 1)
def flash_led(seconds):
    neopixel_.fill(flash_color_)
    time.sleep(seconds)
    neopixel_.fill((0,0,0))


def set_run_or_dev():
    '''Set the NeoPixel state and some other globals; return dev mode flag'''

    global SESSION_TIMEOUT
    global DISPLAY_IDLE_TIMEOUT
    global flash_color_

    RUN_MODE_COLOR = (128, 0, 0)
    DEV_MODE_COLOR = (0, 128, 0)
    flash_color_ = RUN_MODE_COLOR

    # Read the non-volatile memory for the dev mode set by boot.py.
    is_dev_mode = False
    if microcontroller.nvm[0] == DEF.MAGIC_NUMBER_DEV_MODE:
        is_dev_mode = True
    # print(f"{microcontroller.nvm[0]=} -> {is_dev_mode=} ({DEF.MAGIC_NUMBER_DEV_MODE=})")

    if is_dev_mode:
        flash_color_ = DEV_MODE_COLOR
        neopixel_.fill(flash_color_)
        SESSION_TIMEOUT = 5
        DISPLAY_IDLE_TIMEOUT = 10
        print(f"\nDEV MODE: Setting timeouts to {SESSION_TIMEOUT=}, {DISPLAY_IDLE_TIMEOUT=}\n")
    else:
        neopixel_.fill(flash_color_)
        print(f"\nRUN MODE")
    return is_dev_mode


def as_hms(seconds):
    s = str(datetime.timedelta(0, int(seconds)))
    if len(s) == 7:
        s = " " + s
    return s


def show_total_time(disp, practice, play):
    """Input params are integer seconds."""
    disp.set_text_1(as_hms(practice))
    disp.set_text_2(as_hms(play))


def write_session_data(session_seconds, play_seconds):
    '''Writes a string-ified version of the integer values.
    This will throw an exception if the filesystem isn't writable. Catch it higher up.'''
    print(f"write_session_data: {session_seconds=}, {play_seconds=}")
    with open(SETTINGS_NAME, "w") as f:
        f.write(str(int(session_seconds)))
        f.write(str(int(play_seconds)))


def read_session_data():
    """Return a tuple of practice & play times (# of seconds) stored on SD card"""

    t1 = t2 = 0
    try:
        with open(SETTINGS_NAME, "r") as f:
            l1 = f.readline()
            l2 = f.readline()
        t1 = int(l1)
        t2 = int(l2)
    except:
        print("No old session data? Continuing....")

    # print(f"read_session_data: returning {t1=} {t2=}")
    return (t1, t2)


def find_midi_device(disp):
    """Does not return until it finds a (suitable?) MIDI device"""

    # does this help weird startup behavior? No,
    # time.sleep(1)

    print("\nLooking for MIDI devices...")

    # display_message_for_a_bit(disp, "Looking for MIDI", delay=1)
    disp.set_text_status("Looking for MIDI....")

    raw_midi = None
    attempt = 1

    no_midi_idle_start_time = time.monotonic()

    while raw_midi is None:

        # gc.collect()
        # print(f"{gc.mem_free()} bytes free")

        all_devices = usb.core.find(find_all=True)
        
        #  no can do 
        # print(f"  Found {len(all_devices)} devices?")
        
        n_devices = 0

        for device in all_devices:
            
            n_devices += 1
            # FIXME: this is not useful?
            print(f" - looking at USB device #{n_devices}: vendor 0x{device.idVendor:04x}, product 0x{device.idProduct:04x}") 

            # I guess this is how we find a MIDI device: try it; if not MIDI, will throw exception.
            try:
                raw_midi = adafruit_usb_host_midi.MIDI(device, timeout=MIDI_TIMEOUT)
                print(f" ^ MIDI OK for {device.product=}")
                if device.product is None:
                    print("FUNNY DEVICE; SKIPPING!")
                    continue
                else:
                   break

            except ValueError:
                print(" * adafruit_usb_host_midi.MIDI: ValueError?")
                continue
            except Exception as e:
                    print(f" * adafruit_usb_host_midi.MIDI: {e}")

        print(f"  Done iterating MIDI devices, found {raw_midi}")

        # Looked at all devices, didn't find MIDI. Try again.
        if raw_midi is None:

            msg = f"No MIDI device found on try #{attempt}. Sleeping...."
            print(msg)
            display.set_text_status(msg)

            display.set_midi_indicator(NO_MIDI_BLINK_COLORS[0])
            time.sleep(.5)
            display.set_midi_indicator(NO_MIDI_BLINK_COLORS[1])
            time.sleep(.5)

            # No-MIDI timeout; flash LED twice
            if time.monotonic() - no_midi_idle_start_time > DISPLAY_IDLE_TIMEOUT:
                # print("no-MIDI idle timeout!")

                # TODO: check if already blanked
                # FIXME: no blanking for no-midi case?
                # disp.blank_screen(True)

                flash_led(0.01)
                time.sleep(0.1)
                flash_led(0.01)

            attempt += 1
    
    midi_device = None
    try:
        midi_device = adafruit_midi.MIDI(midi_in=raw_midi)
    except Exception as e:
        print(f" * adafruit_midi.MIDI: {e}")

    print(f"  returning {midi_device=}")

    disp.set_text_status(f"Found\n{device.product}")
    # time.sleep(2)

    return midi_device


def try_write_session_data(dev_mode, disp, practice_seconds, play_seconds):
    '''Write the given elapsed time to the data file. Display errors as needed.'''
    try:
        write_session_data(practice_seconds, play_seconds)
        display_message_for_a_bit(disp, "DATA SAVED")

    except Exception as e:

        # we expect write errors in dev mode.
        if dev_mode:
            print("Can't write, as expected")
            display_message_for_a_bit(disp, "FAILED TO SAVE - OK")

        else:
            print(f"Can't write! {e}")
            display_message_for_a_bit(disp, "FAILED TO SAVE!")


def toggle_boot_mode(disp):
    nvm_dev_mode = microcontroller.nvm[0] == DEF.MAGIC_NUMBER_DEV_MODE
    nvm_dev_mode = not nvm_dev_mode
    microcontroller.nvm[0] = DEF.MAGIC_NUMBER_DEV_MODE if nvm_dev_mode else DEF.MAGIC_NUMBER_RUN_MODE
    print(f"Setting {microcontroller.nvm[0]=} -> {nvm_dev_mode=}")
    display_message_for_a_bit(disp, f"Dev: {nvm_dev_mode}")


def display_message_for_a_bit(disp, text, delay=2):
    disp.set_text_status(str(text))
    time.sleep(delay)
    disp.set_text_status("")


def show_splash(disp):
    disp.set_label_1("MidiBit")
    disp.set_text_1(MIDIBIT_VERSION_STRING)
    disp.set_text_status("MidiBit starting...")
    time.sleep(2)


def set_display_practice_active(disp, is_practice):
    """Toggle the prac/play display mode, coloring the fields appropriately."""

    color_1 = ACTIVE_MODE_COLOR   if is_practice else INACTIVE_MODE_COLOR
    color_2 = INACTIVE_MODE_COLOR if is_practice else ACTIVE_MODE_COLOR

    disp.set_label_1_color(color_1)
    disp.set_text_1_color(color_1)
    disp.set_label_2_color(color_2)
    disp.set_text_2_color(color_2)


def main():
    pass


# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
print("Version 2a")

# wait for USB ready - needed??
# time.sleep(2)

# turn off auto-reload, cuz it's a pain
supervisor.runtime.autoreload = False
print(f"{supervisor.runtime.autoreload=}")


# The display.
#
display = display_144.TFT144Display(board.D5, board.D6, board.D9, board.D10, 
                                    True, BG_FILE_NAME, 90)

display.set_bl_percent(BACKLIGHT_LEVELS[backlight_level_index])
display.set_midi_indicator(NO_MIDI_BLINK_COLORS[0])


# except Exception as e:
#     print("Can't init display?? Stopping")
#     print(f"{e}")
#     while True:
#         pass

show_splash(display)
display.set_label_1("Practice")
display.set_label_2("Play")
display.set_text_2("??") # for now


# V2: the big diff!
# Determines whether we accumulate to prac_seconds or play_seconds
practice_not_play_mode = True

# NOTES FOR UPDATE
#  prac_seconds: practice time, accumulated to when in right mode, and saved.
#  play_seconds: new 'play' mode time, ditto.


# Set the colors of the labels accordingly
set_display_practice_active(display, practice_not_play_mode)


# Are we running in dev mode? Set some stuff.
in_dev_mode = set_run_or_dev()

# Load previous total time from text file.
prac_seconds, play_seconds = read_session_data()
print(f"read_session_data: {prac_seconds=}, {play_seconds=}")

show_total_time(display, prac_seconds, play_seconds)

last_event_time = time.monotonic()
in_session = False
session_start_time = 0
session_length = 0


# last_displayed_time is the (integer) time we last displayed; only update if changed.
# (The time itself is a float that's always changing.)
# 
last_displayed_time = int(prac_seconds if practice_not_play_mode else play_seconds)

idle_start_time = time.monotonic()
idle_led_blip_time = idle_start_time

# A state machine to watch for the "reset" sequence.
msm_reset = midi_state_machine.midi_state_machine(MIDI_TRIGGER_SEQ_RESET)

# A state machine to watch for the "toggle boot mode" sequence.
msm_toggle_boot = midi_state_machine.midi_state_machine(MIDI_TRIGGER_SEQ_TOGGLE_BOOT)

# Advance the backlight
msm_backlight = midi_state_machine.midi_state_machine(MIDI_TRIGGER_SEQ_BACKLIGHT)

# Toggle practice/play mode
msm_toggle_practice = midi_state_machine.midi_state_machine(MIDI_TRIGGER_SEQ_TOGGLE_PRACTICE)


# Main event loop. Does not exit.
#
midi_device = None
msg_number = 0
display_is_blanked = False

while True:

    # ok? seems to be.
    # gc.collect()
    # print(f"{gc.mem_free()} bytes free")

    # This doesn't return until we have a MIDI device.
    # TODO: Is it always a *usable* device? No. Something funny here.
    #
    if midi_device is None:

        print("MEL loking for MIDI....")

        # Note (haha) that find_midi_device doesn't return until it finds something.
        #
        # TODO: check for None?
        midi_device = find_midi_device(display)
        print("  back from find_midi_device")

        # stop screen timeout immediately after finding ?
        last_event_time = time.monotonic()
        display.blank_screen(False) # ok?

    # print(f"waiting for event; {in_session=}")
    # TODO: remove this as 'else' to fix one-off error?
    # else:

    try:
        msg = midi_device.receive()
    except usb.core.USBError as e:
        print(f" ** midi_device.receive: usb.core.USBError: '{e}'")

        # Assume this is a MIDI disconnect?
        if in_session:

            # FIXME: still wrong for V2?
            if practice_not_play_mode:
                print(f"* Force write: {prac_seconds+session_length=}, {play_seconds=}")
                try_write_session_data(in_dev_mode, display, prac_seconds+session_length, play_seconds)
            else:
                print(f"* Force write: {prac_seconds=}, {play_seconds+session_length=}")
                try_write_session_data(in_dev_mode, display, prac_seconds, play_seconds+session_length)

            # TODO: end the session?

        last_event_time = time.monotonic()

        midi_device = None
        continue


    event_time = time.monotonic()


    # TODO: This acts on *any* kind of MIDI message - on, off, CC, etc.
    # Should we only pay attention to NoteOn events?
    # 
    if msg:
        msg_number += 1

        if not isinstance(msg, NoteOn):
            # print(f"Not a MIDI ON message! ({msg_number})")
            # print(f"  > midi msg: {msg} @ {event_time:.1f}")
            continue
    
        # print(f"midi msg: {msg} @ {event_time:.1f}")

        last_event_time = time.monotonic()

        if display_is_blanked:
            display.blank_screen(False)
            display_is_blanked = False

        # FIXME
        display.set_midi_indicator(0x00_FF_00 if msg_number % 2 == 0 else 0xFF_00_00)

        if not in_session:
            print("\nStarting session")
            session_start_time = time.monotonic()
            in_session = True

            # This would only be missing for <1 sec, but hey.
            show_total_time(display, prac_seconds, play_seconds)

        # Look for command sequences.
        if isinstance(msg, NoteOn):

            # Could be a zero-velocity NoteOn which is really a "note off".
            if msg.velocity == 0:
                # print("note off!")
                continue

            if msm_reset.note(msg.note):
                print(f"* Got {MIDI_TRIGGER_SEQ_RESET=}")
                prac_seconds = 0
                play_seconds = 0

                last_displayed_time = 0
                session_length = 0
                session_start_time = time.monotonic()
                show_total_time(display, prac_seconds, play_seconds)

                try_write_session_data(in_dev_mode, display, prac_seconds, play_seconds)

            elif msm_toggle_boot.note(msg.note):
                print(f"* Got {MIDI_TRIGGER_SEQ_TOGGLE_BOOT=}")
                toggle_boot_mode(display)

            elif msm_backlight.note(msg.note):
                backlight_level_index = (backlight_level_index + 1) % len(BACKLIGHT_LEVELS)
                display.set_bl_percent(BACKLIGHT_LEVELS[backlight_level_index])
                display_message_for_a_bit(display, f"Backlight: {BACKLIGHT_LEVELS[backlight_level_index]}%")

            elif msm_toggle_practice.note(msg.note):

                practice_not_play_mode = not practice_not_play_mode
                display_message_for_a_bit(display, f"Practice: {practice_not_play_mode}")

                set_display_practice_active(display, practice_not_play_mode)


            # elif msm_force_write.note(msg.note):
            #     # don't update prac_seconds yet, but write the new value
            #     total_seconds_temp = prac_seconds + session_length
            #     print(f"* Force write: {prac_seconds=}, {total_seconds_temp=}")
            #     try_write_session_data(display, total_seconds_temp)

    # else:
    #     # print("  empty message")
    #     pass

    # We have handled the event/note. Now do other stuff.
    #
    if in_session:

        # Session timeout?
        if event_time - last_event_time > SESSION_TIMEOUT:

            # print("\nSESSION_TIMEOUT!")
            in_session = False
            display.set_text_status("")

            if practice_not_play_mode:
                prac_seconds += session_length
            else:
                play_seconds += session_length

            try_write_session_data(in_dev_mode, display, prac_seconds, play_seconds)

            # For idle screen timeout
            idle_start_time = time.monotonic()

        else:

            # Update current session info
            session_length = time.monotonic() - session_start_time
            # print(f"  Session now {as_hms(session_length)}")

            # FIXME: clunky
            if practice_not_play_mode:
                new_prac = prac_seconds + session_length
                if last_displayed_time != int(new_prac):
                    last_displayed_time = int(new_prac)
                    # print(f" updating at {last_displayed_time}")
                    show_total_time(display, new_prac, play_seconds)
            else:
                new_play = play_seconds + session_length
                if last_displayed_time != int(new_play):
                    last_displayed_time = int(new_play)
                    # print(f" updating at {last_displayed_time}")
                    show_total_time(display, prac_seconds, new_play)

    else:
        # print("  not in session...")

        # With-MIDI display timeout
        if time.monotonic() - idle_start_time > DISPLAY_IDLE_TIMEOUT:

            # print("idle timeout!")
            if not display_is_blanked:
                display.blank_screen(True)
                display.set_midi_indicator(0x80_80_80)

            display_is_blanked = True

            # Single flash of LED, once per second.
            if time.monotonic() - idle_led_blip_time > 1:
                flash_led(0.01)
                idle_led_blip_time = time.monotonic()

