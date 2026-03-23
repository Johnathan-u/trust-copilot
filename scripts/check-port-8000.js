/**
 * Check if port 8000 is in use. Exit with code 1 and a clear message if so.
 * Set SKIP_PORT_CHECK=1 to skip (e.g. when kill-port already freed it).
 */
const net = require('net');

if (process.env.SKIP_PORT_CHECK === '1') {
  process.exit(0);
}

const PORT = 8000;

const socket = new net.Socket();
const timeout = 500;

socket.setTimeout(timeout);
socket.on('connect', () => {
  socket.destroy();
  console.error('');
  console.error('ERROR: Port 8000 is already in use.');
  console.error('Free it, then start the API again:');
  console.error('  PowerShell: .\\scripts\\kill-port-8000.ps1');
  console.error('  Or close the terminal that is running "npm run dev:all" or the API.');
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
