# Add project specific ProGuard rules here.
# You can control the set of applied configuration files using the
# proguardFiles setting in build.gradle.
#
# For more details, see
#   http://developer.android.com/guide/developing/tools/proguard.html

# If your project uses WebView with JS, uncomment the following
# and specify the fully qualified class name to the JavaScript interface
# class:
#-keepclassmembers class fqcn.of.javascript.interface.for.webview {
#   public *;
#}

# Uncomment this to preserve the line number information for
# debugging stack traces.
#-keepattributes SourceFile,LineNumberTable

# If you keep the line number information, uncomment this to
# hide the original source file name.
#-renamesourcefileattribute SourceFile

# Tauri registers this plugin from Rust by its runtime class name. Release APKs
# are minified, so keep the plugin and its InvokeArg DTOs available for
# reflection and command dispatch after R8 shrinking/obfuscation.
-keep class app.psychologygrowth.desktop.InterestGrowthPlugin { *; }
-keep class app.psychologygrowth.desktop.StageContentUriArgs { *; }
-keep class app.psychologygrowth.desktop.SaveDocumentFromFileArgs { *; }
-keep class app.psychologygrowth.desktop.PickDocumentArgs { *; }
-keepattributes RuntimeVisibleAnnotations,RuntimeInvisibleAnnotations,AnnotationDefault
