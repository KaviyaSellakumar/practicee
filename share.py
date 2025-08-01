pipeline {
    agent any

    environment {
        ANDROID_HOME = "/path/to/android/sdk"
        BUILD_TOOLS = "${ANDROID_HOME}/build-tools/34.0.0"

        KEYSTORE_FILE = credentials('android-keystore-file-id')
        KEYSTORE_PASS = credentials('android-keystore-password-id')
        KEY_ALIAS     = credentials('android-key-alias-id')
        KEY_PASS      = credentials('android-key-password-id')
    }

    stages {
        stage('Prepare Keystore') {
            steps {
                sh 'cp $KEYSTORE_FILE my-release-key.keystore'
            }
        }

        stage('Sign APK') {
            steps {
                sh """
                    ${BUILD_TOOLS}/apksigner sign \
                      --ks my-release-key.keystore \
                      --ks-key-alias $KEY_ALIAS \
                      --ks-pass pass:$KEYSTORE_PASS \
                      --key-pass pass:$KEY_PASS \
                      --out app-release-signed.apk \
                      app-release-unsigned.apk
                """
            }
        }

        stage('Sign AAB') {
            steps {
                sh """
                    jarsigner \
                      -keystore my-release-key.keystore \
                      -storepass $KEYSTORE_PASS \
                      -keypass $KEY_PASS \
                      app-release.aab \
                      $KEY_ALIAS
                """
            }
        }
    }

    post {
        success {
            archiveArtifacts artifacts: '*.apk, *.aab', fingerprint: true
        }
    }
}
