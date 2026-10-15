package com.civiccast.tv

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.app.AlertDialog
import android.widget.Button
import android.widget.FrameLayout
import android.widget.TextView
import android.view.Gravity
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.C
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.launch

/**
 * Media3 HLS playback with D-pad controls and an audio/caption track picker.
 *
 * Resolves playback by fetching the channel's LiveState (`GET <live_state_url>`) — the real backend
 * contract exposes `playback_url` only there, not on the channel object itself.
 *
 */
class PlayerActivity : FragmentActivity() {

    private var player: ExoPlayer? = null
    private val client by lazy { NetworkClient() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        StationAddress.load(this)
        val liveStateUrl = intent.getStringExtra(EXTRA_LIVE_STATE_URL)
        val replayUrl = intent.getStringExtra(EXTRA_REPLAY_URL)
        if (liveStateUrl == null && replayUrl == null) { finish(); return }

        val statusView = TextView(this).apply {
            gravity = Gravity.CENTER
            textSize = 18f
            setPadding(48, 48, 48, 48)
            text = getString(R.string.preparing_stream)
        }
        setContentView(statusView)

        lifecycleScope.launch {
            try {
                val live = liveStateUrl?.let { client.fetchLiveState(it) }
                val hlsUrl = replayUrl ?: live?.playbackUrl
                if (hlsUrl == null) {
                    statusView.text = live?.summary ?: "Replay unavailable"
                    return@launch
                }
                startPlayback(client.mediaUrl(hlsUrl))
            } catch (t: Throwable) {
                statusView.text = t.message ?: t.javaClass.simpleName
            }
        }
    }

    private fun startPlayback(hlsUrl: String) {
        val playerView = PlayerView(this).apply {
            useController = true
            keepScreenOn = true
        }
        val root = FrameLayout(this)
        root.addView(playerView, FrameLayout.LayoutParams(-1, -1))
        root.addView(Button(this).apply {
            text = "Audio / captions"
            contentDescription = "Choose audio or caption track"
            setOnClickListener {
                AlertDialog.Builder(this@PlayerActivity).setTitle("Playback tracks")
                    .setItems(arrayOf("Audio", "Captions")) { _, choice ->
                        showTracks(if (choice == 0) C.TRACK_TYPE_AUDIO else C.TRACK_TYPE_TEXT)
                    }.show()
            }
        }, FrameLayout.LayoutParams(-2, -2, Gravity.TOP or Gravity.END))
        setContentView(root)

        val exo = ExoPlayer.Builder(this).build()
        playerView.player = exo
        val item = MediaItem.Builder()
            .setUri(hlsUrl)
            .setMimeType(MimeTypes.APPLICATION_M3U8)
            .build()
        exo.setMediaItem(item)
        exo.prepare()
        exo.playWhenReady = true
        player = exo
    }

    private data class TrackChoice(val group: Tracks.Group, val index: Int)

    private fun showTracks(type: Int) {
        val exo = player ?: return
        val choices = mutableListOf<TrackChoice>()
        val labels = mutableListOf(if (type == C.TRACK_TYPE_TEXT) "Captions off" else "Automatic audio")
        for (group in exo.currentTracks.groups.filter { it.type == type }) {
            for (index in 0 until group.length) {
                if (!group.isTrackSupported(index)) continue
                val format = group.getTrackFormat(index)
                choices.add(TrackChoice(group, index))
                labels.add(format.label ?: format.language ?: "Track ${choices.size}")
            }
        }
        AlertDialog.Builder(this)
            .setTitle(if (type == C.TRACK_TYPE_TEXT) "Captions" else "Audio")
            .setItems(labels.toTypedArray()) { _, selected ->
                val builder = exo.trackSelectionParameters.buildUpon()
                    .clearOverridesOfType(type)
                    .setTrackTypeDisabled(type, selected == 0 && type == C.TRACK_TYPE_TEXT)
                if (selected > 0) {
                    val choice = choices[selected - 1]
                    builder.setOverrideForType(TrackSelectionOverride(choice.group.mediaTrackGroup, choice.index))
                }
                exo.trackSelectionParameters = builder.build()
            }.show()
    }

    override fun onStop() {
        super.onStop()
        player?.release()
        player = null
    }

    companion object {
        private const val EXTRA_LIVE_STATE_URL = "live_state_url"
        private const val EXTRA_REPLAY_URL = "replay_url"
        private const val EXTRA_TITLE = "title"

        fun intent(context: Context, channel: Channel): Intent =
            Intent(context, PlayerActivity::class.java).apply {
                putExtra(EXTRA_LIVE_STATE_URL, channel.liveStateUrl)
                putExtra(EXTRA_TITLE, channel.branding.displayName)
            }

        fun intent(context: Context, replay: PublishedAsset): Intent =
            Intent(context, PlayerActivity::class.java).apply {
                putExtra(EXTRA_REPLAY_URL, replay.manifestUrl)
                putExtra(EXTRA_TITLE, replay.title)
            }
    }
}
