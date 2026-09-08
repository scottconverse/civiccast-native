// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
'use strict'

const crypto = require('node:crypto')

const LOOPBACK_ORIGIN = 'http://127.0.0.1:8000'

function invariant(condition, message) {
  if (!condition) throw new Error(message)
}

function assertAssetId(value) {
  invariant(typeof value === 'string', 'Asset ID must be a string.')
  invariant(value.length >= 1 && value.length <= 128, 'Asset ID length must be between 1 and 128.')
  invariant(!/[\u0000-\u001f\u007f/\\]/u.test(value), 'Asset ID contains a control character or path separator.')
  invariant(value !== '.' && value !== '..', 'Asset ID cannot be a traversal token.')
  return value
}

function assertLoopbackUrl(value, label = 'URL') {
  let parsed
  try {
    parsed = new URL(value)
  } catch {
    throw new Error(`${label} is not an absolute URL.`)
  }
  invariant(parsed.origin === LOOPBACK_ORIGIN, `${label} must use exact origin ${LOOPBACK_ORIGIN}.`)
  invariant(!parsed.username && !parsed.password, `${label} cannot contain credentials.`)
  return parsed
}

function resolveLoopbackUrl(reference, baseUrl, label) {
  let resolved
  try {
    resolved = new URL(reference, baseUrl)
  } catch {
    throw new Error(`${label} is not a valid URL reference.`)
  }
  return assertLoopbackUrl(resolved.href, label).href
}

function parseAttributeList(text) {
  const result = Object.create(null)
  let cursor = 0
  while (cursor < text.length) {
    const keyStart = cursor
    while (cursor < text.length && text[cursor] !== '=') cursor += 1
    invariant(cursor < text.length, 'Malformed HLS attribute without equals sign.')
    const key = text.slice(keyStart, cursor).trim()
    invariant(/^[A-Z0-9-]+$/u.test(key), `Malformed HLS attribute name '${key}'.`)
    cursor += 1
    let value = ''
    if (text[cursor] === '"') {
      cursor += 1
      while (cursor < text.length) {
        const character = text[cursor]
        if (character === '"') {
          cursor += 1
          break
        }
        invariant(character !== '\r' && character !== '\n', 'Malformed quoted HLS attribute.')
        value += character
        cursor += 1
      }
      invariant(text[cursor - 1] === '"', 'Unterminated quoted HLS attribute.')
    } else {
      const comma = text.indexOf(',', cursor)
      const end = comma < 0 ? text.length : comma
      value = text.slice(cursor, end).trim()
      cursor = end
    }
    invariant(!(key in result), `Duplicate HLS attribute '${key}'.`)
    result[key] = value
    if (cursor < text.length) {
      invariant(text[cursor] === ',', 'Malformed HLS attribute separator.')
      cursor += 1
    }
  }
  return result
}

function playlistLines(text, label) {
  invariant(typeof text === 'string', `${label} body is not text.`)
  const lines = text.replace(/^\uFEFF/u, '').split(/\r?\n/u).map((line) => line.trim())
  invariant(lines[0] === '#EXTM3U', `${label} does not begin with #EXTM3U.`)
  return lines
}

function parseMasterPlaylist(text, masterUrl) {
  const master = assertLoopbackUrl(masterUrl, 'Master playlist URL')
  const lines = playlistLines(text, 'Master playlist')
  const variants = []
  const subtitles = Object.create(null)
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    if (line.startsWith('#EXT-X-MEDIA:')) {
      const attributes = parseAttributeList(line.slice('#EXT-X-MEDIA:'.length))
      if (attributes.TYPE !== 'SUBTITLES') continue
      const language = String(attributes.LANGUAGE || '').toLowerCase()
      invariant(language === 'en' || language === 'es', `Unexpected subtitle language '${language || '(missing)'}'.`)
      invariant(attributes.URI, `Subtitle language '${language}' has no URI.`)
      invariant(!(language in subtitles), `Duplicate subtitle language '${language}'.`)
      subtitles[language] = {
        language,
        name: String(attributes.NAME || ''),
        url: resolveLoopbackUrl(attributes.URI, master.href, `Subtitle ${language} playlist URL`),
      }
    }
    if (line.startsWith('#EXT-X-STREAM-INF:')) {
      let uriIndex = index + 1
      while (uriIndex < lines.length && (!lines[uriIndex] || lines[uriIndex].startsWith('#'))) uriIndex += 1
      invariant(uriIndex < lines.length, 'Variant declaration has no following URI.')
      variants.push(resolveLoopbackUrl(lines[uriIndex], master.href, 'Variant playlist URL'))
      index = uriIndex
    }
  }
  invariant(variants.length > 0, 'Master playlist has no variants.')
  invariant(subtitles.en && subtitles.es, 'Master playlist must expose both English and Spanish subtitle tracks.')
  return { master_url: master.href, variants: [...new Set(variants)], subtitles }
}

function parseMediaPlaylist(text, playlistUrl, kind = 'media') {
  const playlist = assertLoopbackUrl(playlistUrl, `${kind} playlist URL`)
  const lines = playlistLines(text, `${kind} playlist`)
  const references = lines
    .filter((line) => line && !line.startsWith('#'))
    .map((line) => resolveLoopbackUrl(line, playlist.href, `${kind} segment URL`))
  invariant(references.length > 0, `${kind} playlist has no segment references.`)
  if (kind === 'subtitle') {
    invariant(references.some((url) => new URL(url).pathname.toLowerCase().endsWith('.vtt')), 'Subtitle playlist has no WebVTT segment.')
  } else {
    invariant(lines.some((line) => line.startsWith('#EXTINF:')), 'Variant playlist has no EXTINF media entries.')
  }
  return { playlist_url: playlist.href, references }
}

function parseWebVttCues(text, label = 'WebVTT') {
  invariant(typeof text === 'string', `${label} body is not text.`)
  const normalized = text.replace(/^\uFEFF/u, '').replace(/\r\n?/gu, '\n')
  invariant(normalized.startsWith('WEBVTT'), `${label} does not begin with WEBVTT.`)
  const timestamp = '(\\d{2}):(\\d{2}):(\\d{2})\\.(\\d{3})'
  const timingPattern = new RegExp(`^${timestamp}\\s+-->\\s+${timestamp}(?:\\s+.*)?$`, 'u')
  const parseTime = (match, offset) => (
    Number(match[offset]) * 3600 + Number(match[offset + 1]) * 60 +
    Number(match[offset + 2]) + Number(match[offset + 3]) / 1000
  )
  const cues = []
  for (const block of normalized.split(/\n{2,}/u).slice(1)) {
    const lines = block.split('\n')
    let timingIndex = 0
    let id = ''
    if (!lines[0].includes('-->')) {
      id = lines[0].trim()
      timingIndex = 1
    }
    const match = timingPattern.exec(lines[timingIndex] || '')
    if (!match) continue
    const cueText = lines.slice(timingIndex + 1).join('\n').trim()
    invariant(cueText.length > 0, `${label} has an empty timed cue.`)
    cues.push({ id, start_time: parseTime(match, 1), end_time: parseTime(match, 5), text: cueText })
  }
  return cues
}

function assertWebVtt(text, label = 'WebVTT') {
  invariant(parseWebVttCues(text, label).length > 0, `${label} contains no timed cue.`)
  return true
}

function sha256(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex')
}

module.exports = {
  LOOPBACK_ORIGIN,
  assertAssetId,
  assertLoopbackUrl,
  resolveLoopbackUrl,
  parseAttributeList,
  parseMasterPlaylist,
  parseMediaPlaylist,
  parseWebVttCues,
  assertWebVtt,
  sha256,
}
