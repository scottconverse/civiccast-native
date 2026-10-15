package com.civiccast.tv

import android.os.Bundle
import android.content.Intent
import androidx.fragment.app.FragmentActivity

/**
 * Hosts the Leanback BrowseFragment.
 *
 * No XML layout — the fragment fills the window. This mirrors Google's leanback samples and avoids
 * a single-purpose layout file.
 */
class MainActivity : FragmentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        StationAddress.load(this)
        if (savedInstanceState == null) {
            supportFragmentManager.beginTransaction()
                .replace(android.R.id.content, MainBrowseFragment())
                .commit()
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        (supportFragmentManager.findFragmentById(android.R.id.content) as? MainBrowseFragment)
            ?.receiveLink(intent.data)
    }
}
