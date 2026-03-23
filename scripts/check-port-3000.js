/**
 * Check if port 3000 is in use. Exit with code 1 and a clear message if so.
 * Used before starting the Next.js dev server so the frontend does not silently
 * run on 3001 (which would break local OAuth and expectations).
 */
const net = require('net');

const PORT = 3000;

const socket = new net.Socket();
const timeout = 500;

socket.setTimeout(timeout);
socket.on('connect', () => {
  socket.destroy();
  console.error('');
  console.error('ERROR: Port 3000 is already in use.');
  console.error('Local auth and OAuth callbacks expect the frontend at http://localhost:3000.');
  console.error('Stop the process using port 3000, then run npm run dev:full again.');
  console.error('(On Windows: netstat -ano | findstr ":3000" then taskkill /PID <pid> /F)');
  console.error('');
  process.exit(1);
});
socket.on('error', () => {
  socket.destroy();
  process.exit(0);
});
socket.on('timeout', () => {
  socket.destroy();
  process.exit(0);
});

socket.connect(PORT, '127.0.0.1');
