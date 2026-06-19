pipeline {
    agent any

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build Docker image') {
            steps {
                sh 'docker build -t parking-backend:latest .'
            }
        }

        stage('Deploy') {
            steps {
                sh 'docker stop parking-backend || true'
                sh 'docker rm parking-backend || true'
                sh '''
                    docker run -d \
                      --name parking-backend \
                      --network parking-net \
                      --restart unless-stopped \
                      -p 8000:8000 \
                      --env-file /var/jenkins_home/backend.env \
                      -e DB_PATH=/data/parking_history.db \
                      -v /home/mykola/parking-data:/data \
                      parking-backend:latest
                '''
            }
        }
    }

    post {
    always {
        sh 'docker builder prune -f'
        sh 'docker image prune -f'
    }
    success { echo 'Backend deployed!' }
    failure  { echo 'Build failed.' }
    }
}
