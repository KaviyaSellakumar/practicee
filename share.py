pipeline {
    agent { label 'macos' }

    environment {
        // Android
        ANDROID_HOME = "/path/to/android/sdk"
        KEYSTORE_PATH = credentials('android-keystore-file')
        KEYSTORE_PASSWORD = credentials('android-keystore-password')
        KEY_ALIAS = credentials('android-key-alias')
        KEY_PASSWORD = credentials('android-key-password')

        // iOS
        CERT_PASSWORD = credentials('ios-cert-password')
        SIGNING_IDENTITY = "iPhone Distribution: Your Company (TEAMID)"
        PROVISIONING_PROFILE = "/path/to/profile.mobileprovision"

        // macOS
        MAC_SIGN_ID = "Developer ID Application: Your Name (TEAMID)"
    }

    stages {
        stage('Build Android') {
            steps {
                sh './gradlew clean assembleRelease bundleRelease'
            }
        }

        stage('Sign Android APK & AAB') {
            steps {
                sh """
                    ${ANDROID_HOME}/build-tools/34.0.0/apksigner sign \
                      --ks $KEYSTORE_PATH \
                      --ks-key-alias $KEY_ALIAS \
                      --ks-pass pass:$KEYSTORE_PASSWORD \
                      --key-pass pass:$KEY_PASSWORD \
                      --out app-release-signed.apk \
                      app/build/outputs/apk/release/app-release-unsigned.apk

                    jarsigner -keystore $KEYSTORE_PATH -storepass $KEYSTORE_PASSWORD -keypass $KEY_PASSWORD \
                      app/build/outputs/bundle/release/app-release.aab $KEY_ALIAS
                """
            }
        }

        stage('Build & Sign iOS IPA') {
            steps {
                sh """
                    xcodebuild -workspace YourApp.xcworkspace -scheme YourScheme -configuration Release \
                      -archivePath build/YourApp.xcarchive archive

                    xcodebuild -exportArchive -archivePath build/YourApp.xcarchive \
                      -exportOptionsPlist ExportOptions.plist \
                      -exportPath build/
                """
            }
        }

        stage('Sign macOS App and Zip') {
            steps {
                sh """
                    codesign --deep --force --verify --verbose \
                      --sign "$MAC_SIGN_ID" /path/to/YourApp.app

                    ditto -c -k --sequesterRsrc --keepParent /path/to/YourApp.app YourApp.zip
                """
            }
        }
    }

    post {
        success {
            archiveArtifacts artifacts: '**/*.apk, **/*.aab, **/*.ipa, **/*.zip', fingerprint: true
        }
    }
}
