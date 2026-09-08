// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
'use strict'

const assert = require('node:assert/strict')
const {
  assertAssetId,
  assertLoopbackUrl,
  parseAttributeList,
  parseMasterPlaylist,
  parseMediaPlaylist,
  parseWebVttCues,
  assertWebVtt,
} = require('./BrowserProof.Contracts.cjs')

function mustThrow(label, callback, pattern) {
  assert.throws(callback, pattern, label)
}

assert.equal(assertAssetId('asset-123'), 'asset-123')
mustThrow('asset path separator rejected', () => assertAssetId('../asset'), /path separator|traversal/u)
assert.equal(assertLoopbackUrl('http://127.0.0.1:8000/media/a').origin, 'http://127.0.0.1:8000')
mustThrow('localhost alias rejected', () => assertLoopbackUrl('http://localhost:8000/'), /exact origin/u)
mustThrow('credential URL rejected', () => assertLoopbackUrl('http://user@127.0.0.1:8000/'), /credentials/u)

const attributes = parseAttributeList('TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="en",NAME="English, US",URI="captions/en/playlist.m3u8"')
assert.equal(attributes.NAME, 'English, US')
assert.equal(attributes.LANGUAGE, 'en')

const masterText = [
  '#EXTM3U',
  '#EXT-X-VERSION:3',
  '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subtitles",LANGUAGE="en",NAME="English",DEFAULT=YES,AUTOSELECT=YES,URI="captions/en/playlist.m3u8"',
  '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subtitles",LANGUAGE="es",NAME="Spanish",DEFAULT=NO,AUTOSELECT=YES,URI="captions/es/playlist.m3u8"',
  '#EXT-X-STREAM-INF:BANDWIDTH=414000,SUBTITLES="subtitles"',
  '240p/playlist.m3u8',
  '',
].join('\n')
const master = parseMasterPlaylist(masterText, 'http://127.0.0.1:8000/media/vod/exact/playlist.m3u8')
assert.deepEqual(master.variants, ['http://127.0.0.1:8000/media/vod/exact/240p/playlist.m3u8'])
assert.equal(master.subtitles.en.url, 'http://127.0.0.1:8000/media/vod/exact/captions/en/playlist.m3u8')
assert.equal(master.subtitles.es.name, 'Spanish')

mustThrow(
  'master missing Spanish rejected',
  () => parseMasterPlaylist(masterText.replace(/^#EXT-X-MEDIA:.*LANGUAGE="es".*\n/mu, ''), 'http://127.0.0.1:8000/media/vod/exact/playlist.m3u8'),
  /both English and Spanish/u,
)
mustThrow(
  'off-origin subtitle rejected',
  () => parseMasterPlaylist(masterText.replace('captions/es/playlist.m3u8', 'https://example.test/es.m3u8'), 'http://127.0.0.1:8000/media/vod/exact/playlist.m3u8'),
  /exact origin/u,
)

const variant = parseMediaPlaylist(
  '#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4.000,\nseg000.ts\n#EXT-X-ENDLIST\n',
  'http://127.0.0.1:8000/media/vod/exact/240p/playlist.m3u8',
  'variant',
)
assert.equal(variant.references[0], 'http://127.0.0.1:8000/media/vod/exact/240p/seg000.ts')
const subtitle = parseMediaPlaylist(
  '#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4.000,\nseg000.vtt\n#EXT-X-ENDLIST\n',
  'http://127.0.0.1:8000/media/vod/exact/captions/en/playlist.m3u8',
  'subtitle',
)
assert.match(subtitle.references[0], /seg000\.vtt$/u)
mustThrow('empty variant rejected', () => parseMediaPlaylist('#EXTM3U\n#EXT-X-ENDLIST\n', master.master_url, 'variant'), /no segment/u)
assert.equal(assertWebVtt('WEBVTT\n\ncue-1\n00:00:00.000 --> 00:00:01.000\nHello\n'), true)
assert.deepEqual(parseWebVttCues('WEBVTT\n\ncue-1\n00:00:00.000 --> 00:00:01.000\nHello\n')[0], {
  id: 'cue-1', start_time: 0, end_time: 1, text: 'Hello',
})
mustThrow('untimed VTT rejected', () => assertWebVtt('WEBVTT\n\nNo cue\n'), /timed cue/u)

process.stdout.write('PASS: exact loopback/asset binding and real HLS master, variant, bilingual subtitle, and WebVTT contracts.\n')
