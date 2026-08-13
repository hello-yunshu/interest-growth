from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _collect_assets(value: Any, *, key: str = '') -> list[dict[str, str]]:
    assets: list[dict[str, str]] = []
    if isinstance(value, dict):
        for k, child in value.items():
            lk = str(k).lower()
            if isinstance(child, str) and lk in {
                'url', 'preview_url', 'download_url', 'artifact_url', 'path', 'file', 'filename', 'html'
            }:
                text = child.strip()
                if not text: continue
                if lk == 'html':
                    assets.append({'kind': 'inline_html', 'value': text[:50000]})
                elif lk.endswith('url') or lk == 'url':
                    parsed = urlparse(text)
                    if parsed.scheme in {'http', 'https'} or text.startswith('/'):
                        assets.append({'kind': 'url', 'value': text})
                else:
                    # Preserve a reference only. Never dereference arbitrary absolute host paths.
                    p = Path(text)
                    assets.append({'kind': 'file_reference' if not p.is_absolute() else 'upstream_absolute_path_reference', 'value': text})
            assets.extend(_collect_assets(child, key=lk))
    elif isinstance(value, list):
        for child in value: assets.extend(_collect_assets(child, key=key))
    dedup: list[dict[str, str]] = []
    seen = set()
    for asset in assets:
        sig = (asset['kind'], asset['value'])
        if sig not in seen:
            seen.add(sig); dedup.append(asset)
    return dedup


def build_visual_manifest(raw: dict[str, Any], *, concept_id: str, concept_name: str, knowledge_bases: list[str]) -> dict[str, Any]:
    assets = _collect_assets(raw)
    return {
        'schema': 'interest.visual.v1',
        'concept_id': concept_id,
        'concept_name': concept_name,
        'provider': 'native.interest-growth',
        'capability': 'visualize',
        'execution_session_id': str(raw.get('session_id') or ''),
        'execution_turn_id': str(raw.get('turn_id') or ''),
        'knowledge_bases': list(knowledge_bases),
        'assets': assets,
        'preview_kind': assets[0]['kind'] if assets else 'structured_result',
        'review_required': True,
        'security_note': 'Asset references are preserved for review; absolute paths are never dereferenced by the product.',
    }
