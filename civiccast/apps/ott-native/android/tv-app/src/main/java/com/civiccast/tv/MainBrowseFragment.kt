package com.civiccast.tv

import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.TextView
import android.widget.EditText
import androidx.appcompat.app.AlertDialog
import androidx.leanback.app.BrowseSupportFragment
import androidx.leanback.widget.ArrayObjectAdapter
import androidx.leanback.widget.HeaderItem
import androidx.leanback.widget.ListRow
import androidx.leanback.widget.ListRowPresenter
import androidx.leanback.widget.OnItemViewClickedListener
import androidx.leanback.widget.Presenter
import androidx.leanback.widget.PresenterSelector
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch

/**
 * Top-level Leanback browse experience.
 *
 * Layout: a single row labeled "Channels" with one card per channel from /api/public/app/config.
 * Selecting a card launches PlayerActivity for that channel.
 */
class MainBrowseFragment : BrowseSupportFragment() {

    private val client = NetworkClient()
    private val rowsAdapter = ArrayObjectAdapter(ListRowPresenter())
    private var channels: List<Channel> = emptyList()
    private var replays: List<PublishedAsset> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = getString(R.string.app_name)
        headersState = HEADERS_DISABLED
        isHeadersTransitionOnBackEnabled = false
        adapter = rowsAdapter

        onItemViewClickedListener = OnItemViewClickedListener { _, item, _, _ ->
            if (item is Channel) {
                startActivity(PlayerActivity.intent(requireContext(), item))
            } else if (item is PublishedAsset) {
                startActivity(PlayerActivity.intent(requireContext(), item))
            }
        }
        setOnSearchClickedListener {
            val input = EditText(requireContext()).apply { hint = "Search channels and replays" }
            AlertDialog.Builder(requireContext())
                .setTitle("Search CivicCast")
                .setView(input)
                .setPositiveButton("Search") { _, _ -> renderCatalog(input.text.toString()) }
                .setNegativeButton("Cancel", null)
                .show()
        }

        load()
    }

    private fun load() {
        lifecycleScope.launch {
            try {
                val config = client.fetchAppConfig()
                title = config.stationName
                channels = config.channels
                replays = runCatching { client.fetchPublishedAssets() }.getOrDefault(emptyList())
                renderCatalog("")
            } catch (t: Throwable) {
                renderError(t.message ?: t.javaClass.simpleName)
            }
        }
    }

    private fun renderCatalog(query: String) {
        rowsAdapter.clear()
        if (channels.isEmpty() && replays.isEmpty()) {
            renderNotice(getString(R.string.empty_channels))
            return
        }
        val cardPresenter = ChannelCardPresenter()
        val rowAdapter = ArrayObjectAdapter(cardPresenter)
        channels.filter { it.branding.displayName.contains(query, ignoreCase = true) }
            .forEach { rowAdapter.add(it) }
        if (rowAdapter.size() > 0) {
            rowsAdapter.add(ListRow(HeaderItem(0L, getString(R.string.row_channels)), rowAdapter))
        }
        val replayAdapter = ArrayObjectAdapter(cardPresenter)
        replays.filter { it.title.contains(query, ignoreCase = true) ||
            (it.description?.contains(query, ignoreCase = true) == true) }
            .forEach { replayAdapter.add(it) }
        if (replayAdapter.size() > 0) {
            rowsAdapter.add(ListRow(HeaderItem(1L, "Published station replays"), replayAdapter))
        }
        if (rowsAdapter.size() == 0) renderNotice("No matching channels or replays")
    }

    private fun renderError(message: String) {
        rowsAdapter.clear()
        rowsAdapter.add(ListRow(HeaderItem(0L, getString(R.string.row_error)), noticeAdapter(getString(R.string.error_loading, message), true)))
    }

    private fun renderNotice(message: String) {
        rowsAdapter.clear()
        rowsAdapter.add(ListRow(HeaderItem(0L, getString(R.string.row_channels)), noticeAdapter(message, false)))
    }

    private fun noticeAdapter(message: String, isError: Boolean): ArrayObjectAdapter {
        val errorAdapter = ArrayObjectAdapter(object : Presenter() {
            override fun onCreateViewHolder(parent: android.view.ViewGroup): ViewHolder {
                val tv = TextView(parent.context).apply {
                    text = message
                    setTextColor(resources.getColor(if (isError) android.R.color.holo_red_light else android.R.color.white, null))
                    textSize = 18f
                    setPadding(48, 48, 48, 48)
                    gravity = Gravity.CENTER
                    layoutParams = FrameLayout.LayoutParams(900, 240)
                }
                return ViewHolder(tv)
            }
            override fun onBindViewHolder(viewHolder: ViewHolder, item: Any?) = Unit
            override fun onUnbindViewHolder(viewHolder: ViewHolder) = Unit
        })
        errorAdapter.add(Unit)
        return errorAdapter
    }
}
