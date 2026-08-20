package com.civiccast.mobile

import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.exoplayer.ExoPlayer
import com.civiccast.mobile.databinding.ActivityPlayerBinding

class PlayerActivity : AppCompatActivity() {

    private lateinit var binding: ActivityPlayerBinding
    private var player: ExoPlayer? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityPlayerBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val hlsUrl = intent.getStringExtra(EXTRA_HLS_URL)
            ?: run { finish(); return }
        val title = intent.getStringExtra(EXTRA_TITLE) ?: ""

        title(title)
        startPlayback(hlsUrl)
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
        private const val EXTRA_HLS_URL = "hls_url"
        private const val EXTRA_TITLE = "title"

        fun intent(context: Context, channel: Channel): Intent =
            Intent(context, PlayerActivity::class.java).apply {
                putExtra(EXTRA_HLS_URL, channel.hlsUrl)
                putExtra(EXTRA_TITLE, channel.name)
            }
    }
}
