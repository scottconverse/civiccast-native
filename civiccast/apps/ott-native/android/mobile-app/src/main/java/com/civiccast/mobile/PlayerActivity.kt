package com.civiccast.mobile

import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
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
    private val client = NetworkClient()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityPlayerBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val liveStateUrl = intent.getStringExtra(EXTRA_LIVE_STATE_URL)
            ?: run { finish(); return }
        val title = intent.getStringExtra(EXTRA_TITLE) ?: ""
        title(title)

        lifecycleScope.launch {
            try {
                val live = client.fetchLiveState(liveStateUrl)
                val hlsUrl = live.playbackUrl
                if (hlsUrl == null) {
                    title("$title — ${live.summary}")
                    return@launch
                }
                startPlayback(hlsUrl)
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
