pipeline {
    agent none

    parameters {
        choice(name: 'PLATFORM', choices: ['ANDROID', 'MAC', 'IOS'], description: 'Choose the platform')
        choice(name: 'SOURCE_TYPE', choices: ['Upload', 'S3'], description: 'Choose the source type')
        string(name: 'S3', defaultValue: '', description: 'S3 file path (required if SOURCE_TYPE is S3)')
        file(name: 'UPLOAD_FILE', description: 'Upload the app file (required if SOURCE_TYPE is Upload)')
    }

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
                            sh "aws s3 cp ${params.S3} ./downloaded_android_file"
                            inputFile = 'downloaded_android_file'
                        } else {
                            sh "cp ${params.UPLOAD_FILE} ./uploaded_android_file"
                            inputFile = 'uploaded_android_file'
                        }

                        echo "📦 Detected input file: ${inputFile}"
                        def ext = inputFile.tokenize('.').last()

                        if (ext == 'apk') {
                            sh """apksigner sign \
                                --ks "$WORKSPACE/certificate.jks" \
                                --ks-key-alias "hexnodemdmapp" \
                                --ks-pass pass:$ANDROID_PASSPHRASE \
                                --key-pass pass:$ANDROID_PASSPHRASE \
                                --out "signed_${inputFile}" \
                                "${inputFile}" """
                        } else if (ext == 'aab') {
                            sh """jarsigner \
                                -keystore "$WORKSPACE/certificate.jks" \
                                -storepass "$ANDROID_PASSPHRASE" \
                                -keypass "$ANDROID_PASSPHRASE" \
                                -signedjar "signed_${inputFile}" \
                                "${inputFile}" hexnodemdmapp"""
                        } else {
                            error "❌ Unsupported Android file type: ${ext}"
                        }

                        echo "✅ Signed file: signed_${inputFile}"
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
                            sh "aws s3 cp ${params.S3} ./downloaded_apple_file"
                            inputFile = 'downloaded_apple_file'
                        } else {
                            sh "cp ${params.UPLOAD_FILE} ./uploaded_apple_file"
                            inputFile = 'uploaded_apple_file'
                        }

                        echo "📦 Detected input file: ${inputFile}"
                        def ext = inputFile.tokenize('.').last()
                        def fileName = inputFile.tokenize('/').last()
                        def baseName = fileName.replace(".${ext}", "")

                        if (ext == 'ipa') {
                            sh "xcrun altool --sign --file ${inputFile}"
                        } else if (ext == 'zip') {
                            sh """
                                unzip ${inputFile}
                                codesign -f --sign "Developer ID Application: Mitsogo Inc (BX6L6CPUN8)" ${baseName}.app
                                ditto -c -k --sequesterRsrc --keepParent ${baseName}.app ${baseName}.app.zip
                            """
                        } else {
                            error "❌ Unsupported Mac/iOS file type: ${ext}"
                        }

                        echo "✅ Signed file for ${params.PLATFORM}"
                    }
                }
            }
        }
    }
}
