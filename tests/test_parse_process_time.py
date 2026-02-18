"""Tests for ProcessingWorker._parse_process_time() static method."""

from worker import ProcessingWorker


class TestParseProcessTime:
    def test_empty_string_returns_none(self):
        assert ProcessingWorker._parse_process_time('') is None

    def test_whitespace_only_returns_none(self):
        assert ProcessingWorker._parse_process_time('   ') is None

    def test_valid_time(self):
        assert ProcessingWorker._parse_process_time('02:00') == (2, 0)

    def test_midnight(self):
        assert ProcessingWorker._parse_process_time('00:00') == (0, 0)

    def test_end_of_day(self):
        assert ProcessingWorker._parse_process_time('23:59') == (23, 59)

    def test_invalid_format_returns_none(self):
        assert ProcessingWorker._parse_process_time('2pm') is None

    def test_out_of_range_hour_returns_none(self):
        assert ProcessingWorker._parse_process_time('25:00') is None

    def test_out_of_range_minute_returns_none(self):
        assert ProcessingWorker._parse_process_time('12:60') is None

    def test_leading_trailing_whitespace_stripped(self):
        assert ProcessingWorker._parse_process_time('  14:30  ') == (14, 30)
