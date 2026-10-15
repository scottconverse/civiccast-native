package com.civiccast.tv

import android.view.ViewGroup
import androidx.leanback.widget.ImageCardView
import androidx.leanback.widget.Presenter
import coil.load

/**
 * Renders a Channel as a Leanback ImageCardView.
 *
 * Image loading is intentionally omitted — Coil/Glide isn't on the classpath for this starter.
 * The card uses a solid color background when posterUrl is absent.
 */
class ChannelCardPresenter : Presenter() {
    private val client = NetworkClient()

    override fun onCreateViewHolder(parent: ViewGroup): ViewHolder {
        val card = ImageCardView(parent.context).apply {
            isFocusable = true
            isFocusableInTouchMode = true
            setMainImageDimensions(CARD_WIDTH, CARD_HEIGHT)
            // Solid placeholder until image loading is wired.
            setMainImage(android.graphics.drawable.ColorDrawable(0xFF1565C0.toInt()))
        }
        return ViewHolder(card)
    }

    override fun onBindViewHolder(viewHolder: ViewHolder, item: Any) {
        val card = viewHolder.view as ImageCardView
        when (item) {
            is Channel -> {
                card.titleText = item.branding.displayName
                card.contentText = item.branding.shortName ?: item.id
                card.mainImageView.load(item.branding.logoUrl?.let(client::mediaUrl))
            }
            is PublishedAsset -> {
                card.titleText = item.title
                card.contentText = item.description ?: "Replay"
                card.mainImageView.load(item.posterUrl?.let(client::mediaUrl))
            }
        }
    }

    override fun onUnbindViewHolder(viewHolder: ViewHolder) {
        val card = viewHolder.view as ImageCardView
        card.mainImage = null
        card.badgeImage = null
    }

    companion object {
        private const val CARD_WIDTH = 480
        private const val CARD_HEIGHT = 270
    }
}
