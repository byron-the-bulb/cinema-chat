import { createServer } from 'https';
import { parse } from 'url';
import next from 'next';
import fs from 'fs';
import { IncomingMessage, ServerResponse } from 'http';

const dev = process.env.NODE_ENV !== 'production';
const app = next({ dev });
const handle = app.getRequestHandler();

const httpsOptions = {
    key: fs.readFileSync('./key.pem'), // Path to your key file
    cert: fs.readFileSync('./cert.pem'), // Path to your cert file
};

app.prepare().then(() => {
    createServer(httpsOptions, (req: IncomingMessage, res: ServerResponse) => {
        const parsedUrl = parse(req.url!, true); // `!` asserts that req.url is not undefined
        handle(req, res, parsedUrl);
    }).listen(3000, '0.0.0.0', (err?: Error) => {
        if (err) throw err;
        console.log('> Ready on https://0.0.0.0:3000');
    });
});