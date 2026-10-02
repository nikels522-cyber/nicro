// nicro for Android: the web panel in its own app window (WebView, no third-party libraries). Built by GitHub Actions
// (.github/workflows/android.yml) and published as the "android-latest" release asset nicro.apk.
plugins {
    id("com.android.application")
}

android {
    namespace = "app.nicro"
    compileSdk = 34

    defaultConfig {
        applicationId = "app.nicro"
        minSdk = 23
        targetSdk = 34
        versionCode = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()
        versionName = "1.0." + (System.getenv("GITHUB_RUN_NUMBER") ?: "0")
    }

    signingConfigs {
        // A fixed key so updates install over the previous version. It is public on purpose (an open-source build,
        // nothing secret inside the app); for your own fork generate your own keystore.
        create("release") {
            storeFile = file("../nicro-release.keystore")
            storePassword = "nicro-public"
            keyAlias = "nicro"
            keyPassword = "nicro-public"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
