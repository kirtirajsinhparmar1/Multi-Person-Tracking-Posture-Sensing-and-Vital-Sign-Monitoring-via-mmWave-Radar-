"""Send TI mmWave CLI configuration files over the Enhanced/CLI UART.

This is standalone code. It mirrors the relevant behavior from TI's
tools\\visualizers\\Applications_Visualizer\\common\\gui_parser.py:298-345:
skip blank/comment lines, send config lines over the CLI port, read responses,
and allow the config file to provide flushCfg/sensorStart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Callable, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CFG_PATH = (
    REPO_ROOT
    / "source"
    / "ti"
    / "examples"
    / "Industrial_and_Personal_Electronics"
    / "People_Tracking"
    / "3D_People_Tracking"
    / "chirp_configs"
    / "ODS_6m_default.cfg"
)


class CliSenderError(RuntimeError):
    pass


@dataclass
class CliCommandResult:
    command: str
    responses: list[str] = field(default_factory=list)
    done: bool = False
    error: bool = False


@dataclass
class CliSendResult:
    cfg_path: Path
    commands_sent: int
    command_results: list[CliCommandResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not any(result.error for result in self.command_results)


def send_config(
    cli_port: str = "COM7",
    cli_baud: int = 115200,
    cfg_path: str | Path = DEFAULT_CFG_PATH,
    timeout: float = 0.6,
    line_delay: float = 0.03,
    output: Callable[[str], None] | None = print,
) -> CliSendResult:
    """Open the CLI port, send sensorStop, then send cfg lines.

    The cfg file is not edited. If the cfg already contains flushCfg and
    sensorStart, those commands are sent exactly once from the file.
    """
    cfg_path = Path(cfg_path)
    if not cfg_path.exists():
        raise CliSenderError(f"Config file not found: {cfg_path}")

    try:
        import serial
    except ImportError as exc:
        raise CliSenderError("pyserial is required. Install it with: pip install pyserial") from exc

    commands = list(iter_config_commands(cfg_path))
    command_results: list[CliCommandResult] = []

    try:
        cli = serial.Serial(cli_port, cli_baud, timeout=timeout)
    except serial.SerialException as exc:
        raise CliSenderError(
            f"Could not open CLI port {cli_port} at {cli_baud}: {exc}\n"
            "If the port is busy, close TI Visualizer, UniFlash, PuTTY, "
            "TeraTerm, or any other Python script using the port."
        ) from exc

    with cli:
        cli.reset_input_buffer()
        cli.reset_output_buffer()
        _emit(output, f"Opened CLI port {cli_port} at {cli_baud}")

        _emit(output, "Sending sensorStop before cfg")
        stop_result = send_command(
            cli,
            "sensorStop",
            line_delay=line_delay,
            response_timeout=max(timeout, 1.0),
            output=output,
        )
        # sensorStop can return an error when the sensor is already stopped.
        stop_result.error = False
        command_results.append(stop_result)

        for command in commands:
            response_timeout = max(timeout, 2.0) if command.startswith("sensorStart") else timeout
            result = send_command(
                cli,
                command,
                line_delay=line_delay,
                response_timeout=response_timeout,
                output=output,
            )
            command_results.append(result)
            if result.error:
                _emit(output, f"WARNING: CLI reported an error for command: {command}")

        time.sleep(0.03)
        cli.reset_input_buffer()

    return CliSendResult(
        cfg_path=cfg_path,
        commands_sent=len(commands),
        command_results=command_results,
    )


def send_command(
    cli,
    command: str,
    line_delay: float = 0.03,
    response_timeout: float = 0.6,
    output: Callable[[str], None] | None = print,
) -> CliCommandResult:
    time.sleep(line_delay)
    cli.write((command + "\n").encode("utf-8"))
    _emit(output, f">> {command}")

    responses = read_response(cli, response_timeout)
    result = CliCommandResult(command=command, responses=responses)
    for line in responses:
        _emit(output, f"<< {line}")
        lowered = line.lower()
        if "done" in lowered:
            result.done = True
        if "error" in lowered:
            result.error = True

    if not responses:
        _emit(output, f"<< no CLI response within {response_timeout:.1f}s")

    return result


def read_response(cli, response_timeout: float) -> list[str]:
    responses: list[str] = []
    deadline = time.time() + response_timeout

    while time.time() < deadline:
        raw = cli.readline()
        if not raw:
            if responses:
                break
            continue
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        responses.append(line)
        lowered = line.lower()
        if "done" in lowered or "error" in lowered:
            break

    return responses


def iter_config_commands(cfg_path: str | Path) -> Iterable[str]:
    with Path(cfg_path).open("r", encoding="utf-8", errors="replace") as cfg:
        for raw_line in cfg:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("%"):
                continue
            yield line


def _emit(output: Callable[[str], None] | None, message: str) -> None:
    if output is not None:
        output(message)

