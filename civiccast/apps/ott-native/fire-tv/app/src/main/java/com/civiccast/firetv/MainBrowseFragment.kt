package com.civiccast.firetv

import android.os.Bundle
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.TextView
import androidx.leanback.app.BrowseSupportFragment
import androidx.leanback.widget.ArrayObjectAdapter
import androidx.leanback.widget.HeaderItem
import androidx.leanback.widget.ListRow
import androidx.leanback.widget.ListRowPresenter
import androidx.leanback.widget.OnItemViewClickedListener
import androidx.leanback.widget.Presenter
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch

/**
 * Fire TV browse experience — identical Leanback structure to android-tv.
 *
 * Fire OS is Android with Amazon services on top; Leanback works identically. The Fire-specific
 * bits (Amazon feature flag, dual launcher intent filters) all live in the manifest, not the code.
 */
class MainBrowseFragment : BrowseSupportFragment() {

    private val client = NetworkClient()
    private val rowsAdapter = ArrayObjectAdapter(ListRowPresenter())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = getString(R.string.app_name)
        headersState = HEADERS_DISABLED
        isHeadersTransitionOnBackEnabled = false
        adapter = rowsAdapter

        onItemViewClickedListener = OnItemViewClickedListener { _, item, _, _ ->
            if (item is Channel) {
                startActivity(PlayerActivity.intent(requireContext(), item))
            }
        }

        load()
    }

    private fun load() {
        lifecycleScope.launch {
            try {
                val config = client.fetchAppConfig()
                title = config.station.name
                renderChannels(config.channels)
            } catch (t: Throwable) {
                renderError(t.message ?: t.javaClass.simpleName)
            }
        }
    }

    private fun renderChannels(channels: List<Channel>) {
        rowsAdapter.clear()
        if (channels.isEmpty()) {
            renderNotice(getString(R.string.empty_channels))
            return
        }
        val rowAdapter = ArrayObjectAdapter(ChannelCardPresenter())
        channels.forEach { rowAdapter.add(it) }
        rowsAdapter.add(ListRow(HeaderItem(0L, getString(R.string.row_channels)), rowAdapter))
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
