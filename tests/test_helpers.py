import tempfile
import unittest
from pathlib import Path
from suno_downloader import sanitize_filename, build_headers, load_state, save_state, STATE_FILE

class HelperTests(unittest.TestCase):
    def test_filename_is_single_component(self):
        name = sanitize_filename('../bad/name:*?')
        self.assertNotIn('/', name)
        self.assertNotIn('..', name)
        self.assertLessEqual(len(sanitize_filename('x' * 200)), 100)
    def test_empty_filename_has_fallback(self):
        self.assertEqual(sanitize_filename('...'), 'untitled')
    def test_bearer_header(self):
        self.assertEqual(build_headers(' Bearer example ')['Authorization'], 'Bearer example')
    def test_state_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            save_state(path, {'downloaded_ids': ['song-1']})
            self.assertEqual(load_state(path)['downloaded_ids'], ['song-1'])
            (path / STATE_FILE).write_text('{broken')
            self.assertEqual(load_state(path)['downloaded_ids'], [])
