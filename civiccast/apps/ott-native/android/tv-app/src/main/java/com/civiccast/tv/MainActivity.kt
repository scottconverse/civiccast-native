package com.civiccast.tv

import android.os.Bundle
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
        if (savedInstanceState == null) {
            supportFragmentManager.beginTransaction()
                .replace(android.R.id.content, MainBrowseFragment())
                .commit()
        }
    }
}
