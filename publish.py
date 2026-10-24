"""Export only allowlisted public HN data. No persona files or conversations are read."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys
import bridge

PUBLIC_FILES = frozenset({'chatgpt-candidates.md', 'candidates.json'})
META_FIELDS = ('generated_at', 'source_data_as_of', 'offline', 'source_is_stale',
               'window_days', 'window_start', 'eligible_count_before_dedup', 'selection_method')
ARTICLE_FIELDS = ('id', 'hn_id', 'title', 'url', 'hn_url', 'category', 'posted_at', 'fetched_at',
                  'score', 'comment_count', 'score_gain_24h_observed',
                  'comment_gain_24h_observed', 'keywords', 'selection_hints', 'snippet')


def public_pack(pack):
    """Unknown fields, source metadata and private handoff files never enter the feed."""
    result = {key: pack[key] for key in META_FIELDS}
    result['source'] = {'repository': bridge.REPO, 'database_path': bridge.DB_PATH}
    commit = pack.get('source', {}).get('commit')
    if commit is not None:
        if not isinstance(commit, str) or not re.fullmatch('[a-fA-F0-9]{40}', commit):
            raise ValueError('Invalid source commit')
        result['source']['commit'] = commit
    result['articles'] = [{key: article[key] for key in ARTICLE_FIELDS}
                          for article in pack['articles']]
    result['candidate_count'] = len(result['articles'])
    return result


def check_public_directory(out):
    out = Path(out)
    if out.is_symlink():
        raise ValueError('Public directory must not be a symbolic link')
    if out.exists():
        for entry in out.iterdir():
            if entry.name not in PUBLIC_FILES or not entry.is_file() or entry.is_symlink():
                raise ValueError('Unexpected file in public directory; export stopped')


def export_public_pack(root, pack):
    out = Path(root) / 'public'
    check_public_directory(out)
    filtered = public_pack(pack)
    # Render before writing, so malformed input leaves existing outputs untouched.
    markdown = bridge.render_markdown(filtered)
    json_text = json.dumps(filtered, ensure_ascii=False, indent=2) + '\n'
    bridge.write_text(out / 'chatgpt-candidates.md', markdown)
    bridge.write_text(out / 'candidates.json', json_text)
    check_public_directory(out)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description='Generate the two public HN candidate files')
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--limit', type=int, default=40)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--source-commit', help='Pin a verified upstream commit (for cached CI)')
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 365 or not 1 <= args.limit <= 200:
        parser.error('days must be 1..365; limit must be 1..200')
    if args.offline and args.source_commit:
        parser.error('--offline and --source-commit cannot be combined')
    try:
        if args.offline:
            path = bridge.ROOT / 'data/source.sqlite'
            source = json.loads((bridge.ROOT / 'data/source-version.json').read_text(encoding='utf-8'))
        else:
            path, source = bridge.sync_snapshot(version=args.source_commit)
        pack = bridge.build_candidates(path, days=args.days, limit=args.limit,
                                       source=source, offline=args.offline)
        out = export_public_pack(bridge.ROOT, pack)
        print(f"Exported {pack['candidate_count']} public candidates; source UTC: {pack['source_data_as_of']}")
        print(f'Output: {out}')
        return 0
    except (OSError, ValueError, KeyError, IndexError, TypeError, sqlite3.Error) as exc:
        print(f'Public export failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
