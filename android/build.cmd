@echo off
rem Build the Android app with every tool, cache and temp file on D: (C: is nearly full).
rem   build.cmd                 : debug APK in app\build\outputs\apk\debug\
rem   build.cmd installDebug    : also install on a phone connected by USB
setlocal
set "TASK=%~1"
if "%TASK%"=="" set "TASK=assembleDebug"
rem Android build tools need JDK 17/21, not the system Java 26.
set "JAVA_HOME=D:\android\jdk-21"
set "ANDROID_HOME=D:\android\sdk"
rem Gradle + library downloads (default would be C:\Users\<you>\.gradle).
set "GRADLE_USER_HOME=D:\android\gradle-home"
set "TEMP=D:\android\tmp"
set "TMP=D:\android\tmp"
rem Java on Windows makes a socket file in the temp dir; the default one failed with
rem "Unable to establish loopback connection".
set "JAVA_TOOL_OPTIONS=-Djava.io.tmpdir=D:\android\tmp -Djdk.net.unixdomain.tmpdir=D:\android\tmp"
if not exist "%TEMP%" mkdir "%TEMP%"
cd /d "%~dp0"
call gradlew.bat %TASK% --console=plain
