plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "com.civiccast.tv"
    compileSdk = 34

    defaultConfig {
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"

        // Override at build time:  ./gradlew :tv-app:assembleTvDebug -PapiBaseUrl=https://api.example.tv
        val apiBaseUrl = (project.findProperty("apiBaseUrl") as String?) ?: "https://civiccast.example.com"
        buildConfigField("String", "API_BASE_URL", "\"$apiBaseUrl\"")
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    // De-duplication (S12): "tv" (Android TV/Google TV, Google Play) and "firetv" (Amazon Fire TV,
    // Amazon Appstore) used to be two entire copied source trees (android-tv/, fire-tv/) that
    // differed only in applicationId, theme resource names, and a handful of manifest lines. They
    // are now one Gradle module with two product flavors sharing 100% of the Kotlin source; the
    // real per-storefront differences live in src/tv/ and src/firetv/ manifest overlays.
    flavorDimensions += "storefront"
    productFlavors {
        create("tv") {
            dimension = "storefront"
            applicationId = "com.civiccast.tv"
        }
        create("firetv") {
            dimension = "storefront"
            applicationId = "com.civiccast.firetv"
        }
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
        }
        getByName("debug") {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.0")
    implementation("androidx.leanback:leanback:1.0.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.0")
    implementation("androidx.fragment:fragment-ktx:1.7.1")

    // Networking
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.0")

    // Media3 ExoPlayer + HLS
    implementation("androidx.media3:media3-exoplayer:1.3.1")
    implementation("androidx.media3:media3-exoplayer-hls:1.3.1")
    implementation("androidx.media3:media3-ui-leanback:1.3.1")
    implementation("androidx.media3:media3-ui:1.3.1")
}
