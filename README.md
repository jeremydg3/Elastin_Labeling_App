# Elastin_Labeling_App

To install Node.js
https://nodejs.org/en/download



Instructions to edit web app in vscode: https://hackernoon.com/writing-google-apps-script-code-locally-in-vscode

1) Install Clasp (command line)
npm install -g @google/clasp

2) login to clasp
clasp login

3) Clone the Web App package
clasp clone "1hdav6U6jvMI9FED5nrP3SULF4Mao7BQ0mVTeZw10Fk-AnScN4UgDiyd5" --rootDir src

4) To push to google cloud
clasp -P src/ push
