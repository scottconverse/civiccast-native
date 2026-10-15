package com.civiccast.tv

import android.view.ViewGroup
import androidx.leanback.widget.ImageCardView
import androidx.leanback.widget.Presenter
import coil.load

/**
 * Renders a Channel as a Leanback ImageCardView.
 *
 * Channel logos and replay posters load from the selected station.
 */
class ChannelCardPresenter : Presenter() {

    override fun onCreateViewHolder(parent: ViewGroup): ViewHolder {
        val card = ImageCardView(parent.context).apply {
            isFocusable = true
            isFocusableInTouchMode = true
            setMainImageDimensions(CARD_WIDTH, CARD_HEIGHT)
            setMainImage(android.graphics.drawable.ColorDrawable(0xFF0D1B30.toInt()))
        }
        return ViewHolder(card)
    }

    override fun onBindViewHolder(viewHolder: ViewHolder, item: Any) {
        val card = viewHolder.view as ImageCardView
        val client = NetworkClient()
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
