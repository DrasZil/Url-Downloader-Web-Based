# render-build.sh

#!/usr/bin/env bash

# Install Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
apt-get update
apt-get install -y ./google-chrome-stable_current_amd64.deb

# Install ChromeDriver matching the version
CHROME_VERSION=$(google-chrome --version | grep -oP '\d+\.\d+\.\d+')
wget -N https://chromedriver.storage.googleapis.com/${CHROME_VERSION}/chromedriver_linux64.zip
unzip chromedriver_linux64.zip
mv chromedriver /usr/local/bin/chromedriver
chmod +x /usr/local/bin/chromedriver

# Cleanup
rm -rf *.deb *.zip
