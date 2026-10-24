import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import bridge
import publish
from test_bridge import fixture, NOW


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'fixture.sqlite'
        fixture(self.db)
        self.pack = bridge.build_candidates(self.db, now=NOW,
                                            source={'commit': 'a' * 40})

    def tearDown(self):
        self.temp.cleanup()

    def test_private_fields_and_files_cannot_enter_public_export(self):
        canary = 'PRIVATE-COMPANY-CONTEXT-MUST-NOT-LEAK'
        self.pack['company_context'] = canary
        self.pack['source']['local_path'] = canary
        self.pack['articles'][0]['private_notes'] = canary
        (self.root / 'prompts').mkdir()
        (self.root / 'prompts/ai-engineer.txt').write_text(canary, encoding='utf-8')
        (self.root / 'output').mkdir()
        (self.root / 'output/start-chat.txt').write_text(canary, encoding='utf-8')
        out = publish.export_public_pack(self.root, self.pack)
        for file in out.iterdir():
            self.assertNotIn(canary, file.read_text(encoding='utf-8'))
        data = json.loads((out / 'candidates.json').read_text(encoding='utf-8'))
        self.assertEqual(set(data['source']), {'repository', 'database_path', 'commit'})

    def test_no_persona_file_required_and_fixed_names_overwrite(self):
        out = publish.export_public_pack(self.root, self.pack)
        self.pack['articles'] = []
        publish.export_public_pack(self.root, self.pack)
        self.assertEqual({p.name for p in out.iterdir()}, publish.PUBLIC_FILES)
        self.assertEqual(json.loads((out / 'candidates.json').read_text(encoding='utf-8'))['candidate_count'], 0)
        self.assertNotIn('HN-101', (out / 'chatgpt-candidates.md').read_text(encoding='utf-8'))

    def test_unexpected_file_stops_export_without_deleting_it(self):
        out = self.root / 'public'
        out.mkdir()
        unexpected = out / 'private.txt'
        unexpected.write_text('private', encoding='utf-8')
        with self.assertRaises(ValueError):
            publish.export_public_pack(self.root, self.pack)
        self.assertEqual(unexpected.read_text(encoding='utf-8'), 'private')
        self.assertFalse((out / 'candidates.json').exists())

    def test_invalid_source_commit_stops_before_output(self):
        self.pack['source']['commit'] = 'bad\nmetadata'
        with self.assertRaises(ValueError):
            publish.export_public_pack(self.root, self.pack)
        self.assertFalse((self.root / 'public').exists())

    def test_pinned_snapshot_download_avoids_commit_api_and_reuses_cache(self):
        content = self.db.read_bytes()
        calls = []
        def opener(request, **kwargs):
            calls.append(request.full_url)
            self.assertIn('/' + 'b' * 40 + '/', request.full_url)
            return io.BytesIO(content)
        path, info = bridge.sync_snapshot(self.root, opener=opener, version='b' * 40)
        bridge.sync_snapshot(self.root, opener=opener, version='b' * 40)
        self.assertEqual(len(calls), 1)
        self.assertEqual(path.read_bytes(), content)
        self.assertEqual(info['commit'], 'b' * 40)


if __name__ == '__main__':
    unittest.main()
