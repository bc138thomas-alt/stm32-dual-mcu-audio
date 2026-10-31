# Dual-STM32 Audio Acquisition Pipeline

Real-time audio capture across two STM32 microcontrollers: one samples, one filters. The result is streamed to a PC and saved as WAV, CSV or PNG.

Built as a 5-person team project for ECE2071 (Embedded Systems) at Monash University.

![Output waveform](media/output.png)

## How it works

```
Mic ──► Sampling STM32 ──SPI (1 MHz)──► Processing STM32 ──UART (921600)──► PC (Python)
        TIM1 @ 44.1 kHz                  Outlier rejection                   WAV / CSV / PNG
        12-bit ADC + DMA                 Moving average (N=8)
        circular buffer                  2:1 downsample
```

- **Sampling STM32:** TIM1 triggers ADC1 at 44.1 kHz. DMA fills a circular buffer, and half/full-buffer callbacks send blocks over SPI using DMA.
- **Processing STM32:** receives blocks as an SPI slave using DMA, rejects outliers, applies a length-8 moving average and downsamples 2:1. It then packs each 12-bit sample into 2 bytes and sends it to the PC over UART using DMA.
- **PC:** a Python (pySerial) script reads the stream and exports it as WAV, CSV or a matplotlib plot. The output format is chosen from the CLI.

## My contributions (Benjamin COhen)

- CubeIDE `.ioc` peripheral configuration (timers, ADC, UART)
- Working two-MCU UART pipeline, with an ADC callback and a moving-average filter
- Python CLI for WAV/CSV/PNG export

## Repo layout

```
firmware/stm_sampling4/     Sampling MCU (STM32CubeIDE project)
firmware/stm_processing4/   Processing MCU (STM32CubeIDE project)
pc/                         Python receiver and export scripts
media/                      Output plots and demo
samples/                    Example captured data (CSV)
```

## Running it

1. Import both `firmware/` projects into STM32CubeIDE, then build and flash each board.
2. Wire SPI1 (PA5 SCK, PA7 MOSI, plus GND) between the boards. Connect the processing board to the PC over USB.
3. Install the PC dependencies with `pip install pyserial numpy matplotlib`. Run the receiver script in `pc/` from Windows (not WSL, which can't see COM ports).

## Credits

Nageeb, Matt, Kadin, Arjun, Benjamin.
