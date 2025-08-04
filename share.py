pipeline {
    agent none
    stages {

        stage('Sign Android') {
            when {
                expression { params.PLATFORM == 'ANDROID' }
            }
            agent { label 'built-in' }

            steps {
                withCredentials([
                    string(credentialsId: 'ANDROID_KEY_PASSPHRASE', variable: 'ANDROID_PASSPHRASE'),
                    file(credentialsId: 'jenkins_aws_credential', variable: 'AWS_SHARED_CREDENTIALS_FILE')
                ]) {
                    script {
                        def inputFile = ''
                        
                        if (params.SOURCE_TYPE == 'S3') {
                            sh "aws s3 cp '${params.S3}' ./downloaded_file"
                            inputFile = 'downloaded_file'
                        } else {
                            sh "echo 'Workspace contents:' && ls -l"
                            inputFile = sh(script: "find . -maxdepth 1 -type f \\( -name '*.apk' -o -name '*.aab' \\) | head -n 1", returnStdout: true).trim()
                        }

                        if (!inputFile?.trim()) {
                            error "❌ INPUT_FILE is not set! Ensure a file was uploaded or S3 path is valid."
                        }

                        echo "📦 Detected input file: ${inputFile}"
                        def ext = inputFile.tokenize('.').last()

                        if (ext == 'apk') {
                            sh """
                                apksigner sign \
                                --ks "$WORKSPACE/certificate.jks" \
                                --ks-key-alias "hexnodemdmapp" \
                                --ks-pass pass:$ANDROID_PASSPHRASE \
                                --key-pass pass:$ANDROID_PASSPHRASE \
                                --out "signed_${inputFile}" \
                                "${inputFile}"
                            """
                        } else if (ext == 'aab') {
                            sh """
                                jarsigner \
                                -keystore "$WORKSPACE/certificate.jks" \
                                -storepass "$ANDROID_PASSPHRASE" \
                                -keypass "$ANDROID_PASSPHRASE" \
                                -signedjar "signed_${inputFile}" \
                                "${inputFile}" hexnodemdmapp
                            """
                        } else {
                            error "❌ Unsupported Android file type: ${ext}"
                        }
                    }
                }
            }
        }

        stage('Sign Mac/iOS') {
            when {
                expression { params.PLATFORM == 'MAC' || params.PLATFORM == 'IOS' }
            }
            agent { label 'mac_mini_kochi' }

            steps {
                withCredentials([
                    string(credentialsId: 'NOTARY_PASSWORD', variable: 'MAC'),
                    file(credentialsId: 'jenkins_aws_credential', variable: 'AWS_SHARED_CREDENTIALS_FILE')
                ]) {
                    script {
                        def inputFile = ''

                        if (params.SOURCE_TYPE == 'S3') {
                            sh "aws s3 cp '${params.S3}' ./downloaded_file"
                            inputFile = 'downloaded_file'
                        } else {
                            sh "echo 'Workspace contents:' && ls -l"
                            inputFile = sh(script: "find . -maxdepth 1 -type f \\( -name '*.ipa' -o -name '*.zip' \\) | head -n 1", returnStdout: true).trim()
                        }

                        if (!inputFile?.trim()) {
                            error "❌ INPUT_FILE is not set! Ensure a file was uploaded or S3 path is valid."
                        }

                        echo "📦 Detected input file: ${inputFile}"
                        def ext = inputFile.tokenize('.').last()
                        def fileName = inputFile.tokenize('/').last()
                        def baseName = fileName.replace(".${ext}", "")

                        if (ext == 'ipa') {
                            sh "xcrun altool --sign --file '${inputFile}'"
                        } else if (ext == 'zip') {
                            sh """
                                unzip '${inputFile}'
                                codesign -f --sign "Developer ID Application: Mitsogo Inc (BX6L6CPUN8)" "${baseName}.app"
                                ditto -c -k --sequesterRsrc --keepParent "${baseName}.app" "${baseName}.app.zip"
                            """
                        } else {
                            error "❌ Unsupported Mac/iOS file type: ${ext}"
                        }
                    }
                }
            }
        }

    }
}
