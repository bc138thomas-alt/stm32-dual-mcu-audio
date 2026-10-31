import serial
import numpy as np
import wave 
from matplotlib import pyplot as plt

# =========================
# Practical Class 4 - Week 7
# ADC Audio Sampling Script
# =========================

# Change this to match your STM32 COM port, e.g. "COM3", "COM4", etc.
SERIAL_PORT = "COM6"

# UART baud rate from the prac / CubeIDE default
BAUD_RATE = 921600

# Adjust this if the playback sounds too slow/deep or too fast/high.
SAMPLE_RATE = 44100

# Number of seconds to record
RECORD_SECONDS = 5

# Output wav file name
OUTPUT_FILE = "recorded_audio.wav"


def read_audio(sample_rate, record_seconds, baudrate):
    number_of_samples = sample_rate * record_seconds

    print("Opening serial port...")
    ser = serial.Serial(SERIAL_PORT, baudrate)

    print("Recording...")
    print("Number of samples:", number_of_samples)

    samples = []

    for i in range(number_of_samples):
        #print(f"Reading sample {i+1}/{number_of_samples}...", end="\r")
        data = ser.read(2)

        if data:
            #print(data)
            sample = data[0]<<8 | data[1]
            #print(f"{sample}")
            samples.append(sample)

    ser.close()

    print("Finished recording.")
    print("Samples recorded:", len(samples))

    print("Finished recording.")
    print("Samples recorded:", len(samples))

    # Convert 12-bit unsigned ADC samples to signed 16-bit PCM.
    audio_data = ((np.array(samples, dtype=np.uint16) & 0x0FFF).astype(np.int32) - 2048) << 4
    audio_data = audio_data.astype(np.int16)
    return audio_data

def save_wav(audio_data, sample_rate, output_file):
    # Save as 16-bit mono wav file
    wav_file = wave.open(output_file, "wb")
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)
    wav_file.setframerate(sample_rate)
    wav_file.writeframes(audio_data.tobytes())
    wav_file.close()

    print("Saved as wav file:", output_file)

def CLI():
    #mode selection
    while True:
        mode = input("Enter recording mode (Manual (m) /Distance Trigger (d)):")
        mode = mode.lower()
        if "manual" in mode:
            mode = "m"
            break
        elif "distance" in mode:
            mode = "d"
            break
        else:
            print("Invalid input.")
    #settings of mode
    if mode == "m":
        while True:
            rec_time = input("Enter recording length in seconds: ")
            try:
                rec_time = int(rec_time)
                break
            except ValueError:
                print("Invalid input. Please enter a number.")
    elif mode == "d":
        while True:
            distance_threshold = input("Enter distance threshold in cm (default 10cm): ")
            if distance_threshold == "":
                distance_threshold = 10
                break
            try:
                distance_threshold = int(distance_threshold)
                break
            except ValueError:
                print("Invalid input. Please enter a number.")
    #output file type
    while True:
        output_type = input("Output file type (WAV/CSV/PNG): ").lower()
        if output_type in ["wav", "csv", "png"]:
            break
        else:
            print("Invalid input. Please enter 'WAV', 'CSV', or 'PNG'")
    




if __name__ == "__main__":
    audio_data = read_audio(SAMPLE_RATE, RECORD_SECONDS, BAUD_RATE)
    save_wav(audio_data, SAMPLE_RATE, OUTPUT_FILE)
