"""
Subtitle processor - handles the actual MKV subtitle pruning using mkvmerge.
"""

import os
import json
import subprocess
import logging
import shutil
from typing import List

logger = logging.getLogger(__name__)


class SubtitleProcessor:
    """Processes MKV files to remove unwanted subtitle tracks."""
    
    def __init__(self, allowed_languages: List[str]):
        self.allowed_languages = [lang.strip().lower() for lang in allowed_languages]
        logger.info(f"Subtitle processor initialized with allowed languages: {self.allowed_languages}")
        
        # Verify mkvmerge is available
        self._verify_mkvmerge()
    
    def _verify_mkvmerge(self):
        """Verify mkvmerge is installed and accessible."""
        try:
            result = subprocess.run(
                ['mkvmerge', '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.strip().split('\n')[0]
                logger.info(f"Found {version}")
            else:
                raise RuntimeError(f"mkvmerge check failed: {result.stderr}")
        except FileNotFoundError:
            raise RuntimeError("mkvmerge not found. Please install mkvtoolnix.")
    
    def get_track_info(self, file_path: str) -> dict:
        """Get track information from an MKV file."""
        result = subprocess.run(
            ['mkvmerge', '--identify', '--identification-format', 'json', file_path],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"mkvmerge identify failed: {result.stderr}")
        
        return json.loads(result.stdout)
    
    def analyze_file(self, file_path: str) -> dict:
        """
        Analyze an MKV file to determine if subtitle pruning is needed.

        Returns a dict with:
            - needs_processing: True if subtitles need to be removed
            - action: 'skipped' if no processing needed
            - reason: why the file was skipped (if skipped)
            - tracks_to_keep: list of tracks to keep (if needs_processing)
            - tracks_to_remove: list of tracks to remove (if needs_processing)
        """
        # Verify file exists
        if not os.path.exists(file_path):
            return {
                'needs_processing': False,
                'action': 'skipped',
                'reason': f'File not found: {file_path}'
            }

        # Verify it's an MKV file
        if not file_path.lower().endswith('.mkv'):
            return {
                'needs_processing': False,
                'action': 'skipped',
                'reason': 'Not an MKV file'
            }

        # Get track information
        try:
            track_info = self.get_track_info(file_path)
        except Exception as e:
            return {
                'needs_processing': False,
                'action': 'error',
                'reason': f'Failed to read track info: {e}'
            }

        tracks = track_info.get('tracks', [])
        subtitle_tracks = [t for t in tracks if t.get('type') == 'subtitles']

        # No subtitles at all
        if not subtitle_tracks:
            return {
                'needs_processing': False,
                'action': 'skipped',
                'reason': 'No subtitle tracks'
            }

        # Determine which tracks to keep
        # Keep: non-forced tracks in allowed languages
        tracks_to_keep = []
        tracks_to_remove = []

        for track in subtitle_tracks:
            props = track.get('properties', {})
            track_id = track.get('id')
            language = props.get('language', 'und').lower()
            is_forced = props.get('forced_track', False)
            track_name = props.get('track_name', '')

            # Keep if: language is allowed AND not forced
            if language in self.allowed_languages and not is_forced:
                tracks_to_keep.append({
                    'id': track_id,
                    'language': language,
                    'forced': is_forced,
                    'name': track_name
                })
            else:
                tracks_to_remove.append({
                    'id': track_id,
                    'language': language,
                    'forced': is_forced,
                    'name': track_name,
                    'reason': 'forced track' if is_forced else f'language {language} not in allowed list'
                })

        # Nothing to remove
        if not tracks_to_remove:
            return {
                'needs_processing': False,
                'action': 'skipped',
                'reason': 'No subtitle tracks to remove'
            }

        # Nothing to keep - this might be unexpected
        if not tracks_to_keep:
            logger.warning(f"No subtitle tracks would remain after processing: {file_path}")
            return {
                'needs_processing': False,
                'action': 'skipped',
                'reason': 'No allowed subtitle tracks to keep'
            }

        return {
            'needs_processing': True,
            'tracks_to_keep': tracks_to_keep,
            'tracks_to_remove': tracks_to_remove
        }

    def process_file(self, file_path: str) -> dict:
        """
        Process a single MKV file, removing unwanted subtitle tracks.

        Returns a dict with:
            - action: 'processed', 'skipped', or 'error'
            - reason: why the action was taken
            - removed_tracks: count of removed tracks (if processed)
        """
        analysis = self.analyze_file(file_path)

        if not analysis.get('needs_processing'):
            return {
                'action': analysis.get('action', 'skipped'),
                'reason': analysis.get('reason', 'unknown')
            }

        tracks_to_keep = analysis['tracks_to_keep']
        tracks_to_remove = analysis['tracks_to_remove']

        # Build mkvmerge command
        keep_ids = ','.join(str(t['id']) for t in tracks_to_keep)
        
        # Create temp file path (same directory, .mkv.tmp extension to avoid detection as video)
        dir_path = os.path.dirname(file_path)
        base_name = os.path.basename(file_path)
        temp_path = os.path.join(dir_path, f"{base_name}.tmp")
        
        logger.info(f"Keeping subtitle tracks: {keep_ids}")
        logger.info(f"Removing {len(tracks_to_remove)} tracks: {[t['id'] for t in tracks_to_remove]}")
        logger.debug(f"Temp file: {temp_path}")
        
        try:
            # Run mkvmerge
            result = subprocess.run(
                [
                    'mkvmerge',
                    '--output', temp_path,
                    '--subtitle-tracks', keep_ids,
                    file_path
                ],
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout for large files
            )
            
            # mkvmerge returns 0 for success, 1 for warnings, 2 for errors
            if result.returncode == 2:
                raise RuntimeError(f"mkvmerge failed: {result.stderr}")
            
            if result.returncode == 1:
                logger.warning(f"mkvmerge warnings: {result.stderr}")
            
            # Verify temp file was created
            if not os.path.exists(temp_path):
                raise RuntimeError("mkvmerge did not create output file")
            
            # Replace original with temp file
            # Use shutil.move for cross-filesystem support (though should be same fs)
            original_size = os.path.getsize(file_path)
            new_size = os.path.getsize(temp_path)
            
            # Sanity check - new file shouldn't be drastically smaller
            # (subtitles are tiny compared to video/audio)
            if new_size < original_size * 0.5:
                raise RuntimeError(
                    f"Output file suspiciously small ({new_size} vs {original_size} bytes)"
                )
            
            os.replace(temp_path, file_path)
            
            return {
                'action': 'processed',
                'kept_tracks': tracks_to_keep,
                'removed_tracks': len(tracks_to_remove),
                'removed_details': tracks_to_remove,
                'original_size': original_size,
                'new_size': new_size
            }
            
        except Exception as e:
            # Clean up temp file if it exists
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            raise
