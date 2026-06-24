import argparse
import time
import serial


def send_cfg(cli_port: str, cfg_path: str, baud: int = 115200, delay: float = 0.05):
    print(f"Opening CLI port {cli_port} at {baud}")
    print(f"Sending cfg: {cfg_path}")

    with serial.Serial(cli_port, baudrate=baud, timeout=1) as ser:
        time.sleep(0.5)

        with open(cfg_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        for raw in lines:
            line = raw.strip()

            if not line:
                continue
            if line.startswith("%") or line.startswith("#"):
                continue

            print(f">> {line}")
            ser.write((line + "\n").encode("ascii"))
            ser.flush()
            time.sleep(delay)

            resp = ser.read_all().decode("ascii", errors="ignore").strip()
            if resp:
                print(resp)

        time.sleep(0.5)
        resp = ser.read_all().decode("ascii", errors="ignore").strip()
        if resp:
            print(resp)

    print("CFG send complete.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", required=True, help="CLI/Application UART COM port, e.g. COM9")
    parser.add_argument("--cfg", required=True, help="Path to cfg file")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--delay", type=float, default=0.05)
    args = parser.parse_args()

    send_cfg(args.cli, args.cfg, args.baud, args.delay)


if __name__ == "__main__":
    main()