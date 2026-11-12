"""The camera's detection lines: parsing, the serial port and replayed logs.

The detector firmware is written separately and its line format may still
move, so the parser is checked against the planned format and against the
ways it is likely to change.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sketch_artist.detections import (Detection, ReplayDetectionSource,
                                      SerialDetectionSource, find_camera_port,
                                      format_det_line, parse_det_line,
                                      split_log_line)

PLANNED = ("DET n=2 yellow 0.42 0.61 0.93 red 0.70 0.33 0.88 "
           "bin 0.15 0.20 0.97 ms=41")


def test_planned_format():
    frame = parse_det_line(PLANNED, time_s=1.5)
    assert [d.label for d in frame.detections] == ["yellow", "red", "bin"]
    assert frame.detections[0] == Detection("yellow", 0.42, 0.61, 0.93)
    assert frame.detections[2].confidence == 0.97
    assert frame.inference_ms == 41
    assert frame.declared_count == 2      # the count is reported, not trusted
    assert frame.time_s == 1.5


def test_empty_frame_is_a_frame():
    frame = parse_det_line("DET n=0 ms=38")
    assert frame is not None and frame.detections == []


@pytest.mark.parametrize("line", [
    "DET red 0.70 0.33 0.88",                                  # no count, no time
    "det N=1 RED 0.70 0.33 0.88 MS=41",                        # upper case
    "DET v=2 n=1 red 0.70 0.33 0.88 ms=41 fps=19.5",           # new fields
    "DET n=1 red 0.70 0.33 0.88 0.12 0.09 ms=41",              # box size added
    "DET n=1, red, 0.70, 0.33, 0.88, ms=41",                   # commas
    "I (5123) detector: DET n=1 red 0.70 0.33 0.88 ms=41",     # log prefix
    "DET n=1 red 0.70 0.33 0.88 ms=41\r\n",                    # line ending
    "DET n=3 red 0.70 0.33 0.88 ms=41",                        # wrong count
    "DET n=1 ms=41 red 0.70 0.33 0.88",                        # fields moved
])
def test_tolerated_variations(line):
    frame = parse_det_line(line)
    assert len(frame.detections) == 1
    red = frame.detections[0]
    assert (red.label, red.x, red.y, red.confidence) == ("red", 0.70, 0.33, 0.88)


def test_extra_numbers_and_fields_are_kept():
    frame = parse_det_line("DET v=2 n=1 red 0.70 0.33 0.88 0.12 0.09 ms=41")
    assert frame.detections[0].extra == (0.12, 0.09)
    assert frame.meta == {"v": "2"}


@pytest.mark.parametrize("line", [
    "", "boot: camera ready", "DETECTOR starting", "ESP-ROM:esp32s3-20210327",
    None, "n=1 red 0.70 0.33 0.88",
])
def test_other_lines_are_not_frames(line):
    assert parse_det_line(line) is None


def test_bad_groups_are_dropped_and_the_rest_kept():
    frame = parse_det_line(
        "DET n=4 red 0.70 0.33 yellow 0.42 0.61 0.93 white 3.0 0.5 0.9 "
        "bin 0.1 0.2 1.7 ms=40")
    assert [d.label for d in frame.detections] == ["yellow"]


def test_positions_a_hair_outside_the_picture_are_clamped():
    frame = parse_det_line("DET n=1 red 1.02 -0.01 0.9")
    assert (frame.detections[0].x, frame.detections[0].y) == (1.0, 0.0)


def test_with_label_filters_and_sorts():
    frame = parse_det_line("DET n=3 red 0.1 0.1 0.5 red 0.2 0.2 0.9 bin 0.5 0.5 0.8")
    assert [d.confidence for d in frame.with_label("red")] == [0.9, 0.5]
    assert [d.confidence for d in frame.with_label("red", 0.6)] == [0.9]


def test_format_round_trip():
    detections = [Detection("yellow", 0.42, 0.61, 0.93), Detection("bin", 0.15, 0.2, 0.97)]
    line = format_det_line(detections, 41)
    assert line == "DET n=2 yellow 0.42 0.61 0.93 bin 0.15 0.20 0.97 ms=41"
    assert parse_det_line(line).detections == detections


def test_camera_port_is_found_by_espressif_vendor_id():
    ports = [SimpleNamespace(device="/dev/ttyACM0", vid=0x2341),
             SimpleNamespace(device="/dev/ttyACM2", vid=0x303A),
             SimpleNamespace(device="/dev/ttyACM1", vid=0x303A),
             SimpleNamespace(device="/dev/ttyS0", vid=None)]
    assert find_camera_port(ports) == "/dev/ttyACM1"
    assert find_camera_port(ports[:1]) is None


class FakePort:
    def __init__(self, lines):
        self.lines = list(lines)
        self.closed = False

    def readline(self):
        return self.lines.pop(0) if self.lines else b""

    def close(self):
        self.closed = True


def test_serial_source_returns_the_newest_frame_and_records(tmp_path):
    port = FakePort([b"boot noise\n", b"DET n=1 red 0.10 0.10 0.90 ms=40\n",
                     b"\xff\xfe garbage\n", b"DET n=1 red 0.20 0.20 0.90 ms=40\n"])
    log = tmp_path / "det.log"
    source = SerialDetectionSource(record_path=str(log), opener=lambda: port)
    with source:
        source._thread.join(timeout=2.0)        # the fake stream has run out
        frame = source.read(0.5)
        assert frame.detections[0].x == 0.20    # stale frames are skipped
        assert source.read(0.05) is None        # nothing new: times out
        assert (source.lines_seen, source.lines_parsed) == (4, 2)
    assert port.closed
    recorded = log.read_text(encoding="ascii").splitlines()
    assert len(recorded) == 2
    stamp, line = split_log_line(recorded[0])
    assert stamp is not None and line.startswith("DET n=1 red 0.10")


def test_serial_source_reports_a_missing_camera(monkeypatch):
    from sketch_artist import detections

    monkeypatch.setattr(detections, "find_camera_port", lambda ports=None: None)
    with pytest.raises(RuntimeError, match="303A"):
        SerialDetectionSource().open()


def test_replay_keeps_recorded_spacing(tmp_path):
    log = tmp_path / "det.log"
    log.write_text("10.000 DET n=0 ms=40\n"
                   "boot noise\n"
                   "10.050 DET n=1 red 0.5 0.5 0.9 ms=40\n"
                   "13.000 DET n=1 red 0.6 0.5 0.9 ms=40\n", encoding="ascii")
    source = ReplayDetectionSource(str(log), realtime=False)
    assert len(source) == 3
    assert source.read(1.0).detections == []
    assert source.read(1.0).detections[0].x == 0.5
    assert source.now() == pytest.approx(0.05)
    assert source.read(1.0) is None              # a 2.95 s gap: watchdog food
    assert source.now() == pytest.approx(1.05)
    assert source.read(3.0).detections[0].x == 0.6
    assert source.read(1.0) is None              # the log has run out


def test_replay_of_a_plain_capture_and_skipping_stale_frames(tmp_path):
    log = tmp_path / "plain.log"
    log.write_text("".join(f"DET n=1 red 0.{i}0 0.5 0.9\n" for i in range(1, 7)),
                   encoding="ascii")
    source = ReplayDetectionSource(str(log), realtime=False, period_s=0.1)
    assert source.read(1.0).detections[0].x == 0.10
    source.sleep(0.35)                           # the arm was busy
    assert source.read(1.0).detections[0].x == 0.40
