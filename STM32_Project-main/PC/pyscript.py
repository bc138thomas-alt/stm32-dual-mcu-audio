import serial
import struct
import time
import wave
import matplotlib.pyplot as plt
import numpy as np

EXPECTED_SAMPLE_RATE = 44100
DURATION_SECONDS = 5
NUM_SAMPLES = EXPECTED_SAMPLE_RATE * DURATION_SECONDS
NUM_BYTES = NUM_SAMPLES * 2
BAUD_RATE = 921600

PORT = "COM6"

def read_audio(DURATION_SECONDS):
    NUM_SAMPLES = int(EXPECTED_SAMPLE_RATE * DURATION_SECONDS)
    NUM_BYTES = NUM_SAMPLES * 2

    with serial.Serial(PORT, BAUD_RATE, timeout=10) as ser:#cahtpgt wrote some of this
        ser.reset_input_buffer()

        received = bytearray()
        start_time = time.monotonic()
        end_time = None
        while len(received) < NUM_BYTES:
            chunk = ser.read(NUM_BYTES - len(received))
            if not chunk:
                break
            end_time = time.monotonic()
            received.extend(chunk)

        data = bytes(received)

    print(f"Received {len(data)} / {NUM_BYTES} bytes")


    if len(data) % 2 != 0:
        data = data[:-1]

    elapsed = (end_time - start_time) if end_time is not None else 0
    num_received_samples = len(data) // 2
    actual_sample_rate = int(round(num_received_samples / elapsed)) if elapsed > 0 else EXPECTED_SAMPLE_RATE

    if not abs(actual_sample_rate - EXPECTED_SAMPLE_RATE) > EXPECTED_SAMPLE_RATE * 0.01:
        print(
            f"Warning: measured sample rate is {actual_sample_rate} Hz, "
            f"not the expected {EXPECTED_SAMPLE_RATE} Hz. Using the measured rate in the WAV header."
        )
        

    pcm16 = bytearray()
    for (sample,) in struct.iter_unpack("<H", data):
        sample &= 0x0FFF
        signed_sample = (sample - 2048) << 4
        pcm16.extend(int(signed_sample).to_bytes(2, byteorder="little", signed=True))
    return actual_sample_rate, pcm16


def save_wav(actual_sample_rate, pcm16):
    with wave.open('output.wav', 'wb') as wf:
        wf.setnchannels(1)       # mono
        wf.setsampwidth(2)       # 2 bytes = 16-bit PCM
        wf.setframerate(actual_sample_rate)
        wf.writeframes(pcm16)

def save_csv(actual_sample_rate, pcm16):
    with open('output.csv', 'w') as f:
        f.write(f"Sample Index/{EXPECTED_SAMPLE_RATE} s^-1,Sample Value\n")
        for i in range(0, len(pcm16), 2):
            sample_value = int.from_bytes(pcm16[i:i+2], byteorder="little", signed=False)//16
            f.write(f"{i//2},{sample_value}\n")

def save_png(actual_sample_rate, pcm16):
    samples = np.array([])
    for i in range(0, len(pcm16), 2):
        sample_value = int.from_bytes(pcm16[i:i+2], byteorder="little", signed=False)//16
        samples = np.append(samples, sample_value)
    time_axis = np.arange(len(samples)) / actual_sample_rate
    VALUES_TO_SHOW = 100    
    avg_samples = []
    #create 1000 average samples to show in the plot
    for i in range(0, len(samples), len(samples)//VALUES_TO_SHOW):
        avg_sample = np.mean(samples[i:i+len(samples)//VALUES_TO_SHOW])
        avg_samples.append(avg_sample)
    time_axis = time_axis[::len(samples)//VALUES_TO_SHOW]

    plt.figure(figsize=(10, 4))
    plt.plot(time_axis, avg_samples)
    plt.title("Audio Signal")
    plt.xlabel("Time (s)")
    plt.ylabel("Amplitude")
    plt.xlim(0, time_axis[-1])
    plt.grid()
    plt.tight_layout()
    plt.savefig('output.png')
    plt.close()

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
        if not mode in ["m", "d"]:
            print("Invalid input.")
        else:
            break
    #settings of mode
    if mode == "m":
        while True:
            rec_time = input("Enter recording length in seconds: ")
            try:
                rec_time = int(rec_time)/2
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
    return mode, rec_time if mode == "m" else distance_threshold, output_type

if __name__ == "__main__":
    mode, setting, output_type = CLI()
    print(f"Recording to {output_type.upper()} file in mode '{mode}' ")

    actual_sample_rate, pcm16 = read_audio(setting)

    if output_type == "wav":
        save_wav(actual_sample_rate, pcm16)
    elif output_type == "csv":
        save_csv(actual_sample_rate, pcm16)
    elif output_type == "png":
        save_png(actual_sample_rate, pcm16)
