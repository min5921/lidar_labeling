from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lidar_label_tool.services.timestamp_table import (
    TimestampTableError,
    read_timestamp_table,
)


class TimestampTableTests(unittest.TestCase):
    def test_reads_bom_csv_as_exact_int64_nanoseconds(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "시간.csv"
            path.write_text(
                "\ufeffsample_id,device_us\n000001,1778225784354747\n000002,1778225784354746\n",
                encoding="utf-8",
            )

            table = read_timestamp_table(
                path,
                sample_id_column="sample_id",
                value_column="device_us",
                unit="us",
                clock_domain="device",
                offset_ns=3,
            )

            self.assertEqual(table.timestamp_for("000001"), 1_778_225_784_354_747_003)
            self.assertEqual(table.reordered_row_count, 1)
            self.assertEqual(table.rows[0].sample_id, "000001")

    def test_reports_duplicate_sample_and_invalid_values(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "timestamps.csv"
            path.write_text("id,time\na,1\na,2\n", encoding="utf-8")
            with self.assertRaises(TimestampTableError) as duplicate:
                read_timestamp_table(
                    path,
                    sample_id_column="id",
                    value_column="time",
                    unit="ns",
                    clock_domain="bag",
                )
            self.assertEqual(duplicate.exception.code, "timestamp_sample_id_duplicate")

            path.write_text("id,time\na,1.5\n", encoding="utf-8")
            with self.assertRaises(TimestampTableError) as invalid:
                read_timestamp_table(
                    path,
                    sample_id_column="id",
                    value_column="time",
                    unit="ns",
                    clock_domain="bag",
                )
            self.assertEqual(invalid.exception.code, "timestamp_value_invalid")

    def test_reports_duplicate_timestamp_without_losing_rows(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "timestamps.csv"
            path.write_text("id,time\na,10\nb,10\nc,11\n", encoding="utf-8")
            table = read_timestamp_table(
                path,
                sample_id_column="id",
                value_column="time",
                unit="ns",
                clock_domain="bag",
            )
            self.assertEqual(table.duplicate_timestamp_count, 1)
            self.assertEqual(len(table.rows), 3)


if __name__ == "__main__":
    unittest.main()
