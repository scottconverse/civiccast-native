package com.civiccast.mobile

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
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

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val viewModel: MainViewModel by viewModels()
    private lateinit var adapter: ChannelAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        adapter = ChannelAdapter { channel ->
            startActivity(PlayerActivity.intent(this, channel))
        }
        binding.channelList.layoutManager = LinearLayoutManager(this)
        binding.channelList.adapter = adapter

        binding.retryButton.setOnClickListener { viewModel.load() }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { render(it) }
            }
        }

        viewModel.load()
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
                adapter.submit(state.config.channels)
            }
        }
    }
}

sealed interface UiState {
    object Loading : UiState
    data class Error(val message: String) : UiState
    data class Loaded(val config: ConfigResponse) : UiState
}

class MainViewModel : ViewModel() {
    private val client = NetworkClient()
    private val _state = MutableStateFlow<UiState>(UiState.Loading)
    val state: StateFlow<UiState> = _state.asStateFlow()

    fun load() {
        _state.value = UiState.Loading
        viewModelScope.launch {
            try {
                val config = client.fetchAppConfig()
                _state.value = UiState.Loaded(config)
            } catch (t: Throwable) {
                _state.value = UiState.Error(t.message ?: t.javaClass.simpleName)
            }
        }
    }
}

class ChannelAdapter(
    private val onClick: (Channel) -> Unit
) : RecyclerView.Adapter<ChannelAdapter.VH>() {

    private val items = mutableListOf<Channel>()

    fun submit(channels: List<Channel>) {
        items.clear()
        items.addAll(channels)
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val b = ItemChannelBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return VH(b)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val ch = items[position]
        holder.binding.channelName.text = ch.branding.displayName
        holder.binding.channelDescription.text = ch.branding.shortName ?: ch.id
        holder.itemView.setOnClickListener { onClick(ch) }
    }

    override fun getItemCount(): Int = items.size

    class VH(val binding: ItemChannelBinding) : RecyclerView.ViewHolder(binding.root)
}
