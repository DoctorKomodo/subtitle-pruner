"""Tests for apply_path_mapping() in app.py."""

from app import apply_path_mapping, CONFIG


class TestApplyPathMapping:
    def setup_method(self):
        """Save and clear path mappings before each test."""
        self._original = CONFIG['path_mappings'][:]
        CONFIG['path_mappings'] = []

    def teardown_method(self):
        """Restore original path mappings."""
        CONFIG['path_mappings'] = self._original

    def test_no_mappings_returns_unchanged(self):
        assert apply_path_mapping('/media/movies/test.mkv') == '/media/movies/test.mkv'

    def test_matching_mapping_replaces_prefix(self):
        CONFIG['path_mappings'] = [('\\\\server\\movies\\', '/media/movies/')]
        result = apply_path_mapping('\\\\server\\movies\\Film.mkv')
        assert result == '/media/movies/Film.mkv'

    def test_backslashes_normalized_to_forward_slashes(self):
        CONFIG['path_mappings'] = [('\\\\server\\tv\\', '/media/tv/')]
        result = apply_path_mapping('\\\\server\\tv\\Show\\S01\\Episode.mkv')
        assert result == '/media/tv/Show/S01/Episode.mkv'

    def test_first_match_wins(self):
        CONFIG['path_mappings'] = [
            ('/old/', '/new/'),
            ('/old/', '/other/'),
        ]
        assert apply_path_mapping('/old/file.mkv') == '/new/file.mkv'

    def test_no_match_returns_unchanged(self):
        CONFIG['path_mappings'] = [('/foo/', '/bar/')]
        assert apply_path_mapping('/baz/file.mkv') == '/baz/file.mkv'

    def test_partial_prefix_no_match(self):
        CONFIG['path_mappings'] = [('/media/movies/', '/data/movies/')]
        result = apply_path_mapping('/media/tv/show.mkv')
        assert result == '/media/tv/show.mkv'
