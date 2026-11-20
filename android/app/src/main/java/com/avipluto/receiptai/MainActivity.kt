package com.avipluto.receiptai

import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.QuestionAnswer
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.avipluto.receiptai.ui.AppViewModel
import com.avipluto.receiptai.ui.AskScreen
import com.avipluto.receiptai.ui.HomeScreen
import com.avipluto.receiptai.ui.ReceiptDetailScreen
import com.avipluto.receiptai.ui.ReceiptListScreen
import com.avipluto.receiptai.ui.SettingsScreen

private data class Tab(val route: String, val label: String, val icon: ImageVector)

private val TABS = listOf(
    Tab("home", "Home", Icons.Filled.Home),
    Tab("receipts", "Receipts", Icons.AutoMirrored.Filled.ReceiptLong),
    Tab("ask", "Ask", Icons.Filled.QuestionAnswer),
    Tab("settings", "Settings", Icons.Filled.Settings),
)

class MainActivity : ComponentActivity() {
    private val vm: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { AppTheme { App(vm) } }
    }
}

@Composable
private fun AppTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val context = LocalContext.current
    val colors = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        dark -> darkColorScheme()
        else -> lightColorScheme()
    }
    MaterialTheme(colorScheme = colors, content = content)
}

@Composable
private fun App(vm: AppViewModel) {
    val nav = rememberNavController()
    val entry by nav.currentBackStackEntryAsState()
    val current = entry?.destination?.route
    val openReceipt: (Int) -> Unit = { nav.navigate("receipt/$it") }

    Scaffold(bottomBar = {
        NavigationBar {
            TABS.forEach { tab ->
                NavigationBarItem(
                    selected = current == tab.route,
                    onClick = {
                        nav.navigate(tab.route) {
                            popUpTo("home") { saveState = true }
                            launchSingleTop = true
                            restoreState = true
                        }
                    },
                    icon = { Icon(tab.icon, null) },
                    label = { Text(tab.label) },
                )
            }
        }
    }) { padding ->
        NavHost(nav, startDestination = "home", modifier = Modifier.padding(padding)) {
            composable("home") { HomeScreen(vm, openReceipt) { nav.navigate("settings") } }
            composable("receipts") { ReceiptListScreen(vm, openReceipt) }
            composable("ask") { AskScreen(vm, openReceipt) }
            composable("settings") { SettingsScreen(vm) }
            composable("receipt/{id}", arguments = listOf(navArgument("id") { type = NavType.IntType })) {
                ReceiptDetailScreen(vm, it.arguments!!.getInt("id"))
            }
        }
    }
}
