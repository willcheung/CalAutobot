import { cpSync, rmSync } from 'node:fs';
// Publish assets only. The legacy Flask app is never deployed.
rmSync('public/static', { recursive: true, force: true });
cpSync('app/static', 'public/static', { recursive: true });
