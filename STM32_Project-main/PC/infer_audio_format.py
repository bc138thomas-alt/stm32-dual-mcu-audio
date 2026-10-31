import argparse
import math
import pathlib
import struct
import time
import wave


COMMON_SAMPLE_RATES = [
    4000,
    6250,
    8000,
    11025,
    16000,
    22050,
    32000,
    44100,
    48000,
]


class Candidate:
    def __init__(
        self,
        name,
        samples,
        effective_bits,
        storage_description,
        wav_sampwidth,
        notes,
        padding_confidence=0.0,
    ):
        self.name = name
        self.samples = list(samples)
        self.effective_bits = effective_bits
        self.storage_description = storage_description
        self.wav_sampwidth = wav_sampwidth
        self.notes = notes
        self.padding_confidence = padding_confidence
        self.score = float("-inf")
        self.metrics = {}


def load_input_bytes(path):
    input_path = pathlib.Path(path)
    with input_path.open("rb") as handle:
        header = handle.read(12)

    if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        with wave.open(str(input_path), "rb") as wav_file:
            frames = wav_file.readframes(wav_file.getnframes())
            metadata = {
                "kind": "wav",
                "channels": wav_file.getnchannels(),
                "sample_width": wav_file.getsampwidth(),
                "sample_rate": wav_file.getframerate(),
                "num_frames": wav_file.getnframes(),
            }
        return frames, metadata

    return input_path.read_bytes(), {"kind": "raw"}


def capture_serial(port, baud_rate, duration_seconds, bytes_to_read, timeout):
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError(
            "pyserial is required for live capture mode. Install it or analyze a saved raw file instead."
        ) from exc

    if duration_seconds is None and bytes_to_read is None:
        raise ValueError("Provide either --duration-seconds or --bytes-to-read for live serial capture.")

    with serial.Serial(port, baud_rate, timeout=timeout) as serial_port:
        serial_port.reset_input_buffer()
        received = bytearray()

        if bytes_to_read is not None:
            while len(received) < bytes_to_read:
                chunk = serial_port.read(min(4096, bytes_to_read - len(received)))
                if not chunk:
                    break
                received.extend(chunk)
        else:
            started = time.monotonic()
            while time.monotonic() - started < duration_seconds:
                chunk = serial_port.read(4096)
                if chunk:
                    received.extend(chunk)

    return bytes(received), {"kind": "serial"}


def decode_uint16_le(data):
    usable = len(data) - (len(data) % 2)
    return [value for (value,) in struct.iter_unpack("<H", data[:usable])]


def decode_int16_le(data):
    usable = len(data) - (len(data) % 2)
    return [value for (value,) in struct.iter_unpack("<h", data[:usable])]


def decode_packed_12bit_le(data):
    usable = len(data) - (len(data) % 3)
    if usable == 0:
        return []

    samples = []
    for index in range(0, usable, 3):
        byte0 = data[index]
        byte1 = data[index + 1]
        byte2 = data[index + 2]
        first = byte0 | ((byte1 & 0x0F) << 8)
        second = (byte1 >> 4) | (byte2 << 4)
        samples.append(float(first) - 2048.0)
        samples.append(float(second) - 2048.0)
    return samples


def build_candidates(data):
    candidates = []

    if data:
        candidates.append(
            Candidate(
                name="8-bit unsigned PCM",
                samples=[float(byte) - 128.0 for byte in data],
                effective_bits=8,
                storage_description="1 byte per sample",
                wav_sampwidth=1,
                notes="Treat each byte as one unsigned PCM sample.",
            )
        )

    if len(data) >= 2 and len(data) % 2 == 0:
        u16 = decode_uint16_le(data)
        i16 = decode_int16_le(data)

        high_nibble_zero = sum(1 for value in u16 if (value & 0xF000) == 0) / len(u16)
        low_nibble_zero = sum(1 for value in u16 if (value & 0x000F) == 0) / len(u16)

        candidates.append(
            Candidate(
                name="16-bit signed PCM (little-endian)",
                samples=[float(value) for value in i16],
                effective_bits=16,
                storage_description="2 bytes per sample",
                wav_sampwidth=2,
                notes="Treat each 16-bit little-endian word as signed PCM.",
            )
        )

        candidates.append(
            Candidate(
                name="12-bit unsigned, right-justified in 16-bit",
                samples=[float(value & 0x0FFF) - 2048.0 for value in u16],
                effective_bits=12,
                storage_description="2-byte container, upper 4 bits padding",
                wav_sampwidth=2,
                notes="Common ADC layout where bits 11:0 carry the sample and bits 15:12 stay zero.",
                padding_confidence=high_nibble_zero,
            )
        )

        candidates.append(
            Candidate(
                name="12-bit unsigned, left-justified in 16-bit",
                samples=[float(value >> 4) - 2048.0 for value in u16],
                effective_bits=12,
                storage_description="2-byte container, lower 4 bits padding",
                wav_sampwidth=2,
                notes="Common ADC layout where bits 15:4 carry the sample and bits 3:0 stay zero.",
                padding_confidence=low_nibble_zero,
            )
        )

    packed_12 = decode_packed_12bit_le(data)
    if packed_12:
        candidates.append(
            Candidate(
                name="12-bit packed PCM (little-endian)",
                samples=packed_12,
                effective_bits=12,
                storage_description="3 bytes store 2 samples",
                wav_sampwidth=2,
                notes="Two 12-bit samples packed into each 3-byte group.",
            )
        )

    return candidates


def score_candidate(candidate):
    samples = candidate.samples
    if len(samples) < 64:
        candidate.score = float("-inf")
        candidate.metrics = {"reason": "not enough samples to analyze"}
        return candidate

    mean_value = sum(samples) / len(samples)
    centered = [sample - mean_value for sample in samples]
    std_dev = math.sqrt(sum(sample * sample for sample in centered) / len(centered))
    if std_dev <= 1e-9:
        candidate.score = float("-inf")
        candidate.metrics = {"reason": "constant signal"}
        return candidate

    diffs = [centered[index + 1] - centered[index] for index in range(len(centered) - 1)]
    diff_std = math.sqrt(sum(diff * diff for diff in diffs) / len(diffs)) if diffs else 0.0
    smoothness_ratio = diff_std / std_dev if std_dev else math.inf
    smoothness_score = max(0.0, 1.5 - smoothness_ratio) / 1.5

    prev_samples = centered[:-1]
    next_samples = centered[1:]
    prev_energy = sum(sample * sample for sample in prev_samples)
    next_energy = sum(sample * sample for sample in next_samples)
    if prev_energy > 1e-9 and next_energy > 1e-9:
        numerator = sum(left * right for left, right in zip(prev_samples, next_samples))
        lag_corr = numerator / math.sqrt(prev_energy * next_energy)
    else:
        lag_corr = 0.0

    peak = max(abs(sample) for sample in centered)
    clipped_fraction = (
        sum(1 for sample in centered if abs(sample) >= peak * 0.995) / len(centered)
        if peak > 0
        else 1.0
    )

    padding_bonus = 0.0
    if candidate.padding_confidence >= 0.85:
        padding_bonus = (candidate.padding_confidence - 0.85) * 3.0

    score = (0.8 * lag_corr) + (0.7 * smoothness_score) - (0.3 * clipped_fraction) + padding_bonus
    candidate.score = score
    candidate.metrics = {
        "sample_count": len(samples),
        "std_dev": std_dev,
        "smoothness_ratio": smoothness_ratio,
        "lag_corr": lag_corr,
        "clipped_fraction": clipped_fraction,
        "padding_confidence": candidate.padding_confidence,
    }
    return candidate


def estimate_sample_rate(sample_count, duration_seconds):
    if duration_seconds is None or duration_seconds <= 0:
        return None

    exact_rate = sample_count / duration_seconds
    nearest_common = min(COMMON_SAMPLE_RATES, key=lambda rate: abs(rate - exact_rate))
    return {
        "exact_rate": exact_rate,
        "nearest_common": nearest_common,
        "nearest_error": abs(nearest_common - exact_rate),
    }


def normalize_to_int16(samples):
    mean_value = sum(samples) / len(samples)
    centered = [sample - mean_value for sample in samples]
    peak = max(abs(sample) for sample in centered)
    if peak <= 1e-9:
        return [0 for _ in samples]
    return [int(round(max(-1.0, min(1.0, sample / peak)) * 32767.0)) for sample in centered]


def export_candidate_wav(candidate, sample_rate, output_dir, rank):
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = candidate.name.lower().replace(" ", "_").replace("/", "_")
    output_path = output_dir / f"{rank:02d}_{safe_name}.wav"

    pcm16 = normalize_to_int16(candidate.samples)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(round(sample_rate)))
        wav_file.writeframes(struct.pack("<" + "h" * len(pcm16), *pcm16))

    return output_path


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Infer likely audio interpretation for raw STM32 captures, including byte width, "
            "12-bit padding layout, and sample-rate estimates when duration is known."
        )
    )
    parser.add_argument("input", nargs="?", help="Path to a raw capture file or WAV file.")
    parser.add_argument("--serial-port", help="Capture bytes directly from a serial port instead of reading a file.")
    parser.add_argument("--baud-rate", type=int, default=921600, help="Serial baud rate for live capture mode.")
    parser.add_argument(
        "--duration-seconds",
        type=float,
        help="Known audio duration. Required to estimate sample rate from sample count.",
    )
    parser.add_argument(
        "--bytes-to-read",
        type=int,
        help="Exact number of bytes to capture in live serial mode.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Serial timeout in seconds for live capture mode.",
    )
    parser.add_argument(
        "--export-top",
        type=int,
        default=0,
        help="Export WAV previews for the top N ranked candidates.",
    )
    parser.add_argument(
        "--output-dir",
        default="analysis_outputs",
        help="Directory used for exported WAV previews.",
    )
    parser.add_argument(
        "--preview-rate",
        type=float,
        help="Override sample rate to use for preview WAV exports when duration is unknown.",
    )
    return parser.parse_args()


def print_source_metadata(metadata):
    if metadata["kind"] == "wav":
        print("Input source: WAV file")
        print(f"  Header channels: {metadata['channels']}")
        print(f"  Header sample width: {metadata['sample_width']} bytes")
        print(f"  Header sample rate: {metadata['sample_rate']} Hz")
        print(f"  Header frame count: {metadata['num_frames']}")
    elif metadata["kind"] == "serial":
        print("Input source: live serial capture")
    else:
        print("Input source: raw byte stream")


def main():
    args = parse_args()

    if not args.input and not args.serial_port:
        raise SystemExit("Provide an input file or use --serial-port for live capture.")

    if args.serial_port:
        data, metadata = capture_serial(
            port="COM6",
            baud_rate=args.baud_rate,
            duration_seconds=args.duration_seconds,
            bytes_to_read=args.bytes_to_read,
            timeout=args.timeout,
        )
    else:
        data, metadata = load_input_bytes(args.input)

    if not data:
        raise SystemExit("No input data found.")

    print_source_metadata(metadata)
    print(f"Captured payload bytes: {len(data)}")

    candidates = [score_candidate(candidate) for candidate in build_candidates(data)]
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)

    print("\nRanked interpretations:")
    for index, candidate in enumerate(candidates, start=1):
        metrics = candidate.metrics
        rate_estimate = estimate_sample_rate(metrics.get("sample_count", 0), args.duration_seconds)

        print(f"{index}. {candidate.name}")
        print(f"   score: {candidate.score:.3f}")
        print(f"   storage: {candidate.storage_description}")
        print(f"   effective bits: {candidate.effective_bits}")
        print(f"   samples decoded: {metrics.get('sample_count', 0)}")
        print(f"   lag-1 correlation: {metrics.get('lag_corr', float('nan')):.3f}")
        print(f"   smoothness ratio: {metrics.get('smoothness_ratio', float('nan')):.3f}")
        if candidate.padding_confidence > 0.0:
            print(f"   padding evidence: {candidate.padding_confidence * 100:.1f}% of padding bits are zero")
        if rate_estimate is None:
            print("   sample rate estimate: unavailable without --duration-seconds")
        else:
            print(
                "   sample rate estimate: "
                f"{rate_estimate['exact_rate']:.2f} Hz "
                f"(nearest common {rate_estimate['nearest_common']} Hz, "
                f"error {rate_estimate['nearest_error']:.2f})"
            )
        print(f"   notes: {candidate.notes}")

    if not candidates:
        raise SystemExit("No valid interpretations could be produced from the input bytes.")

    best = candidates[0]
    print("\nRecommended interpretation:")
    print(f"  {best.name}")
    print(f"  storage: {best.storage_description}")
    print(f"  effective bits: {best.effective_bits}")
    if best.padding_confidence > 0.0:
        print(f"  padding confidence: {best.padding_confidence * 100:.1f}%")

    if args.export_top > 0:
        output_dir = pathlib.Path(args.output_dir)
        print("\nExporting preview WAVs:")
        for rank, candidate in enumerate(candidates[: args.export_top], start=1):
            rate_estimate = estimate_sample_rate(candidate.metrics["sample_count"], args.duration_seconds)
            preview_rate = args.preview_rate
            if preview_rate is None and rate_estimate is not None:
                preview_rate = rate_estimate["nearest_common"]
            if preview_rate is None and metadata.get("kind") == "wav":
                preview_rate = metadata["sample_rate"]
            if preview_rate is None:
                raise SystemExit(
                    "Preview export needs either --duration-seconds, --preview-rate, or a WAV input with a header sample rate."
                )
            output_path = export_candidate_wav(candidate, preview_rate, output_dir, rank)
            print(f"  {output_path}")


if __name__ == "__main__":
    main()