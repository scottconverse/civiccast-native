package com.civiccast.mobile

import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.C
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.exoplayer.ExoPlayer
import com.civiccast.mobile.databinding.ActivityPlayerBinding
import kotlinx.coroutines.launch

/**
 * Resolves playback by fetching the channel's LiveState (`GET <live_state_url>`) — the real
 * backend contract exposes `playback_url` only there, not on the channel object itself.
 */
class PlayerActivity : AppCompatActivity() {

    private lateinit var binding: ActivityPlayerBinding
    private var player: ExoPlayer? = null
    private val client by lazy { NetworkClient() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        StationAddress.load(this)
        binding = ActivityPlayerBinding.inflate(layoutInflater)
        setContentView(binding.root)
        binding.tracksButton.setOnClickListener {
            AlertDialog.Builder(this).setTitle("Playback tracks")
                .setItems(arrayOf("Audio", "Captions")) { _, choice ->
                    showTracks(if (choice == 0) C.TRACK_TYPE_AUDIO else C.TRACK_TYPE_TEXT)
                }.show()
        }

        val liveStateUrl = intent.getStringExtra(EXTRA_LIVE_STATE_URL)
        val replayUrl = intent.getStringExtra(EXTRA_REPLAY_URL)
        if (liveStateUrl == null && replayUrl == null) { finish(); return }
        val title = intent.getStringExtra(EXTRA_TITLE) ?: ""
        title(title)

        lifecycleScope.launch {
            try {
                val live = liveStateUrl?.let { client.fetchLiveState(it) }
                val hlsUrl = replayUrl ?: live?.playbackUrl
                if (hlsUrl == null) {
                    title("$title — ${live?.summary ?: "Replay unavailable"}")
                    return@launch
                }
                startPlayback(client.mediaUrl(hlsUrl))
            } catch (t: Throwable) {
                title("$title — ${t.message ?: t.javaClass.simpleName}")
            }
        }
    }

    private fun title(t: String) {
        supportActionBar?.title = t
    }

    private fun startPlayback(hlsUrl: String) {
        val exo = ExoPlayer.Builder(this).build()
        binding.playerView.player = exo
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
