"""Source-bound screenshots and stateless, sandboxed Studio button previews."""
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import re
import zipfile

from .storage import canonical, identifier
from .app_sdk import data_fingerprint, SDK_CONTRACT
from .visual_simulator import MAX_PNG_BYTES, render_frame


VISUAL_VERSION = 'fire-visual-preview-v1'
MAX_IMAGES = 8
MAX_REVIEW_IMAGES = 6
HEX = re.compile(r'^[a-f0-9]{64}$')


def preview_folder(store, build_id, source_hash):
    identifier(build_id)
    if not isinstance(source_hash, str) or not HEX.fullmatch(source_hash):
        raise ValueError('Invalid preview source identity')
    # Windows workspaces/test paths can exceed MAX_PATH with two 64-byte hashes.
    # Short file keys are never identities: full source/image hashes are verified.
    path = (store.path('builds', build_id, '') / 'previews' / source_hash[:16]).resolve()
    path.relative_to(store.root)
    return path


def save_screenshots(candidates, store, build_id, source_hash):
    """Render only selected, distinct complete frames, never all simulated frames."""
    fingerprint=data_fingerprint()
    grouped = {}
    for item in candidates[:64]:
        key = (item.get('profile'), item.get('scenario'))
        grouped.setdefault(key, []).append(item)
    ordered = []
    # A case's first frame cannot starve other navigation/fault/gameplay cases.
    for n in range(8):
        ordered.extend(items[n] for items in grouped.values() if len(items) > n)
    frames, seen_ops, seen_pixels = [], set(), set()
    folder = preview_folder(store, build_id, source_hash)
    folder.mkdir(parents=True, exist_ok=True)
    if (folder/'index.json').exists() and json.loads((folder/'index.json').read_text(encoding='utf-8')).get('source_sha256')!=source_hash:
        raise ValueError('Preview source-key collision')
    for item in ordered:
        ops_key = hashlib.sha256(canonical(item['ops'])).hexdigest()
        if ops_key in seen_ops:
            continue
        seen_ops.add(ops_key)
        image = render_frame(item)
        if image.pixel_sha256 in seen_pixels:
            continue
        seen_pixels.add(image.pixel_sha256)
        path = folder / (image.png_sha256[:24] + '.png')
        if not path.exists():
            store.reserve(len(image.png))
            path.write_bytes(image.png)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != image.png_sha256:
            raise ValueError('Stored visual evidence checksum mismatch')
        frames.append({k: item[k] for k in ('profile', 'scenario', 'at_ms', 'frame', 'button', 'input_count') if k in item} |
                      {'image_id': image.png_sha256, 'png_sha256': image.png_sha256,
                       'pixel_sha256': image.pixel_sha256, 'size_bytes': len(image.png),
                       'source_sha256': source_hash, 'sdk_data_sha256':fingerprint, 'metrics': image.metrics})
        if len(frames) == MAX_IMAGES:
            break
    result = {'version': VISUAL_VERSION, 'source_sha256': source_hash,
              'sdk_data_sha256':fingerprint,'sdk_contract':SDK_CONTRACT,
              'width': 320, 'height': 240, 'frames': frames, 'physical_verified': False,
              'note': 'Software simulation; hardware, native timing and exact native primitive rasterization are not proven.'}
    store.write(folder / 'index.json', result)
    return result


def image_inputs(evidence, store, build_id, source_hash, *, limit=MAX_REVIEW_IMAGES):
    """Validate identity and byte hashes before exposing any image to UI/AI."""
    if (not isinstance(evidence, dict) or evidence.get('version') != VISUAL_VERSION
            or evidence.get('source_sha256') != source_hash
            or evidence.get('sdk_data_sha256')!=data_fingerprint() or evidence.get('sdk_contract')!=SDK_CONTRACT):
        raise ValueError('Visual evidence belongs to another source')
    folder = preview_folder(store, build_id, source_hash)
    images = []
    for frame in evidence.get('frames', [])[:min(limit, MAX_IMAGES)]:
        digest = frame.get('png_sha256')
        if (not isinstance(digest, str) or not HEX.fullmatch(digest)
                or frame.get('sdk_data_sha256')!=evidence['sdk_data_sha256']
                or frame.get('image_id') != digest or frame.get('source_sha256') != source_hash
                or type(frame.get('size_bytes')) is not int or not 0 < frame['size_bytes'] <= MAX_PNG_BYTES):
            raise ValueError('Invalid bounded visual evidence metadata')
        path = (folder / (digest[:24] + '.png')).resolve()
        path.relative_to(folder)
        data = path.read_bytes()
        if (len(data) != frame['size_bytes'] or hashlib.sha256(data).hexdigest() != digest
                or data[:8] != b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Visual evidence image checksum mismatch')
        images.append({'source_sha256': source_hash, 'image_id': digest,
                       'sdk_data_sha256':evidence['sdk_data_sha256'],'sdk_contract':SDK_CONTRACT,
                       'profile': frame.get('profile'), 'scenario': frame.get('scenario'),
                       'at_ms': frame.get('at_ms'), 'metrics': frame.get('metrics', {}),
                       'image_url': 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')})
    return images


class PreviewService:
    def __init__(self, service):
        self.service = service
        self.lock = asyncio.Lock()

    async def package(self, package_id, buttons, elapsed_ms):
        from .builds import simulate, verify_archive
        identifier(package_id)
        store = self.service.store
        package = store.get('packages', package_id)
        if store.get('builds', package['build_id'])['status'] != 'ready':
            raise ValueError('Preview requires a completed build')
        # A previously physically failing package may still be inspected safely
        # in a PC preview; this never clears its delivery/installation block.
        archive_path = store.path('packages', package_id, '.zip')
        verify_archive(archive_path, package['manifest'], package['archive_sha256'])
        with zipfile.ZipFile(archive_path) as archive:
            source = archive.read('apps/' + package['manifest']['id'] + '/main.lua').decode('utf-8')
        if self.lock.locked():
            from .service import Conflict
            raise Conflict('En forhåndsvisning beregnes. Vent et øyeblikk.')
        async with self.lock:
            duration = min(12000, max(elapsed_ms, 16 + len(buttons) * 250 + 250))
            if package['manifest'].get('max_runtime_ms'):
                duration = min(duration, package['manifest']['max_runtime_ms'])
            capture = sorted({16, max(16, duration // 2), duration})
            result = await simulate({**package['manifest'], 'main_lua': source,
                                     'profile': 'idle', 'preview_duration_ms': duration,
                                     'button_sequence': buttons, 'interval_ms': 250,
                                     'capture_at_ms': capture}, store, package['build_id'])
            frames = [{'profile': 'interactive', **f} for f in result.pop('visual_frames', [])]
            evidence = await asyncio.to_thread(save_screenshots,frames,store,package['build_id'],package['manifest']['checksum'])
            images = image_inputs(evidence, store, package['build_id'], package['manifest']['checksum'], limit=MAX_IMAGES)
            return {'package_id': package_id, 'source_sha256': package['manifest']['checksum'],
                    'physical_verified': False, 'buttons': buttons, 'elapsed_ms': result['elapsed_ms'],
                    'images': images, 'note': 'PC-simulering. Dette installerer eller kjører ingen app på FIRE.'}
