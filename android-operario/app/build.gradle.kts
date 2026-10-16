// app/build.gradle.kts
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.smartwms.operario"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.smartwms.operario"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    // ─── FLAVORS: permite generar APKs para distintos entornos ────────────────
    val serverIp = (project.findProperty("SERVER_IP") as? String)
        ?: System.getenv("SERVER_IP")
        ?: "192.168.1.5"

    flavorDimensions += "environment"
    productFlavors {
        // Para el EMULADOR Android Studio (10.0.2.2 apunta al localhost de la PC)
        create("emulator") {
            dimension = "environment"
            applicationIdSuffix = ".emulator"
            versionNameSuffix = "-emulator"
            buildConfigField("String", "API_BASE_URL", "\"http://10.0.2.2:8001\"")
            buildConfigField("String", "BOT_BASE_URL",  "\"http://10.0.2.2:8000\"")
        }
        // Para CELULAR FÍSICO conectado a la red WiFi o VPN
        create("device") {
            dimension = "environment"
            applicationIdSuffix = ".device"
            versionNameSuffix = "-device"
            buildConfigField("String", "API_BASE_URL", "\"http://$serverIp:8001\"")
            buildConfigField("String", "BOT_BASE_URL",  "\"http://$serverIp:8000\"")
        }
        // Para PRODUCCIÓN en la nube (completar la URL cuando se suba)
        create("production") {
            dimension = "environment"
            versionNameSuffix = "-prod"
            buildConfigField("String", "API_BASE_URL", "\"https://TU-DOMINIO-EN-LA-NUBE.com\"")
            buildConfigField("String", "BOT_BASE_URL",  "\"https://TU-DOMINIO-EN-LA-NUBE.com\"")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }
    kotlinOptions { jvmTarget = "1.8" }

    buildFeatures {
        viewBinding = true
        buildConfig  = true
    }
}

dependencies {
    // Core Android
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.androidx.constraintlayout)

    // Navigation
    implementation(libs.androidx.navigation.fragment.ktx)
    implementation(libs.androidx.navigation.ui.ktx)

    // ViewModel + LiveData
    implementation(libs.androidx.lifecycle.viewmodel.ktx)
    implementation(libs.androidx.lifecycle.livedata.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)

    // Retrofit + OkHttp (HTTP)
    implementation(libs.retrofit)
    implementation(libs.converter.gson)
    implementation(libs.okhttp)
    implementation(libs.logging.interceptor)

    // Coroutines
    implementation(libs.kotlinx.coroutines.android)

    // DataStore (reemplaza SharedPreferences)
    implementation(libs.androidx.datastore.preferences)

    // QR Scanner
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")

    // Tests
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}
