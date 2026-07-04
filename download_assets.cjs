const http = require('http');
const fs = require('fs');
const path = require('path');

const assets = [
    { url: 'http://91.232.105.47/ints/css/loginmain.css', dest: 'app/static/css/loginmain.css' },
    { url: 'http://91.232.105.47/ints/css/loginutil.css', dest: 'app/static/css/loginutil.css' },
    { url: 'http://91.232.105.47/ints/img/logo.png', dest: 'app/static/img/fly_logo.png' },
    { url: 'http://91.232.105.47/ints/img/bg.jpg', dest: 'app/static/img/bg.jpg' }
];

function download(url, dest) {
    return new Promise((resolve, reject) => {
        const file = fs.createWriteStream(dest);
        http.get(url, (response) => {
            if (response.statusCode !== 200) {
                reject(new Error(`Failed to get '${url}' (Status Code: ${response.statusCode})`));
                return;
            }
            response.pipe(file);
            file.on('finish', () => {
                file.close();
                console.log(`Downloaded ${url} -> ${dest}`);
                resolve();
            });
        }).on('error', (err) => {
            fs.unlink(dest, () => {});
            reject(err);
        });
    });
}

async function run() {
    // Ensure directories exist
    fs.mkdirSync('app/static/css', { recursive: true });
    fs.mkdirSync('app/static/img', { recursive: true });

    for (const asset of assets) {
        try {
            await download(asset.url, asset.dest);
        } catch (e) {
            console.error(`Error downloading ${asset.url}:`, e.message);
        }
    }
}

run();
