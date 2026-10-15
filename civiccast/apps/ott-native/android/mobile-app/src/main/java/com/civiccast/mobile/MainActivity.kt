package com.civiccast.mobile

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.EditText
import androidx.appcompat.app.AlertDialog
import android.text.Editable
import android.text.TextWatcher
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewModelScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.civiccast.mobile.databinding.ActivityMainBinding
import com.civiccast.mobile.databinding.ItemChannelBinding
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import coil.load

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val viewModel: MainViewModel by viewModels()
    private lateinit var adapter: ChannelAdapter
    private var pendingLink: android.net.Uri? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        StationAddress.load(this)
        pendingLink = intent?.data
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        adapter = ChannelAdapter { entry ->
            when (entry) {
                is Channel -> startActivity(PlayerActivity.intent(this, entry))
                is PublishedAsset -> startActivity(PlayerActivity.intent(this, entry))
            }
        }
        binding.channelList.layoutManager = LinearLayoutManager(this)
        binding.channelList.adapter = adapter

        binding.retryButton.setOnClickListener { viewModel.load() }
        binding.stationButton.setOnClickListener { showStationAddress() }
        binding.searchInput.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                adapter.setQuery(s?.toString().orEmpty())
            }
            override fun afterTextChanged(s: Editable?) = Unit
        })

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { render(it) }
            }
        }

        viewModel.load()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        pendingLink = intent.data
        (viewModel.state.value as? UiState.Loaded)?.let(::openPendingLink)
    }

    private fun openPendingLink(state: UiState.Loaded) {
        val link = pendingLink ?: return
        if (link.scheme != "civiccast" || link.pathSegments.size != 1) return
        val id = link.pathSegments[0]
        val playback = when (link.host) {
            "channel" -> state.config.channels.firstOrNull { it.id == id }?.let { PlayerActivity.intent(this, it) }
            "replay" -> state.replays.firstOrNull { it.id == id }?.let { PlayerActivity.intent(this, it) }
            else -> null
        } ?: return
        pendingLink = null
        startActivity(playback)
    }

    private fun showStationAddress() {
        val input = EditText(this).apply {
            hint = "https://station.example.org"
            setText(StationAddress.baseUrl)
        }
        AlertDialog.Builder(this)
            .setTitle("Station HTTPS address")
            .setView(input)
            .setPositiveButton("Save") { _, _ ->
                if (StationAddress.save(this, input.text.toString())) {
                    viewModel.load()
                } else {
                    AlertDialog.Builder(this).setMessage("Enter a full HTTPS station address without a path.")
                        .setPositiveButton("OK", null).show()
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun render(state: UiState) {
        binding.loading.visibility = if (state is UiState.Loading) View.VISIBLE else View.GONE
        binding.errorGroup.visibility = if (state is UiState.Error) View.VISIBLE else View.GONE
        binding.contentGroup.visibility = if (state is UiState.Loaded) View.VISIBLE else View.GONE

        when (state) {
            UiState.Loading -> Unit
            is UiState.Error -> {
                binding.errorText.text = getString(R.string.error_loading, state.message)
            }
            is UiState.Loaded -> {
                binding.stationName.text = state.config.stationName
                adapter.submit(state.config.channels, state.replays)
                openPendingLink(state)
            }
        }
    }
}

sealed interface UiState {
    object Loading : UiState
    data class Error(val message: String) : UiState
    data class Loaded(val config: ConfigResponse, val replays: List<PublishedAsset>) : UiState
}

class MainViewModel : ViewModel() {
    private val _state = MutableStateFlow<UiState>(UiState.Loading)
    val state: StateFlow<UiState> = _state.asStateFlow()

    fun load() {
        _state.value = UiState.Loading
        viewModelScope.launch {
            try {
                val client = NetworkClient()
                val config = client.fetchAppConfig()
                val replays = runCatching { client.fetchPublishedAssets() }.getOrDefault(emptyList())
                _state.value = UiState.Loaded(config, replays)
            } catch (t: Throwable) {
                _state.value = UiState.Error(t.message ?: t.javaClass.simpleName)
            }
        }
    }
}

class ChannelAdapter(
    private val onClick: (Any) -> Unit
) : RecyclerView.Adapter<ChannelAdapter.VH>() {

    private val items = mutableListOf<Any>()
    private var channels: List<Channel> = emptyList()
    private var replays: List<PublishedAsset> = emptyList()
    private var query = ""

    fun submit(channels: List<Channel>, replays: List<PublishedAsset>) {
        this.channels = channels
        this.replays = replays
        refresh()
    }

    fun setQuery(query: String) {
        this.query = query
        refresh()
    }

    private fun refresh() {
        items.clear()
        items.addAll(channels.filter { it.branding.displayName.contains(query, ignoreCase = true) })
        items.addAll(replays.filter { it.title.contains(query, ignoreCase = true) ||
            (it.description?.contains(query, ignoreCase = true) == true) })
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val b = ItemChannelBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return VH(b)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val entry = items[position]
        val client = NetworkClient()
        when (entry) {
            is Channel -> {
                holder.binding.channelName.text = entry.branding.displayName
                holder.binding.channelDescription.text = entry.branding.shortName ?: entry.id
                holder.binding.artwork.load(entry.branding.logoUrl?.let(client::mediaUrl))
            }
            is PublishedAsset -> {
                holder.binding.channelName.text = entry.title
                holder.binding.channelDescription.text = entry.description ?: "Published replay"
                holder.binding.artwork.load(entry.posterUrl?.let(client::mediaUrl))
            }
        }
        holder.itemView.setOnClickListener { onClick(entry) }
    }

    override fun getItemCount(): Int = items.size

    class VH(val binding: ItemChannelBinding) : RecyclerView.ViewHolder(binding.root)
}
