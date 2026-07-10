from __future__ import annotations

import argparse
from bisect import bisect_left
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import struct
from uuid import uuid4

import numpy as np
from PIL import Image


# =============================================================================
# User-editable defaults
# =============================================================================
#
# Usually you only need to edit this block for a new capture/export location.
# Command-line options still override these values when you need one-off runs.

DEFAULT_SOURCE_ROOT = Path(r"E:\one_chip")
DEFAULT_CALIBRATION_ROOT = (
    DEFAULT_SOURCE_ROOT / "calibration" / "results" / "apriltag_calib_main_02"
)
DEFAULT_OUTPUT_ROOT = Path(r"E:\one_chip_converted")
DEFAULT_CALIBRATION_JSON_OUTPUT = Path("artifacts/one_chip_calibration_preview.json")

DEFAULT_DATASET_ID = "one_chip_20260708"
DEFAULT_REFERENCE_FRAME = "robosense"
DEFAULT_SYNC_TOLERANCE_MS = 70.0
DEFAULT_TIMESTAMP_SOURCE = "header_aligned"
DEFAULT_CAMERA_FRAME_CONVENTION = "tool_camera"
DEFAULT_DATASET_LAYOUT = "simple"
DEFAULT_IMAGE_MODE = "block_demosaic"
DEFAULT_JPEG_QUALITY = 90
DEFAULT_PROGRESS_EVERY = 100

# Set this to a tuple like ("cvat_all_20260708_063100",) to convert selected bags.
DEFAULT_BAGS: tuple[str, ...] = ()


MCAP_MAGIC = b"\x89MCAP0\r\n"
OP_SCHEMA = 0x03
OP_CHANNEL = 0x04
OP_MESSAGE = 0x05
OP_CHUNK = 0x06

LIDAR_TOPIC = "/iv_points_10hz"
CAMERA_TOPICS = {
    "CAM_LEFT": "/cam_left/pylon_ros2_camera_node/image_raw",
    "CAM_RIGHT": "/cam_right/pylon_ros2_camera_node/image_raw",
}
POINT_COLUMNS = (
    "x",
    "y",
    "z",
    "intensity",
    "elongation",
    "scan_id",
    "scan_idx",
    "is_2nd_return",
)

POINT_FIELD_DTYPES = {
    1: "i1",
    2: "u1",
    3: "i2",
    4: "u2",
    5: "i4",
    6: "u4",
    7: "f4",
    8: "f8",
}

OPTICAL_TO_TOOL_CAMERA = np.array(
    [
        [0.0, 0.0, 1.0, 0.0],
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, -1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)


@dataclass(frozen=True, slots=True)
class McapMessage:
    topic: str
    sequence: int
    log_time_ns: int
    publish_time_ns: int
    data: bytes


@dataclass(frozen=True, slots=True)
class TimedSample:
    sample_id: str
    timestamp_ns: int
    source_bag: str
    topic_sequence: int


@dataclass(frozen=True, slots=True)
class DatasetLayoutPaths:
    name: str
    lidar_dir: Path
    cam_left_dir: Path
    cam_right_dir: Path
    lidar_pattern: str
    cam_left_pattern: str
    cam_right_pattern: str


@dataclass(frozen=True, slots=True)
class DecodedHeader:
    stamp_ns: int
    frame_id: str


@dataclass(frozen=True, slots=True)
class DecodedPointCloud2:
    header: DecodedHeader
    height: int
    width: int
    fields: tuple[dict[str, int], ...]
    is_bigendian: bool
    point_step: int
    row_step: int
    data: memoryview
    is_dense: bool


@dataclass(frozen=True, slots=True)
class DecodedImage:
    header: DecodedHeader
    height: int
    width: int
    encoding: str
    is_bigendian: bool
    step: int
    data: memoryview


class CdrReader:
    def __init__(self, data: bytes) -> None:
        if len(data) < 4:
            raise ValueError("CDR payload is shorter than the encapsulation header")
        if data[1] != 0x01:
            raise ValueError("only little-endian CDR payloads are supported")
        self.data = data
        self.pos = 4

    def align(self, size: int) -> None:
        self.pos = (self.pos + size - 1) & ~(size - 1)

    def uint8(self) -> int:
        value = self.data[self.pos]
        self.pos += 1
        return value

    def uint16(self) -> int:
        self.align(2)
        value = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return int(value)

    def uint32(self) -> int:
        self.align(4)
        value = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return int(value)

    def string(self) -> str:
        size = self.uint32()
        raw = self.data[self.pos : self.pos + size]
        self.pos += size
        if raw.endswith(b"\x00"):
            raw = raw[:-1]
        return raw.decode("utf-8", errors="replace")

    def octet_sequence(self) -> memoryview:
        size = self.uint32()
        start = self.pos
        self.pos += size
        return memoryview(self.data)[start : start + size]

    def bool(self) -> bool:
        return bool(self.uint8())


def _read_mcap_string(data: bytes, pos: int) -> tuple[str, int]:
    size = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    raw = data[pos : pos + size]
    pos += size
    return raw.decode("utf-8", errors="replace"), pos


def _read_mcap_map(data: bytes, pos: int) -> tuple[dict[str, str], int]:
    byte_count = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    end = pos + byte_count
    values: dict[str, str] = {}
    while pos < end:
        key, pos = _read_mcap_string(data, pos)
        value, pos = _read_mcap_string(data, pos)
        values[key] = value
    if pos != end:
        raise ValueError("invalid MCAP map length")
    return values, pos


def _parse_channel(data: bytes) -> tuple[int, str]:
    pos = 0
    channel_id, _schema_id = struct.unpack_from("<HH", data, pos)
    pos += 4
    topic, pos = _read_mcap_string(data, pos)
    _encoding, pos = _read_mcap_string(data, pos)
    _metadata, _pos = _read_mcap_map(data, pos)
    return int(channel_id), topic


def _parse_message(data: bytes, channels: dict[int, str]) -> McapMessage:
    channel_id, sequence, log_time_ns, publish_time_ns = struct.unpack_from(
        "<HIQQ", data, 0
    )
    topic = channels.get(int(channel_id))
    if topic is None:
        raise ValueError(f"message references unknown MCAP channel {channel_id}")
    return McapMessage(
        topic=topic,
        sequence=int(sequence),
        log_time_ns=int(log_time_ns),
        publish_time_ns=int(publish_time_ns),
        data=data[22:],
    )


def _iter_mcap_records(data: bytes, channels: dict[int, str]) -> Iterator[McapMessage]:
    pos = 0
    end = len(data)
    while pos < end:
        op = data[pos]
        length = struct.unpack_from("<Q", data, pos + 1)[0]
        body_start = pos + 9
        body_end = body_start + length
        if body_end > end:
            raise ValueError("MCAP record length exceeds containing chunk")
        body = data[body_start:body_end]
        pos = body_end
        if op == OP_CHANNEL:
            channel_id, topic = _parse_channel(body)
            channels[channel_id] = topic
        elif op == OP_MESSAGE:
            yield _parse_message(body, channels)
        elif op == OP_SCHEMA:
            continue


def iter_mcap_messages(path: Path, topics: set[str] | None = None) -> Iterator[McapMessage]:
    channels: dict[int, str] = {}
    with Path(path).open("rb") as stream:
        magic = stream.read(len(MCAP_MAGIC))
        if magic != MCAP_MAGIC:
            raise ValueError(f"not an MCAP file: {path}")
        while True:
            header = stream.read(9)
            if len(header) < 9:
                break
            op = header[0]
            length = struct.unpack("<Q", header[1:])[0]
            body = stream.read(length)
            if len(body) != length:
                raise ValueError(f"truncated MCAP record in {path}")
            if op == OP_CHANNEL:
                channel_id, topic = _parse_channel(body)
                channels[channel_id] = topic
            elif op == OP_MESSAGE:
                message = _parse_message(body, channels)
                if topics is None or message.topic in topics:
                    yield message
            elif op == OP_CHUNK:
                pos = 28
                compression_size = struct.unpack_from("<I", body, pos)[0]
                pos += 4
                compression = body[pos : pos + compression_size].decode("utf-8")
                pos += compression_size
                record_size = struct.unpack_from("<Q", body, pos)[0]
                pos += 8
                if compression:
                    raise ValueError(
                        f"compressed MCAP chunks are not supported: {compression}"
                    )
                records = body[pos : pos + record_size]
                for message in _iter_mcap_records(records, channels):
                    if topics is None or message.topic in topics:
                        yield message


def _decode_header(reader: CdrReader) -> DecodedHeader:
    sec = reader.uint32()
    nsec = reader.uint32()
    frame_id = reader.string()
    return DecodedHeader(stamp_ns=sec * 1_000_000_000 + nsec, frame_id=frame_id)


def decode_point_cloud2(data: bytes) -> DecodedPointCloud2:
    reader = CdrReader(data)
    header = _decode_header(reader)
    height = reader.uint32()
    width = reader.uint32()
    field_count = reader.uint32()
    fields: list[dict[str, int]] = []
    for _ in range(field_count):
        name = reader.string()
        fields.append(
            {
                "name": name,
                "offset": reader.uint32(),
                "datatype": reader.uint8(),
                "count": reader.uint32(),
            }
        )
    is_bigendian = reader.bool()
    point_step = reader.uint32()
    row_step = reader.uint32()
    point_data = reader.octet_sequence()
    is_dense = reader.bool()
    return DecodedPointCloud2(
        header=header,
        height=height,
        width=width,
        fields=tuple(fields),
        is_bigendian=is_bigendian,
        point_step=point_step,
        row_step=row_step,
        data=point_data,
        is_dense=is_dense,
    )


def decode_image(data: bytes) -> DecodedImage:
    reader = CdrReader(data)
    header = _decode_header(reader)
    height = reader.uint32()
    width = reader.uint32()
    encoding = reader.string()
    is_bigendian = reader.bool()
    step = reader.uint32()
    image_data = reader.octet_sequence()
    return DecodedImage(
        header=header,
        height=height,
        width=width,
        encoding=encoding,
        is_bigendian=is_bigendian,
        step=step,
        data=image_data,
    )


def point_cloud_to_matrix(cloud: DecodedPointCloud2) -> np.ndarray:
    if cloud.is_bigendian:
        byte_order = ">"
    else:
        byte_order = "<"
    names: list[str] = []
    formats: list[str] = []
    offsets: list[int] = []
    for field in cloud.fields:
        count = int(field["count"])
        if count != 1:
            continue
        dtype = POINT_FIELD_DTYPES.get(int(field["datatype"]))
        if dtype is None:
            continue
        names.append(str(field["name"]))
        formats.append(byte_order + dtype if dtype[-1] != "1" else dtype)
        offsets.append(int(field["offset"]))
    if not {"x", "y", "z"}.issubset(names):
        raise ValueError("PointCloud2 fields must include x, y and z")
    structured_dtype = np.dtype(
        {
            "names": names,
            "formats": formats,
            "offsets": offsets,
            "itemsize": cloud.point_step,
        }
    )
    point_count = cloud.height * cloud.width
    expected_bytes = point_count * cloud.point_step
    raw = cloud.data
    if cloud.row_step != cloud.width * cloud.point_step:
        rows = [
            raw[row * cloud.row_step : row * cloud.row_step + cloud.width * cloud.point_step]
            for row in range(cloud.height)
        ]
        raw = memoryview(b"".join(bytes(row) for row in rows))
    if len(raw) < expected_bytes:
        raise ValueError("PointCloud2 data is shorter than declared point count")
    structured = np.frombuffer(raw, dtype=structured_dtype, count=point_count)
    matrix = np.zeros((point_count, len(POINT_COLUMNS)), dtype="<f4")
    for index, column in enumerate(POINT_COLUMNS):
        if column in structured.dtype.names:
            matrix[:, index] = structured[column].astype(np.float32, copy=False)
    return matrix


def _block_demosaic_bayer(raw: np.ndarray, pattern: str) -> np.ndarray:
    even_height = raw.shape[0] - raw.shape[0] % 2
    even_width = raw.shape[1] - raw.shape[1] % 2
    cropped = raw[:even_height, :even_width]
    top_left = cropped[0::2, 0::2].astype(np.uint16)
    top_right = cropped[0::2, 1::2].astype(np.uint16)
    bottom_left = cropped[1::2, 0::2].astype(np.uint16)
    bottom_right = cropped[1::2, 1::2].astype(np.uint16)
    if pattern == "bayer_gbrg8":
        red, blue = bottom_left, top_right
        green = ((top_left + bottom_right) // 2).astype(np.uint8)
    elif pattern == "bayer_rggb8":
        red, blue = top_left, bottom_right
        green = ((top_right + bottom_left) // 2).astype(np.uint8)
    elif pattern == "bayer_bggr8":
        red, blue = bottom_right, top_left
        green = ((top_right + bottom_left) // 2).astype(np.uint8)
    elif pattern == "bayer_grbg8":
        red, blue = top_right, bottom_left
        green = ((top_left + bottom_right) // 2).astype(np.uint8)
    else:
        raise ValueError(f"unsupported Bayer encoding: {pattern}")
    rgb_small = np.dstack((red.astype(np.uint8), green, blue.astype(np.uint8)))
    rgb = np.repeat(np.repeat(rgb_small, 2, axis=0), 2, axis=1)
    if rgb.shape[:2] != raw.shape:
        padded = np.zeros((raw.shape[0], raw.shape[1], 3), dtype=np.uint8)
        padded[: rgb.shape[0], : rgb.shape[1]] = rgb
        padded[rgb.shape[0] :, :] = padded[rgb.shape[0] - 1 : rgb.shape[0], :]
        padded[:, rgb.shape[1] :] = padded[:, rgb.shape[1] - 1 : rgb.shape[1]]
        rgb = padded
    return rgb


def image_to_rgb(image: DecodedImage, *, mode: str) -> np.ndarray:
    encoding = image.encoding.lower()
    row = np.frombuffer(image.data, dtype=np.uint8).reshape(image.height, image.step)
    if encoding == "mono8" or mode == "grayscale":
        gray = row[:, : image.width]
        return np.dstack((gray, gray, gray))
    if encoding == "rgb8":
        return row[:, : image.width * 3].reshape(image.height, image.width, 3)
    if encoding == "bgr8":
        return row[:, : image.width * 3].reshape(image.height, image.width, 3)[:, :, ::-1]
    if encoding == "rgba8":
        return row[:, : image.width * 4].reshape(image.height, image.width, 4)[:, :, :3]
    if encoding == "bgra8":
        return row[:, : image.width * 4].reshape(image.height, image.width, 4)[:, :, 2::-1]
    if encoding.startswith("bayer_"):
        raw = row[:, : image.width]
        return _block_demosaic_bayer(raw, encoding)
    raise ValueError(f"unsupported image encoding: {image.encoding}")


def _parse_scalar(text: str, key: str) -> str:
    prefix = f"{key}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    raise ValueError(f"missing YAML key: {key}")


def _parse_number_block(text: str, key: str) -> list[float]:
    prefix = f"{key}:"
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            block: list[str] = []
            for candidate in lines[index + 1 :]:
                if candidate and not candidate.startswith((" ", "-")):
                    break
                block.append(candidate)
            numbers: list[float] = []
            for item in block:
                for token in item.replace("[", " ").replace("]", " ").split():
                    token = token.rstrip(",")
                    if token == "-":
                        continue
                    try:
                        numbers.append(float(token))
                    except ValueError:
                        continue
            return numbers
    raise ValueError(f"missing YAML key: {key}")


def _matrix(values: Sequence[float], rows: int, cols: int, key: str) -> list[list[float]]:
    expected = rows * cols
    if len(values) != expected:
        raise ValueError(f"{key} must contain {expected} numbers, found {len(values)}")
    return [
        [float(values[row * cols + col]) for col in range(cols)]
        for row in range(rows)
    ]


def _read_yaml_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def convert_calibration(
    calibration_root: Path,
    *,
    reference_frame: str = "robosense",
    camera_frame_convention: str = "tool_camera",
) -> dict[str, object]:
    root = Path(calibration_root)
    identity = np.eye(4, dtype=np.float64).tolist()
    cameras: dict[str, dict[str, object]] = {}
    for camera_id, stem in (
        ("CAM_LEFT", "cam_left"),
        ("CAM_RIGHT", "cam_right"),
    ):
        intrinsics_text = _read_yaml_text(root / f"{stem}_intrinsics.yaml")
        extrinsics_text = _read_yaml_text(root / f"{stem}_lidar_extrinsics.yaml")
        intrinsic = _matrix(
            _parse_number_block(intrinsics_text, "camera_matrix"),
            3,
            3,
            "camera_matrix",
        )
        distortion_model = _parse_scalar(intrinsics_text, "distortion_model")
        if distortion_model == "plumb_bob":
            output_distortion = "brown_conrady"
        elif distortion_model in {"none", "brown_conrady", "fisheye"}:
            output_distortion = distortion_model
        else:
            raise ValueError(f"unsupported distortion model: {distortion_model}")
        raw_transform = np.asarray(
            _matrix(
                _parse_number_block(extrinsics_text, "transform_lidar_to_camera"),
                4,
                4,
                "transform_lidar_to_camera",
            ),
            dtype=np.float64,
        )
        if camera_frame_convention == "tool_camera":
            transform = OPTICAL_TO_TOOL_CAMERA @ raw_transform
        elif camera_frame_convention == "as_provided":
            transform = raw_transform
        else:
            raise ValueError(f"unsupported camera frame convention: {camera_frame_convention}")
        cameras[camera_id] = {
            "intrinsic": intrinsic,
            "T_camera_reference": transform.tolist(),
            "image_size": [
                int(_parse_scalar(intrinsics_text, "image_width")),
                int(_parse_scalar(intrinsics_text, "image_height")),
            ],
            "distortion_model": output_distortion,
            "distortion_coefficients": _parse_number_block(
                intrinsics_text, "distortion_coefficients"
            ),
            "enabled": True,
        }
    return {
        "schema_version": "1.0",
        "reference_frame": reference_frame,
        "lidars": {"MERGED": {"T_reference_sensor": identity, "enabled": True}},
        "cameras": cameras,
        "metadata": {
            "source_format": "one_chip_apriltag_calib_main_02",
            "source_calibration_root": str(root),
            "raw_extrinsic_convention": "p_ros_optical_camera = T_lidar_to_camera @ p_lidar",
            "camera_frame_convention": camera_frame_convention,
            "tool_camera_note": (
                "tool_camera maps ROS optical [x right, y down, z forward] to "
                "LiDAR Label Tool camera [x forward, y left, z up]"
            ),
        },
    }


def _timestamp_for(
    message: McapMessage,
    decoded_header: DecodedHeader,
    source: str,
    header_log_offset_ns: int | None = None,
) -> int:
    if source == "log":
        return message.log_time_ns
    if source == "publish":
        return message.publish_time_ns
    if source == "header":
        if decoded_header.stamp_ns <= 0:
            raise ValueError("message header timestamp is zero")
        return decoded_header.stamp_ns
    if source == "header_aligned":
        if decoded_header.stamp_ns <= 0:
            raise ValueError("message header timestamp is zero")
        if header_log_offset_ns is None:
            raise ValueError("header_aligned requires a header/log offset")
        return decoded_header.stamp_ns + header_log_offset_ns
    raise ValueError(f"unsupported timestamp source: {source}")


def extract_lidar(
    mcap_path: Path,
    output_dir: Path,
    *,
    start_index: int,
    bag_name: str,
    timestamp_source: str,
    limit: int | None,
    progress_every: int,
) -> list[TimedSample]:
    samples: list[TimedSample] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    header_log_offset_ns: int | None = None
    for message in iter_mcap_messages(mcap_path, {LIDAR_TOPIC}):
        if limit is not None and len(samples) >= limit:
            break
        cloud = decode_point_cloud2(message.data)
        if timestamp_source == "header_aligned" and header_log_offset_ns is None:
            header_log_offset_ns = message.log_time_ns - cloud.header.stamp_ns
        sample_id = f"{start_index + len(samples):06d}"
        matrix = point_cloud_to_matrix(cloud)
        target = output_dir / f"{sample_id}.bin"
        with target.open("xb") as stream:
            matrix.tofile(stream)
        samples.append(
            TimedSample(
                sample_id=sample_id,
                timestamp_ns=_timestamp_for(
                    message, cloud.header, timestamp_source, header_log_offset_ns
                ),
                source_bag=bag_name,
                topic_sequence=message.sequence,
            )
        )
        if len(samples) % progress_every == 0:
            print(
                f"{bag_name} lidar {len(samples)} frames extracted "
                f"({target.name}, {matrix.shape[0]:,} points)",
                flush=True,
            )
    return samples


def extract_camera(
    mcap_path: Path,
    topic: str,
    output_dir: Path,
    *,
    start_index: int,
    bag_name: str,
    camera_id: str,
    timestamp_source: str,
    image_mode: str,
    jpeg_quality: int,
    limit: int | None,
    progress_every: int,
) -> list[TimedSample]:
    samples: list[TimedSample] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    header_log_offset_ns: int | None = None
    for message in iter_mcap_messages(mcap_path, {topic}):
        if limit is not None and len(samples) >= limit:
            break
        image = decode_image(message.data)
        if timestamp_source == "header_aligned" and header_log_offset_ns is None:
            header_log_offset_ns = message.log_time_ns - image.header.stamp_ns
        sample_id = f"{start_index + len(samples):06d}"
        target = output_dir / f"{sample_id}.jpg"
        rgb = image_to_rgb(image, mode=image_mode)
        Image.fromarray(rgb, mode="RGB").save(
            target, format="JPEG", quality=jpeg_quality, subsampling=1
        )
        samples.append(
            TimedSample(
                sample_id=sample_id,
                timestamp_ns=_timestamp_for(
                    message, image.header, timestamp_source, header_log_offset_ns
                ),
                source_bag=bag_name,
                topic_sequence=message.sequence,
            )
        )
        if len(samples) % progress_every == 0:
            print(
                f"{bag_name} {camera_id} {len(samples)} images extracted "
                f"({target.name})",
                flush=True,
            )
    return samples


def _message_header(message: McapMessage) -> DecodedHeader:
    reader = CdrReader(message.data)
    return _decode_header(reader)


def _message_timestamp(
    message: McapMessage, timestamp_source: str, header_log_offset_ns: int | None
) -> int:
    if timestamp_source in {"log", "publish"}:
        return _timestamp_for(
            message,
            DecodedHeader(stamp_ns=0, frame_id=""),
            timestamp_source,
        )
    decoded = _message_header(message)
    return _timestamp_for(message, decoded, timestamp_source, header_log_offset_ns)


def collect_timestamps(
    mcap_path: Path,
    topic: str,
    *,
    start_index: int,
    bag_name: str,
    timestamp_source: str,
) -> list[TimedSample]:
    samples: list[TimedSample] = []
    header_log_offset_ns: int | None = None
    for message in iter_mcap_messages(mcap_path, {topic}):
        if timestamp_source == "header_aligned" and header_log_offset_ns is None:
            header_log_offset_ns = message.log_time_ns - _message_header(message).stamp_ns
        sample_id = f"{start_index + len(samples):06d}"
        samples.append(
            TimedSample(
                sample_id=sample_id,
                timestamp_ns=_message_timestamp(
                    message, timestamp_source, header_log_offset_ns
                ),
                source_bag=bag_name,
                topic_sequence=message.sequence,
            )
        )
    return samples


def nearest_sample(
    target_ns: int, samples: Sequence[TimedSample], tolerance_ns: int
) -> tuple[TimedSample | None, int | None]:
    if not samples:
        return None, None
    timestamps = [sample.timestamp_ns for sample in samples]
    index = bisect_left(timestamps, target_ns)
    candidates = []
    if index < len(samples):
        candidates.append(samples[index])
    if index > 0:
        candidates.append(samples[index - 1])
    best = min(candidates, key=lambda sample: abs(sample.timestamp_ns - target_ns))
    delta = best.timestamp_ns - target_ns
    if abs(delta) > tolerance_ns:
        return None, delta
    return best, delta


def _numeric_sample_id(sample_id: str | None) -> int | None:
    if sample_id is None:
        return None
    try:
        return int(sample_id)
    except ValueError:
        return None


def _percentile(sorted_values: Sequence[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * fraction)))
    return float(sorted_values[index])


def timestamp_interval_qa(
    samples: Sequence[TimedSample], *, expected_ms: float | None = None
) -> dict[str, object]:
    intervals = [
        (samples[index].timestamp_ns - samples[index - 1].timestamp_ns) / 1_000_000.0
        for index in range(1, len(samples))
    ]
    sorted_intervals = sorted(intervals)
    report: dict[str, object] = {
        "sample_count": len(samples),
        "interval_count": len(intervals),
        "min_ms": _percentile(sorted_intervals, 0.0),
        "p50_ms": _percentile(sorted_intervals, 0.5),
        "p95_ms": _percentile(sorted_intervals, 0.95),
        "p99_ms": _percentile(sorted_intervals, 0.99),
        "max_ms": _percentile(sorted_intervals, 1.0),
    }
    if expected_ms is not None:
        short_threshold = expected_ms * 0.5
        long_threshold = expected_ms * 2.0
        short_events: list[dict[str, object]] = []
        long_events: list[dict[str, object]] = []
        for index, interval_ms in enumerate(intervals, start=1):
            if interval_ms < short_threshold and len(short_events) < 20:
                short_events.append(
                    {
                        "previous_sample": samples[index - 1].sample_id,
                        "sample": samples[index].sample_id,
                        "interval_ms": interval_ms,
                    }
                )
            if interval_ms > long_threshold and len(long_events) < 20:
                long_events.append(
                    {
                        "previous_sample": samples[index - 1].sample_id,
                        "sample": samples[index].sample_id,
                        "interval_ms": interval_ms,
                    }
                )
        report["expected_ms"] = expected_ms
        report["short_interval_count"] = sum(
            interval_ms < short_threshold for interval_ms in intervals
        )
        report["long_interval_count"] = sum(
            interval_ms > long_threshold for interval_ms in intervals
        )
        report["short_interval_examples"] = short_events
        report["long_interval_examples"] = long_events
    return report


def camera_sequence_qa(
    camera_usage: Mapping[str, Sequence[tuple[str, str | None]]]
) -> dict[str, object]:
    result: dict[str, object] = {}
    for camera_id, usage in camera_usage.items():
        repeat_runs: list[dict[str, object]] = []
        step_counts: dict[str, int] = {}
        jump_examples: list[dict[str, object]] = []
        non_monotonic_examples: list[dict[str, object]] = []
        previous_frame: str | None = None
        previous_sample: str | None = None
        previous_numeric: int | None = None
        current_run_sample: str | None = None
        current_run_start: str | None = None
        current_run_end: str | None = None
        current_run_count = 0
        max_repeat_run = 0
        repeated_frame_count = 0
        missing_frame_count = 0

        def flush_run() -> None:
            nonlocal max_repeat_run, repeated_frame_count
            if (
                current_run_sample is not None
                and current_run_start is not None
                and current_run_end is not None
                and current_run_count > 1
            ):
                max_repeat_run = max(max_repeat_run, current_run_count)
                repeated_frame_count += current_run_count - 1
                if len(repeat_runs) < 20:
                    repeat_runs.append(
                        {
                            "sample_id": current_run_sample,
                            "start_frame": current_run_start,
                            "end_frame": current_run_end,
                            "frame_count": current_run_count,
                        }
                    )

        for frame_id, sample_id in usage:
            numeric = _numeric_sample_id(sample_id)
            if sample_id is None:
                missing_frame_count += 1
                flush_run()
                current_run_sample = None
                current_run_start = None
                current_run_end = None
                current_run_count = 0
                previous_frame = frame_id
                previous_sample = None
                previous_numeric = None
                continue

            if sample_id == current_run_sample:
                current_run_end = frame_id
                current_run_count += 1
            else:
                flush_run()
                current_run_sample = sample_id
                current_run_start = frame_id
                current_run_end = frame_id
                current_run_count = 1

            if previous_numeric is not None and numeric is not None:
                step = numeric - previous_numeric
                step_counts[str(step)] = step_counts.get(str(step), 0) + 1
                if step < 0 and len(non_monotonic_examples) < 20:
                    non_monotonic_examples.append(
                        {
                            "previous_frame": previous_frame,
                            "frame": frame_id,
                            "previous_sample": previous_sample,
                            "sample": sample_id,
                            "step": step,
                        }
                    )
                elif step > 1 and len(jump_examples) < 20:
                    jump_examples.append(
                        {
                            "previous_frame": previous_frame,
                            "frame": frame_id,
                            "previous_sample": previous_sample,
                            "sample": sample_id,
                            "step": step,
                        }
                    )
            previous_frame = frame_id
            previous_sample = sample_id
            previous_numeric = numeric
        flush_run()
        result[camera_id] = {
            "matched_frame_count": len(usage) - missing_frame_count,
            "missing_frame_count": missing_frame_count,
            "max_repeat_run_frames": max_repeat_run,
            "repeated_frame_count": repeated_frame_count,
            "repeat_runs_first20": repeat_runs,
            "sample_step_counts": dict(sorted(step_counts.items(), key=lambda item: int(item[0]))),
            "jump_examples_first20": jump_examples,
            "non_monotonic_examples_first20": non_monotonic_examples,
        }
    return result


def dataset_layout_paths(layout: str) -> DatasetLayoutPaths:
    if layout == "simple":
        return DatasetLayoutPaths(
            name=layout,
            lidar_dir=Path("lidar"),
            cam_left_dir=Path("cam_left"),
            cam_right_dir=Path("cam_right"),
            lidar_pattern="lidar/{sample_id}.bin",
            cam_left_pattern="cam_left/{sample_id}.jpg",
            cam_right_pattern="cam_right/{sample_id}.jpg",
        )
    if layout == "legacy":
        return DatasetLayoutPaths(
            name=layout,
            lidar_dir=Path("sensors/lidar/MERGED/frames"),
            cam_left_dir=Path("sensors/camera/CAM_LEFT/images"),
            cam_right_dir=Path("sensors/camera/CAM_RIGHT/images"),
            lidar_pattern="sensors/lidar/MERGED/frames/{sample_id}.bin",
            cam_left_pattern="sensors/camera/CAM_LEFT/images/{sample_id}.jpg",
            cam_right_pattern="sensors/camera/CAM_RIGHT/images/{sample_id}.jpg",
        )
    raise ValueError(f"unsupported dataset layout: {layout}")


def write_frames_jsonl(
    path: Path,
    lidar_samples: Sequence[TimedSample],
    camera_samples: dict[str, Sequence[TimedSample]],
    *,
    tolerance_ns: int,
) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    missing: dict[str, int] = {camera_id: 0 for camera_id in camera_samples}
    max_abs_delta_ms: dict[str, float] = {camera_id: 0.0 for camera_id in camera_samples}
    camera_usage: dict[str, list[tuple[str, str | None]]] = {
        camera_id: [] for camera_id in camera_samples
    }
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for frame_index, lidar in enumerate(lidar_samples):
            frame_id = f"{frame_index:06d}"
            samples = {"lidar:MERGED": lidar.sample_id}
            deltas: dict[str, float] = {}
            for camera_id, entries in camera_samples.items():
                camera, delta_ns = nearest_sample(
                    lidar.timestamp_ns, entries, tolerance_ns
                )
                if camera is None:
                    missing[camera_id] += 1
                    camera_usage[camera_id].append((frame_id, None))
                    if delta_ns is not None:
                        deltas[camera_id] = delta_ns / 1_000_000.0
                    continue
                samples[f"camera:{camera_id}"] = camera.sample_id
                camera_usage[camera_id].append((frame_id, camera.sample_id))
                delta_ms = (camera.timestamp_ns - lidar.timestamp_ns) / 1_000_000.0
                deltas[camera_id] = delta_ms
                max_abs_delta_ms[camera_id] = max(
                    max_abs_delta_ms[camera_id], abs(delta_ms)
                )
            item = {
                "frame_id": frame_id,
                "timestamp_us": lidar.timestamp_ns // 1000,
                "samples": samples,
                "sync_delta_ms": deltas,
                "source_bag": lidar.source_bag,
                "source_lidar_sample": lidar.sample_id,
            }
            stream.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {
        "missing_camera_matches": missing,
        "max_abs_delta_ms": max_abs_delta_ms,
        "camera_sequence_qa": camera_sequence_qa(camera_usage),
        "timestamp_interval_qa": {
            "lidar": timestamp_interval_qa(lidar_samples, expected_ms=100.0),
            "cameras": {
                camera_id: timestamp_interval_qa(samples)
                for camera_id, samples in camera_samples.items()
            },
        },
    }


def _manifest(
    dataset_id: str, reference_frame: str, layout_paths: DatasetLayoutPaths
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "dataset_id": dataset_id,
        "layout": "device_centric",
        "storage_layout": layout_paths.name,
        "reference_frame": reference_frame,
        "primary_lidar": "MERGED",
        "sensors": [
            {
                "id": "MERGED",
                "type": "lidar",
                "coordinate_frame": reference_frame,
                "data_patterns": {
                    "return1": layout_paths.lidar_pattern
                },
                "point_columns": list(POINT_COLUMNS),
                "point_dtype": "float32",
                "byte_order": "little-endian",
            },
            {
                "id": "CAM_LEFT",
                "type": "camera",
                "coordinate_frame": "camera:CAM_LEFT",
                "data_patterns": {
                    "image": layout_paths.cam_left_pattern
                },
            },
            {
                "id": "CAM_RIGHT",
                "type": "camera",
                "coordinate_frame": "camera:CAM_RIGHT",
                "data_patterns": {
                    "image": layout_paths.cam_right_pattern
                },
            },
        ],
        "synchronization": {"mode": "index", "index_path": "sync/frames.jsonl"},
        "calibration_path": "calibration/calibration.json",
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _bag_roots(source_root: Path, selected: Sequence[str] | None) -> list[Path]:
    rosbags = source_root / "rosbags"
    if selected:
        return [rosbags / name for name in selected]
    return sorted(path for path in rosbags.iterdir() if path.is_dir())


def _required_mcap_paths(bag_root: Path) -> dict[str, Path]:
    return {
        "lidar": bag_root / "lidar" / "lidar_0.mcap",
        "CAM_LEFT": bag_root / "cam_left" / "cam_left_0.mcap",
        "CAM_RIGHT": bag_root / "cam_right" / "cam_right_0.mcap",
    }


def convert_dataset(args: argparse.Namespace) -> None:
    source_root = Path(args.source).resolve()
    output_root = Path(args.output).resolve()
    calibration_root = Path(args.calibration).resolve()
    layout_paths = dataset_layout_paths(args.dataset_layout)
    if output_root.exists():
        raise FileExistsError(f"output already exists: {output_root}")
    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    if not calibration_root.is_dir():
        raise FileNotFoundError(calibration_root)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = output_root.with_name(f".{output_root.name}.building-{uuid4().hex}")
    staging.mkdir()
    try:
        calibration = convert_calibration(
            calibration_root,
            reference_frame=args.reference_frame,
            camera_frame_convention=args.camera_frame_convention,
        )
        _write_json(staging / "calibration" / "calibration.json", calibration)
        _write_json(
            staging / "dataset.json",
            _manifest(args.dataset_id, args.reference_frame, layout_paths),
        )

        all_lidar: list[TimedSample] = []
        all_left: list[TimedSample] = []
        all_right: list[TimedSample] = []
        remaining = args.limit
        for bag_root in _bag_roots(source_root, args.bag):
            paths = _required_mcap_paths(bag_root)
            missing = [str(path) for path in paths.values() if not path.is_file()]
            if missing:
                raise FileNotFoundError("missing MCAP files: " + ", ".join(missing))
            bag_limit = remaining
            if remaining is not None and remaining <= 0:
                break
            print(f"converting bag: {bag_root.name}", flush=True)
            left = extract_camera(
                paths["CAM_LEFT"],
                CAMERA_TOPICS["CAM_LEFT"],
                staging / layout_paths.cam_left_dir,
                start_index=len(all_left),
                bag_name=bag_root.name,
                camera_id="CAM_LEFT",
                timestamp_source=args.timestamp_source,
                image_mode=args.image_mode,
                jpeg_quality=args.jpeg_quality,
                limit=bag_limit,
                progress_every=args.progress_every,
            )
            right = extract_camera(
                paths["CAM_RIGHT"],
                CAMERA_TOPICS["CAM_RIGHT"],
                staging / layout_paths.cam_right_dir,
                start_index=len(all_right),
                bag_name=bag_root.name,
                camera_id="CAM_RIGHT",
                timestamp_source=args.timestamp_source,
                image_mode=args.image_mode,
                jpeg_quality=args.jpeg_quality,
                limit=bag_limit,
                progress_every=args.progress_every,
            )
            lidar = extract_lidar(
                paths["lidar"],
                staging / layout_paths.lidar_dir,
                start_index=len(all_lidar),
                bag_name=bag_root.name,
                timestamp_source=args.timestamp_source,
                limit=bag_limit,
                progress_every=args.progress_every,
            )
            all_left.extend(left)
            all_right.extend(right)
            all_lidar.extend(lidar)
            if remaining is not None:
                remaining -= len(lidar)

        all_left.sort(key=lambda sample: sample.timestamp_ns)
        all_right.sort(key=lambda sample: sample.timestamp_ns)
        sync_report = write_frames_jsonl(
            staging / "sync" / "frames.jsonl",
            all_lidar,
            {"CAM_LEFT": all_left, "CAM_RIGHT": all_right},
            tolerance_ns=round(args.sync_tolerance_ms * 1_000_000),
        )
        report = {
            "source_root": str(source_root),
            "output_root": str(output_root),
            "dataset_id": args.dataset_id,
            "storage_layout": layout_paths.name,
            "data_patterns": {
                "lidar": layout_paths.lidar_pattern,
                "CAM_LEFT": layout_paths.cam_left_pattern,
                "CAM_RIGHT": layout_paths.cam_right_pattern,
            },
            "timestamp_source": args.timestamp_source,
            "sync_tolerance_ms": args.sync_tolerance_ms,
            "counts": {
                "lidar": len(all_lidar),
                "CAM_LEFT": len(all_left),
                "CAM_RIGHT": len(all_right),
            },
            "sync": sync_report,
            "point_columns": list(POINT_COLUMNS),
            "image_mode": args.image_mode,
            "jpeg_quality": args.jpeg_quality,
        }
        _write_json(staging / "conversion_report.json", report)
        staging.replace(output_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(f"created: {output_root}", flush=True)


def resync_existing_dataset(args: argparse.Namespace) -> None:
    source_root = Path(args.source).resolve()
    output_root = Path(args.output).resolve()
    if not output_root.is_dir():
        raise FileNotFoundError(output_root)
    all_lidar: list[TimedSample] = []
    all_left: list[TimedSample] = []
    all_right: list[TimedSample] = []
    remaining = args.limit
    for bag_root in _bag_roots(source_root, args.bag):
        paths = _required_mcap_paths(bag_root)
        bag_limit = remaining
        if remaining is not None and remaining <= 0:
            break
        print(f"collecting timestamps: {bag_root.name}", flush=True)
        left = collect_timestamps(
            paths["CAM_LEFT"],
            CAMERA_TOPICS["CAM_LEFT"],
            start_index=len(all_left),
            bag_name=bag_root.name,
            timestamp_source=args.timestamp_source,
        )
        right = collect_timestamps(
            paths["CAM_RIGHT"],
            CAMERA_TOPICS["CAM_RIGHT"],
            start_index=len(all_right),
            bag_name=bag_root.name,
            timestamp_source=args.timestamp_source,
        )
        lidar = collect_timestamps(
            paths["lidar"],
            LIDAR_TOPIC,
            start_index=len(all_lidar),
            bag_name=bag_root.name,
            timestamp_source=args.timestamp_source,
        )
        if bag_limit is not None:
            left = left[:bag_limit]
            right = right[:bag_limit]
            lidar = lidar[:bag_limit]
        all_left.extend(left)
        all_right.extend(right)
        all_lidar.extend(lidar)
        if remaining is not None:
            remaining -= len(lidar)
    all_left.sort(key=lambda sample: sample.timestamp_ns)
    all_right.sort(key=lambda sample: sample.timestamp_ns)
    target = output_root / "sync" / "frames.jsonl"
    backup_path: Path | None = None
    if target.is_file() and not args.no_sync_backup:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = target.with_name(f"{target.name}.bak-{timestamp}-{uuid4().hex[:8]}")
        shutil.copy2(target, backup_path)
    temp = target.with_name(f".{target.name}.resync-{uuid4().hex}.tmp")
    sync_report = write_frames_jsonl(
        temp,
        all_lidar,
        {"CAM_LEFT": all_left, "CAM_RIGHT": all_right},
        tolerance_ns=round(args.sync_tolerance_ms * 1_000_000),
    )
    temp.replace(target)
    report_path = output_root / "conversion_report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        report = {}
    report.update(
        {
            "timestamp_source": args.timestamp_source,
            "sync_tolerance_ms": args.sync_tolerance_ms,
            "resynced": True,
            "sync_backup_path": str(backup_path) if backup_path is not None else None,
            "counts": {
                "lidar": len(all_lidar),
                "CAM_LEFT": len(all_left),
                "CAM_RIGHT": len(all_right),
            },
            "sync": sync_report,
        }
    )
    _write_json(report_path, report)
    print(f"resynced: {target}", flush=True)


def write_calibration_only(args: argparse.Namespace) -> None:
    output = Path(args.output).resolve()
    if output.exists() and output.is_dir():
        target = output / "calibration.json"
    else:
        target = output
    if target.exists():
        raise FileExistsError(f"output already exists: {target}")
    calibration = convert_calibration(
        Path(args.calibration).resolve(),
        reference_frame=args.reference_frame,
        camera_frame_convention=args.camera_frame_convention,
    )
    _write_json(target, calibration)
    print(f"created: {target}", flush=True)


def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("value must be a non-negative finite number")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert one_chip MCAP ROS2 bags into LiDAR Label Tool device-centric data."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--calibration",
        type=Path,
        default=DEFAULT_CALIBRATION_ROOT,
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Converted dataset folder, or calibration JSON path with --calibration-only. "
            "If omitted, the user-editable defaults at the top of this script are used."
        ),
    )
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET_ID)
    parser.add_argument("--reference-frame", default=DEFAULT_REFERENCE_FRAME)
    parser.add_argument(
        "--dataset-layout",
        choices=("simple", "legacy"),
        default=DEFAULT_DATASET_LAYOUT,
        help=(
            "Physical output folder layout. simple writes lidar/, cam_left/, cam_right/. "
            "legacy writes sensors/lidar/MERGED/frames and sensors/camera/.../images."
        ),
    )
    parser.add_argument(
        "--bag",
        action="append",
        default=list(DEFAULT_BAGS) if DEFAULT_BAGS else None,
        help="Convert only this rosbag folder name.",
    )
    parser.add_argument(
        "--timestamp-source",
        choices=("log", "publish", "header", "header_aligned"),
        default=DEFAULT_TIMESTAMP_SOURCE,
        help=(
            "Timestamp used for nearest sync. header_aligned preserves message header "
            "intervals but aligns each stream to its first MCAP log time."
        ),
    )
    parser.add_argument(
        "--sync-tolerance-ms",
        type=positive_float,
        default=DEFAULT_SYNC_TOLERANCE_MS,
        help="Maximum absolute camera/LiDAR timestamp delta accepted in frames.jsonl.",
    )
    parser.add_argument(
        "--camera-frame-convention",
        choices=("tool_camera", "as_provided"),
        default=DEFAULT_CAMERA_FRAME_CONVENTION,
        help=(
            "tool_camera converts ROS optical camera axes for the current projection code; "
            "as_provided writes the raw YAML transform."
        ),
    )
    parser.add_argument(
        "--image-mode",
        choices=("block_demosaic", "grayscale"),
        default=DEFAULT_IMAGE_MODE,
    )
    parser.add_argument("--jpeg-quality", type=int, default=DEFAULT_JPEG_QUALITY)
    parser.add_argument("--limit", type=int, help="Limit extracted LiDAR frames for smoke tests.")
    parser.add_argument("--progress-every", type=int, default=DEFAULT_PROGRESS_EVERY)
    parser.add_argument(
        "--calibration-only",
        action="store_true",
        help="Write only calibration.json to --output.",
    )
    parser.add_argument(
        "--sync-only-existing",
        action="store_true",
        help="Regenerate only sync/frames.jsonl for an existing converted dataset.",
    )
    parser.add_argument(
        "--no-sync-backup",
        action="store_true",
        help="Do not copy the previous sync/frames.jsonl before --sync-only-existing replacement.",
    )
    parser.add_argument(
        "--print-default",
        choices=("source", "calibration", "output", "calibration-output"),
        help="Print one user-editable default path and exit. Used by helper .bat files.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.print_default:
        defaults = {
            "source": DEFAULT_SOURCE_ROOT,
            "calibration": DEFAULT_CALIBRATION_ROOT,
            "output": DEFAULT_OUTPUT_ROOT,
            "calibration-output": DEFAULT_CALIBRATION_JSON_OUTPUT,
        }
        print(defaults[args.print_default])
        return 0
    if args.output is None:
        args.output = (
            DEFAULT_CALIBRATION_JSON_OUTPUT
            if args.calibration_only
            else DEFAULT_OUTPUT_ROOT
        )
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if not (1 <= args.jpeg_quality <= 100):
        parser.error("--jpeg-quality must be between 1 and 100")
    if args.progress_every <= 0:
        parser.error("--progress-every must be positive")
    if args.calibration_only:
        write_calibration_only(args)
    elif args.sync_only_existing:
        resync_existing_dataset(args)
    else:
        convert_dataset(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
