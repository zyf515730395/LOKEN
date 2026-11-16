"""Fail closed before uploading the public papers/models site."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
import argparse
import json

PRIVATE = {'writings','journeys','stocks'}
DIRECTORIES = {'assets','milestone-models','notes','reports'}
FILES = {'.nojekyll','index.html','search-index.json','togos-papers.json'}

class ScopeParser(HTMLParser):
    def handle_starttag(self,tag,attrs):
        for name,value in attrs:
            if name=='data-active-section' and value not in {'learning','milestones'}:
                raise ValueError('Non-public active section')
            if name in {'href','src'} and value:
                parts=unquote(urlsplit(value).path).replace('\\','/').split('/')
                if PRIVATE.intersection(parts): raise ValueError('Private route in public page')

def validate_public_site(root: Path) -> dict:
    root=Path(root)
    if root.is_symlink() or not root.is_dir(): raise ValueError('Expected a real public output directory')
    count=0
    for path in root.rglob('*'):
        rel=path.relative_to(root)
        if path.is_symlink(): raise ValueError(f'Symlink in public output: {rel}')
        if any(part.startswith('.') for part in rel.parts) and str(rel)!='.nojekyll':
            raise ValueError(f'Hidden output: {rel}')
        if PRIVATE.intersection(rel.parts): raise ValueError(f'Private output path: {rel}')
        if rel.parts[0] not in DIRECTORIES and str(rel) not in FILES:
            raise ValueError(f'Unowned public output: {rel}')
        if path.is_file():
            count+=1
            if path.suffix=='.html':
                ScopeParser().feed(path.read_text(encoding='utf-8'))
    if not (root/'index.html').is_file(): raise ValueError('Public homepage missing')
    index=json.loads((root/'search-index.json').read_text(encoding='utf-8'))
    if index.get('version')!=1 or not isinstance(index.get('documents'),list):
        raise ValueError('Invalid public search index')
    for item in index['documents']:
        if item.get('section') not in {'learning','milestones'} or item.get('kind') not in {'paper','model'}:
            raise ValueError('Foreign search document')
        url=urlsplit(item.get('url',''))
        parts=unquote(url.path).replace('\\','/').split('/')
        if url.scheme or url.netloc or not url.path or url.path.startswith('/') or '..' in parts or PRIVATE.intersection(parts):
            raise ValueError('Unsafe search route')
    return {'files':count,'search_documents':len(index['documents']),'sections':['learning','milestones']}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('docs'))
    print(json.dumps(validate_public_site(parser.parse_args().root),ensure_ascii=False))
