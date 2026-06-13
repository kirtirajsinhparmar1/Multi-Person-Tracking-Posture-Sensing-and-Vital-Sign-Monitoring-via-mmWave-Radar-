"""Serial frame reader for TI mmWave UART data."""

from __future__ import annotations

import struct
from typing import Optional

from parser import MAGIC_WORD, parse_frame


class SerialDependencyError(RuntimeError):
    pass


class RadarSerialReader:
    """Read complete TI UART frames from the data port.

    This mirrors TI's sync approach from
    tools\\visualizers\\Applications_Visualizer\\common\\gui_parser.py:71-115:
    find the 8-byte magic word, read version and total length, then read the
    rest of the frame.
    """

    def __init__(self, data_port: str = "COM6", baud: int = 921600, timeout: float = 0.6):
        try:
            import serial
        except ImportError as exc:
            raise SerialDependencyError(
                "pyserial is required. Install it with: pip install pyserial"
            ) from exc

        try:
            self.serial = serial.Serial(data_port, baud, timeout=timeout)
        except serial.SerialException as exc:
            raise RuntimeError(
                f"Could not open data port {data_port} at {baud}: {exc}\n"
                "If the port is busy, close TI Visualizer, UniFlash, PuTTY, "
                "TeraTerm, or any other Python script using the port."
            ) from exc

    def close(self) -> None:
        self.serial.close()

    def __enter__(self) -> "RadarSerialReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def read_frame_bytes(self) -> bytes:
        frame_data = bytearray()
        index = 0

        while True:
            b = self.serial.read(1)
            if not b:
                raise TimeoutError("Timed out waiting for UART magic word")

            value = b[0]
            if value == MAGIC_WORD[index]:
                frame_data.append(value)
                index += 1
                if index == len(MAGIC_WORD):
                    break
            else:
                # If this byte could be the start of a new magic word, keep it.
                if value == MAGIC_WORD[0]:
                    frame_data = bytearray([value])
                    index = 1
                else:
                    frame_data = bytearray()
                    index = 0

        version = self._read_exact(4)
        length = self._read_exact(4)
        frame_data += version
        frame_data += length

        total_packet_len = struct.unpack("<I", length)[0]
        if total_packet_len < 16:
            raise ValueError(f"Invalid total packet length: {total_packet_len}")

        frame_data += self._read_exact(total_packet_len - 16)
        return bytes(frame_data)

    def read_parsed_frame(self):
        return parse_frame(self.read_frame_bytes())

    def _read_exact(self, length: int) -> bytes:
        data = self.serial.read(length)
        if len(data) != length:
            raise TimeoutError(f"Timed out reading {length} bytes, received {len(data)}")
        return data
