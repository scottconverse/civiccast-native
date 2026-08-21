package com.civiccast.tv

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.widget.TextView
import android.view.Gravity
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.launch

/**
 * Plain ExoPlayer activity for TV. We use Media3's PlayerView directly (not the leanback PlaybackFragment)
 * because (a) the starter doesn't need the row of related content yet and (b) PlayerView's D-pad handling
 * is sufficient for a single live stream.
 *
 * Resolves playback by fetching the channel's LiveState (`GET <live_state_url>`) — the real backend
 * contract exposes `playback_url` only there, not on the channel object itself.
 *
 * Upgrade path: when you add VOD or related content, swap to PlaybackSupportFragment + LeanbackPlayerAdapter.
 */
class PlayerActivity : FragmentActivity() {

    private var player: ExoPlayer? = null
    private val client = NetworkClient()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val liveStateUrl = intent.getStringExtra(EXTRA_LIVE_STATE_URL)
            ?: run { finish(); return }

        val statusView = TextView(this).apply {
            gravity = Gravity.CENTER
            textSize = 18f
            setPadding(48, 48, 48, 48)
            text = getString(R.string.preparing_stream)
        }
        setContentView(statusView)

        lifecycleScope.launch {
            try {
                val live = client.fetchLiveState(liveStateUrl)
                val hlsUrl = live.playbackUrl
                if (hlsUrl == null) {
                    statusView.text = live.summary
                    return@launch
                }
                startPlayback(hlsUrl)
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
        setContentView(playerView)

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

    override fun onStop() {
        super.onStop()
        player?.release()
        player = null
    }

    companion object {
        private const val EXTRA_LIVE_STATE_URL = "live_state_url"
        private const val EXTRA_TITLE = "title"

        fun intent(context: Context, channel: Channel): Intent =
            Intent(context, PlayerActivity::class.java).apply {
                putExtra(EXTRA_LIVE_STATE_URL, channel.liveStateUrl)
                putExtra(EXTRA_TITLE, channel.branding.displayName)
            }
    }
}
