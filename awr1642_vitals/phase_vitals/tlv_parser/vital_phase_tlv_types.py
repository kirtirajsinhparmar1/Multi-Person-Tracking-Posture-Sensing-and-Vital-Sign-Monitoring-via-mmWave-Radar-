from dataclasses import asdict, dataclass


@dataclass
class VitalPhaseTrace:
    frame_number: int
    range_bin_index_max: int
    range_bin_index_phase: int
    range_meters: float
    i_value: float
    q_value: float
    phase_rad: float
    magnitude: float
    snr_like: float
    motion_detected: int
    reserved: bytes = b"\x00\x00\x00"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["reserved"] = list(self.reserved)
        return data
