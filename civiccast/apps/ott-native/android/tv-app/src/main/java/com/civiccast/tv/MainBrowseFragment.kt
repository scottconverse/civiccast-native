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
 * Live channels and published replays from the public station catalog.
 */
class MainBrowseFragment : BrowseSupportFragment() {

    private var client = NetworkClient()
    private val rowsAdapter = ArrayObjectAdapter(ListRowPresenter())
    private var channels: List<Channel> = emptyList()
    private var replays: List<PublishedAsset> = emptyList()
    private var pendingLink: android.net.Uri? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = getString(R.string.app_name)
        headersState = HEADERS_DISABLED
        isHeadersTransitionOnBackEnabled = false
        adapter = rowsAdapter
        pendingLink = requireActivity().intent?.data

        onItemViewClickedListener = OnItemViewClickedListener { _, item, _, _ ->
            if (item is Channel) {
                startActivity(PlayerActivity.intent(requireContext(), item))
            } else if (item is PublishedAsset) {
                startActivity(PlayerActivity.intent(requireContext(), item))
            }
        }
        setOnSearchClickedListener {
            AlertDialog.Builder(requireContext())
                .setTitle("CivicCast")
                .setItems(arrayOf("Search channels and replays", "Station address")) { _, which ->
                    if (which == 0) showSearch() else showStationAddress()
                }
                .show()
        }

        load()
    }

    private fun showSearch() {
        val input = EditText(requireContext()).apply { hint = "Search channels and replays" }
        AlertDialog.Builder(requireContext())
            .setTitle("Search CivicCast")
            .setView(input)
            .setPositiveButton("Search") { _, _ -> renderCatalog(input.text.toString()) }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showStationAddress() {
        val input = EditText(requireContext()).apply {
            hint = "https://station.example.org"
            setText(StationAddress.baseUrl)
        }
        AlertDialog.Builder(requireContext())
            .setTitle("Station HTTPS address")
            .setView(input)
            .setPositiveButton("Save") { _, _ ->
                if (StationAddress.save(requireContext(), input.text.toString())) {
                    client = NetworkClient()
                    load()
                } else {
                    renderNotice("Enter a full HTTPS station address without a path.")
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun load() {
        lifecycleScope.launch {
            try {
                val config = client.fetchAppConfig()
                title = config.stationName
                channels = config.channels
                replays = runCatching { client.fetchPublishedAssets() }.getOrDefault(emptyList())
                renderCatalog("")
                openPendingLink()
            } catch (t: Throwable) {
                renderError(t.message ?: t.javaClass.simpleName)
            }
        }
    }

    fun receiveLink(link: android.net.Uri?) {
        pendingLink = link
        openPendingLink()
    }

    private fun openPendingLink() {
        val link = pendingLink ?: return
        if (link.scheme != "civiccast" || link.pathSegments.size != 1) return
        val id = link.pathSegments[0]
        val playback = when (link.host) {
            "channel" -> channels.firstOrNull { it.id == id }?.let { PlayerActivity.intent(requireContext(), it) }
            "replay" -> replays.firstOrNull { it.id == id }?.let { PlayerActivity.intent(requireContext(), it) }
            else -> null
        } ?: return
        pendingLink = null
        startActivity(playback)
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
