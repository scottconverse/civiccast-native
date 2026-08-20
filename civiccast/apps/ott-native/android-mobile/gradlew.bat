@rem Gradle start-up script — minimal stub.
@rem In a fresh checkout, run `gradle wrapper --gradle-version 8.7` once to materialize the real gradlew.bat + gradle-wrapper.jar.
@echo off
set DIRNAME=%~dp0
if not exist "%DIRNAME%gradle\wrapper\gradle-wrapper.jar" (
  echo gradle-wrapper.jar missing. Run: gradle wrapper --gradle-version 8.7 1>&2
  exit /b 1
)
java -classpath "%DIRNAME%gradle\wrapper\gradle-wrapper.jar" org.gradle.wrapper.GradleWrapperMain %*
