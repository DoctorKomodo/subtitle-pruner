"""Tests for SubtitleProcessor.analyze_file() logic with mocked track info."""

from unittest.mock import patch
from processor import SubtitleProcessor


def make_processor(languages=None):
    """Create a SubtitleProcessor without mkvmerge verification."""
    if languages is None:
        languages = ['eng', 'dan']
    return SubtitleProcessor(languages, skip_verify=True)


def make_track(track_id, language, forced=False, track_type='subtitles', name=''):
    """Build a track dict matching mkvmerge JSON identify output format."""
    return {
        'id': track_id,
        'type': track_type,
        'properties': {
            'language': language,
            'forced_track': forced,
            'track_name': name,
        }
    }


class TestAnalyzeFileSkipConditions:
    def test_file_not_found(self, tmp_path):
        proc = make_processor()
        result = proc.analyze_file(str(tmp_path / 'nonexistent.mkv'))
        assert result['needs_processing'] is False
        assert 'not found' in result['reason'].lower()

    def test_non_mkv_file(self, tmp_path):
        f = tmp_path / 'test.mp4'
        f.touch()
        proc = make_processor()
        result = proc.analyze_file(str(f))
        assert result['needs_processing'] is False
        assert 'not an mkv' in result['reason'].lower()

    @patch.object(SubtitleProcessor, 'get_track_info')
    def test_no_subtitle_tracks(self, mock_gti, tmp_path):
        f = tmp_path / 'test.mkv'
        f.touch()
        mock_gti.return_value = {
            'tracks': [
                make_track(0, 'eng', track_type='video'),
                make_track(1, 'eng', track_type='audio'),
            ]
        }
        proc = make_processor()
        result = proc.analyze_file(str(f))
        assert result['needs_processing'] is False
        assert 'no subtitle' in result['reason'].lower()

    @patch.object(SubtitleProcessor, 'get_track_info')
    def test_all_tracks_allowed_nothing_to_remove(self, mock_gti, tmp_path):
        f = tmp_path / 'test.mkv'
        f.touch()
        mock_gti.return_value = {
            'tracks': [
                make_track(2, 'eng'),
                make_track(3, 'dan'),
            ]
        }
        proc = make_processor(['eng', 'dan'])
        result = proc.analyze_file(str(f))
        assert result['needs_processing'] is False
        assert 'no subtitle tracks to remove' in result['reason'].lower()


class TestAnalyzeFileProcessingNeeded:
    @patch.object(SubtitleProcessor, 'get_track_info')
    def test_removes_disallowed_language(self, mock_gti, tmp_path):
        f = tmp_path / 'test.mkv'
        f.touch()
        mock_gti.return_value = {
            'tracks': [
                make_track(2, 'eng'),
                make_track(3, 'fre'),
            ]
        }
        proc = make_processor(['eng'])
        result = proc.analyze_file(str(f))
        assert result['needs_processing'] is True
        assert len(result['tracks_to_keep']) == 1
        assert result['tracks_to_keep'][0]['language'] == 'eng'
        assert len(result['tracks_to_remove']) == 1
        assert result['tracks_to_remove'][0]['language'] == 'fre'

    @patch.object(SubtitleProcessor, 'get_track_info')
    def test_removes_forced_tracks(self, mock_gti, tmp_path):
        f = tmp_path / 'test.mkv'
        f.touch()
        mock_gti.return_value = {
            'tracks': [
                make_track(2, 'eng'),
                make_track(3, 'eng', forced=True),
            ]
        }
        proc = make_processor(['eng'])
        result = proc.analyze_file(str(f))
        assert result['needs_processing'] is True
        assert len(result['tracks_to_keep']) == 1
        assert len(result['tracks_to_remove']) == 1
        assert result['tracks_to_remove'][0]['forced'] is True


class TestAnalyzeFileEdgeCases:
    @patch.object(SubtitleProcessor, 'get_track_info')
    def test_unidentified_language_prevents_removal(self, mock_gti, tmp_path):
        """When all tracks would be removed and some have 'und' language, skip."""
        f = tmp_path / 'test.mkv'
        f.touch()
        mock_gti.return_value = {
            'tracks': [
                make_track(2, 'und'),
            ]
        }
        proc = make_processor(['eng'])
        result = proc.analyze_file(str(f))
        assert result['needs_processing'] is False
        assert 'unidentified' in result['reason'].lower()

    @patch.object(SubtitleProcessor, 'get_track_info')
    def test_all_identified_non_allowed_removed(self, mock_gti, tmp_path):
        """When all tracks have known non-allowed languages, allow removal."""
        f = tmp_path / 'test.mkv'
        f.touch()
        mock_gti.return_value = {
            'tracks': [
                make_track(2, 'fre'),
                make_track(3, 'ger'),
            ]
        }
        proc = make_processor(['eng'])
        result = proc.analyze_file(str(f))
        assert result['needs_processing'] is True
        assert len(result['tracks_to_keep']) == 0
        assert len(result['tracks_to_remove']) == 2

    @patch.object(SubtitleProcessor, 'get_track_info')
    def test_get_track_info_exception_returns_error(self, mock_gti, tmp_path):
        f = tmp_path / 'test.mkv'
        f.touch()
        mock_gti.side_effect = RuntimeError('mkvmerge crashed')
        proc = make_processor()
        result = proc.analyze_file(str(f))
        assert result['needs_processing'] is False
        assert result['action'] == 'error'
