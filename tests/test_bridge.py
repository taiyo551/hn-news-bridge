import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
import bridge

NOW = datetime(2026,10,24,12,tzinfo=timezone.utc)


def fixture(path):
    c = sqlite3.connect(path)
    c.executescript('''
        CREATE TABLE articles(id,hn_id,title,url,type,category,score,comment_count,posted_at,fetched_at);
        CREATE TABLE article_content(article_id,snippet,hn_text);
        CREATE TABLE article_snapshots(id,article_id,score,comment_count,recorded_at);
        CREATE TABLE keywords(id,word);
        CREATE TABLE article_keywords(article_id,keyword_id);
    ''')
    rows = [
        (1,101,'LLM agent evaluation','https://example.com/a?utm_source=test','story','AI',50,10,'2026-10-23 12:00:00','2026-10-24 11:00:00'),
        (2,102,'LLM agent evaluation duplicate','https://example.com/a#part','story','AI',40,5,'2026-10-23 12:00:00','2026-10-24 11:00:00'),
        (3,103,'Old LLM story','https://example.com/old','story','AI',900,90,'2026-10-01 12:00:00','2026-10-24 11:00:00'),
        (4,104,'AI developer position','https://example.com/job','job','AI',900,90,'2026-10-23 12:00:00','2026-10-24 11:00:00'),
        (5,105,'Retrieval ranking evaluation','https://example.com/search','story','Other',80,20,'2026-10-23 12:00:00','2026-10-24 11:00:00'),
        (6,106,'Football results','https://example.com/sports','story','Other',900,90,'2026-10-23 12:00:00','2026-10-24 11:00:00'),
        (7,107,'LLM unsafe link','javascript:alert(1)','story','AI',800,80,'2026-10-23 12:00:00','2026-10-24 11:00:00'),
        (8,108,'Future LLM article','https://example.com/future','story','AI',800,80,'2026-10-25 12:00:00','2026-10-24 11:00:00'),
        (9,109,'storage idea','https://example.com/storage','story','Other',900,90,'2026-10-23 12:00:00','2026-10-24 11:00:00'),
    ]
    c.executemany('INSERT INTO articles VALUES(?,?,?,?,?,?,?,?,?,?)',rows)
    c.execute("INSERT INTO article_content VALUES(1,'<p>Known snippet</p>',NULL)")
    c.execute("INSERT INTO keywords VALUES(1,'benchmark')")
    c.execute('INSERT INTO article_keywords VALUES(1,1)')
    c.executemany('INSERT INTO article_snapshots VALUES(?,?,?,?,?)',[
        (1,1,20,3,'2026-10-23 14:00:00'),(2,1,50,10,'2026-10-24 11:00:00')])
    c.commit()
    c.close()


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root/'fixture.sqlite'
        fixture(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_selection_dates_relevance_dedup_and_observations(self):
        pack = bridge.build_candidates(self.db,now=NOW)
        self.assertEqual({a['hn_id'] for a in pack['articles']},{101,105})
        first = next(a for a in pack['articles'] if a['hn_id']==101)
        self.assertEqual(first['score_gain_24h_observed'],30)
        self.assertEqual(first['comment_gain_24h_observed'],7)
        self.assertEqual(first['snippet'],'Known snippet')
        self.assertEqual(first['keywords'],['benchmark'])
        other = next(a for a in pack['articles'] if a['hn_id']==105)
        self.assertIsNone(other['score_gain_24h_observed'])
        self.assertFalse(pack['source_is_stale'])

    def test_source_bytes_unchanged_and_connection_rejects_writes(self):
        before = hashlib.sha256(self.db.read_bytes()).digest()
        bridge.build_candidates(self.db,now=NOW)
        with bridge.read_only(self.db) as c:
            with self.assertRaises(sqlite3.OperationalError):
                c.execute('DELETE FROM articles')
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).digest())

    def test_old_source_is_not_silently_backfilled(self):
        pack = bridge.build_candidates(self.db,now=datetime(2026,11,24,12,tzinfo=timezone.utc))
        self.assertTrue(pack['source_is_stale'])
        self.assertEqual(pack['articles'],[])
        text = bridge.render_markdown(pack)
        self.assertIn('最新ニュースとして扱わない',text)
        self.assertIn('古い記事で自動的に件数を埋めていません',text)

    def test_exports_identity_metadata_and_handoff(self):
        (self.root/'prompts').mkdir()
        (self.root/'prompts/ai-engineer.txt').write_text('AIエンジニアの指示',encoding='utf-8')
        pack = bridge.build_candidates(self.db,now=NOW,source={'commit':'a'*40},offline=True)
        out = bridge.export_pack(self.root,pack)
        data = json.loads((out/'candidates.json').read_text(encoding='utf-8'))
        self.assertEqual(data['source']['commit'],'a'*40)
        self.assertEqual(data['source_data_as_of'],'2026-10-24T11:00:00Z')
        text = (out/'chatgpt-candidates.md').read_text(encoding='utf-8')
        self.assertIn('HN-101',text)
        self.assertIn('今回の公開側更新は未確認',text)
        self.assertIn('全文ではありません',text)
        self.assertIn('原文をWebで確認',(out/'start-chat.txt').read_text(encoding='utf-8'))
        self.assertEqual((out/'project-instructions.txt').read_text(encoding='utf-8'),'AIエンジニアの指示')

    def test_pinned_public_download_and_cached_version(self):
        calls = []
        def opener(request,timeout):
            calls.append(request.full_url)
            if 'api.github.com' in request.full_url:
                return io.BytesIO(json.dumps([{'sha':'a'*40,'commit':{'committer':{'date':'2026-10-24T11:00:00Z'}}}]).encode())
            self.assertIn('/'+'a'*40+'/',request.full_url)
            return io.BytesIO(self.db.read_bytes())
        target,info = bridge.sync_snapshot(self.root,opener)
        self.assertEqual(target,self.root/'data/source.sqlite')
        self.assertEqual(info['sha256'],hashlib.sha256(self.db.read_bytes()).hexdigest())
        bridge.sync_snapshot(self.root,opener)
        self.assertEqual(len(calls),3)

    def test_bad_download_keeps_last_good_snapshot_and_manifest(self):
        data = self.root/'data'
        data.mkdir()
        (data/'source.sqlite').write_bytes(self.db.read_bytes())
        original = json.dumps({'commit':'a'*40})
        (data/'source-version.json').write_text(original,encoding='utf-8')
        before = (data/'source.sqlite').read_bytes()
        def opener(request,timeout):
            if 'api.github.com' in request.full_url:
                return io.BytesIO(json.dumps([{'sha':'b'*40,'commit':{'committer':{'date':'2026-10-24T11:00:00Z'}}}]).encode())
            return io.BytesIO(b'<html>not a SQLite database</html>')
        with self.assertRaises(sqlite3.DatabaseError):
            bridge.sync_snapshot(self.root,opener)
        self.assertEqual((data/'source.sqlite').read_bytes(),before)
        self.assertEqual((data/'source-version.json').read_text(encoding='utf-8'),original)
        self.assertFalse(list(data.glob('*.download')))

    def test_canonical_query_and_tracking_parameters(self):
        self.assertEqual(bridge.canonical('https://EXAMPLE.com/a?utm_source=x&z=2&x=1#p'),
                         'https://example.com/a?x=1&z=2')


if __name__=='__main__':
    unittest.main()
