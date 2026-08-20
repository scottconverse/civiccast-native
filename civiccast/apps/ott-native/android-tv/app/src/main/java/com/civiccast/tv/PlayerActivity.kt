package com.civiccast.tv

import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.fragment.app.FragmentActivity
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView

/**
 * Plain ExoPlayer activity for TV. We use Media3's PlayerView directly (not the leanback PlaybackFragment)
 * because (a) the starter doesn't need the row of related content yet and (b) PlayerView's D-pad handling
 * is sufficient for a single live stream.
 *
 * Upgrade path: when you add VOD or related content, swap to PlaybackSupportFragment + LeanbackPlayerAdapter.
 */
class PlayerActivity : FragmentActivity() {

    private var player: ExoPlayer? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val hlsUrl = intent.getStringExtra(EXTRA_HLS_URL)
            ?: run { finish(); return }

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
        private const val EXTRA_HLS_URL = "hls_url"
        private const val EXTRA_TITLE = "title"

        fun intent(context: Context, channel: Channel): Intent =
            Intent(context, PlayerActivity::class.java).apply {
                putExtra(EXTRA_HLS_URL, channel.hlsUrl)
                putExtra(EXTRA_TITLE, channel.name)
            }
    }
}
